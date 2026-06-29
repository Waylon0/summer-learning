import { create } from 'zustand';
import type { ChatMessage, ReimbursementRecord } from '@/types';

interface AppState {
  sessionId: string | null;
  messages: ChatMessage[];
  currentReimbursement: ReimbursementRecord | null;

  setSessionId: (id: string) => void;
  addMessage: (msg: ChatMessage) => void;
  clearMessages: () => void;
  setCurrentReimbursement: (r: ReimbursementRecord | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sessionId: null,
  messages: [],
  currentReimbursement: null,

  setSessionId: (id) => set({ sessionId: id }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  clearMessages: () => set({ messages: [] }),
  setCurrentReimbursement: (r) => set({ currentReimbursement: r }),
}));
