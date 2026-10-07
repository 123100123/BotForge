"""CORS settings: FRONTEND_ORIGIN lists origins; FRONTEND_ORIGIN_REGEX is anchored, https-only and
refused when loose. The same rules through the app: tests/integration/test_app_boot.py."""

import logging
import re

import pytest

from app.config import Settings
from app.security.cors import allowed_origin_regex, allowed_origins, normalize_origin

PREVIEWS = r"https://deploy-preview-[0-9]+--botforge\.netlify\.app"


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "app.security.cors" and r.levelno == logging.WARNING
    ]


def test_a_comma_separated_list_is_trimmed_normalized_and_deduplicated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    value = (
        " https://botforge.netlify.app/ ,, HTTPS://Bot-Forge.IR,https://www.bot-forge.ir:443 ,"
        "http://localhost:3000, https://bot-forge.ir ,"
    )
    assert allowed_origins(value) == [
        "https://botforge.netlify.app",
        "https://bot-forge.ir",
        "https://www.bot-forge.ir",
        "http://localhost:3000",
    ]
    assert warnings(caplog) == []


@pytest.mark.parametrize(
    ("entry", "origin"),
    [
        ("http://localhost:3000", "http://localhost:3000"),
        ("https://app.example.com//", "https://app.example.com"),
        ("http://localhost:80", "http://localhost"),
        ("https://app.example.com:8443", "https://app.example.com:8443"),
        ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("http://[::1]:3000", "http://[::1]:3000"),
    ],
)
def test_an_entry_takes_the_form_a_browser_sends(entry: str, origin: str) -> None:
    assert normalize_origin(entry) == origin


@pytest.mark.parametrize(
    "entry",
    [
        "*",
        "https://*.netlify.app",
        "null",
        "botforge.netlify.app",  # no scheme
        "ftp://files.example.com",
        "javascript:alert(1)",
        "https://app.example.com/dashboard",
        "https://app.example.com?x=1",
        "https://app.example.com#top",
        "https://user:hunter2@app.example.com",
        "https://app.example.com:0",
        "https://app.example.com:99999",
        "https:/app.example.com",
        "https://",
        "https://exa mple.com",
        "https://-app.example.com",
        "https://app..example.com",
        "https://بات.ir",  # an internationalized host must be given in its xn-- form
        "https://Kelvin.example.com",  # KELVIN SIGN, which lower() would turn into an ASCII "k"
    ],
)
def test_an_entry_that_is_not_an_http_origin_is_ignored_with_a_warning(
    entry: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert normalize_origin(entry) is None
    assert allowed_origins(f"https://app.example.com,{entry}") == ["https://app.example.com"]
    [warning] = warnings(caplog)
    assert warning.startswith("FRONTEND_ORIGIN: ignoring")
    assert "hunter2" not in warning


def test_a_wildcard_never_allows_every_origin() -> None:
    assert allowed_origins("*") == []
    assert allowed_origins("https://app.example.com, *") == ["https://app.example.com"]


def test_an_empty_value_allows_no_origin_and_says_so(caplog: pytest.LogCaptureFixture) -> None:
    assert allowed_origins("") == []
    assert allowed_origins(" , ,") == []
    assert warnings(caplog) == ["FRONTEND_ORIGIN lists no valid origin"] * 2


def test_the_regex_is_unset_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRONTEND_ORIGIN_REGEX", raising=False)
    assert Settings(_env_file=None).FRONTEND_ORIGIN_REGEX is None
    assert allowed_origin_regex(None) is None
    assert allowed_origin_regex("   ") is None


@pytest.mark.parametrize("configured", [PREVIEWS, f"^{PREVIEWS}$"])
def test_the_regex_only_matches_whole_https_origins(configured: str) -> None:
    regex = allowed_origin_regex(configured)
    assert regex is not None
    pattern = re.compile(regex)
    assert pattern.fullmatch("https://deploy-preview-12--botforge.netlify.app")
    for origin in (
        "https://deploy-preview-12--botforge.netlify.app.evil.com",
        "https://evil-deploy-preview-12--botforge.netlify.app",
        "https://deploy-preview-12--botforge-evil.netlify.app",
        "https://deploy-preview-12--botforge.netlify.app\n",
        "http://deploy-preview-12--botforge.netlify.app",
        "https://main--botforge.netlify.app",
        "https://botforge.netlify.app",
    ):
        assert pattern.search(origin) is None, origin  # anchored here, not only by fullmatch()


def test_the_regex_never_admits_plain_http_null_or_an_overlong_origin() -> None:
    regex = allowed_origin_regex(r"null|https?://deploy-preview-[0-9]+--botforge\.netlify\.app")
    assert regex is not None
    pattern = re.compile(regex)
    assert pattern.fullmatch("https://deploy-preview-3--botforge.netlify.app")
    assert pattern.fullmatch("http://deploy-preview-3--botforge.netlify.app") is None
    assert pattern.fullmatch("null") is None
    assert pattern.fullmatch("https://deploy-preview-" + "1" * 300 + "--botforge.netlify.app") is None


@pytest.mark.parametrize(
    "loose",
    [
        ".*",
        "https://.*",
        "https://[^/]+",
        r"https://[a-z0-9.-]+",
        r"https://.*\.netlify\.app",
        r"https://deploy-preview-[0-9]+--[a-z0-9-]+\.netlify\.app",
        r"https://[a-z0-9-]+\.vercel\.app",
        PREVIEWS + "|.*",
    ],
)
def test_a_regex_that_also_matches_other_sites_is_ignored_with_a_warning(
    loose: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert allowed_origin_regex(loose) is None
    [warning] = warnings(caplog)
    assert warning.startswith("FRONTEND_ORIGIN_REGEX ignored: it also matches")


@pytest.mark.parametrize("broken", ["(", "[a-z", "\\", r"x)|(?:.*"])
def test_a_regex_that_does_not_compile_is_ignored_with_a_warning(
    broken: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert allowed_origin_regex(broken) is None  # x)|(?:.* would otherwise escape the anchors
    [warning] = warnings(caplog)
    assert warning.startswith("FRONTEND_ORIGIN_REGEX ignored: not a valid regular expression")
