#!/usr/bin/env python3
"""
e-Kréta login + print student name
===================================
Built STRICTLY from the request/response dumps in requests/*.json.

Flow mirrored from the captures:
  1. GET  idp.../Account/Login          → antiforgery token
  2. POST idp.../account/checkpasswordforwhitespaces
  3. POST idp.../account/login          (fields from 0034.json)
  4. POST idp.../account/loginwithtwofactor  (fields from 0054/0060.json)
  5. Follow authorize/callback form POST to school
  6. POST school.../Adminisztracio/SzerepkorValaszto/ChangeRole
  7. POST school.../Layout/GetLayoutInformation
     → JSON contains "UserName"  (seen in 0136.json)

Usage:
  python3 kreta_login_from_dumps.py
"""

import re
import sys
import getpass
from html import unescape
from urllib.parse import urlparse, parse_qs, urlencode, quote

import requests

# ---------------------------------------------------------------------------
# Constants taken from the dumps
# ---------------------------------------------------------------------------
INSTITUTE_CODE = "hszc-pollak"
CLIENT_ID      = "kreta-web"
IDP            = "https://idp.e-kreta.hu"
SCHOOL         = f"https://{INSTITUTE_CODE}.e-kreta.hu"
USER_AGENT     = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
})


def log(msg: str = ""):
    print(msg, flush=True)


def show_session_keys(label: str = ""):
    """Print cookies that act as the auth 'key' (as seen in the dumps)."""
    keys = []
    for c in session.cookies:
        if any(x in c.name.lower() for x in (
            "kreta", "application", "antiforgery", "session", "lbid", "check-session"
        )):
            val = c.value
            keys.append(f"  {c.name} = {val[:70]}{'...' if len(val) > 70 else ''}")
    if keys:
        log(f"[session keys{(' – ' + label) if label else ''}]")
        for line in keys:
            log(line)
    else:
        log(f"[session keys{(' – ' + label) if label else ''}] (none)")


