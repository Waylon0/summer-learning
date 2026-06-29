# ReimburseAgent 架构文档

## 1. 项目概述

ReimburseAgent 是一个企业级智能财务报销助手系统，基于大语言模型 (LLM) 和 LangGraph 状态机，实现从票据上传到审批完成的端到端报销自动化。

## 2. 系统架构

```
                          ┌──────────────┐
                          │    Nginx     │ :80 (生产)
                          └──────┬───────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  │
       ┌──────────┐      ┌──────────────┐          │
       │  React   │      │   FastAPI    │          │
       │  :3000   │◄────►│   :8000      │          │
       └──────────┘      └──────┬───────┘          │
                                │                  │
              ┌─────────────────┼──────────────────┤
              ▼                 ▼                  ▼
       ┌──────────┐     ┌──────────┐      ┌──────────┐
       │PostgreSQL│     │  Redis   │      │  MinIO   │
       │  :5432   │     │  :6379   │      │  :9000   │
       └──────────┘     └──────────┘      └──────────┘
```

### 2.1 请求处理流程

```
用户输入 ──► FastAPI /api/v1/chat
                │
                ▼
         LangGraph StateGraph
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
 classify    OCR 识别    预算控制
  intent     合规审查     PDF生成
    │           │           │
    └───────────┼───────────┘
                ▼
          响应返回前端
```

### 2.2 LangGraph 状态机流程

```
START
  │
  ▼
[classify_intent] ──► 意图分类 (new_reimbursement / query_status / general)
  │
  ├─ new_reimbursement ──► [ocr_invoice]      票据OCR识别
  │                            │
  │                            ▼
  │                        [compliance_review]  合规审查
  │                            │
  │                            ▼
  │                        [budget_control]     预算池检查
  │                            │
  │                  ┌─────────┴─────────┐
  │                  ▼                   ▼
  │           [special_approval]    [generate_pdf]
  │           预算超标特殊审批        生成报销单PDF
  │                  │                   │
  │                  └────────┬──────────┘
  │                           ▼
  │                       [send_email]     邮件推送审批
  │                           │
  │                           ▼
  │                          END
  │
  ├─ query_status ──► [query_status] ──► END
  │
  └─ general ──► [general_response] ──► END
```

## 3. 后端架构

### 3.1 分层设计

```
┌─────────────────────────────────────────┐
│              API 路由层 (api/v1/)         │
│  chat.py | reimbursements.py | budget.py │
│  upload.py | approval.py                │
├─────────────────────────────────────────┤
│              智能体层 (agent/)            │
│  graph.py (LangGraph) | tools/ (6 tools) │
├─────────────────────────────────────────┤
│            业务逻辑层 (services/)         │
│  ReimbursementService | BudgetService    │
│  ApprovalService | ocr_svc | email_svc  │
├─────────────────────────────────────────┤
│             数据模型层 (models/)          │
│  Reimbursement | Invoice | Budget |      │
│  ApprovalRecord (SQLAlchemy ORM)        │
├─────────────────────────────────────────┤
│             基础设施层 (core/)            │
│  config.py | database.py | celery_app.py │
└─────────────────────────────────────────┘
```

### 3.2 REST API 设计

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/chat` | Agent 对话接口 |
| POST | `/api/v1/reimbursements` | 创建报销单 |
| GET | `/api/v1/reimbursements/{id}` | 查询报销单详情 |
| GET | `/api/v1/reimbursements` | 列表查询 |
| GET | `/api/v1/budget/{department}` | 查询部门预算 |
| GET | `/api/v1/budget` | 所有部门预算 |
| POST | `/api/v1/upload` | 票据文件上传 |
| POST | `/api/v1/approval` | 提交审批操作 |

### 3.3 数据库 ER 图

```
┌──────────────────────┐       ┌──────────────────────┐
│   reimbursements     │       │   department_budget  │
├──────────────────────┤       ├──────────────────────┤
│ id (PK)              │       │ id (PK)              │
│ user_id              │       │ department (UNIQUE)  │
│ user_name            │       │ annual_budget        │
│ department           │       │ used_amount          │
│ expense_type         │       │ fiscal_year          │
│ total_amount         │       └──────────────────────┘
│ description          │
│ invoice_count        │       ┌──────────────────────┐
│ need_special_approval│       │   approval_records   │
│ budget_remaining_after│      ├──────────────────────┤
│ status               │       │ id (PK)              │
│ created_at           │       │ reimbursement_id (FK)│──┐
│ updated_at           │       │ approver             │  │
└──────────┬───────────┘       │ step                 │  │
           │                   │ action               │  │
           │ 1:N               │ comment              │  │
           ▼                   │ acted_at             │  │
