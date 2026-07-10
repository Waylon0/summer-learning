"""
=============================================================================
app/core/approval_rules.py — 多级审批链规则（纯函数，无外部依赖）
=============================================================================
按报销金额与"是否需特殊审批"推导审批链，与知识库
《企业报销流程指引 · 审批级别规则》保持一致：

  - 金额 < 2000            → 部门经理（1 级）
  - 2000 ≤ 金额 < 5000     → 部门经理 → 财务主管（2 级）
  - 5000 ≤ 金额 < 10000    → 部门经理 → 财务主管 → 财务总监（3 级）
  - 金额 ≥ 10000 或含超标/超预算 → 部门经理 → 财务主管 → 财务总监 → 总经理（4 级）

同时定义"哪种角色可审批哪一步"，用于在审批时做越权拦截：
  - 部门经理步：manager / admin
  - 财务主管、财务总监步：finance / admin
  - 总经理步：admin

本模块只依赖标准库，便于单元测试与被服务层/工具层复用。
=============================================================================
"""
from __future__ import annotations

# 审批步骤标题常量
STEP_DEPT_MANAGER = "部门经理"
STEP_FINANCE_LEAD = "财务主管"
STEP_FINANCE_DIRECTOR = "财务总监"
STEP_GENERAL_MANAGER = "总经理"

# 金额阈值（与知识库一致）
TIER_FINANCE_LEAD = 2000.0      # ≥ 触发财务主管
TIER_FINANCE_DIRECTOR = 5000.0  # ≥ 触发财务总监
TIER_GENERAL_MANAGER = 10000.0  # ≥ 触发总经理

# 每个审批步骤允许的角色（admin 恒可审批任意步，便于兜底）
_STEP_ALLOWED_ROLES: dict[str, frozenset[str]] = {
    STEP_DEPT_MANAGER: frozenset({"manager", "admin"}),
    STEP_FINANCE_LEAD: frozenset({"finance", "admin"}),
    STEP_FINANCE_DIRECTOR: frozenset({"finance", "admin"}),
    STEP_GENERAL_MANAGER: frozenset({"admin"}),
}


def build_approval_chain(total_amount: float, need_special_approval: bool = False) -> list[str]:
    """依据金额与特殊审批标记，返回有序的审批步骤标题列表。"""
    amt = float(total_amount or 0)
    chain = [STEP_DEPT_MANAGER]
    if amt >= TIER_FINANCE_LEAD:
        chain.append(STEP_FINANCE_LEAD)
    if amt >= TIER_FINANCE_DIRECTOR or need_special_approval:
        chain.append(STEP_FINANCE_DIRECTOR)
    if amt >= TIER_GENERAL_MANAGER or need_special_approval:
        chain.append(STEP_GENERAL_MANAGER)
    return chain


def can_role_approve_step(role: str, step_title: str) -> bool:
    """判断某角色是否有权审批指定步骤。角色为空/未知时不放行（除 admin）。"""
    r = (role or "").lower()
    if r == "admin":
        return True
    allowed = _STEP_ALLOWED_ROLES.get(step_title)
    if not allowed:
        # 未知步骤：保守放行给 manager/finance/admin，避免流程卡死
        return r in ("manager", "finance", "admin")
    return r in allowed
