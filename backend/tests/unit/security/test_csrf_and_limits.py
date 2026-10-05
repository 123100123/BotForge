"""CSRF origin rules, the rate limiter, client-address keys and the email rules (no database)."""

from collections.abc import Iterator

import pytest
from starlette.requests import Request

from app.config import get_settings
from app.security.accounts import normalize_email, valid_email
from app.security.csrf import allowed_origins, csrf_ok, origin_of
from app.security.rate_limit import AuthRateLimits, RateLimiter, client_address


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://BotForge.example.com/api/")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000/, https://[2001:db8::1]:8443, *")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def request(
    method: str = "POST", headers: list[tuple[str, str]] | None = None, client: str = "1.2.3.4"
) -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers or []]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw, "client": (client, 1)})


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://BotForge.example.com/api/", "https://botforge.example.com"),
        ("https://botforge.example.com:443", "https://botforge.example.com"),
        ("http://localhost:80/x", "http://localhost"),
        ("http://localhost:3000", "http://localhost:3000"),
        ("https://[2001:DB8::1]:8443/", "https://[2001:db8::1]:8443"),
        ("null", None),
        ("*", None),
        ("ftp://example.com", None),
        ("https://", None),
        ("https://example.com:99999", None),
    ],
)
def test_origin_of(url: str, origin: str | None) -> None:
    assert origin_of(url) == origin


def test_allowed_origins_come_from_public_base_url_and_frontend_origin() -> None:
    assert allowed_origins() == {
        "https://botforge.example.com",
        "http://localhost:3000",
        "https://[2001:db8::1]:8443",
    }  # a "*" entry allows nothing


@pytest.mark.parametrize(
    ("headers", "ok"),
    [
        ([("X-BotForge-CSRF", "1")], True),
        ([("X-BotForge-CSRF", "1"), ("Origin", "https://botforge.example.com")], True),
        ([("X-BotForge-CSRF", "1"), ("Origin", "http://localhost:3000")], True),
        ([], False),
        ([("X-BotForge-CSRF", "")], False),
        ([("X-BotForge-CSRF", "yes")], False),
        ([("X-BotForge-CSRF", "1"), ("X-BotForge-CSRF", "1")], False),
        ([("X-BotForge-CSRF", "1"), ("Origin", "https://evil.example.com")], False),
        ([("X-BotForge-CSRF", "1"), ("Origin", "null")], False),
        ([("X-BotForge-CSRF", "1"), ("Origin", "*")], False),
        ([("X-BotForge-CSRF", "1"), ("Origin", "https://botforge.example.com/")], False),  # never sent so
        ([("X-BotForge-CSRF", "1"), ("Origin", "https://botforge.example.com"), ("Origin", "null")], False),
    ],
)
def test_csrf_ok(headers: list[tuple[str, str]], ok: bool) -> None:
    assert csrf_ok(request(headers=headers)) is ok


def test_rate_limiter_window_retry_after_and_sweep() -> None:
    now = [1000.0]
    limiter = RateLimiter(60.0, clock=lambda: now[0])
    assert all(limiter.allow("k", 3) for _ in range(3))
    assert not limiter.allow("k", 3)
    assert limiter.retry_after("k") == 60
    now[0] += 30
    assert limiter.retry_after("k") == 30
    now[0] += 31  # the first three hits leave the window
    assert limiter.allow("k", 3)
    for n in range(100):  # keys chosen by callers ...
        limiter.allow(f"spray-{n}", 3)
    assert len(limiter) == 101
    now[0] += 61
    limiter.allow("fresh", 3)  # ... are dropped once idle for a whole window
    assert len(limiter) == 1


@pytest.mark.parametrize(
    ("client", "key"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::ffff", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("testclient", "other:testclient"),
    ],
)
def test_client_address(client: str, key: str) -> None:
    assert client_address(request(client=client)) == key


def test_login_limits_count_per_address_and_per_email() -> None:
    now = [0.0]
    limits = AuthRateLimits(clock=lambda: now[0])
    assert all(limits.allow_login("a", "x@example.com") is None for _ in range(10))
    assert limits.allow_login("b", "x@example.com") is not None  # 11th for this email
    assert limits.allow_login("b", "y@example.com") is None
    assert "x@example.com" not in repr(limits.by_email._hits)  # only a digest of the email is kept


@pytest.mark.parametrize(
    ("raw", "normalized", "valid"),
    [
        ("  Owner@Example.COM \n", "owner@example.com", True),
        ("first.last+tag@sub.example.co", "first.last+tag@sub.example.co", True),
        ("owner@localhost", "owner@localhost", True),
        ("o'brien@example.com", "o'brien@example.com", True),
        ("Kelvin@example.com", "Kelvin@example.com", False),  # not case-mapped
        ("ÄRGER@example.com", "ÄRGER@example.com", False),
        ("a@b@c", "a@b@c", False),
        ("x" * 64 + "@example.com", "x" * 64 + "@example.com", True),
        ("x" * 65 + "@example.com", "x" * 65 + "@example.com", False),
    ],
)
def test_email_rules(raw: str, normalized: str, valid: bool) -> None:
    assert normalize_email(raw) == normalized
    assert valid_email(normalize_email(raw)) is valid


def test_email_length_limit() -> None:
    label = "d" * 63
    email = f"a@{label}.{label}.{label}.{'e' * 56}.com"
    assert len(email) == 254 and valid_email(email)
    assert not valid_email("a" + email)
