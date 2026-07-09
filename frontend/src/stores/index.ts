import { create } from 'zustand';
import type { ChatMessage, ReimbursementRecord, UserInfo } from '@/types';
import { getMe } from '@/services/api';

// =============================================================================
// 会话持久化 helper
// =============================================================================

interface SessionMeta {
  id: string;
  title: string;
  createdAt: string;
}

function loadSessions(): SessionMeta[] {
  try {
    const raw = localStorage.getItem('reimburse_sessions');
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveSessions(sessions: SessionMeta[]) {
  localStorage.setItem('reimburse_sessions', JSON.stringify(sessions));
}

function loadAllMessages(): Record<string, ChatMessage[]> {
  try {
    const raw = localStorage.getItem('reimburse_all_messages');
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
}

function saveAllMessages(all: Record<string, ChatMessage[]>) {
  try {
    // 每个会话最多保留 40 条消息，减少 localStorage 占用
    const trimmed: Record<string, ChatMessage[]> = {};
    for (const [k, v] of Object.entries(all)) {
      if (v.length > 0) trimmed[k] = v.slice(-40);
    }
    localStorage.setItem('reimburse_all_messages', JSON.stringify(trimmed));
  } catch { /* quota exceeded, ignore */ }
}

// =============================================================================
// 应用状态
// =============================================================================

interface AppState {
  sessionId: string | null;
  messages: ChatMessage[];
  sessions: SessionMeta[];
  allMessages: Record<string, ChatMessage[]>;
  currentReimbursement: ReimbursementRecord | null;

  setSessionId: (id: string | null) => void;
  createSession: () => string;
  switchSession: (id: string) => void;
  deleteSession: (id: string) => void;
  addMessage: (msg: ChatMessage) => void;
  updateLastMessage: (msg: ChatMessage) => void;
  appendToLastAssistant: (content: string) => void;
  setLastAssistantEntities: (intent?: string, entities?: Record<string, unknown>) => void;
  clearMessages: () => void;
  setCurrentReimbursement: (r: ReimbursementRecord | null) => void;
}

function newSessionId(): string {
  return crypto.randomUUID().replace(/-/g, '').slice(0, 12);
}

function autoTitle(content: string): string {
  return content.replace(/\s+/g, ' ').trim().slice(0, 20) || '新对话';
}

export const useAppStore = create<AppState>((set, get) => ({
  sessionId: null,
  messages: [],
  sessions: loadSessions(),
  allMessages: loadAllMessages(),
  currentReimbursement: null,

  setSessionId: (id) => set({ sessionId: id }),

  // ---- 新建会话 ----
  createSession: () => {
    const id = newSessionId();
    const meta: SessionMeta = { id, title: '新对话', createdAt: new Date().toISOString() };
    const sessions = [meta, ...get().sessions];
    saveSessions(sessions);
    set({
      sessionId: id,
      messages: [],
      sessions,
    });
    return id;
  },

  // ---- 切换会话（切换前保存当前会话消息） ----
  switchSession: (id) => {
    const { sessionId, messages, allMessages } = get();
    // 保存当前会话的 messages 到 allMessages（包括流式未完成的内容）
    const nextAll = { ...allMessages };
    if (sessionId && messages.length > 0) {
      nextAll[sessionId] = messages;
    }
    saveAllMessages(nextAll);
    const msgs = nextAll[id] || [];
    set({
      sessionId: id,
      messages: msgs,
      allMessages: nextAll,
    });
  },

  // ---- 删除会话 ----
  deleteSession: (id) => {
    const { sessions, allMessages, sessionId, messages } = get();
    // 先保存当前会话消息
    const nextAll = { ...allMessages };
    if (sessionId && messages.length > 0) {
      nextAll[sessionId] = messages;
    }
    const nextSessions = sessions.filter((s) => s.id !== id);
    delete nextAll[id];
    saveSessions(nextSessions);
    saveAllMessages(nextAll);

    // 如果删的是当前会话，自动切到第一个
    if (sessionId === id) {
      const next = nextSessions[0];
      if (next) {
        set({
          sessions: nextSessions,
          allMessages: nextAll,
          sessionId: next.id,
          messages: nextAll[next.id] || [],
        });
      } else {
        // 全删了，新建一个
        const newId = newSessionId();
        const meta: SessionMeta = { id: newId, title: '新对话', createdAt: new Date().toISOString() };
        saveSessions([meta]);
        set({
          sessions: [meta],
          allMessages: {},
          sessionId: newId,
          messages: [],
        });
      }
    } else {
      set({ sessions: nextSessions, allMessages: nextAll });
    }
  },

  // ---- 添加消息（自动关联当前 session，自动更新标题） ----
  addMessage: (msg) => {
    const { sessionId, sessions, allMessages } = get();
    if (!sessionId) return;
    const msgs = [...(allMessages[sessionId] || []), msg];
    const nextAll = { ...allMessages, [sessionId]: msgs };
    saveAllMessages(nextAll);

    // 首条用户消息自动更新标题
    const isFirstUserMsg = msg.role === 'user' && msgs.filter((m) => m.role === 'user').length === 1;
    if (isFirstUserMsg) {
      const nextSessions = sessions.map((s) =>
        s.id === sessionId ? { ...s, title: autoTitle(msg.content) } : s,
      );
      saveSessions(nextSessions);
      set({ messages: msgs, allMessages: nextAll, sessions: nextSessions });
    } else {
      set({ messages: msgs, allMessages: nextAll });
    }
  },

  updateLastMessage: (msg) =>
    set((s) => {
      const msgs = [...s.messages];
      if (msgs.length > 0 && msg.id) {
        const idx = msgs.findIndex((m) => m.id === msg.id);
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
      // 同步更新 allMessages，防止切会话时流式内容丢失
      if (s.sessionId) {
        const nextAll = { ...s.allMessages, [s.sessionId]: msgs };
        // 不频繁写 localStorage，只在切换/删除时写
        return { messages: msgs, allMessages: nextAll };
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

  clearMessages: () => {
    const { sessionId, allMessages } = get();
    if (!sessionId) return;
    const nextAll = { ...allMessages, [sessionId]: [] };
    saveAllMessages(nextAll);
    set({ messages: [], allMessages: nextAll });
  },

  setCurrentReimbursement: (r) => set({ currentReimbursement: r }),
}));

// =============================================================================
// 认证状态
// =============================================================================

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
    try { await get().fetchUser(); } catch { /* keep cached user */ }
  },
}));
