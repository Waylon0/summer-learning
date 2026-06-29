export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
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

export interface InvoiceInfo {
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
  action: string;
  comment?: string;
  acted_at?: string;
}

export interface BudgetInfo {
  id: string;
  department: string;
  annual_budget: number;
  used_amount: number;
  remaining: number;
  fiscal_year: number;
  usage_rate: number;
}

export interface UploadResult {
  filename: string;
  object_name: string;
  size: number;
  status: string;
}
