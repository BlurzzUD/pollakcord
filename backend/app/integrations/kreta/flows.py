import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum

from ...crypto.envelope import Vault
from ...errors import AppError
from ...logging_config import get_logger
from .adapter import KretaAuthPort, KretaOutcome, KretaResult, KretaSession, has_control_characters

logger = get_logger("pollakcord.kreta.flows")

MAX_USERNAME_LENGTH = 128
MAX_PASSWORD_LENGTH = 256
POST_IDENTITY_TTL_SECONDS = 900


class FlowState(StrEnum):
    AWAITING_TWO_FACTOR = "awaiting_two_factor"
    IDENTIFIED = "identified"
    CONFIRMED = "confirmed"


class FlowIntent(StrEnum):
    REGISTER = "register"
    RECOVER = "recover"


@dataclass
class KretaFlow:
    intent: FlowIntent
    state: FlowState
    expires_at: float
    identity_hash: str
    session: KretaSession | None = None
    full_name: str | None = None


@dataclass(frozen=True)
class FlowView:
    token: str
    state: FlowState
    full_name: str | None


def _key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_credentials(username: str, password: str) -> tuple[str, str]:
    cleaned_user = username.strip()
    cleaned_pass = password.strip()
    if not cleaned_user or not cleaned_pass:
        raise AppError("kreta_credentials_required", 422)
    if len(cleaned_user) > MAX_USERNAME_LENGTH or len(cleaned_pass) > MAX_PASSWORD_LENGTH:
        raise AppError("kreta_credentials_invalid_format", 422)
    if has_control_characters(cleaned_user) or has_control_characters(cleaned_pass):
        raise AppError("kreta_credentials_invalid_format", 422)
    return cleaned_user, cleaned_pass


def validate_two_factor_code(code: str) -> str:
    cleaned = code.strip().replace(" ", "")
    if len(cleaned) != 6 or not cleaned.isdigit() or not cleaned.isascii():
        raise AppError("kreta_two_factor_format", 422)
    return cleaned


def raise_for_failure(result: KretaResult) -> None:
    mapping = {
        KretaOutcome.INVALID_CREDENTIALS: ("kreta_invalid_credentials", 401),
        KretaOutcome.INVALID_TWO_FACTOR: ("kreta_invalid_two_factor", 401),
        KretaOutcome.SERVICE_UNAVAILABLE: ("kreta_unavailable", 503),
        KretaOutcome.FAILED: ("kreta_failed", 502),
    }
    if result.outcome in mapping:
        code, status = mapping[result.outcome]
        raise AppError(code, status)


