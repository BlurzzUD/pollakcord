import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import Settings
from ..errors import AppError

MIN_LENGTH = 10
MAX_LENGTH = 128
COMMON_PASSWORDS = frozenset(
    {
        "password123",
        "password1234",
        "passw0rd123",
        "1234567890",
        "12345678910",
        "123456789012",
        "qwertyuiop",
        "qwertzuiop",
        "asdfghjkl1",
        "iloveyou123",
        "jelszo1234",
        "jelszo12345",
        "jelszojelszo",
        "kreta12345",
        "ekreta1234",
        "iskola12345",
        "diakjelszo",
        "letmein1234",
        "welcome1234",
        "adminadmin1",
        "0000000000",
        "1111111111",
        "aaaaaaaaaa",
    }
)


def validate_password_policy(password: str, username: str) -> None:
    if len(password) < MIN_LENGTH:
        raise AppError("password_too_short", 422, params={"min": MIN_LENGTH})
    if len(password) > MAX_LENGTH:
        raise AppError("password_too_long", 422, params={"max": MAX_LENGTH})
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(lowered)) < 4:
        raise AppError("password_too_common", 422)
    if username and username.lower() in lowered:
        raise AppError("password_contains_username", 422)


class PasswordService:
    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
        self._dummy_hash = self._hasher.hash("pollakcord-timing-equalizer")

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, stored_hash: str, password: str) -> tuple[bool, str | None]:
        try:
            await asyncio.to_thread(self._hasher.verify, stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, None
        if self._hasher.check_needs_rehash(stored_hash):
            return True, await self.hash(password)
        return True, None

    async def burn(self, password: str) -> None:
        try:
            await asyncio.to_thread(self._hasher.verify, self._dummy_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return
