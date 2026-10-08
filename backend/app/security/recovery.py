import base64
import secrets

from ..crypto.envelope import Vault

CODE_COUNT = 8
CODE_BYTES = 10
GROUP_SIZE = 4


def generate_codes(count: int = CODE_COUNT) -> list[str]:
    codes = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(CODE_BYTES)).decode("ascii")
        codes.append("-".join(raw[i : i + GROUP_SIZE] for i in range(0, len(raw), GROUP_SIZE)))
    return codes


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def hash_code(vault: Vault, code: str) -> str:
    return vault.mac_hex("recovery-code", normalize_code(code).encode("ascii", errors="ignore"))
