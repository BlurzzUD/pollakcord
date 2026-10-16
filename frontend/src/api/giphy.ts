import { ApiError } from "./client";

export interface GiphyItem {
  id: string;
  title: string;
  url: string;
  image: string;
  preview: string;
  attribution: string;
}

function mediaUrl(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port && /^(media[0-9]*|i)\.giphy\.com$/.test(url.hostname) ? value : null;
  } catch {
    return null;
  }
}

function item(value: any): GiphyItem | null {
  if (!value || typeof value.id !== "string" || !/^[A-Za-z0-9]{1,64}$/.test(value.id) || !["g", "pg"].includes(value.rating)) {
    return null;
  }
  const image = mediaUrl(value.images?.downsized?.url) ?? mediaUrl(value.images?.fixed_width?.url);
  const preview = mediaUrl(value.images?.fixed_width_small?.url) ?? image;
  if (!image || !preview) {
    return null;
  }
  return {
    id: value.id, title: String(value.title || "GIF").slice(0, 200), url: `https://giphy.com/gifs/${value.id}`,
    image, preview, attribution: String(value.user?.display_name || value.username || "GIPHY").slice(0, 100),
  };
}

async function query(key: string, params: Record<string, string>, signal?: AbortSignal): Promise<GiphyItem[]> {
  if (!key) {
    return [];
  }
  const url = new URL(`https://api.giphy.com/v1/gifs${"q" in params ? "/search" : ""}`);
  url.search = new URLSearchParams({ api_key: key, rating: "pg", ...params }).toString();
  try {
    const response = await fetch(url, { signal, credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store" });
    if (!response.ok) {
      throw new Error();
    }
    const payload = await response.json();
    if (!Array.isArray(payload.data)) {
      throw new Error();
    }
    return payload.data.map(item).filter((value: GiphyItem | null): value is GiphyItem => value !== null);
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    throw new ApiError(503, "giphy_unavailable", "giphy_unavailable");
  }
}

export const searchGiphy = (key: string, q: string, language: string, signal?: AbortSignal) => query(key, { q, lang: language.slice(0, 2), limit: "20" }, signal);
export const loadGiphy = async (key: string, id: string, signal?: AbortSignal) => (await query(key, { ids: id }, signal))[0] ?? null;
