import pytest

from app.services.css_sanitizer import SCOPE_SELECTOR, CssRejected, sanitize_css

GOOD = """
:root { --accent: #ff0066; }
.message { background: linear-gradient(90deg, #111, #333); border-radius: 12px !important; }
body .sidebar:hover, .channel[data-x="y"] > span { color: red; }
@media (max-width: 600px) { .message { padding: 4px; } }
"""

REJECTED = {
    "import": ("@import url('https://evil.example/x.css');", "css_forbidden_at_rule"),
    "remote url": (".a { background: url(https://evil.example/p) }", "css_forbidden_value"),
    "quoted url": (".a { background: url('//evil') }", "css_forbidden_function"),
    "escaped function": (".a { background: u\\72l(https://evil) }", "css_forbidden_escape"),
    "fixed overlay": (".a { position: fixed; inset: 0 }", "css_forbidden_value"),
    "spoofed text": (".a::before { content: 'Enter your password:' }", "css_forbidden_value"),
    "font face": ("@font-face { font-family: x; src: local(x) }", "css_forbidden_at_rule"),
    "expression": (".a { width: expression(alert(1)) }", "css_forbidden_function"),
    "javascript string": (".a { font-family: 'javascript:alert(1)' }", "css_forbidden_value"),
    "variable url": (":root { --x: url(//evil) }", "css_forbidden_value"),
    "huge z-index": (".a { z-index: 99999 }", "css_forbidden_value"),
    "keyframes": ("@keyframes x { from {opacity:0} }", "css_forbidden_at_rule"),
    "bad media": ("@media (min-width: 1px) and (-webkit-foo: 1) { .a{color:red} }", "css_forbidden_media"),
    "binding": (".a { -moz-binding: url(x) }", "css_forbidden_property"),
    "image set": (".a { background: image-set('a.png' 1x) }", "css_forbidden_function"),
    "nested braces in selector": (".a { b { color: red } }", "css_parse_error"),
    "attr leak": (".a::after { content: attr(data-token) }", "css_forbidden_function"),
    "null byte": (".a { color: red }\x00", "css_forbidden_escape"),
    "oversized": ("a{b:c}" * 10000, "css_too_large"),
}


def test_valid_css_is_scoped_to_the_user_container():
    result = sanitize_css(GOOD)
    assert f"{SCOPE_SELECTOR} {{\n  --accent: #ff0066;" in result
    assert f"{SCOPE_SELECTOR} .message" in result
    assert f"{SCOPE_SELECTOR} .sidebar:hover" in result
    assert "@media (max-width: 600px)" in result
    assert "body" not in result.replace("--", "")


def test_every_rule_in_the_output_is_scoped():
    result = sanitize_css(".a, .b > .c, html .d, :root { color: red } @media (min-width: 10px) { .z { color: blue } }")
    selectors = [line.rstrip(",") for line in result.splitlines() if line.strip() and not line.startswith(("  ", "}", "@media"))]
    assert selectors and all(line.startswith(SCOPE_SELECTOR) for line in selectors)


@pytest.mark.parametrize("name", REJECTED)
def test_dangerous_css_is_rejected(name):
    source, code = REJECTED[name]
    with pytest.raises(CssRejected) as error:
        sanitize_css(source)
    assert error.value.code == code


def test_empty_and_comment_only_css_is_allowed():
    assert sanitize_css("") == ""
    assert sanitize_css("/* just a note */") == ""


def test_api_stores_only_sanitized_css(make_user):
    user = make_user("stilus")
    bad = user.patch("/me/settings", {"custom_css": "@import url(https://evil.example/x.css);"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "css_rejected"
    ok = user.patch("/me/settings", {"custom_css": ".message { color: #123456 }"})
    assert ok.status_code == 200
    stored = ok.json()["settings"]["custom_css"]
    assert stored.startswith(SCOPE_SELECTOR)
    cleared = user.patch("/me/settings", {"custom_css": "   "})
    assert cleared.json()["settings"]["custom_css"] == ""
