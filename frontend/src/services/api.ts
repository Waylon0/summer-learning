import axios, { AxiosError } from 'axios';
import type {
  ChatRequest, ChatResponse,
  ReimbursementRecord,
  BudgetInfo,
  UploadResult,
  ApprovalRequest,
  ApprovalRecord,
  HealthStatus,
  ApiError,
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  UserInfo,
} from '@/types';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// Token 拦截器：自动附加 Bearer token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 统一错误拦截: 将后端标准错误格式转为可读消息
api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<ApiError>) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_user');
      window.dispatchEvent(new Event('auth:logout'));
    }
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

/**
 * SSE 流式对话 —— 通过 fetch + ReadableStream 接收事件
 *
 * SSE 事件类型（对齐 API 文档）：
 *   intent  - 意图识别结果  { type, intent, session_id }
 *   message - 中间消息      { type, content }
 *   done    - 处理完成      { type, session_id }
 *   error   - 异常          { type, content }
 *
 * 用法:
 *   for await (const event of sendChatMessageStream({ message: "你好" })) {
 *     if (event.type === 'message') console.log(event.content);
 *   }
 */
export async function* sendChatMessageStream(data: ChatRequest) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ message: '请求失败' }));
    throw new Error(err.message || err.detail || `HTTP ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('浏览器不支持流式读取');

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        try {
          const payload = JSON.parse(line.slice(6));
          yield { type: currentEvent || 'message', ...payload };
        } catch {
          // 解析失败跳过
        }
      }
    }
  }
}

// ========== 报销单 CRUD ==========

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

// ========== 用户认证 ==========

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>('/auth/login', data);
  return res.data;
}

export async function register(data: RegisterRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>('/auth/register', data);
  return res.data;
}

export async function getMe(): Promise<UserInfo> {
  const res = await api.get<UserInfo>('/auth/me');
  return res.data;
}
