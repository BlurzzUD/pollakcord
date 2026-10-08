import json
from functools import lru_cache
from pathlib import Path

SUPPORTED_LANGUAGES = ("hu", "en", "de")
DEFAULT_LANGUAGE = "hu"
LOCALE_DIR = Path(__file__).resolve().parent / "locales"


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@lru_cache
def _catalog(language: str) -> dict[str, dict[str, str]]:
    path = LOCALE_DIR / f"{language}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def translate(section: str, key: str, language: str = DEFAULT_LANGUAGE, **params: object) -> str:
    language = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    template = _catalog(language).get(section, {}).get(key)
    if template is None:
        template = _catalog(DEFAULT_LANGUAGE).get(section, {}).get(key, key)
    return template.format_map(_SafeDict(params))


def negotiate_language(header: str | None) -> str:
    if not header:
        return DEFAULT_LANGUAGE
    candidates = []
    for index, part in enumerate(header.split(",")):
        pieces = part.strip().split(";")
        tag = pieces[0].strip().lower().split("-")[0]
        quality = 1.0
        for extra in pieces[1:]:
            extra = extra.strip()
            if extra.startswith("q="):
                try:
                    quality = float(extra[2:])
                except ValueError:
                    quality = 0.0
        if quality > 0:
            candidates.append((-quality, index, tag))
    for _, _, tag in sorted(candidates):
        if tag in SUPPORTED_LANGUAGES:
            return tag
    return DEFAULT_LANGUAGE
