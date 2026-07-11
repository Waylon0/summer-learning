"""
=============================================================================
tests/test_rules_edge.py — 核心业务规则【边界/补充】回归测试
=============================================================================
与 tests/test_rules.py 一样，仅依赖标准库与项目内纯规则模块
（app.core.budget_rules / app.core.approval_rules / app.agent.expense_rules），
无需数据库、LLM、向量库即可运行。

本文件专注补齐 test_rules.py 未覆盖的【边界条件与降级分支】：
  - 预算迁移的"同态/非占用态之间"零增量分支；
  - 审批越权的未知阶段兜底与空角色；
  - 费用别名归一化、conditional 门槛边界、全局兜底门槛；
  - 有效单价反推、发票日期边界（恰好 90 天 vs 91 天）、出差天数缺失不判定。

运行方式:
  cd backend
  python -m pytest tests/test_rules_edge.py     # 有 pytest 时
  python tests/test_rules_edge.py               # 无 pytest 时直接跑
=============================================================================
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.budget_rules import budget_delta_for_transition, is_committed
from app.core.approval_rules import can_role_approve_step, build_approval_chain, APPROVAL_CHAIN
from app.agent import expense_rules as er


# ---------------------------------------------------------------- 预算：零增量分支
def test_budget_zero_delta_transitions():
    # 占用态内部流转（pending→approved→paid）不变动 used_amount
    assert budget_delta_for_transition("pending", "pending", 100) == 0
    assert budget_delta_for_transition("approved", "paid", 100) == 0
    # 非占用态之间流转（draft/returned/rejected/cancelled 互转）也为 0
    assert budget_delta_for_transition("draft", "cancelled", 100) == 0
    assert budget_delta_for_transition("rejected", "draft", 100) == 0
    assert budget_delta_for_transition("returned", "cancelled", 100) == 0
    # 金额为 0 或 None 时不报错且为 0
    assert budget_delta_for_transition("draft", "pending", 0) == 0
    assert budget_delta_for_transition("draft", "pending", None) == 0


def test_is_committed_case_insensitive():
    assert is_committed("PENDING") and is_committed("Approved") and is_committed("paid")
    assert not is_committed("DRAFT") and not is_committed("returned")
    assert not is_committed("") and not is_committed(None)


# ---------------------------------------------------------------- 审批：兜底与空角色
def test_approval_unknown_step_and_empty_role():
    # 未知阶段：保守放行给 manager/finance/admin，拒绝 employee
    assert can_role_approve_step("manager", "未知阶段")
    assert can_role_approve_step("finance", "未知阶段")
    assert can_role_approve_step("admin", "未知阶段")
    assert not can_role_approve_step("employee", "未知阶段")
    # 空/None 角色一律拒绝（admin 除外的规则不放行空角色）
    assert not can_role_approve_step("", "部门经理")
    assert not can_role_approve_step(None, "财务审批")


def test_approval_chain_is_stable_copy():
    # build_approval_chain 每次返回独立列表副本，修改不影响全局常量
    c = build_approval_chain(123)
    assert c == ["部门经理", "财务审批"]
    c.append("篡改")
    assert APPROVAL_CHAIN == ["部门经理", "财务审批"]


# ---------------------------------------------------------------- 别名归一化
def test_normalize_subtype_aliases():
    assert er.normalize_subtype("高铁") == "train"
    assert er.normalize_subtype("打车报销") == "taxi"       # 子串命中
    assert er.normalize_subtype("网约车") == "taxi"
    assert er.normalize_subtype("酒店住宿费") == "hotel"
    assert er.normalize_subtype("flight") == "flight"        # 已是标准码原样返回
    assert er.normalize_subtype("量子传送") is None          # 无法识别
    assert er.normalize_subtype("") is None
    assert er.normalize_subtype(None) is None


# ---------------------------------------------------------------- conditional / 全局门槛
def test_conditional_and_global_threshold():
    # 打车 conditional：门槛 100，边界包含（≥100 需票）
    assert er.is_subsidy("taxi", 99) is True
    assert er.is_subsidy("taxi", 100) is False
    assert er.requires_invoice("taxi", 100) is True
    # 补贴类若单笔异常大（≥全局 500）也要发票，防滥用
    assert er.requires_invoice("metro_bus", 600) is True
    assert er.is_subsidy("metro_bus", 600) is False
    # 未知子类：回退到全局门槛 500
    assert er.requires_invoice("zzz_unknown", 600) is True
    assert er.requires_invoice("zzz_unknown", 400) is False


# ---------------------------------------------------------------- 有效单价反推
def test_effective_unit_price():
    assert er.effective_unit_price(500, 1500, 3) == 500.0    # 显式单价优先
    assert er.effective_unit_price(0, 1500, 3) == 500.0      # 单价缺失 → 金额/数量反推
    assert er.effective_unit_price(0, 1200, 1) == 1200.0     # 数量=1 → 金额即单价
    assert er.effective_unit_price(0, 0, 0) == 0.0


# ---------------------------------------------------------------- 单位上限缺失/边界
def test_unit_limit_edges():
    # 无单位上限的子类（机票）永不超标
    assert er.exceeds_unit_limit("flight", amount=99999)[0] is False
    assert er.per_unit_limit("flight") == 0.0
    assert er.per_unit_limit("hotel") == 500.0
    # 恰好等于上限不算超标（> limit + eps 才算），极小容差(1e-6)内也不算
    assert er.exceeds_unit_limit("hotel", unit_price=500, quantity=3)[0] is False
    assert er.exceeds_unit_limit("hotel", unit_price=500.0000001, quantity=1)[0] is False  # 容差内
    assert er.exceeds_unit_limit("hotel", unit_price=501, quantity=1)[0] is True


# ---------------------------------------------------------------- 招待人均边界
def test_per_person_limit_boundary():
    assert er.exceeds_per_person_limit("banquet", 2000, 10)[0] is False   # 恰好 200/人
    assert er.exceeds_per_person_limit("banquet", 2001, 10)[0] is True    # 略超
    assert er.exceeds_per_person_limit("banquet", 3000, 0)[0] is False    # 无人数不判定
    assert er.exceeds_per_person_limit("flight", 3000, 10)[0] is False    # 非招待类无人均限制


# ---------------------------------------------------------------- 出差天数勾稽缺失
def test_quantity_vs_trip_days_missing():
    # trip_days 未知 → 不判定超出
    assert er.quantity_vs_trip_days("hotel", 10, None)[0] is False
    assert er.quantity_vs_trip_days("meal_allowance", 10, 0)[0] is False
    # 非按天/晚计的子类不判定
    assert er.quantity_vs_trip_days("flight", 99, 3)[0] is False


# ---------------------------------------------------------------- 发票日期边界
def test_invoice_date_boundary():
    ref = date(2026, 7, 9)
    assert er.invoice_date_status(date(2026, 4, 10), ref) == "ok"     # 恰好 90 天
    assert er.invoice_date_status(date(2026, 4, 9), ref) == "stale"   # 91 天超期
    assert er.invoice_date_status(date(2026, 7, 9), ref) == "ok"      # 同日
    assert er.invoice_date_status(date(2026, 7, 10), ref) == "future" # 晚于参考日
    assert er.invoice_date_status(None, ref) == "ok"                  # 缺失不判定
    assert er.invoice_date_status(date(2026, 1, 1), None) == "ok"


# ---------------------------------------------------------------- 顶层类型推导兜底
def test_derive_expense_type_fallbacks():
    assert er.derive_expense_type([]) == "travel"                          # 空 → 默认
    assert er.derive_expense_type([], default="office") == "office"        # 空 → 指定默认
    # 金额全为 0 时仍能确定性返回（不抛异常）
    assert er.derive_expense_type([("flight", 0), ("hotel", 0)]) in ("travel",)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} edge rule tests passed.")


if __name__ == "__main__":
    _run_all()
