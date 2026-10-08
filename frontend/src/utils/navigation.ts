export function safeNext(value: string | null | undefined): string {
  if (value && (value.startsWith("/app") || /^\/invite\/[A-Za-z0-9]+$/.test(value)) && !value.startsWith("//")) {
    return value;
  }
  return "/app";
}
