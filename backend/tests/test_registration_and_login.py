import re

import pyotp

from .conftest import ORIGIN, STRONG_PASSWORD, database_dump, sql_rows


def test_default_language_is_hungarian(api):
    response = api.client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "A keresett elem nem található."


def test_error_messages_follow_accept_language(api):
    english = api.client.get("/api/v1/me", headers={"Accept-Language": "en-US,en;q=0.9"})
    german = api.client.get("/api/v1/me", headers={"Accept-Language": "de"})
    hungarian = api.client.get("/api/v1/me")
    assert english.json()["error"]["message"] == "Sign in to continue."
    assert german.json()["error"]["message"] == "Melde dich an, um fortzufahren."
    assert hungarian.json()["error"]["message"] == "Jelentkezz be a folytatáshoz."


def test_registration_shows_real_name_only_to_the_verified_person(api):
    started = api.kreta_verify("diak1", "jelszo-egy")
    assert started.status_code == 200
    assert started.json() == {"status": "identified", "full_name": "Kiss Éva", "resume": False}


def test_rejecting_identity_ends_the_flow(api):
    api.kreta_verify("diak1", "jelszo-egy")
    assert api.post("/auth/kreta/confirm", {"confirmed": False}).json() == {"status": "cancelled"}
    again = api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "kreta_flow_invalid"


def test_register_requires_confirmation(api):
    api.kreta_verify("diak1", "jelszo-egy")
    response = api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    assert response.status_code == 409


def test_wrong_kreta_credentials_are_rejected(api, kreta):
    response = api.kreta_verify("diak1", "rossz-jelszo")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "kreta_invalid_credentials"
    assert "rossz-jelszo" not in response.text


