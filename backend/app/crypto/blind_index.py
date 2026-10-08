import re
import unicodedata

TOKEN_PATTERN = re.compile(r"[^\W_]{2,}", re.UNICODE)
MAX_TOKENS_PER_MESSAGE = 64
MAX_TOKEN_LENGTH = 48
DIGEST_LENGTH = 16


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def tokenize(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in TOKEN_PATTERN.finditer(fold(text)):
        token = match.group(0)[:MAX_TOKEN_LENGTH]
        seen.setdefault(token, None)
        if len(seen) >= MAX_TOKENS_PER_MESSAGE:
            break
    return list(seen)
