import time
from collections import deque

from fastapi import Request

from ..errors import AppError
from .deps_ip import client_ip


class RateLimiter:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._hits: dict[str, deque[float]] = {}
        self._last_cleanup = time.monotonic()

    def check(self, key: str, limit: int, window: float) -> float | None:
        if not self.enabled:
            return None
        now = time.monotonic()
        bucket = self._hits.setdefault(key, deque())
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(1.0, window - (now - bucket[0]))
        bucket.append(now)
        self._cleanup(now, window)
        return None

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _cleanup(self, now: float, window: float) -> None:
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        stale = [k for k, bucket in self._hits.items() if not bucket or bucket[-1] <= now - max(window, 3600)]
        for key in stale:
            del self._hits[key]


def enforce(request: Request, name: str, limit: int, window: float, subject: str | None = None) -> None:
    limiter: RateLimiter = request.app.state.limiter
    key = f"{name}:{subject if subject is not None else client_ip(request)}"
    retry_after = limiter.check(key, limit, window)
    if retry_after is not None:
        raise AppError(
            "rate_limited",
            429,
            params={"seconds": int(retry_after)},
            headers={"Retry-After": str(int(retry_after))},
        )
