import io
import json
import logging
import re
import threading
import tokenize
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ids import SnowflakeGenerator
from app.logging_config import JsonFormatter, redact_value
from app.main import create_app
from app.security.ratelimit import RateLimiter
from app.services.servers import INVITE_ALPHABET, generate_invite_code

from .conftest import ORIGIN, Api, create_server
from .fakes import FakeKretaAdapter

BACKEND = Path(__file__).resolve().parent.parent
PUBLIC_ENDPOINTS = {
    ("GET", "/api/v1/auth/csrf"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/kreta/start"),
    ("POST", "/api/v1/auth/kreta/two-factor"),
    ("POST", "/api/v1/auth/kreta/confirm"),
    ("POST", "/api/v1/auth/kreta/cancel"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/recover/kreta"),
    ("POST", "/api/v1/auth/recover/code"),
    ("POST", "/api/v1/auth/login/method"),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/me/classes"),
    ("GET", "/api/v1/invites/{code}"),
    ("GET", "/api/v1/meta"),
}


def test_responses_carry_security_headers(api):
    response = api.client.get("/api/v1/meta")
    headers = response.headers
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "'unsafe-eval'" not in csp and "script-src 'self' 'unsafe-inline'" not in csp
    assert "connect-src 'self' ws://testserver" in csp
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "same-origin"
    assert "microphone=(self)" in headers["permissions-policy"] and "camera=()" in headers["permissions-policy"]
    assert headers["cache-control"] == "no-store"
    assert re.fullmatch(r"[0-9a-f]{16}", headers["x-request-id"])


def test_hsts_is_sent_in_production_only(settings, kreta):
    production = settings.model_copy(update={"environment": "production", "cookie_secure": True})
    with TestClient(create_app(production, kreta_adapter=kreta), base_url="https://testserver") as client:
        assert "max-age=31536000" in client.get("/healthz").headers["strict-transport-security"]
        assert client.get("/api/docs").status_code == 404
        cookie = client.get("/api/v1/auth/csrf").headers["set-cookie"]
        assert cookie.startswith("__Host-pc_csrf=") and "Secure" in cookie and "Path=/" in cookie


def test_every_non_public_endpoint_rejects_anonymous_callers(app, api):
    api.refresh_csrf()
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            method = method.upper()
            if (method, path) in PUBLIC_ENDPOINTS:
                continue
            url = re.sub(r"\{[^}]+\}", "1", path)
            response = api.request(method, url.removeprefix("/api/v1"), **({"json": {}} if method in ("POST", "PUT", "PATCH") else {}))
            assert response.status_code in (401, 403, 404, 405), (method, path, response.status_code)
            checked += 1
    assert checked > 80


def test_unexpected_errors_never_leak_internals(settings, kreta):
    app = create_app(settings, kreta_adapter=kreta)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        api = Api(client, app)
        api.register("diak1", "jelszo-egy", "eva_k", "Éva")
        detail = create_server(api)
        channel = next(c for c in detail["channels"] if c["type"] == "text")

        async def explode(*args, **kwargs):
            raise RuntimeError("secret path /home/prod/.env password=hunter2 SELECT * FROM users")

        app.state.messages.history = explode
        response = api.get(f"/channels/{channel['id']}/messages")
        assert response.status_code == 500
        body = response.text
        assert response.json()["error"]["code"] == "internal_error"
        for leaked in ("RuntimeError", "hunter2", "/home/prod", "SELECT", "Traceback"):
            assert leaked not in body


def test_rate_limits_apply_to_login_and_kreta_verification(settings, kreta):
    limited = settings.model_copy(update={"rate_limit_enabled": True})
    app = create_app(limited, kreta_adapter=kreta)
    with TestClient(app, base_url=ORIGIN) as client:
        api = Api(client, app)
        body = {"intent": "register", "username": "diak1", "password": "rossz"}
        statuses = [api.post("/auth/kreta/start", body).status_code for _ in range(8)]
        assert statuses == [401] * 6 + [429] * 2
        blocked = api.post("/auth/kreta/start", body)
        assert blocked.json()["error"]["code"] == "rate_limited" and int(blocked.headers["retry-after"]) > 0
        others = [api.post("/auth/kreta/start", {**body, "username": f"user{i}"}).status_code for i in range(10)]
        assert others[-1] == 429
        logins = [api.post("/auth/login", {"username": f"nincs{i}", "secret": "x"}).status_code for i in range(40)]
        assert 429 in logins


def test_rate_limiter_is_a_sliding_window():
    limiter = RateLimiter()
    assert all(limiter.check("k", 3, 60) is None for _ in range(3))
    assert limiter.check("k", 3, 60) > 0
    assert limiter.check("other", 3, 60) is None
    limiter.reset("k")
    assert limiter.check("k", 3, 60) is None
    assert RateLimiter(enabled=False).check("k", 0, 1) is None


def kreta_attempts(settings, kreta, count=12):
    app = create_app(settings, kreta_adapter=kreta)
    with TestClient(app, base_url=ORIGIN) as client:
        api = Api(client, app)
        return [
            api.post(
                "/auth/kreta/start",
                {"intent": "register", "username": f"user{index}", "password": "x"},
                headers={"X-Forwarded-For": f"10.0.0.{index}"},
            ).status_code
            for index in range(count)
        ]


def test_forwarded_headers_are_ignored_unless_proxies_are_trusted(settings, kreta):
    limited = settings.model_copy(update={"rate_limit_enabled": True})
    assert 429 in kreta_attempts(limited, kreta)
    trusted = limited.model_copy(update={"trusted_proxy_hops": 1})
    assert 429 not in kreta_attempts(trusted, kreta)


def test_log_formatter_redacts_secrets(caplog):
    formatter = JsonFormatter()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "login password=hunter2 token: abc123 ok", (), None)
    record.password = "hunter2"
    record.session_token = "abc"
    record.nested = {"authorization": "Bearer x", "safe": "visible"}
    record.recovery_codes = ["AAAA-BBBB"]
    record.kreta_username = "diak1"
    line = formatter.format(record)
    payload = json.loads(line)
    assert "hunter2" not in line and "abc123" not in line and "Bearer" not in line and "AAAA" not in line
    assert payload["password"] == "[redacted]" and payload["nested"]["safe"] == "visible"
    assert payload["level"] == "info" and payload["event"].endswith("ok")
    assert redact_value("plain", "visible") == "visible"


def test_requests_are_logged_without_bodies_cookies_or_secrets(api, capsys):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/login", {"username": "x", "secret": "SuperSecretValue-123"})
    output = capsys.readouterr().out
    assert "SuperSecretValue" not in output and "jelszo-egy" not in output and "pc_session" not in output


def test_invite_codes_are_random_and_use_a_wide_alphabet():
    codes = {generate_invite_code() for _ in range(2000)}
    assert len(codes) == 2000
    assert all(len(c) == 10 and set(c) <= set(INVITE_ALPHABET) for c in codes)
    assert len({c[0] for c in codes}) > 30


def test_snowflake_ids_are_unique_and_increasing_across_threads():
    generator = SnowflakeGenerator(worker_id=7)
    collected: list[list[int]] = []

    def worker():
        collected.append([generator.next_id() for _ in range(2000)])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    flat = [i for chunk in collected for i in chunk]
    assert len(set(flat)) == len(flat)
    assert all(chunk == sorted(chunk) for chunk in collected)
    assert max(flat) < 2**63


def test_media_and_api_do_not_allow_cross_origin_state_changes(api, make_user):
    user = make_user("eva_k")
    user.client.cookies = user.jar
    response = user.client.put(
        f"/api/v1/blocks/{user.uid}",
        headers={"Origin": "https://evil.example", "X-CSRF-Token": user.csrf},
    )
    assert response.status_code == 403
    no_origin = user.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": user.csrf})
    assert no_origin.status_code == 403


def test_passwords_use_argon2id_and_unique_salts(app, make_user):
    import sqlite3

    from .conftest import database_path

    make_user("eva_k")
    make_user("anna_t")
    connection = sqlite3.connect(database_path(app))
    hashes = [row[0] for row in connection.execute("SELECT password_hash FROM auth_methods")]
    connection.close()
    assert len(hashes) == 2 and hashes[0] != hashes[1]
    assert all(h.startswith("$argon2id$") for h in hashes)


def test_python_sources_contain_no_comments_or_docstrings():
    offenders = []
    vendored = BACKEND / "app" / "integrations" / "kreta" / "script"
    for path in sorted(BACKEND.rglob("*.py")):
        if vendored in path.parents or "node_modules" in path.parts or ".venv" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                offenders.append(f"{path.relative_to(BACKEND)}:{token.start[0]} comment")
        import ast

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node, clean=False):
                offenders.append(f"{path.relative_to(BACKEND)}:{getattr(node, 'lineno', 1)} docstring")
    assert offenders == []
