import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, resetCsrf } from "../api/client";
import i18n from "../i18n";
import { RealtimeClient } from "../realtime/socket";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    resetCsrf();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the csrf token and the interface language on state-changing requests", async () => {
    fetchMock.mockImplementation(async (url: string) => (url.endsWith("/auth/csrf") ? json({ csrf_token: "tok-1" }) : json({ ok: true })));
    await api.post("/friends/requests", { username: "anna" });
    const call = fetchMock.mock.calls.find(([url]) => (url as string).endsWith("/friends/requests"));
    expect(call).toBeDefined();
    const init = call?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("tok-1");
    expect(headers["Accept-Language"]).toBe(i18n.language);
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe(JSON.stringify({ username: "anna" }));
  });

  it("does not request a csrf token for plain reads", async () => {
    fetchMock.mockResolvedValue(json([]));
    await api.get("/friends");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0][0] as string)).toBe("/api/v1/friends");
  });

  it("builds query strings and skips empty values", async () => {
    fetchMock.mockResolvedValue(json({}));
    await api.get("/search", { q: "tanár", limit: 5, before: undefined, after: null });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/search?q=tan%C3%A1r&limit=5");
  });

  it("refreshes the token once when the server rejects it", async () => {
    let issued = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/csrf")) {
        issued += 1;
        return json({ csrf_token: `tok-${issued}` });
      }
      const token = (init?.headers as Record<string, string>)["X-CSRF-Token"];
      return token === "tok-2" ? json({ done: true }) : json({ error: { code: "csrf_failed", message: "x" } }, 403);
    });
    await expect(api.post("/blocks/1")).resolves.toEqual({ done: true });
    expect(issued).toBe(2);
  });

  it("turns error payloads into ApiError with code and parameters", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith("/auth/csrf") ? json({ csrf_token: "t" }) : json({ error: { code: "rate_limited", message: "Túl sok", params: { seconds: 12 } } }, 429),
    );
    const failure = await api.post("/auth/login", {}).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("rate_limited");
    expect((failure as ApiError).status).toBe(429);
    expect((failure as ApiError).params).toEqual({ seconds: 12 });
  });

  it("copes with non-json error bodies", async () => {
    fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    const failure = await api.get("/me").catch((error: unknown) => error);
    expect((failure as ApiError).code).toBe("request_failed");
  });

  it("uploads files as multipart without forcing a content type", async () => {
    fetchMock.mockImplementation(async (url: string) => (url.endsWith("/auth/csrf") ? json({ csrf_token: "t" }) : json({ avatar_url: "/media/avatar/x.webp" })));
    await api.upload("/uploads/avatar", new File(["x"], "a.png", { type: "image/png" }));
    const init = fetchMock.mock.calls.at(-1)?.[1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }
}

describe("realtime client", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("connects to the same-origin websocket endpoint and dispatches events", () => {
    const client = new RealtimeClient();
    const seen: unknown[] = [];
    client.on("message.create", (data) => seen.push(data));
    client.connect();
    const socket = FakeSocket.instances[0];
    expect(socket.url).toMatch(/^wss?:\/\/[^/]+\/api\/v1\/ws$/);
    socket.open();
    socket.onmessage?.({ data: JSON.stringify({ t: "message.create", d: { id: "1" } }) });
    socket.onmessage?.({ data: "not json" });
    expect(seen).toEqual([{ id: "1" }]);
    client.disconnect();
  });

  it("re-subscribes to channels after reconnecting with backoff", () => {
    const client = new RealtimeClient();
    client.connect();
    FakeSocket.instances[0].open();
    client.subscribeChannel("42");
    expect(FakeSocket.instances[0].sent.map((s) => JSON.parse(s))).toContainEqual({ op: "subscribe", d: { channel_id: "42" } });
    FakeSocket.instances[0].close(1006);
    vi.advanceTimersByTime(2000);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1].open();
    expect(FakeSocket.instances[1].sent.map((s) => JSON.parse(s))).toContainEqual({ op: "subscribe", d: { channel_id: "42" } });
    client.disconnect();
  });

  it("stops reconnecting and reports an expired session", () => {
    const client = new RealtimeClient();
    const unauthorized = vi.fn();
    client.on("unauthorized", unauthorized);
    client.connect();
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].close(4401);
    vi.advanceTimersByTime(60000);
    expect(unauthorized).toHaveBeenCalledOnce();
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("sends keep-alive pings and refuses to send while closed", () => {
    const client = new RealtimeClient();
    expect(client.send("ping")).toBe(false);
    client.connect();
    FakeSocket.instances[0].open();
    vi.advanceTimersByTime(26000);
    expect(FakeSocket.instances[0].sent.some((s) => JSON.parse(s).op === "ping")).toBe(true);
    client.disconnect();
  });
});