def extract_antiforgery(html: str) -> str | None:
    # Patterns observed in dumps + common ASP.NET variants
    patterns = [
        r'name=["\']__RequestVerificationToken["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']__RequestVerificationToken["\']',
        r'name=["\']__RequestVerificationToken["\']\s+type=["\']hidden["\']\s+value=["\']([^"\']+)["\']',
        r'__RequestVerificationToken["\']\s+value=["\']([^"\']+)["\']',
        r'name=__RequestVerificationToken[^>]*value=([^\s>]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            return m.group(1)
    # Last resort: any long CfDJ... token near the words RequestVerification
    m = re.search(
        r'RequestVerificationToken.{0,80}?(CfDJ[A-Za-z0-9_-]{20,})',
        html, re.I | re.S
    )
    if m:
        return m.group(1)
    m = re.search(
        r'(CfDJ[A-Za-z0-9_-]{30,}).{0,80}?RequestVerificationToken',
        html, re.I | re.S
    )
    if m:
        return m.group(1)
    return None


def extract_return_url_from_login_page(html: str) -> str | None:
    patterns = [
        r'name=["\']ReturnUrl["\'][^>]*value=["\']([^"\']+)["\']',
        r'value=["\']([^"\']+)["\'][^>]*name=["\']ReturnUrl["\']',
        r'id=["\']ReturnUrl["\'][^>]*value=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            # HTML may contain &amp; instead of &
            return unescape(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step1_login_page():
    """
    Real flow from the dumps:
      Browser opens https://hszc-pollak.e-kreta.hu/
      → 302 to idp/connect/authorize?...&institute_code=...&institute_data=...
      → 302 to /Account/Login?ReturnUrl=...
      Login HTML contains the form + __RequestVerificationToken.

    Starting at the school root is required so the server embeds a valid
    institute_data (license flag). Hitting authorize without it returns
    the "licence lejárt / belépés nem elérhető" page with no form.
    """
    log("=== 1. School home → authorize → Login page ===")

    # Start at the school – this is what produces institute_data in the dumps
    r = session.get(
        SCHOOL + "/",
        headers={
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
        },
        allow_redirects=True,
        timeout=30,
    )
    log(f"  school home status={r.status_code} final={r.url[:100]}...")
    log(f"  HTML length={len(r.text)}  cookies={list(session.cookies.keys())}")
    show_session_keys("after school redirect")

    # Detect the expired-license error page
    if "licence" in r.text.lower() or "license" in r.text.lower() or "lejárt" in r.text.lower():
        if "belépési lehetőségei nem elérhetőek" in r.text or "belép" in r.text.lower():
            log("")
            log("  !!! IDP returned the EXPIRED LICENSE page !!!")
            log("  Message from server:")
            import re as _re
            m = _re.search(r'alert alert-danger[^>]*>(.*?)</div>', r.text, _re.S | _re.I)
            if m:
                msg = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
                log(f"  → {msg}")
            log("")
            log("  This means the school (hszc-pollak) is currently blocked for login")
            log("  by the central IDP. Your earlier dumps worked because the school")
            log("  still served a valid institute_data at that time.")
            log("  Try opening https://hszc-pollak.e-kreta.hu/ in a normal browser")
            log("  – if you see the same red error, login is blocked for everyone.")
            debug_path = "login_page_debug.html"
            with open(debug_path, "w", encoding="utf-8") as df:
                df.write(r.text)
            log(f"  Saved HTML to {debug_path}")
            sys.exit(1)

    token = extract_antiforgery(r.text)
    if not token:
        log("  ERROR: __RequestVerificationToken not found in login HTML")
        debug_path = "login_page_debug.html"
        with open(debug_path, "w", encoding="utf-8") as df:
            df.write(r.text)
        log(f"  Saved full HTML to {debug_path} ({len(r.text)} bytes)")
        inputs = re.findall(r'<input[^>]{0,400}>', r.text, re.I)
        log(f"  Found {len(inputs)} <input> tags")
        for inp in inputs[:15]:
            log(f"    {inp[:200]}")
        forms = re.findall(r'<form[^>]{0,300}>', r.text, re.I)
        log(f"  Found {len(forms)} <form> tags")
        for frm in forms[:5]:
            log(f"    {frm[:200]}")
        title = re.search(r'<title[^>]*>(.*?)</title>', r.text, re.I | re.S)
        log(f"  page title: {title.group(1).strip() if title else '(none)'}")
        log("  --- HTML (first 1500 chars) ---")
        log(r.text[:1500])
        sys.exit(1)
    log(f"  antiforgery = {token[:50]}...")

    form_return = extract_return_url_from_login_page(r.text)
    if form_return:
        return_url = form_return
        log(f"  ReturnUrl from form (len={len(return_url)})")
    else:
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(r.url).query)
        return_url = qs.get("ReturnUrl", [""])[0]
        log(f"  ReturnUrl from query (len={len(return_url)})")
    return token, return_url



def step2_password_check(password: str):
    """POST /account/checkpasswordforwhitespaces – body shape from 0032.json"""
    log("\n=== 2. POST /account/checkpasswordforwhitespaces ===")
    url = f"{IDP}/account/checkpasswordforwhitespaces"
    payload = {
        "password": password,
        "username": None,
        "redirectUri": None,
        "token": None,
    }
    r = session.post(
        url,
        json=payload,
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": IDP,
        },
        timeout=15,
    )
    log(f"  status {r.status_code}  body={r.text[:120]}")


def step3_login(username: str, password: str, token: str, return_url: str):
    """
    POST /account/login
    Exact field names from 0034.json.
    On success the dump shows 302 → /account/loginwithtwofactor (or authorize callback).
    """
    log("\n=== 3. POST /account/login ===")
    url = f"{IDP}/account/login"
    data = {
        "ReturnUrl": return_url,
        "ClientId": "",
        "IsTemporaryLogin": "False",
        "InstituteCode": INSTITUTE_CODE,
        "UserName": username,
        "Password": password,
        "loginType": "InstituteLogin",
        "__RequestVerificationToken": token,
    }
    r = session.post(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": IDP,
            "Referer": f"{IDP}/Account/Login",
        },
        allow_redirects=True,
        timeout=20,
    )
    log(f"  status {r.status_code}  final url={r.url[:120]}")
    show_session_keys("after password login")

    # Detect outcome from URL + HTML
    url_l = r.url.lower()
    html = r.text or ""
    is_2fa = (
        "loginwithtwofactor" in url_l
        or "VerificationValue" in html
        or "otp-input" in html
        or 'VerificationType' in html
        or "Kétlépcsős" in html
        or "ketlepcso" in html.lower()
        or "Authenticator" in html
    )
    still_login = (
        ("account/login" in url_l and "twofactor" not in url_l)
        and ("name=\"UserName\"" in html or 'name="UserName"' in html)
    )
    login_error = None
    # ASP.NET validation / error summary
    import re as _re
    err = _re.search(r'class="[^"]*validation-summary[^"]*"[^>]*>(.*?)</div>', html, _re.S | _re.I)
    if err:
        login_error = _re.sub(r'<[^>]+>', ' ', err.group(1)).strip()
    err2 = _re.search(r'alert alert-danger[^>]*>(.*?)</div>', html, _re.S | _re.I)
    if err2 and not login_error:
        login_error = _re.sub(r'<[^>]+>', ' ', err2.group(1)).strip()

    if still_login and not is_2fa:
        log("  WARNING: still on login page – password login likely failed")
        if login_error:
            log(f"  server message: {login_error[:200]}")
        # save for debug
        with open("login_after_post_debug.html", "w", encoding="utf-8") as df:
            df.write(html)
        log("  saved login_after_post_debug.html")

    new_token = extract_antiforgery(html) or token
    if is_2fa:
        log("  → 2FA page detected")
        log(f"  new antiforgery = {new_token[:50]}...")
    return r, is_2fa, new_token, return_url


