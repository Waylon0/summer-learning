# ReimburseAgent 后端 API 文档

> Base URL: `http://localhost:8000`  
> Swagger UI: `http://localhost:8000/docs`  

---

## 目录
1. [通用说明](#通用说明)
2. [健康检查](#1-健康检查)
3. [Agent 对话](#2-agent-对话)
4. [报销单 CRUD](#3-报销单-crud)
5. [部门预算](#4-部门预算)
6. [文件上传](#5-文件上传)
7. [审批操作](#6-审批操作)

---

## 通用说明

### 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Content-Type` | 是 | `application/json`（上传文件用 `multipart/form-data`） |
| `X-Request-ID` | 否 | 请求追踪 ID，不传则后端自动生成 |

### 错误响应格式

所有异常返回统一结构：

```json
{
  "error": true,
  "error_code": "NOT_FOUND",
  "message": "人类可读的错误描述",
  "detail": {}
}
```

| 状态码 | error_code | 含义 |
|--------|-----------|------|
| 400 | `BUSINESS_ERROR` | 业务规则校验失败 |
| 400 | `COMPLIANCE_VIOLATION` | 报销金额超标准 |
| 400 | `BUDGET_EXCEEDED` | 部门预算不足 |
| 400 | `FILE_VALIDATION_ERROR` | 文件类型/大小不符合要求 |
| 400 | `INVALID_APPROVAL_ACTION` | 无效的审批动作 |
| 404 | `NOT_FOUND` | 资源不存在（报销单/预算） |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 |
| 500 | `AGENT_EXECUTION_ERROR` | Agent 工作流执行失败 |
| 503 | `SERVICE_UNAVAILABLE` | 外部服务不可用 |

---

## 1. 健康检查

### GET /health

检测服务运行状态和数据库连通性。

**请求示例**
```
GET http://localhost:8000/health
```

**成功响应** `200`
```json
{
  "status": "ok",
  "version": "0.2.0",
  "database": "connected",
  "llm_model": "deepseek-chat"
}
```

**降级响应** `200`（数据库不通）
```json
{
  "status": "degraded",
  "version": "0.2.0",
  "database": "disconnected",
  "llm_model": "deepseek-chat"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `ok` = 正常, `degraded` = 数据库不通 |
| database | string | `connected` / `disconnected` |
| llm_model | string | 当前配置的大模型名称 |

---

## 2. Agent 对话

### POST /api/v1/chat

向智能报销助手发送消息，返回完整回复。

**请求体**
```json
{
  "message": "我要报销差旅费1500元，部门技术部",
  "session_id": "abc123",
  "attachments": ["invoices/a1b2c3.pdf"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | **是** | 用户输入文本 |
| session_id | string | 否 | 会话 ID（不传则自动生成） |
| attachments | string[] | 否 | 已上传的票据文件路径（MinIO object_name） |

**成功响应** `200`
```json
{
  "reply": "📧 报销单已提交审批！\n审批流程: 部门经理 → 财务审核 → 出纳付款",
  "session_id": "abc123",
  "intent": "new_reimbursement",
  "entities": {
    "department": "技术部",
    "expense_type": "travel",
    "total_amount": 1500.0
  },
  "tool_calls": null
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| reply | string | Agent 回复文本（支持换行符 `\n`） |
| session_id | string | 会话 ID（多轮对话时保持一致） |
| intent | string | 识别的意图：`new_reimbursement` / `query_status` / `general_question` |
| entities | object | 提取的实体：department（部门）、expense_type（费用类型）、total_amount（金额） |
| tool_calls | object\|null | 工具调用记录（当前未启用） |

**intent 枚举值**

| 值 | 含义 | 触发关键词 |
|----|------|-----------|
| `new_reimbursement` | 新建报销 | 报销、申请、差旅、招待、办公 |
| `query_status` | 查询进度 | 查询、进度、状态、审批 |
| `general_question` | 一般问题 | 你好、费用标准等 |

**错误响应**

| 状态码 | error_code | 场景 |
|--------|-----------|------|
| 500 | `AGENT_EXECUTION_ERROR` | Agent 工作流执行异常 |

---

### POST /api/v1/chat/stream

SSE（Server-Sent Events）流式对话，实时推送处理进度。

**请求体** — 同 `POST /api/v1/chat`

**响应** `200`（`text/event-stream`）

SSE 事件流格式，每行以 `data: ` 开头，两个 `\n` 结尾：

```
data: {"type":"intent","intent":"new_reimbursement","session_id":"abc123"}

data: {"type":"message","content":"✅ 票据识别完成，已提取发票信息。"}

data: {"type":"message","content":"📄 报销单已生成，总金额: ¥1,500"}

data: {"type":"message","content":"📧 报销单已提交审批！"}

data: {"type":"done","session_id":"abc123"}
```

**SSE 事件类型**

| type | 说明 |
|------|------|
| `intent` | 意图识别结果 |
| `message` | Agent 工作流中间消息（可能多条） |
| `done` | 处理完成 |
| `error` | 处理异常 |

**前端接收示例（JavaScript）**
```javascript
const response = await fetch("http://localhost:8000/api/v1/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "我要报销差旅费1500元" })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split("\n");
  buffer = lines.pop();

  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const event = JSON.parse(line.slice(6));
      if (event.type === "message") {
        console.log(event.content);
      } else if (event.type === "done") {
        console.log("完成, session_id:", event.session_id);
      } else if (event.type === "error") {
        console.error(event.content);
      }
    }
  }
}
```

---

## 3. 报销单 CRUD

### POST /api/v1/reimbursements

创建一条新的报销申请。

**请求体**
```json
{
  "user_id": "user001",
  "user_name": "张三",
  "department": "技术部",
  "expense_type": "travel",
  "description": "去上海参加技术峰会",
  "invoices": [
    {
      "invoice_code": "044001900111",
      "invoice_number": "87654321",
      "amount": 1500.00,
      "invoice_date": "2026-06-15",
      "seller_name": "某某科技有限公司",
      "buyer_name": "中国石油华东分公司"
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | **是** | 申请人 ID |
| user_name | string | **是** | 申请人姓名 |
| department | string | **是** | 部门名称（如"技术部"） |
| expense_type | string | **是** | 费用类型 |
| description | string | 否 | 报销说明 |
| invoices | object[] | 否 | 发票列表 |

**expense_type 枚举值**

| 值 | 含义 | 限额 |
|----|------|------|
| `travel` | 差旅费 | 单次上限 ¥10,000 |
| `entertainment` | 招待费 | 单次上限 ¥3,000 |
| `office` | 办公费 | 单品上限 ¥5,000 |
| `other` | 其他 | 单次上限 ¥2,000 |

**发票对象 InvoiceInfo**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| invoice_code | string | 否 | 发票代码 |
| invoice_number | string | 否 | 发票号码 |
| amount | float | 否 | 发票金额 |
| invoice_date | string | 否 | 开票日期 |
| seller_name | string | 否 | 销售方 |
| buyer_name | string | 否 | 购买方 |

**成功响应** `200`
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "user001",
  "user_name": "张三",
  "department": "技术部",
  "expense_type": "travel",
  "total_amount": 1500.0,
  "description": "去上海参加技术峰会",
  "invoice_count": 1,
  "need_special_approval": false,
  "budget_remaining_after": 298500.0,
  "status": "pending",
  "created_at": "2026-06-30T10:30:00+08:00",
  "updated_at": "2026-06-30T10:30:00+08:00",
  "invoices": [
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "reimbursement_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "invoice_code": "044001900111",
      "invoice_number": "87654321",
      "amount": 1500.0,
      "invoice_date": "2026-06-15",
      "seller_name": "某某科技有限公司",
      "buyer_name": "中国石油华东分公司",
      "file_path": null
    }
  ],
  "approvals": []
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string(UUID) | 报销单唯一标识 |
| total_amount | float | 所有发票金额之和 |
| invoice_count | int | 发票张数 |
| need_special_approval | bool | 是否预算超标需特殊审批 |
| budget_remaining_after | float\|null | 报销后部门剩余预算 |
| status | string | 当前状态 |
| invoices | object[] | 关联的发票明细 |
| approvals | object[] | 关联的审批记录 |

**status 状态流转**

```
pending（待审批） → approved（已通过）→ paid（已付款）
                  → rejected（已驳回）
                  → returned（已退回）
```

**错误响应**

| 状态码 | error_code | 场景 |
|--------|-----------|------|
| 404 | `NOT_FOUND` | 部门预算数据不存在 |

---

### GET /api/v1/reimbursements/{id}

根据 ID 查询单个报销单详情。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| id | string(UUID) | 报销单 ID |

**请求示例**
```
GET http://localhost:8000/api/v1/reimbursements/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**成功响应** `200` — 同 [POST 创建报销单](#post-apiv1reimbursements) 的响应结构

**错误响应**

| 状态码 | error_code | 场景 |
|--------|-----------|------|
| 404 | `NOT_FOUND` | 报销单不存在 |

---

### GET /api/v1/reimbursements

查询报销单列表，支持按用户、状态筛选。

**查询参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| user_id | string | 否 | — | 按申请人 ID 筛选 |
| status | string | 否 | — | 按状态筛选（pending/approved/rejected/returned/paid） |
| limit | int | 否 | 50 | 最多返回条数 |

**请求示例**
```
GET http://localhost:8000/api/v1/reimbursements?status=pending&limit=10
GET http://localhost:8000/api/v1/reimbursements?user_id=user001
```

**成功响应** `200`
```json
[
  {
    "id": "a1b2c3d4-...",
    "user_name": "张三",
    "department": "技术部",
    "expense_type": "travel",
    "total_amount": 1500.0,
    "status": "pending",
    "invoices": [...],
    "approvals": [...]
  }
]
```

> 返回数组，每项结构同 [POST 创建报销单](#post-apiv1reimbursements) 的响应。

---

## 4. 部门预算

### GET /api/v1/budget

列出所有部门的预算信息。

**请求示例**
```
GET http://localhost:8000/api/v1/budget
```

**成功响应** `200`
```json
[
  {
    "id": "132946d3-ac50-4dbd-af77-dd295ca9ea99",
    "department": "技术部",
    "annual_budget": 500000.0,
    "used_amount": 200000.0,
    "remaining": 300000.0,
    "fiscal_year": 2026,
    "usage_rate": 40.0
  },
  {
    "id": "fa878328-db7c-4c4b-8b61-46b346805018",
    "department": "市场部",
    "annual_budget": 300000.0,
    "used_amount": 250000.0,
    "remaining": 50000.0,
    "fiscal_year": 2026,
    "usage_rate": 83.33
  }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string(UUID) | 预算记录 ID |
| department | string | 部门名称 |
| annual_budget | float | 年度预算总额 |
| used_amount | float | 已使用金额 |
| remaining | float | 剩余金额（annual_budget - used_amount） |
| fiscal_year | int | 财政年度 |
| usage_rate | float | 使用率（百分比，如 40.0 表示已使用 40%） |

---

### GET /api/v1/budget/{department}

查询单个部门的预算。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| department | string | 部门名称（需 URL 编码） |

**请求示例**
```
GET http://localhost:8000/api/v1/budget/%E6%8A%80%E6%9C%AF%E9%83%A8
GET http://localhost:8000/api/v1/budget/技术部
```

**成功响应** `200`
```json
{
  "id": "132946d3-ac50-4dbd-af77-dd295ca9ea99",
  "department": "技术部",
  "annual_budget": 500000.0,
  "used_amount": 200000.0,
  "remaining": 300000.0,
  "fiscal_year": 2026,
  "usage_rate": 40.0
}
```

**错误响应**

| 状态码 | error_code | 场景 |
|--------|-----------|------|
| 404 | `NOT_FOUND` | 部门预算不存在（如 "销售部"） |

---

## 5. 文件上传

### POST /api/v1/upload

上传发票/票据文件到 MinIO 对象存储。

**请求格式**: `multipart/form-data`

| 表单字段 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| file | file | **是** | 票据文件 |

**允许的文件类型**: `.pdf` `.png` `.jpg` `.jpeg` `.webp`  
**大小限制**: 最大 10MB

**请求示例（curl）**
```bash
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@/path/to/invoice.pdf"
```

**请求示例（JavaScript）**
```javascript
const form = new FormData();
form.append("file", fileInput.files[0]);

const response = await fetch("http://localhost:8000/api/v1/upload", {
  method: "POST",
  body: form
});
const data = await response.json();
```

**成功响应** `200`
```json
{
  "filename": "invoice.pdf",
  "object_name": "invoices/a1b2c3d4e5f6.pdf",
  "size": 24530,
  "status": "uploaded"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| filename | string | 原始文件名 |
| object_name | string | MinIO 存储路径（传给 `/chat` 的 attachments 字段） |
| size | int | 文件大小（字节） |
| status | string | `uploaded` = 上传成功 |

**错误响应**

| 状态码 | error_code | 场景 |
|--------|-----------|------|
| 400 | `FILE_VALIDATION_ERROR` | 文件类型不支持 / 超过 10MB |
| 503 | `SERVICE_UNAVAILABLE` | MinIO 服务不可用 |

---

## 6. 审批操作

### POST /api/v1/approval

提交审批操作（通过/驳回/退回）。

**请求体**
```json
{
  "reimbursement_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "approver": "张经理",
  "action": "approve",
  "comment": "费用合理，同意报销"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| reimbursement_id | string | **是** | 报销单 ID |
| approver | string | **是** | 审批人姓名 |
| action | string | **是** | 审批动作 |
| comment | string | 否 | 审批意见 |

**action 枚举值**

| 值 | 含义 | 对报销单状态的影响 |
|----|------|-------------------|
| `approve` | 通过 | status → `approved` |
| `reject` | 驳回 | status → `rejected` |
| `return` | 退回修改 | status → `returned` |

**成功响应** `200`
```json
{
  "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "reimbursement_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "approver": "张经理",
  "step": 1,
  "action": "approve",
  "comment": "费用合理，同意报销",
  "acted_at": "2026-06-30T14:00:00+08:00"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string(UUID) | 审批记录 ID |
| step | int | 审批步骤序号（第几步审批） |
| action | string | 审批动作 |
| acted_at | string(ISO8601) | 审批时间 |

**错误响应**

| 状态码 | error_code | 场景 |
|--------|-----------|------|
| 404 | `NOT_FOUND` | 报销单不存在 |
| 400 | `INVALID_APPROVAL_ACTION` | action 值无效（不是 approve/reject/return） |

---

## 附录：完整请求示例

### 完整报销流程

```bash
# 1. 健康检查
curl http://localhost:8000/health

# 2. 上传发票
curl -X POST http://localhost:8000/api/v1/upload -F "file=@invoice.pdf"
# → {"object_name": "invoices/abc123.pdf", ...}

# 3. Agent 对话提交报销
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"我要报销差旅费1500元，部门技术部","attachments":["invoices/abc123.pdf"]}'

# 4. 查看报销单
curl http://localhost:8000/api/v1/reimbursements?user_id=user001

# 5. 审批通过
curl -X POST http://localhost:8000/api/v1/approval \
  -H "Content-Type: application/json" \
  -d '{"reimbursement_id":"xxx","approver":"张经理","action":"approve","comment":"同意"}'

# 6. 查看部门预算
curl http://localhost:8000/api/v1/budget/技术部
```
