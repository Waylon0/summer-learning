import { create } from 'zustand';
import type { ChatMessage, ReimbursementRecord, UserInfo } from '@/types';
import { getMe } from '@/services/api';

// ===== 应用状态 (聊天等) =====

interface AppState {
  sessionId: string | null;
  messages: ChatMessage[];
  currentReimbursement: ReimbursementRecord | null;

  setSessionId: (id: string | null) => void;
  addMessage: (msg: ChatMessage) => void;
  updateLastMessage: (msg: ChatMessage) => void;
  appendToLastAssistant: (content: string) => void;
  setLastAssistantEntities: (intent?: string, entities?: Record<string, unknown>) => void;
  clearMessages: () => void;
  setCurrentReimbursement: (r: ReimbursementRecord | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sessionId: null,
  messages: [],
  currentReimbursement: null,

  setSessionId: (id) => set({ sessionId: id }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  updateLastMessage: (msg) =>
    set((s) => {
      const msgs = [...s.messages];
      if (msgs.length > 0 && msg.id) {
        const idx = msgs.findIndex(m => m.id === msg.id);
        if (idx >= 0) msgs[idx] = msg;
        else msgs[msgs.length - 1] = msg;
      }
      return { messages: msgs };
    }),
  appendToLastAssistant: (content) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'assistant') {
        msgs[msgs.length - 1] = { ...last, content: last.content + content };
      } else {
        msgs.push({
          id: Date.now().toString(),
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
        });
      }
      return { messages: msgs };
    }),
  setLastAssistantEntities: (intent, entities) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'assistant') {
        msgs[msgs.length - 1] = { ...last, intent, entities };
      }
      return { messages: msgs };
    }),
  clearMessages: () => set({ messages: [] }),
  setCurrentReimbursement: (r) => set({ currentReimbursement: r }),
}));

// ===== 认证状态 =====

interface AuthState {
  user: UserInfo | null;
  token: string | null;
  loading: boolean;

  setAuth: (token: string, user: UserInfo) => void;
  logout: () => void;
  fetchUser: () => Promise<void>;
  initialize: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: localStorage.getItem('auth_token'),
  loading: true,

  setAuth: (token, user) => {
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(user));
    set({ token, user, loading: false });
  },

  logout: () => {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_user');
    set({ token: null, user: null, loading: false });
  },

  fetchUser: async () => {
    try {
      const user = await getMe();
      set({ user, loading: false });
      localStorage.setItem('auth_user', JSON.stringify(user));
    } catch {
      get().logout();
    }
  },

  initialize: async () => {
    const token = localStorage.getItem('auth_token');
    if (!token) {
      set({ loading: false });
      return;
    }
    const cached = localStorage.getItem('auth_user');
    if (cached) {
      try { set({ user: JSON.parse(cached), loading: false }); } catch { /* ignore */ }
    }
    // 后台验证 token 有效性
    try { await get().fetchUser(); } catch { /* keep cached user */ }
  },
}));