def step4_2fa(totp: str, token: str, return_url: str):
    """
    POST /account/loginwithtwofactor
    Exact fields from 0054.json / 0060.json.
    Successful dump response is 302 → /connect/authorize/callback.
    """
    log("\n=== 4. POST /account/loginwithtwofactor ===")
    url = f"{IDP}/account/loginwithtwofactor"
    digits = list(totp.strip())
    if len(digits) != 6 or not all(c.isdigit() for c in digits):
        log(f"  WARNING: TOTP should be 6 digits, got {totp!r}")

    data = [
        ("ReturnUrl", return_url),
        ("ClientId", CLIENT_ID),
        ("RememberLogin", "False"),
        ("VerificationType", "Totp"),
    ]
    for d in digits[:6]:
        data.append(("VerificationValue", d))
    # pad if short
    for _ in range(max(0, 6 - len(digits))):
        data.append(("VerificationValue", ""))
    data.append(("TrustDevice", "false"))
    data.append(("TrustDevice", "false"))
    data.append(("__RequestVerificationToken", token))

    r = session.post(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": IDP,
            "Referer": f"{IDP}/account/loginwithtwofactor",
        },
        allow_redirects=True,
        timeout=20,
    )
    log(f"  status {r.status_code}  final url={r.url[:120]}")
    show_session_keys("after 2FA")

    # Detect failure
    html = r.text or ""
    if "loginwithtwofactor" in r.url.lower() or "Account/Login" in r.url:
        log("  WARNING: still on auth page after 2FA – code may be wrong/expired")
        import re as _re
        err = _re.search(r'alert alert-danger[^>]*>(.*?)</div>', html, _re.S | _re.I)
        if err:
            msg = _re.sub(r'<[^>]+>', ' ', err.group(1)).strip()
            log(f"  server message: {msg[:200]}")
        with open("2fa_after_post_debug.html", "w", encoding="utf-8") as df:
            df.write(html)
        log("  saved 2fa_after_post_debug.html")
    return r



def step5_follow_code_form(html: str):
    """
    The authorize/callback response (0061.json) is an HTML form that POSTs
    code/scope/state/session_state to the school domain.
    """
    log("\n=== 5. Follow code form → school ===")
    action = re.search(r"<form[^>]+action=['\"]([^'\"]+)['\"]", html, re.I)
    if not action:
        log("  No form found – maybe already on school domain")
        return
    action_url = action.group(1)
    fields = re.findall(r"<input[^>]+name=['\"]([^'\"]+)['\"][^>]+value=['\"]([^'\"]*)['\"]", html, re.I)
    # also value-before-name order
    fields2 = re.findall(r"<input[^>]+value=['\"]([^'\"]*)['\"][^>]+name=['\"]([^'\"]+)['\"]", html, re.I)
    data = dict(fields)
    for v, n in fields2:
        data.setdefault(n, v)

    log(f"  posting to {action_url}")
    log(f"  form fields: {list(data.keys())}")
    r = session.post(action_url, data=data, allow_redirects=True, timeout=20)
    log(f"  status {r.status_code}  final url={r.url[:100]}")
    show_session_keys("after code handoff")
    return r


