// ---------- 通用 ----------

export interface ApiError {
  error: true;
  error_code: string;
  message: string;
  detail: Record<string, unknown>;
}

// ---------- 健康检查 ----------

export interface HealthStatus {
  status: string;
  version: string;
  database: string;
  llm_model: string;
}

// ---------- 聊天 ----------

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  intent?: string;
  entities?: Record<string, unknown>;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  attachments?: string[];
}

export interface ChatResponse {
  reply: string;
  session_id: string;
  intent?: string;
  entities?: Record<string, unknown>;
  tool_calls?: Record<string, unknown>[];
}

// ---------- SSE 事件 ----------

export interface SSEEvent {
  type: 'intent' | 'message' | 'done' | 'error';
  content?: string;
  session_id?: string;
  intent?: string;
}

// ---------- 报销单 ----------

export interface CreateReimbursementRequest {
  user_id: string;
  user_name: string;
  department: string;
  expense_type: string;
  description?: string;
  invoices?: InvoiceInfo[];
}

export interface InvoiceInfo {
  id?: string;
  reimbursement_id?: string;
  invoice_code?: string;
  invoice_number?: string;
  amount?: number;
  invoice_date?: string;
  seller_name?: string;
  buyer_name?: string;
  file_path?: string;
}

export interface ReimbursementRecord {
  id: string;
  user_id: string;
  user_name: string;
  department: string;
  expense_type: string;
  total_amount: number;
  description?: string;
  invoice_count: number;
  need_special_approval: boolean;
  budget_remaining_after?: number;
  status: 'pending' | 'approved' | 'rejected' | 'returned' | 'paid';
  created_at?: string;
  updated_at?: string;
  invoices: InvoiceInfo[];
  approvals: ApprovalRecord[];
}

export interface ApprovalRecord {
  id: string;
  reimbursement_id: string;
  approver: string;
  step: number;
  action: 'approve' | 'reject' | 'return';
  comment?: string;
  acted_at?: string;
}

// ---------- 预算 ----------

export interface BudgetInfo {
  id: string;
  department: string;
  annual_budget: number;
  used_amount: number;
  remaining: number;
  fiscal_year: number;
  usage_rate: number;
}

// ---------- 文件上传 ----------

export interface UploadResult {
  filename: string;
  object_name: string;
  size: number;
  status: string;
}

// ---------- 审批 ----------

export interface ApprovalRequest {
  reimbursement_id: string;
  approver: string;
  action: 'approve' | 'reject' | 'return';
  comment?: string;
}
