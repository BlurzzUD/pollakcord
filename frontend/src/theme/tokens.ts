import type { ThemeTokens } from "../api/types";

export const TOKEN_VARIABLES: Record<keyof ThemeTokens, string> = {
  bg: "--paper",
  bg_alt: "--paper-2",
  bg_deep: "--paper-3",
  text: "--text",
  text_muted: "--text-muted",
  accent: "--ink",
  accent_text: "--ink-text",
  danger: "--margin",
  mention: "--highlight",
  border: "--border",
  background: "--chat-bg",
  radius: "--radius",
};

export const COLOR_KEYS = ["bg", "bg_alt", "bg_deep", "text", "text_muted", "accent", "accent_text", "danger", "mention", "border"] as const;
export const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
export const GRADIENT = /^linear-gradient\(\s*\d{1,3}deg\s*,\s*#[0-9a-fA-F]{6}\s*,\s*#[0-9a-fA-F]{6}\s*\)$/;

export function isValidToken(key: keyof ThemeTokens, value: string): boolean {
  if ((COLOR_KEYS as readonly string[]).includes(key)) {
    return HEX_COLOR.test(value);
  }
  if (key === "background") {
    return HEX_COLOR.test(value) || GRADIENT.test(value);
  }
  if (key === "radius") {
    return /^\d{1,2}$/.test(value) && Number(value) <= 24;
  }
  return false;
}

export function tokensToVariables(tokens: ThemeTokens): Record<string, string> {
  const variables: Record<string, string> = {};
  for (const key of Object.keys(TOKEN_VARIABLES) as (keyof ThemeTokens)[]) {
    const value = tokens[key];
    if (value !== undefined && isValidToken(key, value)) {
      variables[TOKEN_VARIABLES[key]] = key === "radius" ? `${value}px` : key === "background" && HEX_COLOR.test(value) ? `linear-gradient(${value}, ${value})` : value;
    }
  }
  return variables;
}

function channel(value: number): number {
  const normalized = value / 255;
  return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const value = parseInt(hex.slice(1), 16);
  return 0.2126 * channel((value >> 16) & 255) + 0.7152 * channel((value >> 8) & 255) + 0.0722 * channel(value & 255);
}

export function contrastRatio(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

export const DEFAULT_CUSTOM: Required<Pick<ThemeTokens, (typeof COLOR_KEYS)[number]>> & ThemeTokens = {
  bg: "#fafbff",
  bg_alt: "#f0f3fc",
  bg_deep: "#e5eaf8",
  text: "#1b2033",
  text_muted: "#566079",
  accent: "#2540d9",
  accent_text: "#ffffff",
  danger: "#c4262d",
  mention: "#ffe14d",
  border: "#cfd7ee",
};

export const PRESETS: { id: string; tokens: ThemeTokens }[] = [
  { id: "notebook", tokens: { ...DEFAULT_CUSTOM } },
  {
    id: "chalkboard",
    tokens: { bg: "#141e1b", bg_alt: "#1a2723", bg_deep: "#22332e", text: "#e8ede4", text_muted: "#a5b2aa", accent: "#9db0ff", accent_text: "#0f1730", danger: "#ff8c84", mention: "#f4dc6b", border: "#33463f" },
  },
  {
    id: "highlighter",
    tokens: { bg: "#fffdf2", bg_alt: "#fff6c9", bg_deep: "#ffee9a", text: "#2b2410", text_muted: "#6b5f2a", accent: "#b4256a", accent_text: "#ffffff", danger: "#c4262d", mention: "#8be8c4", border: "#e8d98a", background: "linear-gradient(160deg, #fffdf2, #fff3b8)" },
  },
  {
    id: "midnight",
    tokens: { bg: "#10131f", bg_alt: "#171b2b", bg_deep: "#1e2338", text: "#e7e9f5", text_muted: "#a2a8c7", accent: "#7cc4ff", accent_text: "#07182a", danger: "#ff8a8a", mention: "#ffd479", border: "#2c3354", background: "linear-gradient(200deg, #10131f, #1b2140)" },
  },
];