def step6_change_role():
    """POST ChangeRole {"Role":"Ellenorzo"} – from 0091.json"""
    log("\n=== 6. POST /Adminisztracio/SzerepkorValaszto/ChangeRole ===")
    url = f"{SCHOOL}/Adminisztracio/SzerepkorValaszto/ChangeRole"
    r = session.post(
        url,
        json={"Role": "Ellenorzo"},
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": SCHOOL,
            "Referer": f"{SCHOOL}/Adminisztracio/BelepesKezelo",
        },
        timeout=15,
    )
    log(f"  status {r.status_code}  body={r.text[:150]}")
    show_session_keys("after ChangeRole")
    return r


def step7_get_student_name() -> str | None:
    """
    POST /Layout/GetLayoutInformation  body={"url":"/Intezmeny/Faliujsag"}
    Response (0136.json) contains:
      {"UserMenu":{"UserName":"Piti Péter (Szabó Erzsébet)", ...}, ...}
    """
    log("\n=== 7. POST /Layout/GetLayoutInformation  → student name ===")
    url = f"{SCHOOL}/Layout/GetLayoutInformation"
    r = session.post(
        url,
        json={"url": "/Intezmeny/Faliujsag"},
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": SCHOOL,
            "Referer": f"{SCHOOL}/Intezmeny/Faliujsag",
        },
        timeout=15,
    )
    log(f"  status {r.status_code}")
    if r.status_code != 200:
        log(f"  body: {r.text[:300]}")
        return None

    try:
        data = r.json()
    except Exception:
        log("  not JSON (probably not logged in). Preview:")
        log("  " + r.text[:300].replace("\n", " "))
        # maybe the name is in HTML UserName class (as in BelepesKezelo dump)
        m = re.search(r'class="UserName">\s*([^<]+)', r.text or "")
        if m:
            name = unescape(m.group(1)).strip()
            log(f"\n>>> Student name (from HTML): {name}")
            return name
        return None

    # Path seen in the dump
    name = None
    if isinstance(data, dict):
        um = data.get("UserMenu") or {}
        name = um.get("UserName") or data.get("UserName")
    if name:
        log(f"\n>>> Student name: {name}")
        return name

    log("  UserName not found. Full JSON keys:", list(data.keys()) if isinstance(data, dict) else type(data))
    log("  preview:", str(data)[:400])
    return None


def main():
    log("e-Kréta login (from your request dumps only)")
    log("=" * 55)
    log(f"Institute : {INSTITUTE_CODE}")
    log(f"Client ID : {CLIENT_ID}")
    log()

    username = input("Username (UserName): ").strip()
    password = input("Password (visible): ").strip()

    if not username or not password:
        log("Username and password are required.")
        sys.exit(1)

    token, return_url = step1_login_page()
    log(f"  (using password: {password!r})")
    step2_password_check(password)
    r, needs_2fa, token, return_url = step3_login(username, password, token, return_url)

    if needs_2fa:
        # Ask for TOTP *now* so it is still valid (30s window)
        totp = input("2FA required – enter current TOTP (6 digits): ").strip()
        r = step4_2fa(totp, token, return_url)
    else:
        log("\n=== 4. 2FA not required (skipped) ===")

    # After successful auth the response is usually the code form (0061.json)
    html = (r.text or "") if r is not None else ""
    if "<form" in html and ("name='code'" in html or 'name="code"' in html or "name='code'" in html):
        step5_follow_code_form(html)
    else:
        log("\n=== 5. GET /Adminisztracio/BelepesKezelo ===")
        br = session.get(f"{SCHOOL}/Adminisztracio/BelepesKezelo", timeout=15, allow_redirects=True)
        log(f"  status {br.status_code} final={br.url[:100]}")
        show_session_keys("after BelepesKezelo")
        # if we got a code form here
        if br is not None and "name='code'" in (br.text or "") or 'name="code"' in (br.text or ""):
            step5_follow_code_form(br.text)

    step6_change_role()
    name = step7_get_student_name()

    log("\n=== Done ===")
    if name:
        log(f"Student name returned by API: {name}")
    else:
        log("Could not extract student name – check the steps above for errors.")
        log("If 2FA/login failed, open the *_debug.html files for the server message.")



if __name__ == "__main__":
    main()
