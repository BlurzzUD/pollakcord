import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { SavedTheme } from "../api/types";
import { useAuth } from "../store/auth";
import { TOKEN_VARIABLES, tokensToVariables } from "./tokens";

const CSS_ELEMENT_ID = "user-custom-css";

function useSystemDark(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const listener = (event: MediaQueryListEvent) => setDark(event.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);
  return dark;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const me = useAuth((state) => state.me);
  const settings = me?.settings;
  const systemDark = useSystemDark();
  const mode = settings?.theme_mode ?? "system";
  const themes = useQuery({
    queryKey: ["themes"],
    queryFn: () => api.get<SavedTheme[]>("/me/themes"),
    enabled: me !== null && mode === "custom",
  });
  const active = themes.data?.find((theme) => theme.id === settings?.active_theme_id);

  useEffect(() => {
    const root = document.documentElement;
    const resolved = mode === "system" ? (systemDark ? "dark" : "light") : mode === "custom" ? "light" : mode;
    root.dataset.theme = resolved;
    root.dataset.themeMode = mode;
    const applied = mode === "custom" && active ? tokensToVariables(active.tokens) : {};
    for (const variable of Object.values(TOKEN_VARIABLES)) {
      root.style.removeProperty(variable);
    }
    for (const [variable, value] of Object.entries(applied)) {
      root.style.setProperty(variable, value);
    }
  }, [mode, systemDark, active]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.density = settings?.chat_appearance.density ?? "cozy";
    root.style.setProperty("--chat-scale", String((settings?.chat_appearance.font_scale ?? 100) / 100));
    root.dataset.timestamps = String(settings?.chat_appearance.show_timestamps ?? true);
  }, [settings?.chat_appearance]);

  useEffect(() => {
    let element = document.getElementById(CSS_ELEMENT_ID);
    const css = settings?.custom_css ?? "";
    if (!css) {
      element?.remove();
      return;
    }
    if (!element) {
      element = document.createElement("style");
      element.id = CSS_ELEMENT_ID;
      document.head.appendChild(element);
    }
    element.textContent = css;
  }, [settings?.custom_css]);

  return <>{children}</>;
}
