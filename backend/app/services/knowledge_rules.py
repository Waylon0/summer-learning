"""
=============================================================================
app/services/knowledge_rules.py — 知识库文档标识/校验纯函数（无外部依赖）
=============================================================================
知识库管理模块（阶段二·方案 A 文件式）的输入校验逻辑下沉为纯函数，便于单测，
且集中所有“防路径遍历/防非法文件名”的安全判定。

约束（安全关键）：
  - doc_key 仅允许 [A-Za-z0-9_]，禁止 '/'、'.'、'..'、空白等 → 杜绝路径遍历。
  - 由 doc_key 推导的文件名固定为 {doc_key}.md（启用）或 {doc_key}.md.disabled（停用）。
=============================================================================
"""
from __future__ import annotations

import re

# doc_key 白名单：字母/数字/下划线，长度 1~64
_DOC_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

# 停用文件后缀（软删）
DISABLED_SUFFIX = ".md.disabled"
ENABLED_SUFFIX = ".md"


def is_valid_doc_key(doc_key: str) -> bool:
    """doc_key 是否合法（字母/数字/下划线，1~64 位）。杜绝路径遍历与隐藏字符。"""
    return bool(doc_key) and bool(_DOC_KEY_RE.match(doc_key))


def enabled_filename(doc_key: str) -> str:
    """启用态文件名。"""
    return f"{doc_key}{ENABLED_SUFFIX}"


def disabled_filename(doc_key: str) -> str:
    """停用态文件名（{doc_key}.md.disabled）。"""
    return f"{doc_key}{DISABLED_SUFFIX}"


def doc_key_from_filename(filename: str) -> str | None:
    """从文件名反解 doc_key。支持 {key}.md 与 {key}.md.disabled；非法返回 None。"""
    name = (filename or "").strip()
    if name.endswith(DISABLED_SUFFIX):
        key = name[: -len(DISABLED_SUFFIX)]
    elif name.endswith(ENABLED_SUFFIX):
        key = name[: -len(ENABLED_SUFFIX)]
    else:
        return None
    return key if is_valid_doc_key(key) else None


def is_disabled_filename(filename: str) -> bool:
    """该文件名是否为停用态（.md.disabled）。"""
    return (filename or "").endswith(DISABLED_SUFFIX)
