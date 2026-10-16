import json
import re

from ..config import Settings
from ..crypto.envelope import DecryptionError, Vault
from ..errors import AppError

GIPHY_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")


def validate_giphy(giphy_id: str | None, settings: Settings) -> None:
    if giphy_id is None:
        return
    if not settings.giphy_api_key or not settings.giphy_api_key.get_secret_value().strip():
        raise AppError("giphy_disabled", 503)
    if not GIPHY_ID.fullmatch(giphy_id):
        raise AppError("validation_error", 422)


def seal_media(vault: Vault, domain: str, message_id: int, embeds: list[dict], giphy_id: str | None = None) -> tuple[bytes | None, str | None]:
    if not embeds and giphy_id is None:
        return None, None
    payload = json.dumps({"embeds": embeds, "giphy_id": giphy_id}, ensure_ascii=False).encode("utf-8")
    return vault.encrypt("message-media", payload, f"{domain}|{message_id}".encode())


def open_media(vault: Vault, domain: str, message_id: int, blob: bytes | None, key_id: str | None) -> dict:
    if blob is None or key_id is None:
        return {"embeds": [], "giphy_id": None}
    try:
        return json.loads(vault.decrypt("message-media", blob, f"{domain}|{message_id}".encode(), key_id))
    except (DecryptionError, ValueError, UnicodeError):
        return {"embeds": [], "giphy_id": None}
