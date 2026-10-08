import base64
import hmac
import io
import time

import pyotp
import segno

STEP_SECONDS = 30
WINDOW = 1


def generate_secret() -> str:
    return pyotp.random_base32(32)


def provisioning_uri(secret: str, account_name: str, issuer: str) -> str:
    return pyotp.TOTP(secret, interval=STEP_SECONDS).provisioning_uri(name=account_name, issuer_name=issuer)


def qr_data_uri(uri: str) -> str:
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", scale=6, border=2, dark="#111111", light="#ffffff", xmldecl=False)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify_code(secret: str, code: str, last_used_step: int, now: float | None = None) -> int | None:
    candidate = code.strip().replace(" ", "")
    if len(candidate) != 6 or not candidate.isdigit():
        return None
    totp = pyotp.TOTP(secret, interval=STEP_SECONDS)
    base_step = current_step(now)
    matched: int | None = None
    for offset in range(-WINDOW, WINDOW + 1):
        step = base_step + offset
        expected = totp.at(step * STEP_SECONDS)
        if hmac.compare_digest(expected, candidate):
            matched = step
    if matched is None or matched <= last_used_step:
        return None
    return matched