class KretaFlowStore:
    def __init__(
        self,
        adapter: KretaAuthPort,
        vault: Vault,
        *,
        namespace: str,
        two_factor_ttl: float,
        max_concurrent: int,
    ) -> None:
        self._adapter = adapter
        self._vault = vault
        self._namespace = namespace
        self._two_factor_ttl = two_factor_ttl
        self._max_concurrent = max_concurrent
        self._flows: dict[str, KretaFlow] = {}
        self._active_processes = 0
        self._sweeper: asyncio.Task[None] | None = None

    def start_sweeper(self) -> None:
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(self._sweep_forever())

    async def shutdown(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        for key in list(self._flows):
            await self._discard(key)

    def identity_hash(self, kreta_username: str) -> str:
        material = f"{self._namespace}|{kreta_username.strip().lower()}".encode("utf-8")
        return self._vault.mac_hex("kreta-identity", material)

    async def begin(self, intent: FlowIntent, username: str, password: str) -> FlowView:
        cleaned_user, cleaned_pass = validate_credentials(username, password)
        if self._active_processes >= self._max_concurrent:
            raise AppError("kreta_busy", 503, headers={"Retry-After": "10"})
        identity_hash = self.identity_hash(cleaned_user)
        self._active_processes += 1
        try:
            session, result = await self._adapter.start(cleaned_user, cleaned_pass)
        except Exception:
            self._active_processes -= 1
            raise
        finally:
            del cleaned_pass
        if session is None:
            self._active_processes -= 1
        raise_for_failure(result)
        token = secrets.token_urlsafe(32)
        flow = KretaFlow(
            intent=intent,
            state=FlowState.AWAITING_TWO_FACTOR,
            expires_at=time.monotonic() + self._two_factor_ttl,
            identity_hash=identity_hash,
            session=session,
        )
        if result.outcome is KretaOutcome.IDENTIFIED:
            self._mark_identified(flow, result.full_name)
        self._flows[_key(token)] = flow
        return FlowView(token, flow.state, flow.full_name)

    async def submit_two_factor(self, token: str, code: str) -> FlowView:
        cleaned = validate_two_factor_code(code)
        flow = self._require(token, FlowState.AWAITING_TWO_FACTOR)
        session = flow.session
        flow.session = None
        if session is None:
            await self._discard(_key(token))
            raise AppError("kreta_flow_invalid", 409)
        try:
            result = await self._adapter.submit_two_factor(session, cleaned)
        finally:
            self._active_processes = max(0, self._active_processes - 1)
        if result.outcome is not KretaOutcome.IDENTIFIED:
            self._flows.pop(_key(token), None)
            raise_for_failure(result)
            raise AppError("kreta_failed", 502)
        self._mark_identified(flow, result.full_name)
        return FlowView(token, flow.state, flow.full_name)

    async def decide(self, token: str, accepted: bool) -> None:
        flow = self._require(token, FlowState.IDENTIFIED)
        if accepted:
            flow.state = FlowState.CONFIRMED
            flow.expires_at = time.monotonic() + POST_IDENTITY_TTL_SECONDS
            return
        await self._discard(_key(token))

    def identity_hash_of(self, token: str) -> str:
        flow = self._flows.get(_key(token))
        if flow is None:
            raise AppError("kreta_flow_invalid", 409)
        return flow.identity_hash

    def intent_of(self, token: str) -> FlowIntent:
        flow = self._flows.get(_key(token))
        if flow is None:
            raise AppError("kreta_flow_invalid", 409)
        return flow.intent

    def peek_confirmed(self, token: str | None, intent: FlowIntent) -> KretaFlow:
        flow = self._require(token, FlowState.CONFIRMED)
        if flow.intent is not intent:
            raise AppError("kreta_flow_invalid", 409)
        return flow

    def finish(self, token: str | None) -> None:
        if not token:
            return
        flow = self._flows.pop(_key(token), None)
        if flow is not None:
            flow.full_name = None

    async def cancel(self, token: str | None) -> None:
        if token:
            await self._discard(_key(token))

    def _mark_identified(self, flow: KretaFlow, full_name: str | None) -> None:
        flow.state = FlowState.IDENTIFIED
        flow.full_name = full_name
        flow.session = None
        flow.expires_at = time.monotonic() + POST_IDENTITY_TTL_SECONDS

    def _require(self, token: str | None, state: FlowState) -> KretaFlow:
        flow = self._flows.get(_key(token)) if token else None
        if flow is None or flow.expires_at < time.monotonic() or flow.state is not state:
            raise AppError("kreta_flow_invalid", 409)
        return flow

    async def _discard(self, key: str) -> None:
        flow = self._flows.pop(key, None)
        if flow is not None and flow.session is not None:
            await self._adapter.abort(flow.session)
            self._active_processes = max(0, self._active_processes - 1)
            flow.session = None
        if flow is not None:
            flow.full_name = None

    async def sweep(self) -> None:
        now = time.monotonic()
        for key, flow in list(self._flows.items()):
            if flow.expires_at < now:
                await self._discard(key)

    async def _sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(15)
            try:
                await self.sweep()
            except Exception as exc:
                logger.error("kreta_flow_sweep_failed", extra={"error_type": type(exc).__name__})
