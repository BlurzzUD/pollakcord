import { create } from "zustand";

export const useLinkPolicy = create<{ publicOrigin: string | null; setPublicOrigin: (origin: string) => void }>((set) => ({
  publicOrigin: null,
  setPublicOrigin: (origin) => {
    try {
      const url = new URL(origin);
      if (url.protocol === "https:" || url.protocol === "http:") {
        set({ publicOrigin: url.origin });
      }
    } catch {
      return;
    }
  },
}));

export function isExternalUrl(value: string, publicOrigin = window.location.origin): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === "https:" || url.protocol === "http:") && url.origin !== new URL(publicOrigin).origin;
  } catch {
    return false;
  }
}
