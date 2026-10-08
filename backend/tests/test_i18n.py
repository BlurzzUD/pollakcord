import json
import re
from pathlib import Path

import pytest

from app.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, negotiate_language, translate

APP_DIR = Path(__file__).resolve().parent.parent / "app"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def catalog(language: str) -> dict:
    return json.loads((APP_DIR / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def codes_used_in_source() -> set[str]:
    codes: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        codes.update(re.findall(r'AppError\(\s*"([a-z_]+)"', text))
        codes.update(re.findall(r'_csrf_failure\(request, "([a-z_]+)"', text))
        codes.update(re.findall(r'(?:not_found|forbidden)\("([a-z_]+)"\)', text))
        codes.update(re.findall(r'raise_for_failure|"code": "([a-z_]+)"', text))
    codes.discard("")
    return codes


def test_languages_are_hungarian_english_and_german_with_hungarian_default():
    assert SUPPORTED_LANGUAGES == ("hu", "en", "de") and DEFAULT_LANGUAGE == "hu"


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_every_error_code_used_by_the_backend_is_translated(language):
    messages = catalog(language)["errors"]
    missing = sorted(code for code in codes_used_in_source() if code not in messages)
    assert missing == []


def test_every_css_rejection_reason_is_translated():
    from app.services import css_sanitizer

    reasons = set(re.findall(r'CssRejected\(\s*"([a-z_]+)"', Path(css_sanitizer.__file__).read_text(encoding="utf-8")))
    for language in SUPPORTED_LANGUAGES:
        assert sorted(r for r in reasons if r not in catalog(language)["errors"]) == []


def test_all_languages_have_identical_keys_and_placeholders():
    reference = catalog("hu")
    for language in ("en", "de"):
        other = catalog(language)
        for section in reference:
            assert reference[section].keys() == other[section].keys(), (language, section)
            for key, template in reference[section].items():
                assert set(PLACEHOLDER.findall(template)) == set(PLACEHOLDER.findall(other[section][key])), (language, key)


def test_translations_are_not_copies_of_each_other():
    hu, en, de = (catalog(lang)["errors"] for lang in ("hu", "en", "de"))
    identical = [key for key in hu if hu[key] == en[key] or en[key] == de[key]]
    assert identical == []


def test_translate_formats_parameters_and_falls_back():
    assert translate("errors", "rate_limited", "en", seconds=30) == "Too many attempts. Try again in 30 seconds."
    assert translate("errors", "rate_limited", "de", seconds=5).endswith("5 Sekunden erneut.")
    assert translate("errors", "rate_limited", "xx", seconds=5).startswith("Túl sok")
    assert translate("errors", "no_such_code", "en") == "no_such_code"
    assert "{seconds}" in translate("errors", "rate_limited", "hu")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "hu"),
        ("", "hu"),
        ("en-US,en;q=0.9", "en"),
        ("de-DE,de;q=0.8,en;q=0.5", "de"),
        ("fr-FR,fr;q=0.9,de;q=0.4", "de"),
        ("fr", "hu"),
        ("en;q=0.1,de;q=0.9", "de"),
        ("*", "hu"),
        ("en;q=abc", "hu"),
    ],
)
def test_language_negotiation(header, expected):
    assert negotiate_language(header) == expected


def test_validation_errors_are_localized_without_leaking_input(api):
    response = api.client.post(
        "/api/v1/auth/login",
        json={"username": "x"},
        headers={"Origin": "http://testserver", "X-CSRF-Token": "bad", "Accept-Language": "de"},
    )
    assert response.status_code == 403
    api.refresh_csrf()
    invalid = api.post("/auth/login", {"username": "x"}, headers={"Accept-Language": "de"})
    assert invalid.status_code == 422
    body = invalid.json()["error"]
    assert body["code"] == "validation_error" and body["message"].startswith("Die übermittelten")
    assert body["fields"][0]["field"] == "secret"
