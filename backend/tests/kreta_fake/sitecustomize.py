import io
import json
import os
import time
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import BaseAdapter
from requests.models import Response
from requests.structures import CaseInsensitiveDict

SCHOOL = "https://hszc-pollak.e-kreta.hu"
IDP = "https://idp.e-kreta.hu"
LOGIN_FORM = (
    "<html><body><form method=\"post\" action=\"/account/login\">"
    "<input name=\"__RequestVerificationToken\" type=\"hidden\" value=\"CfDJ8FAKEANTIFORGERYTOKEN0123456789\" />"
    "<input type=\"hidden\" name=\"ReturnUrl\" value=\"/connect/authorize/callback?client_id=kreta-web&amp;state=fake\" />"
    "<input name=\"UserName\" /><input name=\"Password\" type=\"password\" />{error}</form></body></html>"
)
TWO_FACTOR_FORM = (
    "<html><body><form method=\"post\" action=\"/account/loginwithtwofactor\">"
    "<input name=\"__RequestVerificationToken\" type=\"hidden\" value=\"CfDJ8FAKETWOFACTORTOKEN0123456789012\" />"
    "<input name=\"VerificationType\" value=\"Totp\" />{inputs}{error}</form></body></html>"
)
CODE_FORM = (
    "<html><body><form method='post' action='" + SCHOOL + "/signin-oidc'>"
    "<input type='hidden' name='code' value='FAKECODE'/><input type='hidden' name='scope' value='openid'/>"
    "<input type='hidden' name='state' value='fake'/><input type='hidden' name='session_state' value='fake'/>"
    "</form></body></html>"
)


def make_response(request, status, body="", headers=None, content_type="text/html; charset=utf-8"):
    response = Response()
    response.status_code = status
    response.url = request.url
    response.request = request
    response.encoding = "utf-8"
    response.reason = "OK"
    payload = body.encode("utf-8") if isinstance(body, str) else body
    response._content = payload
    response.raw = io.BytesIO(payload)
    merged = {"Content-Type": content_type}
    merged.update(headers or {})
    response.headers = CaseInsensitiveDict(merged)
    return response


def form_fields(request):
    body = request.body or ""
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return parse_qs(body, keep_blank_values=True)


class FakeKreta(BaseAdapter):
    def __init__(self):
        super().__init__()
        self.scenario = os.environ.get("FAKE_KRETA_SCENARIO", "ok")
        self.user = os.environ.get("FAKE_KRETA_USER", "diak123")
        self.password = os.environ.get("FAKE_KRETA_PASS", "titkos-jelszo")
        self.totp = os.environ.get("FAKE_KRETA_TOTP", "123456")
        self.name = os.environ.get("FAKE_KRETA_NAME", "Piti Péter (Szabó Erzsébet)")
        self.authenticated = False
        self.password_ok = False

    def close(self):
        return None

    def send(self, request, **kwargs):
        parsed = urlparse(request.url)
        host, path, method = parsed.netloc, parsed.path.lower(), request.method
        if self.scenario == "hang":
            time.sleep(60)
        if host.startswith("hszc-pollak") and path == "/" and method == "GET":
            if self.scenario == "license":
                return make_response(
                    request, 200, "<html><div class=\"alert alert-danger\">Az intézmény licence lejárt, belépés nem elérhető</div></html>"
                )
            return make_response(request, 302, headers={"Location": IDP + "/connect/authorize?client_id=kreta-web&institute_data=x"})
        if host == "idp.e-kreta.hu" and path == "/connect/authorize":
            return make_response(request, 302, headers={"Location": "/Account/Login?ReturnUrl=%2Fconnect%2Fauthorize%2Fcallback"})
        if host == "idp.e-kreta.hu" and path == "/account/login" and method == "GET":
            return make_response(request, 200, LOGIN_FORM.format(error=""))
        if path == "/account/checkpasswordforwhitespaces":
            return make_response(request, 200, "false", content_type="application/json")
        if path == "/account/login" and method == "POST":
            fields = form_fields(request)
            ok = fields.get("UserName", [""])[0] == self.user and fields.get("Password", [""])[0] == self.password
            if not ok:
                return make_response(
                    request, 200, LOGIN_FORM.format(error="<div class=\"alert alert-danger\">Hibás felhasználónév vagy jelszó</div>")
                )
            self.password_ok = True
            if self.scenario == "twofactor":
                return make_response(request, 302, headers={"Location": IDP + "/account/loginwithtwofactor"})
            self.authenticated = True
            return make_response(request, 200, CODE_FORM)
        if path == "/account/loginwithtwofactor" and method == "GET":
            inputs = "".join("<input name=\"VerificationValue\" class=\"otp-input\" />" for _ in range(6))
            return make_response(request, 200, TWO_FACTOR_FORM.format(inputs=inputs, error=""))
        if path == "/account/loginwithtwofactor" and method == "POST":
            digits = "".join(form_fields(request).get("VerificationValue", []))
            if self.password_ok and digits == self.totp:
                self.authenticated = True
                return make_response(request, 200, CODE_FORM)
            inputs = "".join("<input name=\"VerificationValue\" class=\"otp-input\" />" for _ in range(6))
            error = "<div class=\"alert alert-danger\">Érvénytelen kód</div>"
            return make_response(request, 200, TWO_FACTOR_FORM.format(inputs=inputs, error=error))
        if path == "/signin-oidc":
            return make_response(request, 200, "<html>school</html>")
        if path == "/adminisztracio/belepeskezelo":
            return make_response(request, 200, "<html>belepes</html>")
        if path == "/adminisztracio/szerepkorvalaszto/changerole":
            return make_response(request, 200 if self.authenticated else 401, "{}", content_type="application/json")
        if path == "/layout/getlayoutinformation":
            if not self.authenticated:
                return make_response(request, 401, "unauthorized")
            body = json.dumps({"UserMenu": {"UserName": self.name}}, ensure_ascii=False)
            return make_response(request, 200, body, content_type="application/json; charset=utf-8")
        return make_response(request, 404, "not found")


_original_init = requests.Session.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self.mount("https://", FakeKreta())


requests.Session.__init__ = _patched_init
