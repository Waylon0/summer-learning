"""
=============================================================================
app/agent/policy.py — 企业报销政策引擎
=============================================================================
区别于简单的硬编码 if-else，本模块实现可配置的多级规则引擎。

规则层级:
  Level 1 — 金额硬限制（超过直接拒绝，不可豁免）
  Level 2 — 金额软限制（超过需特殊审批 + 额外证明材料）
  Level 3 — 建议性规则（超过给出提示，不阻止提交）
  Level 4 — 部门专项规则（不同部门有不同的额度配置）

每条规则包含:
  - rule_id      : 唯一规则编号
  - level        : 规则层级 (1-4)
  - condition    : 触发条件（expense_type / department / amount 范围）
  - limit        : 限额
  - message      : 超标时的提示信息
  - action       : 超标动作 (reject / special_approval / warn)
  - overridable  : 是否可被更高级别的审批人豁免
=============================================================================
"""
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class RuleLevel(IntEnum):
    """规则层级——数字越小越严格"""
    HARD_REJECT = 1               # 硬拒绝（不可豁免）
    SOFT_LIMIT = 2                # 软限制（需特殊审批）
    ADVISORY = 3                  # 建议性（仅提示）
    DEPARTMENTAL = 4              # 部门专项


class RuleAction(str):
    """超标时的处理动作"""
    REJECT = "reject"             # 直接拒绝
    SPECIAL_APPROVAL = "special_approval"  # 标记特殊审批
    WARN = "warn"                 # 仅警告
    FLAG = "flag"                 # 标记供人工审核


@dataclass
class PolicyRule:
    """单条报销政策规则"""
    rule_id: str                                    # 规则编号（如 R001）
    level: RuleLevel                                # 规则层级
    title: str                                      # 规则名称（如"差旅住宿标准"）
    condition: dict                                 # 触发条件
    limit: float                                    # 金额上限
    unit: str = "per_request"                       # 限额单位（per_request/per_day/per_person）
    message: str = ""                               # 超标提示（含格式模板）
    action: str = RuleAction.WARN                   # 超标动作
    overridable: bool = True                        # 是否可被高级审批人豁免
    requires_evidence: bool = False                 # 是否需要上传证明材料
    applicable_departments: list[str] = field(default_factory=list)  # 适用部门（空=全部）

    def check(self, amount: float, expense_type: str, department: str) -> dict:
        """
        检查一次报销申请是否违反本规则。

        Returns:
            {"violated": True/False, "message": "...", "action": "...", "severity": "critical/warning/info"}
        """
        cond_type = self.condition.get("expense_type", "")
        if cond_type and cond_type != expense_type:
            return {"violated": False, "message": "", "action": "", "severity": ""}

        if self.applicable_departments and department not in self.applicable_departments:
            return {"violated": False, "message": "", "action": "", "severity": ""}

        exceeded = amount > self.limit
        if not exceeded:
            return {"violated": False, "message": "", "action": "", "severity": ""}

        severity_map = {
            RuleLevel.HARD_REJECT: "critical",
            RuleLevel.SOFT_LIMIT: "warning",
            RuleLevel.ADVISORY: "info",
            RuleLevel.DEPARTMENTAL: "warning",
        }

        msg = self.message.format(
            amount=amount, limit=self.limit, unit=self.unit,
            expense_type=expense_type, department=department,
        )

        return {
            "violated": True,
            "rule_id": self.rule_id,
            "level": self.level.name,
            "message": msg,
            "action": self.action,
            "severity": severity_map.get(self.level, "warning"),
            "overridable": self.overridable,
            "requires_evidence": self.requires_evidence,
        }


