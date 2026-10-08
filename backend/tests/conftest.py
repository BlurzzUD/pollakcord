import sqlite3
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pyotp
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.crypto.keyring import generate_key_text
from app.main import create_app

from .fakes import FakeKretaAdapter

ORIGIN = "http://testserver"
STRONG_PASSWORD = "Tavaszi-eso-2026!"


class Api:
    def __init__(self, client: TestClient, app) -> None:
        self.client = client
        self.app = app
        self.jar = httpx.Cookies()
        self.csrf = ""
        self.totp_secret: str | None = None
        self.username = ""
        self.secret = ""
        self.user: dict = {}

    def _send(self, method: str, url: str, headers: dict | None = None, **kwargs):
        self.client.cookies = self.jar
        merged = {"Origin": ORIGIN}
        merged.update(headers or {})
        response = self.client.request(method, url, headers=merged, **kwargs)
        self.jar = httpx.Cookies(self.client.cookies)
        return response

    def refresh_csrf(self) -> None:
        self.csrf = self._send("GET", "/api/v1/auth/csrf").json()["csrf_token"]

    def request(self, method: str, path: str, headers: dict | None = None, **kwargs):
        if not self.csrf:
            self.refresh_csrf()
        merged = {"X-CSRF-Token": self.csrf}
        merged.update(headers or {})
        return self._send(method, "/api/v1" + path, headers=merged, **kwargs)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json=None, **kwargs):
        return self.request("POST", path, json=json, **kwargs)

    def put(self, path: str, json=None, **kwargs):
        return self.request("PUT", path, json=json, **kwargs)

    def patch(self, path: str, json=None, **kwargs):
        return self.request("PATCH", path, json=json, **kwargs)

    def delete(self, path: str, json=None, **kwargs):
        if json is not None:
            return self.request("DELETE", path, json=json, **kwargs)
        return self.request("DELETE", path, **kwargs)

    def websocket(self):
        self.client.cookies = self.jar
        return self.client.websocket_connect("/api/v1/ws", headers={"Origin": ORIGIN})

    def kreta_verify(self, kreta_user: str, kreta_password: str, intent: str = "register", two_factor: str | None = None):
        started = self.post("/auth/kreta/start", {"intent": intent, "username": kreta_user, "password": kreta_password})
        if two_factor is not None and started.status_code == 200 and started.json().get("status") == "two_factor_required":
            started = self.post("/auth/kreta/two-factor", {"code": two_factor})
        return started

    def register(
        self,
        kreta_user: str,
        kreta_password: str,
        username: str,
        display_name: str,
        *,
        method: str = "password",
        password: str = STRONG_PASSWORD,
        two_factor: str | None = None,
    ) -> dict:
        started = self.kreta_verify(kreta_user, kreta_password, two_factor=two_factor)
        assert started.status_code == 200, started.text
        assert self.post("/auth/kreta/confirm", {"confirmed": True}).status_code == 200
        created = self.post("/auth/register", {"username": username, "display_name": display_name})
        assert created.status_code == 200, created.text
        self.username = username
        if method == "password":
            done = self.post("/auth/security/password", {"password": password})
            self.secret = password
        else:
            begun = self.post("/auth/security/totp/begin").json()
            self.totp_secret = begun["manual_key"].replace(" ", "")
            done = self.post("/auth/security/totp/confirm", {"code": pyotp.TOTP(self.totp_secret).now()})
        assert done.status_code == 200, done.text
        payload = done.json()
        self.user = payload["user"]
        return payload

    def login(self, username: str | None = None, secret: str | None = None):
        return self.post("/auth/login", {"username": username or self.username, "secret": secret or self.secret})

    def next_totp(self, ahead: int = 1) -> str:
        return pyotp.TOTP(self.totp_secret).at(int(time.time()) + 30 * ahead)

    @property
    def uid(self) -> str:
        return self.user["id"]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        public_origin=ORIGIN,
        cookie_secure=False,
        master_key=generate_key_text(),
        pepper=generate_key_text(),
        upload_dir=tmp_path / "uploads",
        auto_create_schema=True,
        serve_frontend=False,
        argon2_time_cost=1,
        argon2_memory_kib=1024,
        argon2_parallelism=1,
        rate_limit_enabled=False,
        log_level="WARNING",
    )


@pytest.fixture
def kreta() -> FakeKretaAdapter:
    return FakeKretaAdapter()


@pytest.fixture
def app(settings, kreta):
    return create_app(settings, kreta_adapter=kreta)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


def database_path(app) -> str:
    return app.state.settings.database_url.split("///", 1)[1]


def sql_rows(app, statement: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(database_path(app))
    try:
        return connection.execute(statement, params).fetchall()
    finally:
        connection.close()


def database_dump(app) -> str:
    connection = sqlite3.connect(database_path(app))
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


@pytest.fixture
def new_api(client, app) -> Callable[[], Api]:
    return lambda: Api(client, app)


@pytest.fixture
def api(new_api) -> Api:
    return new_api()


@pytest.fixture
def make_user(new_api) -> Callable[..., Api]:
    counter = {"index": 0}
    kreta_users = ["diak1", "diak3", "diak4"]

    def factory(username: str, display_name: str | None = None, *, kreta_user: str | None = None, method: str = "password") -> Api:
        user_api = new_api()
        index = counter["index"]
        counter["index"] += 1
        known = {"diak1": "jelszo-egy", "diak3": "jelszo-harom", "diak4": "jelszo-negy", "diak2": "jelszo-ketto"}
        if kreta_user is not None:
            chosen, secret = kreta_user, known[kreta_user]
        elif index < len(kreta_users):
            chosen = kreta_users[index]
            secret = known[chosen]
        else:
            chosen, secret = f"user{index}", f"pw-{index}"
        user_api.register(chosen, secret, username, display_name or username.title(), method=method)
        return user_api

    return factory


def create_server(api: Api, name: str = "Teszt szerver") -> dict:
    response = api.post("/servers", {"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def channel_named(detail: dict, name: str) -> dict:
    return next(c for c in detail["channels"] if c["name"] == name)


def first_channel(detail: dict, kind: str) -> dict:
    return next(c for c in detail["channels"] if c["type"] == kind)


def join_server(api: Api, invite_code: str) -> dict:
    response = api.post(f"/invites/{invite_code}/accept")
    assert response.status_code == 200, response.text
    return response.json()


def role_named(detail: dict, kind: str) -> dict:
    return next(r for r in detail["roles"] if r["kind"] == kind)
