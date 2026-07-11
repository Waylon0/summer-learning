"""
=============================================================================
app/core/budget_admin_rules.py — 预算【人工管理】校验纯函数（无外部依赖）
=============================================================================
预算管理模块（阶段一）的决策/校验逻辑下沉为纯函数，便于单元测试
（无需数据库/LLM/网络）。与既有 core/budget_rules.py（报销状态机的
预留/释放模型）职责区分：

  - budget_rules.py         : 报销单状态迁移驱动的 used_amount 自动增减（占用/释放）
  - budget_admin_rules.py   : 财务/管理员【人工】调整预算的合法性校验（本文件）

本模块只依赖标准库，任何"是否允许该笔调整""调整后额度是多少"的判断都在此，
服务层只负责加行锁、落库、写审计。
=============================================================================
"""
from __future__ import annotations

# 允许执行预算写操作的角色（已敲定：admin + finance）
BUDGET_WRITE_ROLES = frozenset({"admin", "finance"})


def can_manage_budget(role: str) -> bool:
    """该角色是否可执行预算写操作（建/调/冲正/调拨）。"""
    return (role or "").lower() in BUDGET_WRITE_ROLES


def resolve_new_annual(
    current_annual: float,
    delta: float | None,
    new_annual_budget: float | None,
) -> float:
    """由「增量 delta」或「绝对值 new_annual_budget」推算目标年度额度。

    - 两者都给：以 new_annual_budget 为准（绝对改写优先）。
    - 只给 delta：current_annual + delta。
    - 都不给：抛 ValueError（调用方转 400）。
    """
    if new_annual_budget is not None:
        return float(new_annual_budget)
    if delta is not None:
        return float(current_annual) + float(delta)
    raise ValueError("必须提供 delta 或 new_annual_budget 之一")


def validate_annual_change(
    current_annual: float,
    current_used: float,
    target_annual: float,
    force: bool = False,
) -> tuple[bool, str]:
    """校验把年度额度改为 target_annual 是否允许。

    返回 (是否允许, 错误消息)。允许时消息为空。
      - target_annual 必须 > 0；
      - 调整后额度不得低于已用额 used_amount（否则余额为负），除非 force=True。
    """
    if target_annual <= 0:
        return False, "调整后的年度额度必须大于 0。"
    if target_annual < float(current_used) - 1e-9 and not force:
        return False, (
            f"调整后年度额度 ¥{target_annual:,.2f} 低于已使用额 ¥{float(current_used):,.2f}，"
            f"将导致余额为负。如确需调减，请显式传 force=true 确认。"
        )
    return True, ""


def validate_correction(current_used: float, delta_used: float) -> tuple[bool, str, float]:
    """校验人工冲正 used_amount。返回 (是否允许, 错误消息, 冲正后 used)。

      - delta_used 不可为 0；
      - 冲正后 used 允许被夹到 0（不报错），但不允许把 used 冲到负数“再被夹0”后
        仍标记异常——这里统一：冲正后 <0 视为夹到 0（与既有 adjust_budget_used 一致）。
    """
    if not delta_used:
        return False, "冲正金额不可为 0。", float(current_used)
    after = float(current_used) + float(delta_used)
    if after < 0:
        after = 0.0
    return True, "", after


def validate_transfer(
    from_dept: str,
    to_dept: str,
    amount: float,
    from_annual: float,
    from_used: float,
    force: bool = False,
) -> tuple[bool, str]:
    """校验部门间调拨（from_dept 转出 amount 到 to_dept）。

    返回 (是否允许, 错误消息)。
      - 金额必须 > 0；
      - 转出/转入部门不能相同；
      - 转出后转出方年度额度(from_annual - amount) 不得低于其已用额，除非 force=True。
    """
    if amount <= 0:
        return False, "调拨金额必须大于 0。"
    if (from_dept or "").strip() == (to_dept or "").strip():
        return False, "转出部门与转入部门不能相同。"
    after_from = float(from_annual) - float(amount)
    if after_from < float(from_used) - 1e-9 and not force:
        return False, (
            f"转出后「{from_dept}」年度额度 ¥{after_from:,.2f} 低于其已使用额 "
            f"¥{float(from_used):,.2f}。如确需调拨，请显式传 force=true 确认。"
        )
    if after_from < 0:
        return False, f"转出金额 ¥{float(amount):,.2f} 超过「{from_dept}」年度额度 ¥{float(from_annual):,.2f}。"
    return True, ""


def classify_annual_change(delta_annual: float) -> str:
    """按年度额度变化量方向给出审计 change_type：increase / decrease / create(0 不用)。"""
    if delta_annual > 0:
        return "increase"
    if delta_annual < 0:
        return "decrease"
    return "increase"  # 0 变化理论上不落审计；兜底归为 increase
