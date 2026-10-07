"""DATABASE_URL normalization for SQLAlchemy + asyncpg (app.config.to_async_url)."""

import pytest
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.engine import make_url

from app.config import Settings, to_async_url

SUPABASE_SESSION = (
    "postgresql://postgres.abcdefghij:s3cret@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
)


@pytest.mark.parametrize("url", [None, ""])
def test_unset(url: str | None) -> None:
    assert to_async_url(url) is None


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_every_postgres_scheme_becomes_asyncpg(scheme: str) -> None:
    assert to_async_url(f"{scheme}://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"


def test_an_asyncpg_url_without_sslmode_is_returned_unchanged() -> None:
    url = "postgresql+asyncpg://u:p@h:5432/db?ssl=require"
    assert to_async_url(url) == url


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
def test_sslmode_becomes_the_asyncpg_ssl_parameter(mode: str) -> None:
    url = make_url(to_async_url(f"{SUPABASE_SESSION}?sslmode={mode}"))
    assert url.drivername == "postgresql+asyncpg"
    assert dict(url.query) == {"ssl": mode}


def test_an_explicit_ssl_wins_over_sslmode() -> None:
    url = make_url(to_async_url("postgresql://u@h/db?sslmode=disable&ssl=require"))
    assert dict(url.query) == {"ssl": "require"}


def test_other_parts_survive() -> None:
    url = make_url(
        to_async_url("postgres://user.ref:p%40ss%2Fword@host.example:5432/postgres?sslmode=require&x=1")
    )
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "user.ref",
        "p@ss/word",
        "host.example",
        5432,
        "postgres",
    )
    assert dict(url.query) == {"ssl": "require", "x": "1"}


def test_another_driver_is_left_alone() -> None:
    url = "postgresql+psycopg://u@h/db?sslmode=require"
    assert to_async_url(url) == url


def test_settings_use_the_normalization() -> None:
    settings = Settings(_env_file=None, DATABASE_URL=f"{SUPABASE_SESSION}?sslmode=require")
    assert settings.async_database_url == (
        "postgresql+asyncpg://postgres.abcdefghij:s3cret@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
        "?ssl=require"
    )


def test_asyncpg_receives_ssl_and_no_sslmode() -> None:
    """What SQLAlchemy would pass to asyncpg.connect: ``ssl``, never the unsupported ``sslmode``."""
    _, kwargs = PGDialect_asyncpg().create_connect_args(
        make_url(to_async_url(f"{SUPABASE_SESSION}?sslmode=require"))
    )
    assert kwargs["ssl"] == "require"
    assert "sslmode" not in kwargs
    assert kwargs["port"] == 5432
