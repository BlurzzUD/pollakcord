import asyncio
import hashlib
import os
import re
import shutil
import signal
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Protocol

from ...config import Settings
from ...logging_config import get_logger

logger = get_logger("pollakcord.kreta")

TWO_FACTOR_PROMPT = "enter current TOTP"
NAME_LINE = re.compile(r"^Student name returned by API: (.+)$", re.MULTILINE)
DONE_MARKER = "=== Done ==="
BAD_PASSWORD_MARKER = "password login likely failed"
BAD_TWO_FACTOR_MARKER = "code may be wrong/expired"
LICENSE_MARKER = "EXPIRED LICENSE"
MAX_BUFFER_BYTES = 256 * 1024
PASSTHROUGH_ENV = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
NAME_PUNCTUATION = " .,'’-"


class KretaOutcome(StrEnum):
    TWO_FACTOR_REQUIRED = "two_factor_required"
    IDENTIFIED = "identified"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_TWO_FACTOR = "invalid_two_factor"
    SERVICE_UNAVAILABLE = "service_unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class KretaResult:
    outcome: KretaOutcome
    full_name: str | None = None


@dataclass
class KretaSession:
    process: asyncio.subprocess.Process
    workdir: Path
    buffer: bytearray = field(default_factory=bytearray)
    closed: bool = False


class KretaAuthPort(Protocol):
    async def start(self, username: str, password: str) -> tuple[KretaSession | None, KretaResult]: ...

    async def submit_two_factor(self, session: KretaSession, code: str) -> KretaResult: ...

    async def abort(self, session: KretaSession | None) -> None: ...


class KretaConfigurationError(RuntimeError):
    pass


def has_control_characters(value: str) -> bool:
    return any(unicodedata.category(ch).startswith("C") for ch in value)


def parse_full_name(raw: str) -> str | None:
    normalized = unicodedata.normalize("NFC", raw).strip()
    base = normalized.split(" (", 1)[0].strip()
    base = re.sub(r"\s+", " ", base)
    if not 2 <= len(base) <= 120:
        return None
    for ch in base:
        if not (ch.isalpha() or unicodedata.category(ch).startswith("M") or ch in NAME_PUNCTUATION):
            return None
    if sum(1 for ch in base if ch.isalpha()) < 2:
        return None
    return base


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


LIMIT_LAUNCHER = (
    "import os, resource, sys\n"
    "limits = ((resource.RLIMIT_CPU, 60), (resource.RLIMIT_FSIZE, 2 * 1024 * 1024),"
    " (resource.RLIMIT_CORE, 0), (resource.RLIMIT_AS, 1024 * 1024 * 1024))\n"
    "for kind, value in limits:\n"
    "    resource.setrlimit(kind, (value, value))\n"
    "os.execv(sys.argv[1], [sys.argv[1], '-u', sys.argv[2]])\n"
)