def test_kreta_two_factor_flow(api, kreta):
    started = api.kreta_verify("diak2", "jelszo-ketto")
    assert started.json() == {"status": "two_factor_required"}
    bad = api.post("/auth/kreta/two-factor", {"code": "000000"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "kreta_invalid_two_factor"
    api.kreta_verify("diak2", "jelszo-ketto")
    good = api.post("/auth/kreta/two-factor", {"code": "123456"})
    assert good.json()["status"] == "identified"
    assert good.json()["full_name"] == "Nagy Péter"
    assert all(session.aborted for session in kreta.sessions)


def test_two_factor_code_must_be_six_digits(api):
    api.kreta_verify("diak2", "jelszo-ketto")
    response = api.post("/auth/kreta/two-factor", {"code": "12ab56"})
    assert response.status_code == 422


def test_full_registration_with_password(api):
    payload = api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    assert payload["user"]["username"] == "eva_k"
    assert payload["user"]["display_name"] == "Éva"
    assert len(payload["recovery_codes"]) == 8
    assert "Kiss" not in str(payload)
    session = api.get("/auth/session").json()
    assert session["authenticated"] is True


def test_real_name_never_appears_in_any_response(api, make_user):
    other = make_user("masik_diak")
    me = api.register("diak3", "jelszo-harom", "anna_t", "Anna")
    responses = [
        api.get("/me"),
        api.get("/auth/session"),
        other.get(f"/users/{me['user']['id']}"),
        other.get("/users/search", params={"q": "anna"}),
        api.get("/friends"),
    ]
    for response in responses:
        assert "Tóth" not in response.text
        assert "Anna Tóth" not in response.text


def test_real_name_is_encrypted_at_rest(app, api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    blob, identity_hash = sql_rows(app, "SELECT real_name_enc, identity_hash FROM user_identities")[0]
    assert "Kiss".encode() not in blob
    assert "Éva".encode() not in blob
    assert "diak1" not in identity_hash
    assert len(identity_hash) == 64


def test_username_rules(api):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    for bad in ["ab", "Admin", "has space", "dot..dot", "x" * 40, "árvíz", "moderator"]:
        response = api.post("/auth/register", {"username": bad, "display_name": "X"})
        assert response.status_code in (422, 409), (bad, response.text)
        assert response.status_code != 200


def test_username_is_unique_case_insensitively(api, make_user):
    make_user("eva_k")
    fresh = type(api)(api.client, api.app)
    fresh.kreta_verify("diak4", "jelszo-negy")
    fresh.post("/auth/kreta/confirm", {"confirmed": True})
    response = fresh.post("/auth/register", {"username": "EVA_K", "display_name": "Más"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "username_taken"


def test_same_kreta_identity_cannot_register_twice(api, make_user):
    make_user("eva_k", kreta_user="diak1")
    again = type(api)(api.client, api.app)
    response = again.kreta_verify("diak1", "jelszo-egy")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_registered"


def test_pending_registration_can_be_resumed(api):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    fresh = type(api)(api.client, api.app)
    resumed = fresh.kreta_verify("diak1", "jelszo-egy")
    assert resumed.json()["resume"] is True
    fresh.post("/auth/kreta/confirm", {"confirmed": True})
    renamed = fresh.post("/auth/register", {"username": "eva_uj", "display_name": "Éva"})
    assert renamed.status_code == 200
    assert fresh.post("/auth/security/password", {"password": STRONG_PASSWORD}).status_code == 200


def test_kreta_credentials_are_never_stored(api, app):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    dump = database_dump(app)
    assert "jelszo-egy" not in dump
    assert "diak1" not in dump


def test_password_login_and_greeting_data(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    api.post("/auth/logout")
    assert api.get("/me").status_code == 401
    method = api.post("/auth/login/method", {"username": "eva_k"}).json()
    assert method == {"method": "password"}
    response = api.login()
    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "Éva"
    assert api.get("/me").status_code == 200


def test_password_policy(api):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    assert api.post("/auth/security/password", {"password": "short"}).json()["error"]["code"] == "password_too_short"
    assert api.post("/auth/security/password", {"password": "password123"}).json()["error"]["code"] == "password_too_common"
    assert api.post("/auth/security/password", {"password": "xx-eva_k-xx-yy"}).json()["error"]["code"] == "password_contains_username"
    assert api.post("/auth/security/password", {"password": STRONG_PASSWORD}).status_code == 200


def test_security_setup_is_required_before_using_the_app(api):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    assert api.get("/me").status_code == 403
    assert api.get("/friends").status_code == 403
    assert api.post("/servers", {"name": "Teszt"}).status_code == 403


def test_totp_registration_and_login(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva", method="totp")
    api.post("/auth/logout")
    assert api.post("/auth/login/method", {"username": "eva_k"}).json() == {"method": "totp"}
    assert api.login("eva_k", "000000").status_code == 401
    good = api.login("eva_k", api.next_totp(1))
    assert good.status_code == 200, good.text


def test_totp_codes_cannot_be_replayed(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva", method="totp")
    api.post("/auth/logout")
    code = api.next_totp(1)
    assert api.login("eva_k", code).status_code == 200
    api.post("/auth/logout")
    assert api.login("eva_k", code).status_code == 401


def test_totp_setup_requires_valid_code_and_shows_qr(api):
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    begun = api.post("/auth/security/totp/begin").json()
    assert begun["qr_svg"].startswith("data:image/svg+xml;base64,")
    assert begun["otpauth_uri"].startswith("otpauth://totp/")
    assert re.fullmatch(r"[A-Z2-7 ]+", begun["manual_key"])
    assert api.post("/auth/security/totp/confirm", {"code": "000000"}).json()["error"]["code"] == "totp_code_invalid"
    secret = begun["manual_key"].replace(" ", "")
    assert api.post("/auth/security/totp/confirm", {"code": pyotp.TOTP(secret).now()}).status_code == 200


def test_totp_secret_is_encrypted_at_rest(app, api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva", method="totp")
    blob = sql_rows(app, "SELECT secret_enc FROM totp_configs")[0][0]
    assert api.totp_secret.encode() not in blob


def test_unknown_user_looks_like_wrong_password(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    api.post("/auth/logout")
    unknown = api.login("nincs_ilyen", "valami-jelszo")
    wrong = api.login("eva_k", "valami-rossz")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"] == "invalid_credentials"
    assert api.post("/auth/login/method", {"username": "nincs_ilyen"}).status_code == 200


def test_progressive_lockout(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    api.post("/auth/logout")
    for _ in range(5):
        assert api.login("eva_k", "rossz-jelszo-xx").status_code == 401
    locked = api.login("eva_k", STRONG_PASSWORD)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


def test_logout_revokes_the_session(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    stolen = api.jar
    api.post("/auth/logout")
    attacker = type(api)(api.client, api.app)
    attacker.jar = stolen
    assert attacker.get("/me").status_code == 401


def test_login_creates_a_fresh_session_token(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    first = api.jar.get("pc_session")
    api.post("/auth/logout")
    api.login()
    assert api.jar.get("pc_session") != first


def test_session_cookie_flags(api, app):
    api.refresh_csrf()
    api.kreta_verify("diak1", "jelszo-egy")
    api.post("/auth/kreta/confirm", {"confirmed": True})
    response = api.post("/auth/register", {"username": "eva_k", "display_name": "Éva"})
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("pc_session="))
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()


def test_csrf_protection(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    missing = api.client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"
    api.client.cookies = api.jar
    wrong_origin = api.client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example", "X-CSRF-Token": api.csrf})
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error"]["code"] == "origin_not_allowed"
    api.client.cookies = api.jar
    mismatch = api.client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": "forged"})
    assert mismatch.status_code == 403


def test_recovery_codes_are_single_use_and_hashed(app, api):
    payload = api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    codes = payload["recovery_codes"]
    stored = " ".join(row[0] for row in sql_rows(app, "SELECT code_hash FROM recovery_codes"))
    assert len(stored.split()) == 8
    assert all(code.replace("-", "") not in stored for code in codes)
    api.post("/auth/logout")
    fresh = type(api)(api.client, api.app)
    first = fresh.post("/auth/recover/code", {"username": "eva_k", "recovery_code": codes[0]})
    assert first.status_code == 200
    assert fresh.post("/auth/security/password", {"password": "Uj-jelszo-2026-hosszu"}).status_code == 200
    reuse = type(api)(api.client, api.app).post("/auth/recover/code", {"username": "eva_k", "recovery_code": codes[0]})
    assert reuse.status_code == 401


def test_recovery_via_kreta_resets_credentials_and_revokes_sessions(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    old_jar = api.jar
    fresh = type(api)(api.client, api.app)
    started = fresh.kreta_verify("diak1", "jelszo-egy", intent="recover")
    assert started.json()["status"] == "identified"
    fresh.post("/auth/kreta/confirm", {"confirmed": True})
    assert fresh.post("/auth/recover/kreta").status_code == 200
    stale = type(api)(api.client, api.app)
    stale.jar = old_jar
    assert stale.get("/me").status_code == 401
    assert fresh.post("/auth/security/totp/begin").status_code == 200


def test_recovery_requires_existing_account(api):
    response = api.kreta_verify("diak5", "jelszo-ot", intent="recover")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_account"


def test_sessions_can_be_listed_and_revoked(api):
    api.register("diak1", "jelszo-egy", "eva_k", "Éva")
    second = type(api)(api.client, api.app)
    second.login("eva_k", STRONG_PASSWORD)
    sessions = api.get("/me/sessions").json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["current"])
    assert api.delete(f"/me/sessions/{other['id']}").status_code == 200
    assert second.get("/me").status_code == 401
