"""
=============================================================================
app/core/approval_rules.py — 两阶段审批规则（纯函数，无外部依赖）
=============================================================================
审批模型：两阶段串联

  阶段一（部门经理审批）：本部门任一 manager 通过，或 admin 代签 → 进入阶段二
  阶段二（财务审批）    ：任一 finance 通过，或 admin 代签 → 最终 approved

任一阶段 reject/return → 整单 rejected/returned（释放预算，后阶段作废）。

特殊审批（need_special_approval=True）：不增加审批层级，但标记告知财务审慎复核；
仍走同一两阶段流程。

本模块只依赖标准库，便于单元测试与被服务层/工具层复用。
=============================================================================
"""
from __future__ import annotations

# 两阶段标题
STEP_MANAGER = "部门经理"
STEP_FINANCE = "财务审批"

APPROVAL_CHAIN = [STEP_MANAGER, STEP_FINANCE]

# 每个阶段允许审批的角色（admin 恒可审批任意阶段，便于兜底）
_STEP_ALLOWED_ROLES: dict[str, frozenset[str]] = {
    STEP_MANAGER: frozenset({"manager", "admin"}),
    STEP_FINANCE: frozenset({"finance", "admin"}),
}


def build_approval_chain(total_amount: float = 0, need_special_approval: bool = False) -> list[str]:
    """返回审批步骤标题列表（忽略金额与特殊标记，统一两阶段）。

    参数保留 total_amount / need_special_approval 是为兼容旧调用方签名，
    实际不改变审批链结构。
    """
    return list(APPROVAL_CHAIN)


def can_role_approve_step(role: str, step_title: str) -> bool:
    """判断某角色是否有权审批指定阶段。角色为空/未知时不放行（除 admin）。"""
    r = (role or "").lower()
    if r == "admin":
        return True
    allowed = _STEP_ALLOWED_ROLES.get(step_title)
    if not allowed:
        # 未知阶段：保守放行给 manager/finance/admin（兜底）
        return r in ("manager", "finance", "admin")
    return r in allowed
