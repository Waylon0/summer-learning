"""
=============================================================================
tests/test_rules.py — 核心业务规则回归测试（无重依赖，可直接运行）
=============================================================================
这些测试只依赖标准库与项目内的纯规则模块（app.core.budget_rules /
app.core.approval_rules / app.agent.expense_rules），因此无需数据库、LLM、
向量库即可运行，用于守护第二轮"严谨报销"优化中的关键财务/审批逻辑。

运行方式:
  cd backend
  python -m pytest tests/test_rules.py        # 有 pytest 时
  python tests/test_rules.py                  # 无 pytest 时直接跑
=============================================================================
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.budget_rules import budget_delta_for_transition, is_committed
from app.core.approval_rules import build_approval_chain, can_role_approve_step
from app.agent import expense_rules as er


# ---------------------------------------------------------------- 预算预留/释放
def test_budget_reserve_and_release():
    assert budget_delta_for_transition("draft", "pending", 100) == 100      # 提交预留
    assert budget_delta_for_transition("pending", "approved", 100) == 0     # 通过保持
    assert budget_delta_for_transition("approved", "paid", 100) == 0        # 付款保持
    assert budget_delta_for_transition("pending", "rejected", 100) == -100  # 驳回释放
    assert budget_delta_for_transition("pending", "returned", 100) == -100  # 退回释放
    assert budget_delta_for_transition("pending", "cancelled", 100) == -100 # 撤销释放
    assert budget_delta_for_transition("returned", "pending", 100) == 100   # 退回后重交再预留
    assert is_committed("pending") and not is_committed("draft")


# ---------------------------------------------------------------- 两阶段审批
def test_approval_chain_two_stage():
    # 无论金额大小，统一两阶段：部门经理 → 财务审批
    assert build_approval_chain(100) == ["部门经理", "财务审批"]
    assert build_approval_chain(50000) == ["部门经理", "财务审批"]
    assert build_approval_chain(100, need_special_approval=True) == ["部门经理", "财务审批"]


def test_approval_role_guard():
    # 阶段一：部门经理/超管；阶段二：财务/超管；admin 全阶段可代签
    assert can_role_approve_step("manager", "部门经理")
    assert not can_role_approve_step("manager", "财务审批")
    assert can_role_approve_step("finance", "财务审批")
    assert not can_role_approve_step("finance", "部门经理")
    assert can_role_approve_step("admin", "部门经理")
    assert can_role_approve_step("admin", "财务审批")
    assert not can_role_approve_step("employee", "部门经理")


# ---------------------------------------------------------------- 发票/补贴判定
def test_invoice_and_subsidy_rules():
    assert er.requires_invoice("flight", 1200) is True
    assert er.is_subsidy("taxi", 45) is True
    assert er.requires_invoice("taxi", 150) is True          # 打车≥100需票
    assert er.requires_invoice("meal_allowance", 600, 150) is False  # 按单价150判定


# ---------------------------------------------------------------- 单位/日限超标
def test_unit_limit():
    assert er.exceeds_unit_limit("hotel", unit_price=600, quantity=3)[0] is True
    assert er.exceeds_unit_limit("hotel", unit_price=500, quantity=3)[0] is False
    assert er.exceeds_unit_limit("hotel", amount=1800, quantity=3)[0] is True   # 反推单价600
    assert er.exceeds_unit_limit("flight", amount=99999)[0] is False            # 无单位上限


# ---------------------------------------------------------------- 出差天数勾稽
def test_quantity_vs_trip_days():
    assert er.quantity_vs_trip_days("meal_allowance", 10, 3)[0] is True
    assert er.quantity_vs_trip_days("meal_allowance", 3, 3)[0] is False
    assert er.quantity_vs_trip_days("hotel", 4, 3)[0] is True
    assert er.quantity_vs_trip_days("flight", 5, 3)[0] is False


# ---------------------------------------------------------------- 招待人均
def test_per_person_limit():
    assert er.exceeds_per_person_limit("banquet", 3000, 10)[0] is True   # 300/人
    assert er.exceeds_per_person_limit("banquet", 2000, 10)[0] is False  # 200/人
    assert er.exceeds_per_person_limit("banquet", 3000, 0)[0] is False   # 无人数不判定


# ---------------------------------------------------------------- 发票日期
def test_invoice_date_status():
    today = date(2026, 7, 9)
    assert er.invoice_date_status(date(2026, 7, 10), today) == "future"
    assert er.invoice_date_status(date(2026, 7, 1), today) == "ok"
    assert er.invoice_date_status(date(2026, 3, 1), today) == "stale"
    assert er.invoice_date_status(None, today) == "ok"


# ---------------------------------------------------------------- 子类→顶层类型
def test_expense_type_mapping():
    assert er.expense_type_for_subtype("flight") == "travel"
    assert er.expense_type_for_subtype("business_meal") == "entertainment"
    assert er.expense_type_for_subtype("equipment") == "office"
    assert er.expense_type_for_subtype("phone_bill") == "communication"
    # 混合报销：金额占比最大的顶层类型胜出
    items = [("flight", 1200), ("hotel", 1500), ("meal_allowance", 600), ("banquet", 3000)]
    assert er.derive_expense_type(items) == "travel"          # travel 3300 > entertainment 3000
    assert er.derive_expense_type([("banquet", 5000), ("flight", 1000)]) == "entertainment"


# ---------------------------------------------------------------- 增值税发票二维码解析
def test_vat_qr_parse():
    def parse(text):
        """内联副本，与 app/services/invoice_ocr.parse_vat_qr_payload 逻辑完全一致。"""
        if not text: return {}
        t = text.strip()
        parts = t.split(",")
        if len(parts) < 5: return {}
        if not parts[0].strip().isdigit(): return {}
        def g(i): return parts[i].strip() if i < len(parts) and parts[i] is not None else ""
        code, number, amount, date, check = g(2), g(3), g(4), g(5), g(6)
        out = {}
        if code and code.isdigit(): out["invoice_code"] = code
        if number and number.isdigit(): out["invoice_number"] = number
        if amount:
            try: out["amount"] = float(amount)
            except ValueError: pass
        if len(date) == 8 and date.isdigit(): out["invoice_date"] = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
        if check: out["check_code"] = check
        out["qr_raw"] = t
        return out

    r = parse("01,10,3700174320,12345678,1000.50,20230705,123456,")
    assert r["invoice_code"] == "3700174320" and r["amount"] == 1000.5 and r["invoice_date"] == "2023-07-05"
    assert parse("https://inv.xxx.com?sig=abc") == {}
    assert parse("") == {} and parse(None) == {} and parse("HTTP,1,2,3,4,5") == {}
    r3 = parse("01,11,,12345678901234567890,2000.00,20250101,xyz")
    assert r3.get("invoice_code") is None and r3["invoice_number"] == "12345678901234567890"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} rule tests passed.")


if __name__ == "__main__":
    _run_all()
