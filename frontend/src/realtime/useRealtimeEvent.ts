import { useEffect, useRef } from "react";

import { realtime } from "./socket";

export function useRealtimeEvent<T = any>(event: string, handler: (data: T) => void): void {
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => realtime.on(event, (data) => latest.current(data as T)), [event]);
}
