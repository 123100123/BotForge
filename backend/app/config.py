"""Application settings read from the environment (names match ``.env.example``)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TelegramMode = Literal["webhook", "polling"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Optional until a database call is made. Accepts postgres://, postgresql:// or
    # postgresql+asyncpg:// (normalized by ``async_database_url``).
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None

    FRONTEND_ORIGIN: str = "http://localhost:3000"  # one origin, or several separated by commas
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # How Telegram updates arrive. "webhook" (default): Telegram posts them to
    # {PUBLIC_BASE_URL}/tg/{bot_id}, so it must reach this server over public https. "polling": the
    # backend fetches them with getUpdates (outbound only; app/integrations/telegram/poller.py), for
    # servers Telegram cannot reach. Polling needs exactly one backend process.
    TELEGRAM_MODE: TelegramMode = "webhook"

    # Owner accounts and login sessions (app/security/). The session cookie is Secure unless
    # AUTH_COOKIE_SECURE is false, which is meant only for plain-http local development. A session ends
    # AUTH_SESSION_TTL_HOURS after it was last renewed, and AUTH_SESSION_MAX_AGE_DAYS after it was
    # created however active it is (renewal never extends it past that).
    AUTH_COOKIE_SECURE: bool = True
    AUTH_ALLOW_SIGNUP: bool = True
    AUTH_SESSION_TTL_HOURS: int = Field(default=168, ge=1, le=24 * 366)
    AUTH_SESSION_MAX_AGE_DAYS: int = Field(default=30, ge=1, le=366)

    # FastAPI's /docs, /redoc and /openapi.json map every route and are served without a login, so they
    # are off unless enabled. Enable them only for local development, never on a public server.
    API_DOCS_ENABLED: bool = False

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

    # Notifications (app/notifications/): one ticker task in this process sends queued outbox rows
    # (reminders, announcements, scheduled reports). Off by default so tests and local runs never send;
    # the compose deployment turns it on. It must run in exactly one backend process.
    NOTIFICATIONS_TICKER: bool = False
    NOTIFICATIONS_TICK_SECONDS: int = Field(default=20, ge=1, le=3600)
    # Global send ceiling across all bots (Telegram allows about 30 messages per second per bot token).
    NOTIFICATIONS_SEND_RATE_PER_SECOND: int = Field(default=15, ge=1, le=30)

    # Spreadsheet uploads (app/spreadsheets/): where the files are stored and how large they may be.
    UPLOAD_DIR: str = "./uploads"
    UPLOAD_MAX_BYTES: int = Field(default=5 * 1024 * 1024, ge=1)
    SPREADSHEET_MAX_ROWS: int = Field(default=50_000, ge=1)
    SPREADSHEET_MAX_COLUMNS: int = Field(default=100, ge=1)

    # Manager Copilot (app/copilot/): questions per owner account per rolling 24 hours (cost control,
    # counted like AGENT_DAILY_RUN_CAP).
    COPILOT_DAILY_CAP: int = Field(default=50, ge=0)

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
