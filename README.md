# ReimburseAgent — 企业财务报销助手

基于 LangChain/LangGraph 的企业级智能报销助手，支持票据 OCR、合规审查、预算控制、报销单生成与邮件推送。

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + Ant Design X + ECharts |
| 后端 REST API | FastAPI (async) + SQLAlchemy 2.0 (async) + Alembic |
| 智能体引擎 | LangChain + LangGraph (状态机驱动的审批工作流) |
| 任务队列 | Celery + Redis (OCR/邮件/PDF 异步处理) |
| 数据库 | PostgreSQL 16 |
| 缓存 | Redis 7 |
| 文件存储 | MinIO (S3 兼容) |
| 向量检索 | Chroma (公司政策 RAG) |
| 反向代理 | Nginx |
| 包管理 | uv |
| 容器化 | Docker Compose |

## 架构概述

```
┌──────────┐     ┌─────────────────────────────────┐     ┌──────────────┐
│  React   │────▶│         FastAPI 后端              │────▶│  PostgreSQL  │
│  前端     │◀────│                                  │◀────│              │
│  :3000   │     │  ┌──────────┐  ┌──────────────┐  │     └──────────────┘
└──────────┘     │  │ API 路由  │  │  Agent 智能体 │  │     ┌──────────────┐
                 │  └─────┬────┘  │  ┌──────────┐ │  │     │    Redis     │
                 │        │       │  │ LangChain │ │  │────▶│  (Celery)    │
                 │  ┌─────▼────┐  │  │ LangGraph │ │  │     └──────────────┘
                 │  │ Service  │  │  ├──────────┤ │  │     ┌──────────────┐
                 │  │ 业务逻辑  │◀─┼──│ Tools     │ │  │     │    MinIO     │
                 │  └──────────┘  │  │ OCR/合规   │ │  │────▶│  (文件存储)   │
                 │                │  │ 预算/PDF   │ │  │     └──────────────┘
                 │                │  └──────────┘ │  │
                 │                └──────────────┘  │
                 └─────────────────────────────────┘
```

## 快速开始

```bash
# 1. 复制环境变量配置
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY 和 SMTP 配置

# 2. 启动全部服务
docker compose up -d

# 3. 初始化数据库
docker compose exec backend uv run alembic upgrade head

# 4. 导入模拟数据
docker compose exec backend uv run python seed_data/seed.py

# 5. 访问
# 前端:      http://localhost:3000
# API 文档:  http://localhost:8000/docs
# MinIO 控制台: http://localhost:9001 (minioadmin/minioadmin123)
```

## 本地开发 (不使用 Docker)

```bash
# 后端
cd backend
uv sync
cp ../.env.example ../.env  # 编辑 .env
uv run alembic upgrade head
uv run python seed_data/seed.py
uv run uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

## 项目结构

```
ReimburseAgent/
├── docker-compose.yml          # 服务编排 (PG + Redis + MinIO + 前后端 + Nginx)
├── nginx.conf                  # Nginx 反向代理
├── .env.example               # 环境变量模板
├── backend/
│   ├── pyproject.toml          # uv 项目配置
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py             # FastAPI 入口
│   │   ├── api/v1/             # REST API 路由层
│   │   │   ├── chat.py         #   POST /chat — Agent 对话 (SSE 流式)
│   │   │   ├── reimbursements.py # CRUD /reimbursements
│   │   │   ├── budget.py       #   GET  /budget/{dept_id}
│   │   │   ├── upload.py       #   POST /upload — 票据文件上传
│   │   │   └── approval.py     #   POST /approval — 模拟审批
│   │   ├── agent/              # 智能体层
│   │   │   ├── graph.py        #   LangGraph 状态机 (报销审批工作流)
│   │   │   ├── router.py       #   意图识别与工具路由
│   │   │   └── tools/          #   Agent 工具集
│   │   │       ├── ocr.py      #     票据 OCR 识别
│   │   │       ├── compliance.py #   合规审查
│   │   │       ├── budget_control.py # 预算池控制
│   │   │       ├── pdf_gen.py  #     报销单 PDF 生成
│   │   │       ├── email_send.py #   邮件推送
│   │   │       └── status.py   #     报销进度查询
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   │   ├── reimbursement.py
│   │   │   ├── department_budget.py
│   │   │   └── approval_record.py
│   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   ├── services/           # 业务逻辑层
│   │   │   ├── reimbursement_svc.py
│   │   │   ├── budget_svc.py
│   │   │   ├── ocr_svc.py
│   │   │   └── email_svc.py
│   │   └── core/
│   │       ├── config.py       #   pydantic-settings 配置
│   │       ├── database.py     #   async SQLAlchemy engine + session
│   │       └── celery_app.py   #   Celery 实例
│   ├── alembic/                # 数据库迁移
│   ├── tasks/                  # Celery 异步任务
│   │   ├── email_task.py
│   │   └── ocr_task.py
│   └── seed_data/              # 模拟数据脚本
│       └── seed.py
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx            # React 入口
│       ├── App.tsx             # 路由 + 布局
│       ├── pages/
│       │   ├── ChatReimbursement/  # Tab1: 对话报销
│       │   ├── Dashboard/          # Tab2: 报销看板
│       │   └── StatusQuery/        # Tab3: 进度查询
│       ├── components/             # 通用组件
│       ├── services/               # axios API 调用
│       ├── stores/                 # Zustand 状态管理
│       └── types/                  # TypeScript 类型
└── docs/
    └── ARCHITECTURE.md         # 详细架构文档
```
