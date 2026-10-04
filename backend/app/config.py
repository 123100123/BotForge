"""Application settings read from the environment (names match ``.env.example``)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Optional until a database call is made. Accepts postgres://, postgresql:// or
    # postgresql+asyncpg:// (normalized by ``async_database_url``).
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None

    FRONTEND_ORIGIN: str = "http://localhost:3000"
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


def to_async_url(url: str | None) -> str | None:
    """Rewrite a plain Postgres URL to the asyncpg driver form; empty means unset."""
    if not url:
        return None
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
