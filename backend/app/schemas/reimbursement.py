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
class InvoiceInfo(BaseModel):
    """单张发票的结构化信息"""
    invoice_code: Optional[str] = None       # 发票代码
    invoice_number: Optional[str] = None     # 发票号码
    amount: Optional[float] = None           # 发票金额
    invoice_date: Optional[str] = None       # 开票日期
    seller_name: Optional[str] = None        # 销售方
    buyer_name: Optional[str] = None         # 购买方


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


# =============================================================================
# 7. 状态查询
# =============================================================================
class StatusQuery(BaseModel):
    """报销进度查询参数"""
    reimbursement_id: Optional[str] = None   # 按报销单号查
    start_date: Optional[str] = None         # 按开始日期查
    end_date: Optional[str] = None           # 按结束日期查
