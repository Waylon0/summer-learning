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

export interface ThinkingStep {
  kind: 'tool_call' | 'tool_result';
  tool: string;
  label: string;
  input?: Record<string, unknown>;
  output?: string;
  thought?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  intent?: string;
  entities?: Record<string, unknown>;
  thinking?: ThinkingStep[];
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

// ---------- 会话管理 ----------

export interface ConversationSummary {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
}

export interface ConversationMessageItem {
  id: string;
  seq: number;
  role: string;
  content: string;
  reasoning?: ThinkingStep[] | null;
  created_at?: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  messages: ConversationMessageItem[];
}

// ---------- SSE 事件 ----------

export interface SSEEvent {
  type: 'start' | 'thinking' | 'tool_call' | 'tool_result' | 'message' | 'done' | 'error';
  content?: string;
  session_id?: string;
  tool?: string;
  label?: string;
  input?: Record<string, unknown>;
  output?: string;
  thought?: string;
  message?: string;
  elapsed_ms?: number;
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

// ---------- 用户认证 ----------

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
  name: string;
  department: string;
  email?: string;
  role?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export interface UserInfo {
  id: string;
  username: string;
  name: string;
  email?: string;
  department: string;
  role: 'employee' | 'manager' | 'admin';
  is_active: boolean;
  created_at?: string;
}

// ---------- 费用统计 ----------

export interface TrendSeries {
  expense_type: string;
  label: string;
  data: number[];
}

export interface TrendResponse {
  months: string[];
  series: TrendSeries[];
}

export interface PersonalStatsResponse {
  user_name: string;
  current_month: { count: number; total: number };
  last_month: { count: number; total: number };
  status_breakdown: Record<string, number>;
}

export interface DepartmentRankingResponse {
  rankings: { department: string; total: number; budget: number; usage_rate: number }[];
}

export interface SummaryResponse {
  annual_budget_total: number;
  used_total: number;
  remaining_total: number;
  pending_count: number;
  this_month_total: number;
  last_month_total: number;
}

// ---------- 发票台账 ----------

export interface InvoiceRecord {
  id: string;
  invoice_code: string;
  invoice_number: string;
  amount: number;
  invoice_date: string;
  seller_name: string;
  buyer_name: string;
  expense_type: string;
  reimbursement_id: string;
  file_path?: string;
}

export interface InvoiceListResponse {
  total: number;
  items: InvoiceRecord[];
}

// ---------- 发票生成 ----------

export interface InvoiceLineItem {
  name: string;
  specification?: string;
  unit?: string;
  quantity?: number;
  unit_price?: number;
  amount: number;
  tax_rate?: string;
}

export interface InvoiceGenerateRequest {
  invoice_code?: string;
  invoice_number?: string;
  invoice_date?: string;
  invoice_type?: string;
  buyer_name?: string;
  buyer_tax_id?: string;
  seller_name: string;
  seller_tax_id?: string;
  amount?: number;
  tax_amount?: number;
  total_with_tax?: number;
  items?: InvoiceLineItem[];
  remarks?: string;
  payee?: string;
  reviewer?: string;
  drawer?: string;
}

export interface InvoiceGenerateResponse {
  invoice_number: string;
  invoice_code: string;
  object_name: string;
  download_url: string;
  total_with_tax: number;
  status: string;
}

// ---------- 单据中心 ----------

export interface PdfGenerateResponse {
  download_url: string;
  object_name: string;
  reimb_id: string;
}

export interface EmailSendResponse {
  sent: boolean;
  message: string;
}

// ---------- 流程演示 ----------

export interface FlowStep {
  key: string;
  title: string;
  description: string;
  status: 'wait' | 'process' | 'finish' | 'error';
  detail?: string;
}