# =============================================================================
# 企业报销政策库（可按需从数据库/配置文件加载）
# =============================================================================
REIMBURSEMENT_POLICIES: list[PolicyRule] = [

    # ===== Level 1: 硬拒绝（不可豁免）=====
    PolicyRule(
        rule_id="R001",
        level=RuleLevel.HARD_REJECT,
        title="单次报销总金额上限",
        condition={"expense_type": ""},
        limit=50000,
        unit="per_request",
        message="单次报销总金额不得超过 ¥{limit:,.0f}，当前 ¥{amount:,.2f} 超出硬限制。请拆分报销或联系财务总监。",
        action=RuleAction.REJECT,
        overridable=False,
    ),

    # ===== Level 2: 软限制（需特殊审批）=====
    # 差旅
    PolicyRule(rule_id="R101", level=RuleLevel.SOFT_LIMIT, title="差旅费单次上限",
               condition={"expense_type": "travel"}, limit=10000, unit="per_request",
               message="差旅费单次上限为 ¥{limit:,.0f}，当前 ¥{amount:,.2f} 超出标准。请上传出差审批单。",
               action=RuleAction.SPECIAL_APPROVAL, requires_evidence=True),
    PolicyRule(rule_id="R102", level=RuleLevel.SOFT_LIMIT, title="差旅住宿日标准",
               condition={"expense_type": "travel"}, limit=500, unit="per_day",
               message="差旅住宿日标准为 ¥{limit:,.0f}/天，当前日均为 ¥{amount:,.2f}。超标部分需自付或特批。",
               action=RuleAction.SPECIAL_APPROVAL, overridable=True),
    # 招待
    PolicyRule(rule_id="R103", level=RuleLevel.SOFT_LIMIT, title="招待费单次上限",
               condition={"expense_type": "entertainment"}, limit=3000, unit="per_request",
               message="招待费单次上限为 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。请说明招待必要性。",
               action=RuleAction.SPECIAL_APPROVAL, requires_evidence=True),
    PolicyRule(rule_id="R104", level=RuleLevel.SOFT_LIMIT, title="招待费人均标准",
               condition={"expense_type": "entertainment"}, limit=200, unit="per_person",
               message="招待费人均标准为 ¥{limit:,.0f}，当前人均 ¥{amount:,.2f}。超标部分需主管审批。",
               action=RuleAction.SPECIAL_APPROVAL, overridable=True),
    # 通信
    PolicyRule(rule_id="R105", level=RuleLevel.SOFT_LIMIT, title="通信费月度上限",
               condition={"expense_type": "communication"}, limit=500, unit="per_month",
               message="通信费月度上限为 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。超出部分需部门经理特批。",
               action=RuleAction.SPECIAL_APPROVAL),
    # 会议
    PolicyRule(rule_id="R106", level=RuleLevel.SOFT_LIMIT, title="会议费单次上限",
               condition={"expense_type": "meeting"}, limit=8000, unit="per_request",
               message="会议费单次上限为 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。请提供会议议程。",
               action=RuleAction.SPECIAL_APPROVAL, requires_evidence=True),
    # 培训
    PolicyRule(rule_id="R107", level=RuleLevel.SOFT_LIMIT, title="培训费单次上限",
               condition={"expense_type": "training"}, limit=5000, unit="per_request",
               message="培训费单次上限为 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。请提供培训通知。",
               action=RuleAction.SPECIAL_APPROVAL),

    # ===== Level 3: 建议性规则 =====
    PolicyRule(rule_id="R201", level=RuleLevel.ADVISORY, title="办公费单品上限",
               condition={"expense_type": "office"}, limit=5000, unit="per_request",
               message="办公费单品建议不超过 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。请确认是否为必需采购。",
               action=RuleAction.FLAG),
    PolicyRule(rule_id="R202", level=RuleLevel.ADVISORY, title="其他费用上限",
               condition={"expense_type": "other"}, limit=2000, unit="per_request",
               message="其他类费用建议不超过 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。请补充详细说明。",
               action=RuleAction.WARN),
    PolicyRule(rule_id="R203", level=RuleLevel.ADVISORY, title="市内交通费上限",
               condition={"expense_type": "transport"}, limit=300, unit="per_request",
               message="市内交通费建议不超过 ¥{limit:,.0f}，当前 ¥{amount:,.2f}。",
               action=RuleAction.WARN),

    # ===== Level 4: 部门专项规则 =====
    # 研发部
    PolicyRule(rule_id="R301", level=RuleLevel.DEPARTMENTAL, title="研发部差旅专项额度",
               condition={"expense_type": "travel"}, limit=15000, unit="per_request",
               message="研发部差旅专项额度 ¥{limit:,.0f}。",
               action=RuleAction.WARN, applicable_departments=["研发部"]),
    PolicyRule(rule_id="R302", level=RuleLevel.DEPARTMENTAL, title="研发材料费上限",
               condition={"expense_type": "rd_materials"}, limit=20000, unit="per_request",
               message="研发材料费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["研发部"]),
    PolicyRule(rule_id="R303", level=RuleLevel.DEPARTMENTAL, title="研发设备费上限",
               condition={"expense_type": "rd_equipment"}, limit=50000, unit="per_request",
               message="研发设备费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["研发部"]),
    # 技术部
    PolicyRule(rule_id="R304", level=RuleLevel.DEPARTMENTAL, title="技术引进费上限",
               condition={"expense_type": "tech_acquisition"}, limit=100000, unit="per_request",
               message="技术引进费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["技术部"]),
    PolicyRule(rule_id="R305", level=RuleLevel.DEPARTMENTAL, title="软件许可费上限",
               condition={"expense_type": "software_license"}, limit=30000, unit="per_year",
               message="软件许可费年度上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["技术部"]),
    # 市场部
    PolicyRule(rule_id="R306", level=RuleLevel.DEPARTMENTAL, title="广告推广费上限",
               condition={"expense_type": "advertisement"}, limit=50000, unit="per_request",
               message="广告推广费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["市场部"]),
    PolicyRule(rule_id="R307", level=RuleLevel.DEPARTMENTAL, title="展会费上限",
               condition={"expense_type": "exhibition"}, limit=30000, unit="per_request",
               message="展会费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["市场部"]),
    # 人事部
    PolicyRule(rule_id="R308", level=RuleLevel.DEPARTMENTAL, title="人事部招待专项额度",
               condition={"expense_type": "entertainment"}, limit=1500, unit="per_request",
               message="人事部招待费额度 ¥{limit:,.0f}，当前 ¥{amount:,.2f} 超标。",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["人事部"]),
    PolicyRule(rule_id="R309", level=RuleLevel.DEPARTMENTAL, title="招聘费上限",
               condition={"expense_type": "recruitment"}, limit=10000, unit="per_request",
               message="招聘费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["人事部"]),
    # 行政部
    PolicyRule(rule_id="R310", level=RuleLevel.DEPARTMENTAL, title="办公室装修费上限",
               condition={"expense_type": "renovation"}, limit=50000, unit="per_request",
               message="办公室装修费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["行政部"]),
    # 财务部
    PolicyRule(rule_id="R311", level=RuleLevel.DEPARTMENTAL, title="审计服务费上限",
               condition={"expense_type": "audit"}, limit=20000, unit="per_request",
               message="审计服务费上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["财务部"]),
    # 运维部
    PolicyRule(rule_id="R312", level=RuleLevel.DEPARTMENTAL, title="云服务费月度上限",
               condition={"expense_type": "cloud_service"}, limit=20000, unit="per_month",
               message="云服务费月度上限 ¥{limit:,.0f}，当前 ¥{amount:,.2f}",
               action=RuleAction.SPECIAL_APPROVAL, applicable_departments=["运维部"]),
]


# =============================================================================
# 政策检查主函数
# =============================================================================
def evaluate_policies(
    amount: float,
    expense_type: str,
    department: str,
    guest_count: int = 0,
) -> dict:
    """
    对一次报销申请执行全部政策规则检查。

    Args:
        amount       : 报销总金额
        expense_type : 费用类型
        department   : 部门名称
        guest_count  : 招待人数（用于计算人均）

    Returns:
        {
            "passed": True/False,          # 是否通过所有硬限制
            "violations": [...],            # 违规规则列表
            "max_severity": "critical",     # 最高严重级别
            "requires_special_approval": bool,
            "requires_evidence": bool,
            "action_required": "reject|special_approval|warn|none",
        }
    """
    violations = []
    max_severity = "info"
    action_required = "none"

    for rule in REIMBURSEMENT_POLICIES:
        # 计算实际检查金额
        check_amount = amount
        if rule.unit == "per_person" and guest_count > 0:
            check_amount = amount / guest_count

        result = rule.check(check_amount, expense_type, department)

        if result["violated"]:
            violations.append(result)

            # 追踪最高严重级别
            severity_order = {"critical": 3, "warning": 2, "info": 1, "": 0}
            if severity_order.get(result["severity"], 0) > severity_order.get(max_severity, 0):
                max_severity = result["severity"]

            # 确定最终动作
            action_priority = {"reject": 3, "special_approval": 2, "flag": 1, "warn": 0, "none": -1}
            if action_priority.get(result["action"], -1) > action_priority.get(action_required, -1):
                action_required = result["action"]

    passed = action_required != "reject"

    return {
        "passed": passed,
        "violations": violations,
        "violation_count": len(violations),
        "max_severity": max_severity,
        "requires_special_approval": action_required in ("special_approval", "reject"),
        "requires_evidence": any(v.get("requires_evidence", False) for v in violations),
        "action_required": action_required,
        "summary": (
            "✅ 全部合规" if not violations
            else f"⚠️ {len(violations)} 条规则违规（最高:{max_severity}），需执行:{action_required}"
        ),
    }
