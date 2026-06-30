# ReimburseAgent Backend — 依赖分析文档

## 依赖总览

共 **17 个运行时依赖** + 3 个开发依赖，全部由 `uv` 管理，声明于 `pyproject.toml`。

---

## 一、运行时依赖 (17 个)

### Web 框架层

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **fastapi** | >=0.115.0 | 异步 Web 框架，路由/中间件/依赖注入 | `fastapi`, `fastapi.middleware.cors`, `fastapi.responses` | `main.py`, `api/v1/*.py` |
| **uvicorn[standard]** | >=0.30.0 | ASGI 服务器 (uvloop + httptools) | CLI: `uvicorn app.main:app` | 仅运行命令，无代码导入 |

### 数据库层

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **sqlalchemy[asyncio]** | >=2.0.30 | 异步 ORM (引擎/会话/声明式基类) | `sqlalchemy`, `sqlalchemy.ext.asyncio`, `sqlalchemy.orm` | `database.py`, `models/`, `services/` |
| **asyncpg** | >=0.29.0 | PostgreSQL 异步驱动 (Docker 生产环境) | — (SQLAlchemy 自动加载) | 无直接导入 |
| **aiosqlite** | >=0.22.1 | SQLite 异步驱动 (本地无 Docker 开发) | — (SQLAlchemy 自动加载) | 无直接导入 |
| **alembic** | >=1.13.0 | 数据库迁移工具 | CLI: `alembic upgrade head` | `alembic/env.py`, `alembic.ini` |

### 数据校验与配置

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **pydantic** | >=2.7.0 | 请求/响应模型校验 | `pydantic` | `schemas/reimbursement.py` |
| **pydantic-settings** | >=2.3.0 | 环境变量加载与配置管理 | `pydantic_settings` | `core/config.py` |

### AI / 智能体引擎

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **langchain-core** | >=0.3.0 | 消息类型 (HumanMessage/AIMessage) | `langchain_core.messages` | `agent/graph.py`, `api/v1/chat.py` |
| **langchain-openai** | >=0.2.0 | OpenAI LLM 调用 (ChatOpenAI) | `langchain_openai` (懒加载) | `agent/graph.py` (_get_llm 函数内) |
| **langgraph** | >=0.2.0 | 有状态 Agent 工作流编排 | `langgraph.graph` | `agent/graph.py` |

### 任务队列与缓存

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **celery[redis]** | >=5.4.0 | 异步任务队列 (邮件/OCR/PDF) | `celery` | `core/celery_app.py`, `tasks/` |
| **redis** | >=5.0.0 | Celery broker + result backend | — (Celery 自动加载) | 无直接导入 |

### 文件存储

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **minio** | >=7.2.0 | S3 兼容对象存储 (票据/报销单文件) | `minio`, `minio.error` | `services/ocr_svc.py` |

### 邮件服务

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **aiosmtplib** | >=3.0.0 | 异步 SMTP 邮件发送 | `aiosmtplib` | `services/email_svc.py` |

### 文件处理

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **python-multipart** | >=0.9.0 | FastAPI 文件上传解析 (UploadFile) | — (FastAPI 自动加载) | `api/v1/upload.py` |
| **reportlab** | >=4.2.0 | PDF 报销单生成 | `reportlab.pdfgen`, `reportlab.lib.pagesizes` | `agent/tools/reimburse_tools.py` |

### 日志

| 包名 | 版本 | 用途 | 导入路径 | 调用文件 |
|------|------|------|----------|----------|
| **loguru** | >=0.7.0 | 结构化日志 (控制台 + 文件轮转) | `loguru` | `core/config.py`, `main.py`, `agent/graph.py`, `api/v1/chat.py`, `services/`, `tasks/` |

---

## 二、开发依赖 (3 个)

| 包名 | 版本 | 用途 |
|------|------|------|
| **pytest** | >=8.0.0 | 单元测试框架 |
| **pytest-asyncio** | >=0.23.0 | async 测试支持 |
| **httpx** | >=0.27.0 | FastAPI TestClient 异步 HTTP 测试 |

---

## 三、依赖关系图

```
fastapi ──────────────── Web 框架入口
  ├── uvicorn ────────── ASGI 服务器
  ├── python-multipart ── 文件上传解析
  ├── pydantic ────────── 数据校验
  ├── pydantic-settings ─ 配置管理
  └── sqlalchemy[asyncio] 异步 ORM
        ├── asyncpg ───── PostgreSQL 驱动 (生产)
        └── aiosqlite ─── SQLite 驱动 (本地开发)

langchain-core ────────── LLM 消息基类
langchain-openai ──────── OpenAI API 调用
langgraph ─────────────── Agent 状态机

celery[redis] ─────────── 异步任务队列
  └── redis ───────────── 消息代理

minio ────────────────── 对象存储 (票据文件)
aiosmtplib ─────────────── 邮件发送
reportlab ──────────────── PDF 生成
loguru ─────────────────── 日志系统

alembic ───────────────── 数据库迁移 (独立 CLI)
```

---

## 四、包审计记录

| 审计项 | 结果 |
|--------|------|
| 代码中使用的第三方包 | 全部已声明 ✅ |
| 声明的包是否被代码使用 | 已移除 4 个未使用包 (langchain/chromadb/langchain-chroma/pymupdf) ✅ |
| 直接导入 vs 传递依赖 | `langchain-core` 由传递升为显式声明 ✅ |
| 本地开发兼容性 | SQLite+aiosqlite 无 Docker 可运行 ✅ |
| 生产环境兼容性 | PostgreSQL+asyncpg Docker 部署 ✅ |
| uv.lock 一致性 | 已执行 `uv lock` → `uv sync` 验证通过 ✅ |
| 全模块导入测试 | 15 个模块全部导入成功 ✅ |

---

## 五、已移除的依赖 (及原因)

| 包名 | 原声明原因 | 移除原因 |
|------|-----------|----------|
| `langchain` | 初始设计用于 ReAct Agent | 仅用 `langchain-core` + `langgraph`，全量 `langchain` 未使用 |
| `chromadb` | 初始设计用于 RAG 政策文档检索 | 未实现 RAG 功能，配置中仅保留占位 |
| `langchain-chroma` | Chroma 的 LangChain 适配 | 随 chromadb 一同移除 |
| `pymupdf` | 初始设计用于 PDF 发票解析 | OCR 工具为 mock 实现，未实际调用 |

> 若后续实现 RAG 政策检索或真实 PDF 解析，可随时通过 `uv add chromadb langchain-chroma pymupdf` 恢复。
