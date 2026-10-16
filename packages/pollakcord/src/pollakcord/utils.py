import re
from datetime import datetime, timezone


def get(iterable, **attrs):
    for item in iterable:
        if all(getattr(item, key, None) == value for key, value in attrs.items()):
            return item
    return None


def find(predicate, iterable):
    return next((item for item in iterable if predicate(item)), None)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def escape_markdown(text: str) -> str:
    return re.sub(r"([\\`*_~|>])", r"\\\1", text)


def escape_mentions(text: str) -> str:
    return text.replace("@", "@\u200b")
