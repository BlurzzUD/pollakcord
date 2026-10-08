type Handler = (data: any) => void;

export type SocketStatus = "idle" | "connecting" | "open" | "closed";

const PING_INTERVAL_MS = 25000;
const MAX_BACKOFF_MS = 15000;

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private channels = new Set<string>();
  private attempts = 0;
  private pingTimer: number | null = null;
  private retryTimer: number | null = null;
  private wanted = false;
  status: SocketStatus = "idle";

  on(event: string, handler: Handler): () => void {
    const set = this.handlers.get(event) ?? new Set<Handler>();
    set.add(handler);
    this.handlers.set(event, set);
    return () => {
      set.delete(handler);
    };
  }

  private emit(event: string, data: unknown): void {
    this.handlers.get(event)?.forEach((handler) => handler(data));
    this.handlers.get("*")?.forEach((handler) => handler({ t: event, d: data }));
  }

  connect(): void {
    this.wanted = true;
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      return;
    }
    this.status = "connecting";
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/ws`);
    this.socket = socket;
    socket.onopen = () => {
      this.attempts = 0;
      this.status = "open";
      this.channels.forEach((id) => this.send("subscribe", { channel_id: id }));
      this.pingTimer = window.setInterval(() => this.send("ping"), PING_INTERVAL_MS);
      this.emit("socket.open", {});
    };
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string) as { t: string; d: unknown };
        this.emit(message.t, message.d);
      } catch {
        return;
      }
    };
    socket.onclose = (event) => {
      this.cleanupTimers();
      this.status = "closed";
      this.emit("socket.close", { code: event.code });
      if (event.code === 4401 || event.code === 4403) {
        this.wanted = false;
        this.emit("unauthorized", {});
        return;
      }
      if (this.wanted) {
        this.scheduleRetry();
      }
    };
  }

  private cleanupTimers(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private scheduleRetry(): void {
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempts) + Math.random() * 500;
    this.attempts += 1;
    this.retryTimer = window.setTimeout(() => this.connect(), delay);
  }

  disconnect(): void {
    this.wanted = false;
    this.cleanupTimers();
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.socket?.close(1000);
    this.socket = null;
    this.channels.clear();
    this.status = "idle";
  }

  send(op: string, data?: Record<string, unknown>): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify({ op, d: data ?? {} }));
    return true;
  }

  subscribeChannel(channelId: string): void {
    this.channels.add(channelId);
    this.send("subscribe", { channel_id: channelId });
  }

  unsubscribeChannel(channelId: string): void {
    this.channels.delete(channelId);
    this.send("unsubscribe", { channel_id: channelId });
  }
}

export const realtime = new RealtimeClient();
