import json
import logging
import re
import sys
import time
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

SENSITIVE_KEYS = (
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "authorization",
    "totp",
    "code",
    "key",
    "recovery",
    "credential",
    "session",
    "csrf",
    "pepper",
    "plaintext",
    "content",
    "real_name",
    "full_name",
)
SENSITIVE_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|cookie|authorization|totp|recovery[_-]?code|api[_-]?key)(\s*[=:]\s*)(\S+)"
)
RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


def redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in SENSITIVE_KEYS):
        return "[redacted]"
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, v) for v in value]
    if isinstance(value, str):
        return SENSITIVE_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = SENSITIVE_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", record.getMessage())
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": message,
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in RESERVED and not key.startswith("_"):
                payload[key] = redact_value(key, value)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