┌──────────────────────┐       └──────────────────────┘  │
│      invoices        │                                 │
├──────────────────────┤       ◄─────────────────────────┘
│ id (PK)              │
│ reimbursement_id (FK)│──┐
│ invoice_code         │  │
│ invoice_number       │  │
│ amount               │  │
│ invoice_date         │  │
│ seller_name          │  │
│ buyer_name           │  │
│ file_path            │  │
└──────────────────────┘  │
                          │
       ◄──────────────────┘
```

## 4. 前端架构

### 4.1 组件树

```
App
├── Tabs
│   ├── ChatReimbursement (Tab 1)
│   │   └── ChatPanel + Upload + Input
│   ├── Dashboard (Tab 2)
│   │   └── Statistics + Budget Table
│   └── StatusQuery (Tab 3)
│       └── SearchForm + DetailView + Timeline
│
├── stores/ (Zustand)
│   └── appStore (sessionId, messages, currentReimb)
│
└── services/ (Axios)
    └── api.ts (chat, reimb CRUD, budget, upload, approval)
```

### 4.2 技术栈详情

| 类别 | 库 | 版本 | 用途 |
|------|---|------|------|
| UI 框架 | React | 19 | 组件化 UI |
| 组件库 | Ant Design | 5.22 | 表格/表单/上传/标签等 |
| AI 对话 | @ant-design/x | 1.0 | 聊天气泡/流式渲染 |
| 图表 | @antv/g2 | 5.2 | 预算统计图表 |
| 状态管理 | Zustand | 5.0 | 轻量全局状态 |
| HTTP | Axios | 1.7 | API 请求 |
| 路由 | React Router | 7 | SPA 路由 |
| 构建 | Vite | 6 | 开发/构建工具 |

## 5. 部署架构

### 5.1 开发环境

```bash
# 后端
cd backend && uv sync && uv run uvicorn app.main:app --reload

# 前端
cd frontend && npm install && npm run dev

# 基础设施
docker compose up postgres redis minio -d
```

### 5.2 生产环境

```bash
docker compose --profile production up -d
# 启动: PostgreSQL + Redis + MinIO + Backend + Celery + Frontend + Nginx
```

### 5.3 容器拓扑

```
┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐
│ postgres │  │  redis  │  │  minio   │  │ backend  │  │ celery   │  │ frontend│
│  :5432   │  │  :6379  │  │ :9000/01 │  │  :8000   │  │  worker  │  │  :3000  │
└─────────┘  └─────────┘  └──────────┘  └──────────┘  └──────────┘  └─────────┘
```

## 6. 智能体工具集

| 工具 | 函数 | 描述 |
|------|------|------|
| OCR 识别 | `ocr_recognize_invoice` | 识别上传的票据文件(图片/PDF)，提取发票代码、号码、金额、日期等 |
| 合规审查 | `compliance_check` | 校验报销金额是否在公司差旅/招待/办公费用标准内 |
| 预算控制 | `budget_check` | 查询部门预算余额，超标自动标记 need_special_approval |
| PDF 生成 | `generate_reimbursement_pdf` | 将报销信息渲染为标准化 PDF 报销单 |
| 邮件推送 | `send_approval_email` | 使用 SMTP 将报销单 PDF 发送给审批人 |
| 进度查询 | `query_reimbursement_status` | 查询报销单审批流转状态 |

## 7. 安全设计

- **认证**: JWT Bearer Token (后续集成)
- **文件上传**: 10MB 限制，仅允许 PDF/PNG/JPG/JPEG
- **CORS**: 仅允许 localhost:3000
- **SQL 注入防护**: SQLAlchemy 参数化查询
- **敏感配置**: 通过环境变量 `.env` 注入，不提交至版本控制
