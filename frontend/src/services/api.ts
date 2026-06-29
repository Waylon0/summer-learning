import axios from 'axios';
import type {
  ChatRequest, ChatResponse,
  ReimbursementRecord,
  BudgetInfo,
  UploadResult,
} from '@/types';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

export async function sendChatMessage(data: ChatRequest): Promise<ChatResponse> {
  const res = await api.post<ChatResponse>('/chat', data);
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

export async function uploadInvoice(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await api.post<UploadResult>('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

export async function getAllBudgets(): Promise<BudgetInfo[]> {
  const res = await api.get<BudgetInfo[]>('/budget');
  return res.data;
}

export async function getDepartmentBudget(dept: string): Promise<BudgetInfo> {
  const res = await api.get<BudgetInfo>(`/budget/${dept}`);
  return res.data;
}

export async function submitApproval(data: {
  reimbursement_id: string;
  approver: string;
  action: string;
  comment?: string;
}): Promise<Record<string, unknown>> {
  const res = await api.post('/approval', data);
  return res.data;
}
