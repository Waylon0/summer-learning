"""
=============================================================================
app/core/exceptions.py — 自定义异常体系
=============================================================================
定义项目专属的异常类，替代裸字符串和通用 Exception。

好处：
  1. 异常类型一眼就能看出是哪层出了问题
  2. 统一携带 HTTP 状态码，FastAPI 异常处理器直接映射
  3. 前端可以根据 error_code 做差异化处理

异常层级：
  ReimburseBaseException (基类)
    ├── NotFoundException        — 404 资源不存在
    ├── BusinessException        — 400 业务规则不满足
    ├── ServiceUnavailableException — 503 服务不可用
    └── InternalErrorException   — 500 内部错误
=============================================================================
"""


class ReimburseBaseException(Exception):
    """
    项目异常基类 —— 所有自定义异常都继承于此。

    属性:
        message    : 人类可读的错误消息（给前端展示）
        status_code: HTTP 状态码
        error_code : 机器可读的错误代码（给前端判断用）
        detail     : 详细信息字典（可选，调试用）
    """
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        detail: dict | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail or {}
        super().__init__(self.message)


# =============================================================================
# 404 — 资源不存在
# =============================================================================
class NotFoundException(ReimburseBaseException):
    """请求的资源不存在（报销单、部门预算等）"""
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} 不存在: {identifier}",
            status_code=404,
            error_code="NOT_FOUND",
            detail={"resource": resource, "identifier": identifier},
        )


class ReimbursementNotFoundError(NotFoundException):
    """报销单不存在"""
    def __init__(self, reimb_id: str):
        super().__init__(resource="报销单", identifier=reimb_id)


class BudgetNotFoundError(NotFoundException):
    """部门预算信息不存在"""
    def __init__(self, department: str):
        super().__init__(resource="部门预算", identifier=department)


# =============================================================================
# 400 — 业务规则不满足
# =============================================================================
class BusinessException(ReimburseBaseException):
    """业务规则校验失败"""
    def __init__(self, message: str, error_code: str = "BUSINESS_ERROR", detail: dict | None = None):
        super().__init__(
            message=message,
            status_code=400,
            error_code=error_code,
            detail=detail,
        )


class ComplianceViolationError(BusinessException):
    """合规审查不通过（金额超标准）"""
    def __init__(self, expense_type: str, amount: float, limit: float):
        super().__init__(
            message=f"{expense_type} 类费用 {amount} 元超过标准 {limit} 元",
            error_code="COMPLIANCE_VIOLATION",
            detail={"expense_type": expense_type, "amount": amount, "limit": limit},
        )


class BudgetExceededError(BusinessException):
    """部门预算超标"""
    def __init__(self, department: str, amount: float, remaining: float):
        super().__init__(
            message=f"部门 {department} 预算不足：申请 {amount} 元，剩余 {remaining} 元",
            error_code="BUDGET_EXCEEDED",
            detail={"department": department, "amount": amount, "remaining": remaining},
        )


class FileValidationError(BusinessException):
    """文件上传校验失败（类型/大小不符合）"""
    def __init__(self, message: str):
        super().__init__(message=message, error_code="FILE_VALIDATION_ERROR")


# =============================================================================
# 503 — 外部服务不可用
# =============================================================================
class ServiceUnavailableException(ReimburseBaseException):
    """依赖的外部服务暂时不可用"""
    def __init__(self, service: str, detail: str = ""):
        super().__init__(
            message=f"{service} 服务暂时不可用，请稍后重试" + (f": {detail}" if detail else ""),
            status_code=503,
            error_code="SERVICE_UNAVAILABLE",
            detail={"service": service},
        )


class LLMServiceError(ServiceUnavailableException):
    """大模型服务调用失败"""
    def __init__(self, detail: str = ""):
        super().__init__(service="大模型(LLM)", detail=detail)


class DatabaseServiceError(ServiceUnavailableException):
    """数据库连接失败"""
    def __init__(self, detail: str = ""):
        super().__init__(service="数据库", detail=detail)


class StorageServiceError(ServiceUnavailableException):
    """对象存储(MinIO)服务不可用"""
    def __init__(self, detail: str = ""):
        super().__init__(service="文件存储(MinIO)", detail=detail)


class EmailServiceError(ServiceUnavailableException):
    """邮件服务不可用"""
    def __init__(self, detail: str = ""):
        super().__init__(service="邮件", detail=detail)


# =============================================================================
# 500 — 内部错误
# =============================================================================
class InternalErrorException(ReimburseBaseException):
    """服务器内部错误（未知/未预期的错误）"""
    def __init__(self, message: str = "服务器内部错误", detail: dict | None = None):
        super().__init__(
            message=message,
            status_code=500,
            error_code="INTERNAL_ERROR",
            detail=detail,
        )


class AgentExecutionError(InternalErrorException):
    """Agent 工作流执行失败"""
    def __init__(self, detail: str = ""):
        super().__init__(
            message=f"智能体执行异常: {detail}",
            detail={"agent_error": detail},
        )
