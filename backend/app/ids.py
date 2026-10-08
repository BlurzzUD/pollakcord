import secrets
import threading
import time

EPOCH_MS = 1_735_689_600_000
WORKER_BITS = 10
SEQUENCE_BITS = 12
SEQUENCE_MASK = (1 << SEQUENCE_BITS) - 1


class SnowflakeGenerator:
    def __init__(self, worker_id: int | None = None) -> None:
        self._worker_id = worker_id if worker_id is not None else secrets.randbits(WORKER_BITS)
        self._lock = threading.Lock()
        self._last_ms = -1
        self._sequence = 0

    def next_id(self) -> int:
        with self._lock:
            now = int(time.time() * 1000)
            if now < self._last_ms:
                now = self._last_ms
            if now == self._last_ms:
                self._sequence = (self._sequence + 1) & SEQUENCE_MASK
                if self._sequence == 0:
                    now = self._wait_next_ms(now)
            else:
                self._sequence = 0
            self._last_ms = now
            return ((now - EPOCH_MS) << (WORKER_BITS + SEQUENCE_BITS)) | (self._worker_id << SEQUENCE_BITS) | self._sequence

    @staticmethod
    def _wait_next_ms(current: int) -> int:
        now = int(time.time() * 1000)
        while now <= current:
            now = int(time.time() * 1000)
        return now


_generator = SnowflakeGenerator()


def new_id() -> int:
    return _generator.next_id()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
