"""
=============================================================================
app/api/v1/__init__.py — API 路由包导出
=============================================================================
统一导出所有 API 路由模块。
"""
from app.api.v1.chat import router as chat_router
from app.api.v1.reimbursements import router as reimb_router
from app.api.v1.budget import router as budget_router
from app.api.v1.upload import router as upload_router
from app.api.v1.approval import router as approval_router

__all__ = ["chat_router", "reimb_router", "budget_router", "upload_router", "approval_router"]
