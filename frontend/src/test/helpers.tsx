import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import type { Me } from "../api/types";
import { setLanguage } from "../i18n";
import { useAuth } from "../store/auth";

export function makeMe(overrides: Partial<Me> = {}, settings: Partial<Me["settings"]> = {}): Me {
  return {
    id: "1001",
    username: "eva_k",
    display_name: "Éva",
    avatar_url: null,
    staff: false,
    bio: "",
    banner_url: null,
    accent_color: null,
    created_at: "2026-01-01T10:00:00+00:00",
    status: "active",
    platform_role: "user",
    class_code: null,
    settings: {
      language: "hu",
      theme_mode: "system",
      active_theme_id: null,
      custom_css: "",
      developer_mode: false,
      chat_appearance: { density: "cozy", font_scale: 100, show_timestamps: true },
      notification_prefs: { friend_requests: true, direct_messages: true, mentions: true, server: true, calls: true, moderation: true, dok: true, sounds: false },
      privacy: {
        friend_requests: "everyone",
        direct_messages: "shared_servers",
        class_visibility: "hidden",
        online_status: "friends",
        profile_visibility: "shared_context",
        activity_visibility: "friends",
        voice_calls: "friends",
      },
      class_prompt_answered: true,
      ...settings,
    },
    ...overrides,
  };
}

export function signIn(me: Me = makeMe()): Me {
  useAuth.setState({ status: "authenticated", me, setup: null });
  return me;
}

export function signOut(): void {
  useAuth.setState({ status: "anonymous", me: null, setup: null });
}

export function renderApp(ui: ReactElement, route = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export function resetLanguage(): void {
  setLanguage("hu");
}
