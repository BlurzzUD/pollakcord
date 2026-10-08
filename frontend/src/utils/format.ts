import i18n from "../i18n";

function locale(): string {
  return i18n.language === "de" ? "de-DE" : i18n.language === "en" ? "en-GB" : "hu-HU";
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(locale(), { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat(locale(), { year: "numeric", month: "long", day: "numeric", weekday: "long" }).format(new Date(iso));
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(locale(), { year: "numeric", month: "long", day: "numeric" }).format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function sameDay(a: string, b: string): boolean {
  return new Date(a).toDateString() === new Date(b).toDateString();
}

export function formatRelative(iso: string): string {
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) {
      return formatter.format(Math.round(seconds / size), unit);
    }
  }
  return formatter.format(seconds, "second");
}

export function compareIds(a: string, b: string): number {
  if (a.length !== b.length) {
    return a.length - b.length;
  }
  return a < b ? -1 : a > b ? 1 : 0;
}
