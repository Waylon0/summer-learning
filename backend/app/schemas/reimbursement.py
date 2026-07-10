"""
=============================================================================
app/schemas/reimbursement.py — 数据校验模型（Pydantic Schemas）
=============================================================================
Pydantic 的作用：在数据进入系统前做"安检"。

  比如前端发来 {"message": 123}，但 message 应该是字符串。
  Pydantic 会立即拦截并返回清晰的错误信息，而不是让错误藏在深层逻辑里。

本文件定义了前后端通信时使用的数据结构：
  1. ChatRequest / ChatResponse  — Agent 对话的请求和响应
  2. InvoiceInfo                 — 发票信息
  3. ReimbursementCreate         — 创建报销单时前端发来的数据
  4. ReimbursementResponse       — 返回给前端的报销单数据
  5. BudgetResponse              — 部门预算数据
  6. ApprovalAction              — 审批操作
  7. StatusQuery                 — 状态查询参数

小白理解：这些类就像合同的"条款模板"，不合规的数据根本进不来。
=============================================================================
"""
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import date, datetime
from typing import Optional


# =============================================================================
# 1. Agent 对话
# =============================================================================
class ChatRequest(BaseModel):
    """前端发送给 Agent 的对话请求"""
    message: str = Field(..., description="用户输入文本")                          # ... 表示必填
    session_id: Optional[str] = Field(None, description="会话ID")                 # None 表示可空
    attachments: Optional[list[str]] = Field(None, description="已上传的票据文件路径列表")


class ChatResponse(BaseModel):
    """Agent 返回给前端的对话响应"""
    reply: str                                                                   # Agent 的回复内容
    session_id: str                                                              # 会话 ID（用于多轮对话）
    intent: Optional[str] = None                                                 # 识别的意图
    entities: Optional[dict] = None                                              # 提取的实体（部门、金额等）
    tool_calls: Optional[list[dict]] = None                                      # 工具调用记录


# =============================================================================
# 2. 发票信息
# =============================================================================
class InvoiceLineItem(BaseModel):
    """发票明细行"""
    name: str = ""                       # 货物或应税劳务名称
    specification: str = ""              # 规格型号
    unit: str = ""                       # 单位
    quantity: float = 0.0                # 数量
    unit_price: float = 0.0              # 单价
    amount: float = 0.0                  # 金额
    tax_rate: str = ""                   # 税率 (如 "13%", "6%")


class InvoiceInfo(BaseModel):
    """发票结构化信息（兼容旧数据库 NULL 字段）"""
    invoice_code: str = ""
    invoice_number: str = ""
    invoice_date: str | None = None  # 旧数据可能为 NULL
    invoice_type: str = ""            # NULL 时默认空字符串

    buyer_name: str = ""
    buyer_tax_id: str = ""
    seller_name: str = ""
    seller_tax_id: str = ""

    amount: float = 0.0
    tax_amount: float = 0.0
    total_with_tax: float | None = None  # 旧数据可能为 NULL

    items: list[InvoiceLineItem] = []

    # 其他信息
    remarks: str = ""                    # 备注
    payee: str = ""                      # 收款人
    reviewer: str = ""                   # 复核人
    drawer: str = ""                     # 开票人

    # 文件路径
    file_path: str = ""                  # MinIO 存储路径


# =============================================================================
# 2b. 报销单 PDF 生成响应
# =============================================================================
# 说明：发票（invoice）在本系统中仅作为「输入数据」用于 OCR 提取，
#       系统对外生成的结构化单据是「报销单 PDF」。
class ReimbursementPdfResponse(BaseModel):
    """报销单 PDF 生成结果"""
    reimb_id: str                                 # 报销单号
    object_name: str                              # 存储对象路径
    download_url: str                             # 下载/预览地址
    total_amount: float                           # 报销总额
    status: str = "generated"                     # 生成状态


# =============================================================================
# 2c. 分步式报销（草稿 + 费用明细）请求
# =============================================================================
class DraftCreate(BaseModel):
    """创建报销单草稿"""
    expense_type: str = "travel"
    title: str = ""
    trip_destination: str = ""
    trip_start_date: Optional[str] = None
    trip_end_date: Optional[str] = None
    description: str = ""


class ExpenseItemCreate(BaseModel):
    """添加一条费用明细"""
    subtype: str                                   # flight/train/hotel/taxi/meal_allowance...
    amount: float = 0
    unit_price: float = 0
    quantity: float = 0
    description: str = ""
    occur_date: Optional[str] = None
    from_location: str = ""
    to_location: str = ""
    remark: str = ""                               # 超标说明（单价超标准时必填）
    attendee_count: int = 0                        # 招待人数（招待类）
    guest_info: str = ""                           # 招待对象/事由（招待类）
    currency: str = "CNY"                          # 币种（外币需提供 exchange_rate）
    exchange_rate: float = 0                        # 汇率（1 外币 = ? 人民币）


class ItemInvoiceCreate(BaseModel):
    """为明细行关联发票"""
    amount: float = 0
    invoice_code: str = ""
    invoice_number: str = ""
    invoice_date: Optional[str] = None
    seller_name: str = ""


# =============================================================================
# 3. 报销单创建请求
# =============================================================================
class ReimbursementCreate(BaseModel):
    """创建报销单时前端发来的数据"""
    user_id: str                                                      # 用户ID
    user_name: str                                                    # 用户姓名
    department: str                                                   # 部门名称
    expense_type: str                                                 # 费用类型
    description: Optional[str] = None                                 # 报销说明
    invoices: list[InvoiceInfo] = []                                  # 发票列表（可有多张）


# =============================================================================
# 4. 报销单响应
# =============================================================================
class ReimbursementResponse(BaseModel):
    """返回给前端的报销单完整数据"""
    id: str
    user_id: str
    user_name: str
    department: str
    expense_type: str
    total_amount: float                                               # 总金额
    description: Optional[str]
    invoice_count: int                                                # 发票张数
    need_special_approval: bool                                       # 是否需要特殊审批
    budget_remaining_after: Optional[float]                           # 报销后剩余预算
    status: str                                                       # 当前状态
    created_at: Optional[str]
    updated_at: Optional[str]
    invoices: list[InvoiceInfo] = []                                  # 关联的发票列表
    approvals: list[dict] = []                                        # 关联的审批记录


# =============================================================================
# 5. 部门预算
# =============================================================================
class BudgetResponse(BaseModel):
    """部门预算信息"""
    id: str
    department: str
    annual_budget: float                                              # 年度总额
    used_amount: float                                                # 已使用
    remaining: float                                                  # 剩余
    fiscal_year: int                                                  # 财政年度
    usage_rate: float                                                 # 使用率（百分比）


# =============================================================================
# 6. 审批操作
# =============================================================================
class ApprovalAction(BaseModel):
    """审批人提交的审批操作"""
    reimbursement_id: str                                             # 报销单ID
    approver: str                                                     # 审批人
    action: str = Field(..., description="approve / reject / return")  # 动作
    comment: Optional[str] = None                                     # 审批意见


class PaymentRequest(BaseModel):
    """出纳付款请求（approved → paid）"""
    reimbursement_id: str
    comment: Optional[str] = None


# =============================================================================
# 7. 状态查询
# =============================================================================
class StatusQuery(BaseModel):
    """报销进度查询参数"""
    reimbursement_id: Optional[str] = None   # 按报销单号查
    start_date: Optional[str] = None         # 按开始日期查
    end_date: Optional[str] = None           # 按结束日期查
