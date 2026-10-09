import { useEffect, useState } from "react";

const TICK_MS = 250;

export function useVisibleFor(durationMs: number): boolean {
  const [elapsed, setElapsed] = useState(0);
  const done = elapsed >= durationMs;
  useEffect(() => {
    if (done) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") {
        setElapsed((value) => value + TICK_MS);
      }
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [done, durationMs]);
  return done;
}
