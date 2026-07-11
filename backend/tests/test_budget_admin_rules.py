"""
=============================================================================
tests/test_budget_admin_rules.py — 预算【人工管理】校验纯函数回归测试
=============================================================================
与 tests/test_rules.py 同风格：仅依赖标准库与项目内纯规则模块
（app.core.budget_admin_rules），无需数据库/LLM/网络即可运行，守护预算管理
模块（阶段一：建/调/冲正/调拨）的校验逻辑。

运行方式:
  cd backend
  python -m pytest tests/test_budget_admin_rules.py     # 有 pytest 时
  python tests/test_budget_admin_rules.py               # 无 pytest 时直接跑
=============================================================================
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import budget_admin_rules as r


# ---------------------------------------------------------------- 写权限
def test_can_manage_budget():
    assert r.can_manage_budget("admin") is True
    assert r.can_manage_budget("finance") is True
    assert r.can_manage_budget("FINANCE") is True          # 大小写不敏感
    assert r.can_manage_budget("manager") is False
    assert r.can_manage_budget("employee") is False
    assert r.can_manage_budget("") is False
    assert r.can_manage_budget(None) is False


# ---------------------------------------------------------------- 目标额度推算
def test_resolve_new_annual():
    assert r.resolve_new_annual(600000, 100000, None) == 700000    # 增量
    assert r.resolve_new_annual(600000, -50000, None) == 550000    # 削减
    assert r.resolve_new_annual(600000, None, 500000) == 500000    # 绝对改写
    assert r.resolve_new_annual(600000, 100000, 500000) == 500000  # 绝对值优先
    try:
        r.resolve_new_annual(600000, None, None)
        assert False, "should raise when both None"
    except ValueError:
        pass


# ---------------------------------------------------------------- 额度调整校验
def test_validate_annual_change():
    assert r.validate_annual_change(600000, 160000, 700000)[0] is True
    assert r.validate_annual_change(600000, 160000, 0)[0] is False        # <=0
    assert r.validate_annual_change(600000, 160000, -1)[0] is False       # 负
    assert r.validate_annual_change(600000, 160000, 100000)[0] is False   # 低于已用无 force
    assert r.validate_annual_change(600000, 160000, 100000, force=True)[0] is True  # force 放行
    assert r.validate_annual_change(600000, 160000, 160000)[0] is True    # 恰好等于已用
    # 错误消息非空
    ok, msg = r.validate_annual_change(600000, 160000, 100000)
    assert not ok and "force" in msg


# ---------------------------------------------------------------- 冲正校验
def test_validate_correction():
    ok, msg, after = r.validate_correction(160000, -50000)
    assert ok and after == 110000 and msg == ""
    ok, msg, after = r.validate_correction(1000, -5000)
    assert ok and after == 0.0                                          # 夹 0
    ok, msg, after = r.validate_correction(1000, 2000)
    assert ok and after == 3000                                         # 正向冲正
    ok, msg, after = r.validate_correction(1000, 0)
    assert not ok and after == 1000                                     # 0 拒绝


# ---------------------------------------------------------------- 调拨校验
def test_validate_transfer():
    assert r.validate_transfer("A", "B", 1000, 5000, 2000)[0] is True
    assert r.validate_transfer("A", "B", 0, 5000, 2000)[0] is False     # 金额<=0
    assert r.validate_transfer("A", "B", -100, 5000, 2000)[0] is False
    assert r.validate_transfer("A", "A", 100, 5000, 2000)[0] is False   # 同部门
    assert r.validate_transfer("A", "B", 4000, 5000, 2000)[0] is False  # 转出后 1000 < 已用 2000
    assert r.validate_transfer("A", "B", 4000, 5000, 2000, force=True)[0] is True
    assert r.validate_transfer("A", "B", 6000, 5000, 2000, force=True)[0] is False  # 转出后为负，即便 force
    # 恰好转到等于已用额（5000-3000=2000 == used 2000）应放行
    assert r.validate_transfer("A", "B", 3000, 5000, 2000)[0] is True


# ---------------------------------------------------------------- change_type 归类
def test_classify_annual_change():
    assert r.classify_annual_change(100) == "increase"
    assert r.classify_annual_change(-100) == "decrease"
    assert r.classify_annual_change(0) == "increase"        # 兜底


# ---------------------------------------------------------------- 写权限角色集合
def test_write_roles_constant():
    assert r.BUDGET_WRITE_ROLES == frozenset({"admin", "finance"})


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} budget-admin rule tests passed.")


if __name__ == "__main__":
    _run_all()
