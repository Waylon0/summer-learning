"""
=============================================================================
app/core/budget_rules.py — 部门预算"预留/实扣"模型（纯函数，无外部依赖）
=============================================================================
真实企业预算管控采用两段式：

  1. 预留（commit/reserve）：报销单一旦【提交进入审批】，就先从部门预算里
     "占住"这笔额度，避免多人同时提交把预算花超。
  2. 实扣（actual spend）：单据最终审批通过并付款后，这笔额度转为真实支出。

因此 department_budget.used_amount 表示"已占用额度"（预留 + 实扣），
其变动完全由报销单的【状态迁移】驱动：

  - 进入占用态（pending/approved/paid）→ 预留额度（used_amount += 金额）
  - 离开占用态（draft/returned/rejected/cancelled）→ 释放额度（used_amount -= 金额）

把这套决策收敛到一个纯函数里，既保证"驳回/退回/撤销必然释放预算、
不再泄漏"，也方便单元测试（本模块只依赖标准库）。
=============================================================================
"""
from __future__ import annotations

# 占用部门预算的状态：处于这些状态的报销单，其金额计入 used_amount
COMMITTED_STATUSES = frozenset({"pending", "approved", "paid"})

# 不占用预算的状态（草稿尚未提交；退回/驳回/撤销则应释放已占用额度）
RELEASED_STATUSES = frozenset({"draft", "returned", "rejected", "cancelled"})


def is_committed(status: str) -> bool:
    """该状态是否占用部门预算额度。"""
    return (status or "").lower() in COMMITTED_STATUSES


def budget_delta_for_transition(old_status: str, new_status: str, amount: float) -> float:
    """给定报销单状态迁移，返回应施加到部门 used_amount 的增量。

    规则（预留/实扣模型）：
      - 非占用态 → 占用态：预留额度，返回 +amount
      - 占用态   → 非占用态：释放额度，返回 -amount
      - 其余（占用态内部流转 pending→approved→paid，或非占用态之间）：返回 0

    amount 应为该报销单当前总额（非负）。
    """
    amt = float(amount or 0)
    was = is_committed(old_status)
    now = is_committed(new_status)
    if not was and now:
        return amt          # 预留
    if was and not now:
        return -amt         # 释放
    return 0.0
