import { create } from "zustand";

export type ToastKind = "info" | "success" | "error";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface UiState {
  toasts: Toast[];
  drawerOpen: boolean;
  membersOpen: boolean;
  profileUserId: string | null;
  push: (kind: ToastKind, message: string) => void;
  dismiss: (id: number) => void;
  setDrawer: (open: boolean) => void;
  toggleMembers: () => void;
  openProfile: (userId: string) => void;
  closeProfile: () => void;
}

let nextToast = 1;

export const useUi = create<UiState>((set, get) => ({
  toasts: [],
  drawerOpen: false,
  membersOpen: true,
  profileUserId: null,
  push: (kind, message) => {
    const id = nextToast++;
    set((state) => ({ toasts: [...state.toasts.slice(-3), { id, kind, message }] }));
    window.setTimeout(() => get().dismiss(id), kind === "error" ? 7000 : 4500);
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  setDrawer: (open) => set({ drawerOpen: open }),
  toggleMembers: () => set((state) => ({ membersOpen: !state.membersOpen })),
  openProfile: (userId) => set({ profileUserId: userId }),
  closeProfile: () => set({ profileUserId: null }),
}));
