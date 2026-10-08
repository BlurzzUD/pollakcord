import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .keyring import KeyRing

NONCE_LENGTH = 12


class DecryptionError(Exception):
    pass


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_LENGTH)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) <= NONCE_LENGTH:
        raise DecryptionError("ciphertext too short")
    try:
        return AESGCM(key).decrypt(blob[:NONCE_LENGTH], blob[NONCE_LENGTH:], aad)
    except InvalidTag as exc:
        raise DecryptionError("authentication failed") from exc


class Vault:
    def __init__(self, keyring: KeyRing) -> None:
        self._keyring = keyring

    @property
    def current_key_id(self) -> str:
        return self._keyring.current_id

    def encrypt(self, purpose: str, plaintext: bytes, aad: bytes) -> tuple[bytes, str]:
        key_id = self._keyring.current_id
        return seal(self._keyring.encryption_key(purpose, key_id), plaintext, aad), key_id

    def decrypt(self, purpose: str, blob: bytes, aad: bytes, key_id: str) -> bytes:
        return unseal(self._keyring.encryption_key(purpose, key_id), blob, aad)

    def mac_hex(self, purpose: str, data: bytes) -> str:
        return self._keyring.mac_hex(purpose, data)

    def mac(self, purpose: str, data: bytes) -> bytes:
        return self._keyring.mac(purpose, data)
