import { create } from 'zustand';
import type { ChatMessage, ReimbursementRecord } from '@/types';

interface AppState {
  sessionId: string | null;
  messages: ChatMessage[];
  currentReimbursement: ReimbursementRecord | null;

  setSessionId: (id: string | null) => void;
  addMessage: (msg: ChatMessage) => void;
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
