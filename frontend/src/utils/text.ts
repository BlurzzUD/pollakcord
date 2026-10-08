export type TextPart = { type: "text"; value: string } | { type: "mention"; userId: string } | { type: "link"; value: string };

const TOKEN = /<@(\d{1,20})>|(https?:\/\/[^\s<>"']+)/g;
const TRAILING = /[.,;:!?)\]}]+$/;

export function tokenizeMessage(content: string): TextPart[] {
  const parts: TextPart[] = [];
  let cursor = 0;
  for (const match of content.matchAll(TOKEN)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      parts.push({ type: "text", value: content.slice(cursor, index) });
    }
    if (match[1]) {
      parts.push({ type: "mention", userId: match[1] });
      cursor = index + match[0].length;
      continue;
    }
    const raw = match[2];
    const trimmed = raw.replace(TRAILING, "");
    parts.push({ type: "link", value: trimmed });
    cursor = index + trimmed.length;
  }
  if (cursor < content.length) {
    parts.push({ type: "text", value: content.slice(cursor) });
  }
  return parts;
}

export function isSafeUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

export function encodeMentions(text: string, picks: Record<string, string>): string {
  let output = text;
  const names = Object.keys(picks).sort((a, b) => b.length - a.length);
  for (const name of names) {
    output = output.split(`@${name}`).join(`<@${picks[name]}>`);
  }
  return output;
}

export function initials(name: string): string {
  const letters = Array.from(name.trim()).filter((ch) => /\p{L}/u.test(ch));
  return (letters[0] ?? "?").toUpperCase() + (letters.length > 1 && name.includes(" ") ? (name.split(" ").at(-1)?.[0] ?? "").toUpperCase() : "");
}

export function hueFor(value: string): number {
  let hash = 0;
  for (const ch of value) {
    hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  }
  return hash;
}
