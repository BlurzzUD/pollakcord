import { create } from "zustand";

import type { Id } from "../api/types";

interface ClassSpaceUiState {
  dismissedFor: Id | null;
  dismiss: (classId: Id) => void;
  reopen: () => void;
}

export const useClassSpaceUi = create<ClassSpaceUiState>((set) => ({
  dismissedFor: null,
  dismiss: (classId) => set({ dismissedFor: classId }),
  reopen: () => set({ dismissedFor: null }),
}));
