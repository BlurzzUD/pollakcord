import { create } from "zustand";

import type { Id, UserCard, VoiceParticipant } from "../api/types";

export interface IncomingCall {
  conversationId: Id;
  from: UserCard;
  expiresAt: number;
}

interface LiveState {
  connected: boolean;
  presence: Record<Id, "online" | "offline">;
  typing: Record<string, Record<Id, number>>;
  voiceStates: Record<Id, VoiceParticipant[]>;
  incomingCall: IncomingCall | null;
  setConnected: (connected: boolean) => void;
  setPresence: (userId: Id, status: "online" | "offline") => void;
  markTyping: (key: string, userId: Id) => void;
  clearTyping: (key: string, userId: Id) => void;
  setVoiceChannel: (channelId: Id, participants: VoiceParticipant[]) => void;
  seedVoiceStates: (states: Record<Id, VoiceParticipant[]>) => void;
  setIncomingCall: (call: IncomingCall | null) => void;
}

export const useLive = create<LiveState>((set) => ({
  connected: false,
  presence: {},
  typing: {},
  voiceStates: {},
  incomingCall: null,
  setConnected: (connected) => set({ connected }),
  setPresence: (userId, status) => set((state) => ({ presence: { ...state.presence, [userId]: status } })),
  markTyping: (key, userId) =>
    set((state) => ({ typing: { ...state.typing, [key]: { ...state.typing[key], [userId]: Date.now() + 5000 } } })),
  clearTyping: (key, userId) =>
    set((state) => {
      const current = { ...state.typing[key] };
      delete current[userId];
      return { typing: { ...state.typing, [key]: current } };
    }),
  setVoiceChannel: (channelId, participants) => set((state) => ({ voiceStates: { ...state.voiceStates, [channelId]: participants } })),
  seedVoiceStates: (states) => set((state) => ({ voiceStates: { ...state.voiceStates, ...states } })),
  setIncomingCall: (incomingCall) => set({ incomingCall }),
}));
