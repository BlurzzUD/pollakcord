import base64
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import Settings

KEY_LENGTH = 32
INFO_PREFIX = b"pollakcord/v1/"


class KeyConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MasterKey:
    key_id: str
    material: bytes


def generate_key_text() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(KEY_LENGTH)).decode("ascii").rstrip("=")


def decode_key_text(raw: str) -> bytes:
    cleaned = raw.strip()
    try:
        data = base64.urlsafe_b64decode(cleaned + "=" * (-len(cleaned) % 4))
    except ValueError as exc:
        raise KeyConfigurationError("key is not valid base64") from exc
    if len(data) != KEY_LENGTH:
        raise KeyConfigurationError("key must decode to exactly 32 bytes")
    return data


def _derive(material: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_LENGTH, salt=None, info=INFO_PREFIX + info).derive(material)


class KeyRing:
    def __init__(self, current: MasterKey, previous: list[MasterKey], pepper: bytes) -> None:
        self._keys = {key.key_id: key for key in [*previous, current]}
        self._current_id = current.key_id
        self._pepper = pepper
        self._cache: dict[tuple[str, str], bytes] = {}

    @property
    def current_id(self) -> str:
        return self._current_id

    def encryption_key(self, purpose: str, key_id: str | None = None) -> bytes:
        resolved = key_id or self._current_id
        if resolved not in self._keys:
            raise KeyConfigurationError(f"unknown key id {resolved}")
        cache_key = (resolved, purpose)
        if cache_key not in self._cache:
            self._cache[cache_key] = _derive(self._keys[resolved].material, b"enc/" + purpose.encode())
        return self._cache[cache_key]

    def mac(self, purpose: str, data: bytes) -> bytes:
        cache_key = ("pepper", purpose)
        if cache_key not in self._cache:
            self._cache[cache_key] = _derive(self._pepper, b"mac/" + purpose.encode())
        signer = hmac.HMAC(self._cache[cache_key], hashes.SHA256())
        signer.update(data)
        return signer.finalize()

    def mac_hex(self, purpose: str, data: bytes) -> str:
        return self.mac(purpose, data).hex()


def _read_secret(inline: str | None, file_path: Path | None) -> str | None:
    if inline:
        return inline
    if file_path is not None:
        return file_path.read_text(encoding="utf-8").strip()
    return None


def _load_dev_secrets(path: Path) -> dict[str, str]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    secrets_payload = {"master_key": generate_key_text(), "pepper": generate_key_text()}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(secrets_payload, handle)
    return secrets_payload


def _parse_previous(raw: str | None) -> list[MasterKey]:
    keys: list[MasterKey] = []
    if not raw:
        return keys
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key_id, _, text = entry.partition(":")
        if not key_id or not text:
            raise KeyConfigurationError("previous master keys must use the form id:key")
        keys.append(MasterKey(key_id, decode_key_text(text)))
    return keys


def load_keyring(settings: Settings) -> KeyRing:
    master_text = _read_secret(
        settings.master_key.get_secret_value() if settings.master_key else None, settings.master_key_file
    )
    pepper_text = _read_secret(settings.pepper.get_secret_value() if settings.pepper else None, settings.pepper_file)
    if master_text is None or pepper_text is None:
        if settings.is_production:
            raise KeyConfigurationError("POLLAKCORD_MASTER_KEY and POLLAKCORD_PEPPER are required in production")
        dev = _load_dev_secrets(settings.dev_secrets_file)
        master_text = master_text or dev["master_key"]
        pepper_text = pepper_text or dev["pepper"]
    previous_text = settings.previous_master_keys.get_secret_value() if settings.previous_master_keys else None
    current = MasterKey(settings.master_key_id, decode_key_text(master_text))
    previous = _parse_previous(previous_text)
    if any(key.key_id == current.key_id for key in previous):
        raise KeyConfigurationError("previous master key ids must differ from the current id")
    return KeyRing(current, previous, decode_key_text(pepper_text))