class KretaScriptAdapter:
    def __init__(
        self,
        script_path: Path,
        *,
        expected_sha256: str | None = None,
        python_executable: str | None = None,
        process_timeout: float = 75.0,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self._script_path = Path(script_path).resolve()
        self._expected_sha256 = expected_sha256.lower() if expected_sha256 else None
        self._python = python_executable or sys.executable
        self._timeout = process_timeout
        self._extra_env = dict(extra_env or {})

    @classmethod
    def from_settings(cls, settings: Settings) -> "KretaScriptAdapter":
        return cls(
            settings.kreta_script_path,
            expected_sha256=settings.kreta_script_sha256,
            python_executable=settings.kreta_python,
            process_timeout=settings.kreta_process_timeout_seconds,
        )

    def verify_script(self) -> str:
        if not self._script_path.is_file():
            raise KretaConfigurationError("the E-Kréta script was not found at the configured path")
        actual = sha256_of_file(self._script_path)
        if self._expected_sha256 and actual != self._expected_sha256:
            raise KretaConfigurationError("the E-Kréta script does not match the pinned SHA-256 digest")
        return actual

    async def start(self, username: str, password: str) -> tuple[KretaSession | None, KretaResult]:
        session = await self._spawn()
        try:
            session.process.stdin.write((username + "\n" + password + "\n").encode("utf-8"))
            await session.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            await self.abort(session)
            return None, KretaResult(KretaOutcome.FAILED)
        result = await self._pump(session, stop_at_prompt=True)
        if result.outcome is not KretaOutcome.TWO_FACTOR_REQUIRED:
            await self.abort(session)
            return None, result
        return session, result

    async def submit_two_factor(self, session: KretaSession, code: str) -> KretaResult:
        try:
            session.process.stdin.write((code + "\n").encode("utf-8"))
            await session.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            await self.abort(session)
            return KretaResult(KretaOutcome.FAILED)
        result = await self._pump(session, stop_at_prompt=False)
        await self.abort(session)
        return result

    async def abort(self, session: KretaSession | None) -> None:
        if session is None or session.closed:
            return
        session.closed = True
        process = session.process
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            logger.warning("kreta_process_wait_timeout")
        session.buffer.clear()
        shutil.rmtree(session.workdir, ignore_errors=True)

    async def _spawn(self) -> KretaSession:
        workdir = Path(tempfile.mkdtemp(prefix="pollakcord-kreta-"))
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
            "HOME": str(workdir),
            "TMPDIR": str(workdir),
        }
        for name in PASSTHROUGH_ENV:
            if name in os.environ:
                env[name] = os.environ[name]
        env.update(self._extra_env)
        process = await asyncio.create_subprocess_exec(
            self._python,
            "-c",
            LIMIT_LAUNCHER,
            self._python,
            str(self._script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workdir),
            env=env,
            start_new_session=True,
        )
        return KretaSession(process=process, workdir=workdir)

    async def _pump(self, session: KretaSession, *, stop_at_prompt: bool) -> KretaResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while True:
            if stop_at_prompt and TWO_FACTOR_PROMPT in session.buffer.decode("utf-8", errors="ignore"):
                return KretaResult(KretaOutcome.TWO_FACTOR_REQUIRED)
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning("kreta_process_timeout")
                return KretaResult(KretaOutcome.SERVICE_UNAVAILABLE)
            try:
                chunk = await asyncio.wait_for(session.process.stdout.read(4096), timeout=remaining)
            except asyncio.TimeoutError:
                logger.warning("kreta_process_timeout")
                return KretaResult(KretaOutcome.SERVICE_UNAVAILABLE)
            if not chunk:
                break
            if len(session.buffer) + len(chunk) > MAX_BUFFER_BYTES:
                logger.warning("kreta_output_too_large")
                return KretaResult(KretaOutcome.FAILED)
            session.buffer.extend(chunk)
        try:
            await asyncio.wait_for(session.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            return KretaResult(KretaOutcome.FAILED)
        return interpret_output(session.buffer.decode("utf-8", errors="ignore"), session.process.returncode)


def interpret_output(text: str, return_code: int | None) -> KretaResult:
    if return_code == 0 and DONE_MARKER in text:
        matches = NAME_LINE.findall(text.split(DONE_MARKER, 1)[1])
        if matches:
            name = parse_full_name(matches[-1])
            if name:
                return KretaResult(KretaOutcome.IDENTIFIED, name)
            return KretaResult(KretaOutcome.FAILED)
    if BAD_TWO_FACTOR_MARKER in text:
        return KretaResult(KretaOutcome.INVALID_TWO_FACTOR)
    if BAD_PASSWORD_MARKER in text:
        return KretaResult(KretaOutcome.INVALID_CREDENTIALS)
    if LICENSE_MARKER in text:
        return KretaResult(KretaOutcome.SERVICE_UNAVAILABLE)
    return KretaResult(KretaOutcome.FAILED)
