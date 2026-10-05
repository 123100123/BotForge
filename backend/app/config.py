"""Application settings read from the environment (names match ``.env.example``)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Optional until a database call is made. Accepts postgres://, postgresql:// or
    # postgresql+asyncpg:// (normalized by ``async_database_url``).
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None

    FRONTEND_ORIGIN: str = "http://localhost:3000"  # one origin, or several separated by commas
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    SUPABASE_URL: str | None = None
    SUPABASE_JWT_SECRET: str | None = None
    SUPABASE_JWKS_URL: str | None = None

    ANTHROPIC_API_KEY: str | None = None
    LLM_MODEL_STRONG: str | None = None
    LLM_MODEL_FAST: str | None = None

    # "anthropic": the API (production). "claude_cli": headless Claude Code with the developer's login
    # (local development and live evals; needs `uv sync --group headless`).
    LLM_PROVIDER: Literal["anthropic", "claude_cli"] = "anthropic"
    CLAUDE_CLI_MODEL: str = "claude-opus-5-5"
    CLAUDE_CLI_EFFORT: str = "medium"
    CLAUDE_CLI_PATH: str | None = None  # default: the CLI bundled with claude-agent-sdk, else `claude`

    TOKEN_ENC_KEY: str | None = None
    LOG_LLM_BODIES: bool = False

    @property
    def frontend_origins(self) -> list[str]:
        """``FRONTEND_ORIGIN`` split on commas, whitespace and trailing slashes
        stripped (browsers send ``Origin`` without one), empty entries dropped."""
        return [origin for part in self.FRONTEND_ORIGIN.split(",") if (origin := part.strip().rstrip("/"))]

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
