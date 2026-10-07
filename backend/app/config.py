"""Application settings read from the environment (names match ``.env.example``)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Optional until a database call is made. Accepts postgres://, postgresql:// or
    # postgresql+asyncpg://, with sslmode= or ssl= (normalized by ``to_async_url``).
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None

    # CORS (app.security.cors): comma-separated origins; the optional regex is for preview URLs.
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    FRONTEND_ORIGIN_REGEX: str | None = None
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    SUPABASE_URL: str | None = None
    SUPABASE_JWT_SECRET: str | None = None
    SUPABASE_JWKS_URL: str | None = None

    ANTHROPIC_API_KEY: str | None = None
    LLM_MODEL_STRONG: str | None = None
    LLM_MODEL_FAST: str | None = None

    TOKEN_ENC_KEY: str | None = None
    LOG_LLM_BODIES: bool = False

    @property
    def async_database_url(self) -> str | None:
        return to_async_url(self.DATABASE_URL)


ASYNC_DRIVER = "postgresql+asyncpg"
_PLAIN_DRIVERS = ("postgres", "postgresql", ASYNC_DRIVER)


def to_async_url(url: str | None) -> str | None:
    """Normalize a Postgres URL for SQLAlchemy + asyncpg; empty means unset.

    The one place DATABASE_URL is interpreted: the app engine (``app.db.session``) and
    ``alembic/env.py`` both go through ``Settings.async_database_url``.

    * ``postgres://`` and ``postgresql://`` become ``postgresql+asyncpg://``.
    * libpq's ``sslmode=...`` becomes asyncpg's ``ssl=...``. SQLAlchemy hands every query
      parameter to ``asyncpg.connect`` as a keyword, and asyncpg has no ``sslmode`` keyword (it
      fails with a TypeError), while its ``ssl`` keyword takes the same mode names (disable,
      allow, prefer, require, verify-ca, verify-full). An explicit ``ssl=`` wins over ``sslmode=``.

    Deployment uses Supabase's **session** pooler (port 5432), not the transaction pooler (port
    6543): asyncpg prepares and caches statements per connection, and in transaction mode
    consecutive statements may run on different server connections, so prepared statements break.
    Session mode keeps one server connection per client connection, like a direct connection.
    """
    if not url:
        return None
    parsed = make_url(url)
    if parsed.drivername not in _PLAIN_DRIVERS:
        return url  # another driver chosen on purpose; leave it alone
    query = dict(parsed.query)
    sslmode = query.pop("sslmode", None)
    if sslmode is not None and "ssl" not in query:
        query["ssl"] = sslmode
    if parsed.drivername == ASYNC_DRIVER and query == dict(parsed.query):
        return url  # already normalized: hand it over exactly as given
    return parsed.set(drivername=ASYNC_DRIVER, query=query).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
