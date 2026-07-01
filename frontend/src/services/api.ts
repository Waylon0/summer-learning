import axios, { AxiosError } from 'axios';
import type {
  ChatRequest, ChatResponse,
  CreateReimbursementRequest,
  ReimbursementRecord,
  BudgetInfo,
  UploadResult,
  ApprovalRequest,
  ApprovalRecord,
  HealthStatus,
  ApiError,
} from '@/types';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// 统一错误拦截: 将后端标准错误格式转为可读消息
api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<ApiError>) => {
    const detail = err.response?.data;
    if (detail?.message) {
      const code = detail.error_code ? `[${detail.error_code}] ` : '';
      return Promise.reject(new Error(`${code}${detail.message}`));
    }
    return Promise.reject(err);
  },
);

// ========== 健康检查 ==========

const healthApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL?.replace(/\/api\/v1$/, '') || '',
  timeout: 5000,
});

export async function healthCheck(): Promise<HealthStatus> {
  const res = await healthApi.get<HealthStatus>('/health');
  return res.data;
}

// ========== Agent 对话 ==========

export async function sendChatMessage(data: ChatRequest): Promise<ChatResponse> {
  const res = await api.post<ChatResponse>('/chat', data);
  return res.data;
}

// ========== 报销单 CRUD ==========

export async function createReimbursement(data: CreateReimbursementRequest): Promise<ReimbursementRecord> {
  const res = await api.post<ReimbursementRecord>('/reimbursements', data);
  return res.data;
}

export async function getReimbursements(params?: {
  user_id?: string; status?: string; limit?: number;
}): Promise<ReimbursementRecord[]> {
  const res = await api.get<ReimbursementRecord[]>('/reimbursements', { params });
  return res.data;
}

export async function getReimbursement(id: string): Promise<ReimbursementRecord> {
  const res = await api.get<ReimbursementRecord>(`/reimbursements/${id}`);
  return res.data;
}

// ========== 预算 ==========

export async function getAllBudgets(): Promise<BudgetInfo[]> {
  const res = await api.get<BudgetInfo[]>('/budget');
  return res.data;
}

export async function getDepartmentBudget(dept: string): Promise<BudgetInfo> {
  const res = await api.get<BudgetInfo>(`/budget/${encodeURIComponent(dept)}`);
  return res.data;
}

// ========== 文件上传 ==========

export async function uploadInvoice(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await api.post<UploadResult>('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

// ========== 审批操作 ==========

export async function submitApproval(data: ApprovalRequest): Promise<ApprovalRecord> {
  const res = await api.post<ApprovalRecord>('/approval', data);
  return res.data;
}
