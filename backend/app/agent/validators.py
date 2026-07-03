"""
=============================================================================
app/agent/validators.py — 多阶段校验流水线
=============================================================================
报销申请的完整性校验，分为 3 个阶段：

  Phase 1 — 前置校验（Pre-validation）
    在进入正式流程前快速拦截明显不合规的请求：
      - 金额为 0 或负数
      - 部门名不在已知列表中
      - 费用类型不在枚举值内
      - 缺少必要字段

  Phase 2 — 政策校验（Policy Check）
    调用 PolicyEngine 逐条检查费用标准：
      - 硬限制 → 直接拒绝
      - 软限制 → 标记特殊审批 + 要求补充材料
      - 建议规则 → 仅提示

  Phase 3 — 预算校验（Budget Check）
    查询数据库中的部门预算余额：
      - 余额充足 → 通过
      - 超标 → 标记特殊审批

每个阶段返回 ValidationResult，包含 pass/fail + 原因列表。
=============================================================================
"""
import re
from dataclasses import dataclass, field
from app.agent.policy import evaluate_policies, REIMBURSEMENT_POLICIES


# =============================================================================
# 校验结果数据结构
# =============================================================================
@dataclass
class ValidationResult:
    """单次校验的结果"""
    phase: str                           # 校验阶段名称
    passed: bool                         # 是否通过
    errors: list[str] = field(default_factory=list)    # 错误信息
    warnings: list[str] = field(default_factory=list)  # 警告信息
    actions_required: list[str] = field(default_factory=list)  # 需要的动作


# =============================================================================
# 已知部门列表
# =============================================================================
KNOWN_DEPARTMENTS = {
    "技术部", "研发部", "市场部", "销售部", "财务部",
    "人事部", "人力资源部", "行政部", "运营部", "运维部",
    "产品部", "设计部", "法务部", "公关部",
}

KNOWN_EXPENSE_TYPES = {"travel", "entertainment", "office", "other"}


# =============================================================================
# Phase 1: 前置校验
# =============================================================================
def pre_validate(
    amount: float,
    department: str,
    expense_type: str,
    description: str = "",
) -> ValidationResult:
    """
    前置校验 —— 在进入正式流程前快速拦截明显不合规的请求。

    校验项:
      1. 金额必须 > 0
      2. 金额不超过硬上限 100,000
      3. 部门名在已知列表中（非严格，仅警告）
      4. 费用类型必须合法
      5. 说明不能完全为空
    """
    result = ValidationResult(phase="pre_validation", passed=True)

    # 1. 金额校验
    if amount <= 0:
        result.errors.append("报销金额必须大于 0，请提供正确的金额。")
        result.passed = False
    if amount > 100000:
        result.errors.append(f"单次报销金额 ¥{amount:,.2f} 超过系统上限 ¥100,000。")
        result.passed = False

    # 2. 部门校验（非阻塞，仅警告）
    if department and department not in KNOWN_DEPARTMENTS:
        result.warnings.append(
            f"部门 '{department}' 不在已知部门列表中。"
            f"已知部门: {', '.join(sorted(KNOWN_DEPARTMENTS))}"
        )

    # 3. 费用类型校验
    if expense_type and expense_type not in KNOWN_EXPENSE_TYPES:
        result.errors.append(
            f"费用类型 '{expense_type}' 无效。"
            f"有效值: {', '.join(sorted(KNOWN_EXPENSE_TYPES))}"
        )
        result.passed = False

    # 4. 说明校验（非阻塞）
    if not description or len(description.strip()) < 5:
        result.warnings.append("报销说明过于简短，建议补充详细描述以便审批。")

    return result


# =============================================================================
# Phase 2: 政策校验
# =============================================================================
def policy_validate(
    amount: float,
    expense_type: str,
    department: str,
    guest_count: int = 0,
) -> ValidationResult:
    """
    政策校验 —— 逐条检查费用是否符合公司标准。

    调用 PolicyEngine 执行逐规则检查，汇总结果。
    """
    result = ValidationResult(phase="policy_check", passed=True)

    policy_result = evaluate_policies(amount, expense_type, department, guest_count)

    for violation in policy_result["violations"]:
        if violation["severity"] == "critical":
            result.errors.append(violation["message"])
            result.passed = False
        elif violation["severity"] == "warning":
            result.warnings.append(violation["message"])
        else:
            result.warnings.append(violation["message"])

    if policy_result["requires_special_approval"]:
        result.actions_required.append("special_approval")

    if policy_result["requires_evidence"]:
        result.actions_required.append("upload_evidence")

    return result


# =============================================================================
# Phase 3: 预算校验
# =============================================================================
def budget_validate(
    amount: float,
    department: str,
    budget_remaining: float,
) -> ValidationResult:
    """
    预算校验 —— 检查部门预算余额是否充足。

    Args:
        amount           : 报销金额
        department       : 部门名称
        budget_remaining : 部门剩余预算（从数据库查询）
    """
    result = ValidationResult(phase="budget_check", passed=True)

    if budget_remaining < 0:
        result.errors.append(
            f"部门 {department} 预算已超支 ¥{abs(budget_remaining):,.2f}。"
            f"本次报销 ¥{amount:,.2f} 需要财务总监特批。"
        )
        result.passed = False
        result.actions_required.append("special_approval")
    elif budget_remaining < amount:
        result.warnings.append(
            f"部门 {department} 剩余预算 ¥{budget_remaining:,.2f} "
            f"不足以覆盖本次报销 ¥{amount:,.2f}。将触发特殊审批流程。"
        )
        result.actions_required.append("special_approval")

    return result


# =============================================================================
# 全阶段校验
# =============================================================================
def run_full_validation(
    amount: float,
    department: str,
    expense_type: str,
    description: str = "",
    guest_count: int = 0,
    budget_remaining: float = 0,
) -> dict:
    """
    执行全部三个阶段校验，返回汇总结果。

    Returns:
        {
            "passed": True/False,
            "phases": {"pre_validation": {...}, "policy_check": {...}, "budget_check": {...}},
            "all_errors": [...],
            "all_warnings": [...],
            "actions_required": [...],
        }
    """
    phases = {}

    # Phase 1
    p1 = pre_validate(amount, department, expense_type, description)
    phases["pre_validation"] = {"passed": p1.passed, "errors": p1.errors, "warnings": p1.warnings}

    # Phase 2
    p2 = policy_validate(amount, expense_type, department, guest_count)
    phases["policy_check"] = {"passed": p2.passed, "errors": p2.errors, "warnings": p2.warnings}

    # Phase 3
    p3 = budget_validate(amount, department, budget_remaining)
    phases["budget_check"] = {"passed": p3.passed, "errors": p3.errors, "warnings": p3.warnings}

    all_errors = p1.errors + p2.errors + p3.errors
    all_warnings = p1.warnings + p2.warnings + p3.warnings
    all_actions = list(set(p1.actions_required + p2.actions_required + p3.actions_required))

    passed = p1.passed and p2.passed and p3.passed

    return {
        "passed": passed,
        "phases": phases,
        "all_errors": all_errors,
        "all_warnings": all_warnings,
        "actions_required": all_actions,
    }
