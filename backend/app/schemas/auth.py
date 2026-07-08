"""
=============================================================================
app/schemas/auth.py — 认证相关 Pydantic 模型
=============================================================================
"""
from pydantic import BaseModel, Field, field_validator
import re


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    name: str = Field(..., min_length=1, max_length=64, description="姓名")
    email: str | None = None
    department: str = Field(..., description="部门名称")
    role: str = Field(default="employee", description="角色: employee/manager/admin/finance")

    @field_validator("department")
    @classmethod
    def validate_department(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("部门不能为空")
        return v.strip()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: str
    username: str
    name: str
    email: str | None
    department: str
    role: str
    is_active: bool
    created_at: str | None
