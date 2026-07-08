"""
=============================================================================
app/agent/intent_registry.py — 意图定义注册中心（数据化，去硬编码）
=============================================================================
把「意图 → 关键词 / 例句 / 槽位 / 路由节点」集中为一份可配置的数据结构。
新增一个意图只需在此增加一条 IntentSpec，无需改动分类/路由等多处代码。

三种识别信号统一来源于本注册表:
  1. keywords  — 关键词快速匹配（规则层，最快）
  2. examples  — 典型例句，供「语义向量路由」做相似度匹配（NLP 层，抗表达变化）
  3. LLM       — classify_intent 里用本表自动生成 few-shot 提示词（语义层，最强）

这样三层用的是「同一份意图知识」，避免各处定义漂移。
=============================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.intents import PrimaryIntent, SubIntent


# =============================================================================
# 意图规格
# =============================================================================
@dataclass
class IntentSpec:
    """单个（子）意图的完整定义。"""
    primary: PrimaryIntent
    sub: SubIntent = SubIntent.NONE
    # 中文标签，用于日志/提示词可读性
    label: str = ""
    # 关键词（规则层快速匹配）；phrase=True 的词优先级更高（复合短语）
    keywords: list[str] = field(default_factory=list)
    priority_keywords: list[str] = field(default_factory=list)
    # 典型例句（语义向量路由的锚点，也用于 LLM few-shot）
    examples: list[str] = field(default_factory=list)
    # 该（子）意图额外需要的实体槽位
    extra_slots: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.primary.value}:{self.sub.value}"


# =============================================================================
# 意图注册表（唯一事实来源）
# =============================================================================
INTENT_SPECS: list[IntentSpec] = [
    # ---------------- 新建报销 ----------------
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_CREATE, sub=SubIntent.TRAVEL_EXPENSE,
        label="差旅报销",
        priority_keywords=["差旅费", "差旅", "出差"],
        keywords=["机票", "酒店", "住宿", "高铁", "动车", "车票", "路费"],
        examples=[
            "我要报销差旅费1500元",
            "上个月去北京出差的费用报一下",
            "帮我把出差的机票酒店报了",
            "申请一笔差旅报销，金额2000",
        ],
        extra_slots=["destination"],
    ),
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_CREATE, sub=SubIntent.ENTERTAINMENT_EXPENSE,
        label="招待报销",
        priority_keywords=["招待费", "招待", "宴请"],
        keywords=["请客", "商务宴请", "接待"],
        examples=[
            "报销一笔招待费3000元",
            "宴请客户花了2000报一下",
            "接待供应商的餐费怎么报",
        ],
        extra_slots=["guest_count", "guest_company"],
    ),
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_CREATE, sub=SubIntent.OFFICE_EXPENSE,
        label="办公报销",
        priority_keywords=["办公用品", "办公费"],
        keywords=["办公", "文具", "耗材", "采购", "打印", "复印"],
        examples=[
            "报销办公用品500元",
            "买文具的钱报一下",
            "采购了一批耗材要报销",
        ],
    ),
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_CREATE, sub=SubIntent.ADVANCE_REQUEST,
        label="预支申请",
        priority_keywords=["预支", "借款", "预借"],
        keywords=["备用金"],
        examples=[
            "我要预支5000元差旅备用金",
            "申请借款8000",
        ],
    ),
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_CREATE, sub=SubIntent.NONE,
        label="通用报销",
        keywords=["报销", "申请", "提交", "通信", "话费", "会议", "培训",
                  "研发材料", "研发设备", "技术引进", "软件许可", "广告",
                  "展会", "审计", "招聘", "装修", "云服务", "报账"],
        examples=[
            "我要报销一笔费用",
            "提交一个报销申请",
            "这笔钱怎么报销",
        ],
    ),

    # ---------------- 报销查询 ----------------
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_QUERY, sub=SubIntent.STATUS_CHECK,
        label="进度查询",
        priority_keywords=["进度", "审批进度"],
        keywords=["查询", "状态", "审批到哪"],
        examples=[
            "查询报销单6441a34d的进度",
            "我那笔报销审批到哪了",
            "看看这个单子的状态",
        ],
    ),
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_QUERY, sub=SubIntent.HISTORY_LIST,
        label="记录列表",
        priority_keywords=["我的报销", "报销记录"],
        keywords=["列出", "所有", "全部", "列表", "记录", "我的", "有哪些"],
        examples=[
            "列出我的所有报销记录",
            "我提交过哪些报销",
            "看看有哪些待审批的单子",
            "技术部金额超过5000的报销",
            "查询张三申请的已通过报销",
        ],
    ),
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_QUERY, sub=SubIntent.AMOUNT_SUMMARY,
        label="金额汇总",
        keywords=["汇总", "统计", "合计", "总额", "一共报了"],
        examples=[
            "统计一下我这个月报销总额",
            "汇总各部门的报销金额",
        ],
        extra_slots=["date_range"],
    ),

    # ---------------- 修改报销 ----------------
    IntentSpec(
        primary=PrimaryIntent.REIMBURSEMENT_MODIFY, sub=SubIntent.NONE,
        label="修改撤回",
        priority_keywords=["撤回", "撤销"],
        keywords=["修改", "更正", "取消报销", "删掉"],
        examples=[
            "撤回我刚提交的报销单",
            "把那笔报销取消掉",
            "修改一下报销金额",
        ],
        extra_slots=["reimbursement_id"],
    ),

    # ---------------- 政策咨询 ----------------
    IntentSpec(
        primary=PrimaryIntent.POLICY_INQUIRY, sub=SubIntent.EXPENSE_STANDARD,
        label="费用标准",
        priority_keywords=["报销标准", "费用标准", "标准是多少", "限额", "能报多少", "最多报", "最多能报"],
        keywords=["标准", "规定", "上限", "政策"],
        examples=[
            "差旅费报销标准是多少",
            "出差住宿最多能报多少钱",
            "招待费有什么限额",
        ],
    ),
    IntentSpec(
        primary=PrimaryIntent.POLICY_INQUIRY, sub=SubIntent.PROCESS_GUIDE,
        label="流程指引",
        priority_keywords=["报销流程"],
        keywords=["流程", "怎么报", "怎么申请", "步骤", "如何报销"],
        examples=[
            "报销的流程是怎样的",
            "第一次报销该怎么操作",
        ],
    ),
    IntentSpec(
        primary=PrimaryIntent.POLICY_INQUIRY, sub=SubIntent.DEPARTMENT_QUOTA,
        label="部门额度",
        keywords=["额度", "预算", "部门预算", "还剩多少"],
        examples=[
            "技术部还有多少预算",
            "我们部门的报销额度是多少",
        ],
        extra_slots=["department"],
    ),

    # ---------------- 票据识别（上传） ----------------
    IntentSpec(
        primary=PrimaryIntent.DOCUMENT_PARSE, sub=SubIntent.NONE,
        label="票据识别",
        priority_keywords=["识别发票", "识别票据", "识别一下"],
        keywords=["上传", "识别", "扫描", "解析发票"],
        examples=[
            "识别一下我上传的发票",
            "帮我扫描这张票据",
            "解析上传的发票内容",
        ],
        extra_slots=["file_path"],
    ),

    # ---------------- 票据生成 ----------------
    IntentSpec(
        primary=PrimaryIntent.INVOICE_GENERATE, sub=SubIntent.NONE,
        label="票据生成",
        priority_keywords=["生成发票", "生成票据", "生成pdf票据", "开具发票",
                           "开发票", "开票", "制作发票", "出具发票"],
        keywords=[],
        examples=[
            "帮我生成一张发票",
            "为这个报销单开一张票据",
            "制作一张1500元的差旅费发票",
            "能不能弄一张电子发票",
        ],
    ),

    # ---------------- 审批操作 ----------------
    IntentSpec(
        primary=PrimaryIntent.APPROVAL_ACTION, sub=SubIntent.NONE,
        label="审批操作",
        priority_keywords=["批准", "驳回", "退回"],
        keywords=["通过", "同意报销", "拒绝", "审批通过"],
        examples=[
            "通过这笔报销",
            "驳回6441a34d这个单子",
            "同意报销并备注费用合理",
        ],
        extra_slots=["reimbursement_id", "action"],
    ),

    # ---------------- 闲聊 ----------------
    IntentSpec(
        primary=PrimaryIntent.GENERAL_CHAT, sub=SubIntent.NONE,
        label="通用对话",
        keywords=["你好", "你是谁", "帮助", "能做什么", "谢谢"],
        examples=[
            "你好",
            "你能帮我做什么",
            "谢谢",
        ],
    ),
]


# =============================================================================
# 派生索引（供其它模块高效使用）
# =============================================================================
def get_all_examples() -> list[tuple[str, PrimaryIntent, SubIntent]]:
    """展开所有例句 → (例句, primary, sub)，供语义路由建索引。"""
    out = []
    for spec in INTENT_SPECS:
        for ex in spec.examples:
            out.append((ex, spec.primary, spec.sub))
    return out


def build_llm_fewshot() -> str:
    """根据注册表动态生成 LLM few-shot 示例块（避免提示词与注册表漂移）。"""
    lines = []
    for spec in INTENT_SPECS:
        if not spec.examples:
            continue
        ex = spec.examples[0]
        lines.append(f'用户: {ex}\n输出: {{"primary":"{spec.primary.value}","sub":"{spec.sub.value}"}}')
    return "\n".join(lines)


def find_spec(primary: PrimaryIntent, sub: SubIntent) -> IntentSpec | None:
    for spec in INTENT_SPECS:
        if spec.primary == primary and spec.sub == sub:
            return spec
    # 回退：同 primary 的 NONE 子意图
    for spec in INTENT_SPECS:
        if spec.primary == primary and spec.sub == SubIntent.NONE:
            return spec
    return None
