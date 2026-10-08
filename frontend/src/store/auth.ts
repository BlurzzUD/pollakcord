import { create } from "zustand";

import { api, resetCsrf } from "../api/client";
import type { Me, SessionInfo } from "../api/types";
import { isLanguage, setLanguage } from "../i18n";
import i18n from "../i18n";

interface AuthState {
  status: "loading" | "anonymous" | "authenticated";
  me: Me | null;
  setup: SessionInfo["setup"] | null;
  load: () => Promise<void>;
  setMe: (me: Me) => void;
  logout: () => Promise<void>;
}

function syncLanguage(me: Me): void {
  const preferred = me.settings.language;
  if (isLanguage(preferred) && preferred !== i18n.language) {
    setLanguage(preferred);
  }
}

export const useAuth = create<AuthState>((set) => ({
  status: "loading",
  me: null,
  setup: null,
  load: async () => {
    try {
      const session = await api.get<SessionInfo>("/auth/session");
      if (session.authenticated && session.user) {
        syncLanguage(session.user);
        set({ status: "authenticated", me: session.user, setup: null });
      } else {
        set({ status: "anonymous", me: null, setup: session.setup ?? null });
      }
    } catch {
      set({ status: "anonymous", me: null, setup: null });
    }
  },
  setMe: (me) => {
    syncLanguage(me);
    set({ status: "authenticated", me, setup: null });
  },
  logout: async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      resetCsrf();
      set({ status: "anonymous", me: null, setup: null });
    }
  },
}));
