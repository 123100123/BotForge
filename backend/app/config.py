"""Application settings read from the environment (names match ``.env.example``)."""

import json
import math
import re
from contextlib import suppress
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

TelegramMode = Literal["webhook", "polling"]
AuthProvider = Literal["local", "supabase"]


LLM_PROVIDERS = ("anthropic", "claude_cli", "liara", "top_tools", "gemini", "chain")
CHAIN_PROVIDERS = ("gemini", "top_tools", "liara")  # OpenAI-compatible providers only
GEMINI_DEFAULT_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MAX_KEYS = 5


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # Optional until a database call is made. Accepts postgres://, postgresql:// or
    # postgresql+asyncpg://, with sslmode= or ssl= (normalized by ``to_async_url``).
    DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None

    # CORS (app.security.cors): one origin, or several separated by commas; the optional regex is for
    # preview URLs. The CSRF origin check (app.security.csrf) admits only the listed origins.
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    FRONTEND_ORIGIN_REGEX: str | None = None
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # How Telegram updates arrive. "webhook" (default): Telegram posts them to
    # {PUBLIC_BASE_URL}/tg/{bot_id}, so it must reach this server over public https. "polling": the
    # backend fetches them with getUpdates (outbound only; app/integrations/telegram/poller.py), for
    # servers Telegram cannot reach. Polling needs exactly one backend process.
    TELEGRAM_MODE: TelegramMode = "webhook"

    # Who signs owners in (app/api/deps.py). The same code serves both deployments:
    # "local" (default; the self-hosted Docker stack in deploy/): this backend's own email + password
    #   login, the session in the HttpOnly bf_session cookie plus the CSRF header. The cookie is
    #   SameSite=Lax and sent "same-origin", so the web app must reach the API on its own origin
    #   (Caddy proxies /api/*). The AUTH_* settings below apply to this mode only.
    # "supabase" (the hosted Render deployment, web app and API on two origins): the web app signs in
    #   with Supabase Auth and sends the access token as "Authorization: Bearer <jwt>"; the backend
    #   verifies it with the SUPABASE_* settings below (app/security/supabase_auth.py), ignores
    #   cookies, and answers 404 on /auth/signup, /auth/login and /auth/logout. Whether new accounts
    #   may sign up is then set in the Supabase dashboard, not by AUTH_ALLOW_SIGNUP.
    # The web app's NEXT_PUBLIC_AUTH_PROVIDER must name the same provider.
    AUTH_PROVIDER: AuthProvider = "local"

    # Supabase Auth (AUTH_PROVIDER=supabase only). SUPABASE_URL (https://<ref>.supabase.co) also pins
    # the token issuer to <SUPABASE_URL>/auth/v1. Verification keys: SUPABASE_JWKS_URL
    # (<SUPABASE_URL>/auth/v1/.well-known/jwks.json; the project's ES256/RS256 signing keys) or, for a
    # project still on the legacy shared secret, SUPABASE_JWT_SECRET (HS256). JWKS wins when both are
    # set. With neither, the service fails closed: 401 without a token, 503 with one.
    SUPABASE_URL: str | None = None
    SUPABASE_JWKS_URL: str | None = None
    SUPABASE_JWT_SECRET: str | None = None

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
    # (local development and live evals; needs `uv sync --group headless`). "gemini", "liara",
    # "top_tools": one OpenAI-compatible provider. "chain": the providers of LLM_CHAIN, in order, each
    # model call falling through to the next on failure. An unknown value never stops the app from
    # starting: agent runs fail with a clear configuration error instead.
    LLM_PROVIDER: str = "anthropic"
    LLM_CHAIN: str = "gemini,top_tools"
    LLM_COOLDOWN_SECONDS: float = Field(default=60, ge=0, allow_inf_nan=False)
    CLAUDE_CLI_MODEL: str = "claude-opus-5-5"
    CLAUDE_CLI_EFFORT: str = "medium"
    CLAUDE_CLI_PATH: str | None = None  # default: the CLI bundled with claude-agent-sdk, else `claude`

    # Project-scoped AI credentials; never the Liara account/management token. Empty settings let
    # the app boot, but AI endpoints remain unavailable until both values are configured.
    LIARA_API_KEY: SecretStr | None = Field(default=None, repr=False, exclude=True)
    LIARA_BASE_URL: str | None = Field(default=None, repr=False)
    LIARA_MODEL_STRONG: str = "google/gemini-3.8-flash"
    LIARA_MODEL_FAST: str = "deepseek/deepseek-v4-flash"
    LIARA_MAX_TOKENS: int = Field(default=32000, gt=0)
    LIARA_TIMEOUT_SECONDS: float = Field(default=180, gt=0, allow_inf_nan=False)
    LIARA_MAX_RETRIES: int = Field(default=2, ge=0, le=10)
    LIARA_TOKEN_PRICES_JSON: str = Field(default="", repr=False)

    # Top Tools is independently configured. Model slugs must be confirmed for the operator's
    # account; empty model defaults prevent accidental requests or a fallback to another provider.
    TOP_TOOLS_API_KEY: SecretStr | None = Field(default=None, repr=False, exclude=True)
    TOP_TOOLS_BASE_URL: str | None = Field(default="https://top-tools-ai.com/api/v1", repr=False)
    TOP_TOOLS_MODEL_STRONG: str = ""
    TOP_TOOLS_MODEL_FAST: str = ""
    TOP_TOOLS_MAX_TOKENS: int = Field(default=32000, gt=0)
    TOP_TOOLS_TIMEOUT_SECONDS: float = Field(default=180, gt=0, allow_inf_nan=False)
    TOP_TOOLS_MAX_RETRIES: int = Field(default=2, ge=0, le=10)
    TOP_TOOLS_TOKEN_PRICES_JSON: str = Field(default="", repr=False)

    # Google Gemini through its OpenAI-compatible endpoint. GEMINI_API_KEYS is comma-separated (up to 5
    # keys, tried in turn); GEMINI_API_KEY, _2 and _3 are also accepted. Pro models are not on the free tier.
    GEMINI_API_KEYS: SecretStr | None = Field(default=None, repr=False, exclude=True)
    GEMINI_API_KEY: SecretStr | None = Field(default=None, repr=False, exclude=True)
    GEMINI_API_KEY_2: SecretStr | None = Field(default=None, repr=False, exclude=True)
    GEMINI_API_KEY_3: SecretStr | None = Field(default=None, repr=False, exclude=True)
    GEMINI_BASE_URL: str | None = Field(default=GEMINI_DEFAULT_URL, repr=False)
    GEMINI_MODEL_STRONG: str = "gemini-flash-latest"
    GEMINI_MODEL_FAST: str = "gemini-flash-latest"
    GEMINI_MAX_TOKENS: int = Field(default=32000, gt=0)
    GEMINI_TIMEOUT_SECONDS: float = Field(default=90, gt=0, allow_inf_nan=False)
    GEMINI_MAX_RETRIES: int = Field(default=1, ge=0, le=10)
    GEMINI_TOKEN_PRICES_JSON: str = Field(default="", repr=False)

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

    @field_validator("LLM_PROVIDER", mode="before")
    @classmethod
    def _llm_provider(cls, value: Any) -> Any:
        """Case and spaces do not matter and empty means "anthropic". Unknown values are kept (not a
        startup error); ``llm_configured`` is then false and ``make_llm`` reports the problem."""
        if isinstance(value, str):
            return value.strip().lower() or "anthropic"
        return value

    @field_validator("GEMINI_API_KEYS", mode="after")
    @classmethod
    def _gemini_keys(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        keys = [key.strip() for key in value.get_secret_value().split(",") if key.strip()]
        if not all(re.fullmatch(r"[!-~]+", key) for key in keys):
            raise ValueError("AI API keys must be opaque ASCII tokens without whitespace")
        return SecretStr(",".join(keys)) if keys else None

    @field_validator(
        "LIARA_API_KEY",
        "TOP_TOOLS_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_2",
        "GEMINI_API_KEY_3",
        mode="after",
    )
    @classmethod
    def _ai_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        if not re.fullmatch(r"[!-~]+", value.get_secret_value()):
            raise ValueError("AI API keys must be opaque ASCII tokens without whitespace")
        return value

    @field_validator("LIARA_BASE_URL")
    @classmethod
    def _liara_url(cls, value: str | None) -> str | None:
        return validate_liara_url(value)

    @field_validator("TOP_TOOLS_BASE_URL")
    @classmethod
    def _top_tools_url(cls, value: str | None) -> str | None:
        return validate_top_tools_url(value)

    @field_validator("GEMINI_BASE_URL")
    @classmethod
    def _gemini_url(cls, value: str | None) -> str | None:
        return validate_gemini_url(value)

    @field_validator(
        "TOP_TOOLS_MODEL_STRONG", "TOP_TOOLS_MODEL_FAST", "GEMINI_MODEL_STRONG", "GEMINI_MODEL_FAST"
    )
    @classmethod
    def _top_tools_model(cls, value: str) -> str:
        if not value.strip():
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
            raise ValueError("Top Tools and Gemini models must be model identifiers")
        return value

    @field_validator("LIARA_MODEL_STRONG", "LIARA_MODEL_FAST")
    @classmethod
    def _liara_model(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
            raise ValueError("Liara model must be a nonempty model identifier")
        return value

    @field_validator("LIARA_TOKEN_PRICES_JSON", "TOP_TOOLS_TOKEN_PRICES_JSON", "GEMINI_TOKEN_PRICES_JSON")
    @classmethod
    def _ai_prices(cls, value: str) -> str:
        parse_token_prices(value)
        return value

    @property
    def gemini_api_keys(self) -> list[SecretStr]:
        """GEMINI_API_KEYS then GEMINI_API_KEY, _2, _3: duplicates dropped, at most the first 5."""
        keys: list[str] = []
        listed = self.GEMINI_API_KEYS.get_secret_value().split(",") if self.GEMINI_API_KEYS else []
        singles = (self.GEMINI_API_KEY, self.GEMINI_API_KEY_2, self.GEMINI_API_KEY_3)
        for key in listed + [single.get_secret_value() for single in singles if single]:
            if key not in keys:
                keys.append(key)
        return [SecretStr(key) for key in keys[:GEMINI_MAX_KEYS]]

    @property
    def llm_chain(self) -> list[str]:
        """LLM_CHAIN provider names in order, lower-cased; empty entries dropped."""
        return [name for part in self.LLM_CHAIN.split(",") if (name := part.strip().lower())]

    def provider_configured(self, provider: str) -> bool:
        if provider == "top_tools":
            return bool(
                self.TOP_TOOLS_API_KEY
                and self.TOP_TOOLS_BASE_URL
                and self.TOP_TOOLS_MODEL_STRONG
                and self.TOP_TOOLS_MODEL_FAST
            )
        if provider == "liara":
            return bool(self.LIARA_API_KEY and self.LIARA_BASE_URL)
        if provider == "gemini":
            return bool(self.gemini_api_keys and self.GEMINI_BASE_URL)
        if provider == "chain":
            return any(name in CHAIN_PROVIDERS and self.provider_configured(name) for name in self.llm_chain)
        if provider == "claude_cli":
            return True
        return provider == "anthropic" and bool(self.ANTHROPIC_API_KEY)

    @property
    def llm_configured(self) -> bool:
        return self.provider_configured(self.LLM_PROVIDER)

    @field_validator("AUTH_PROVIDER", mode="before")
    @classmethod
    def _auth_provider(cls, value: Any) -> Any:
        """Case and surrounding spaces do not matter, and empty means the default ("local"). Any other
        value is a configuration error that stops the process at startup: it never falls back."""
        if isinstance(value, str):
            value = value.strip().lower()
            return value or "local"
        return value

    @property
    def frontend_origins(self) -> list[str]:
        """``FRONTEND_ORIGIN`` split on commas, whitespace and trailing slashes
        stripped (browsers send ``Origin`` without one), empty entries dropped."""
        return [origin for part in self.FRONTEND_ORIGIN.split(",") if (origin := part.strip().rstrip("/"))]

    @property
    def async_database_url(self) -> str | None:
        return to_async_url(self.DATABASE_URL)


ASYNC_DRIVER = "postgresql+asyncpg"
_PLAIN_DRIVERS = ("postgres", "postgresql", ASYNC_DRIVER)


def validate_liara_url(value: str | None) -> str | None:
    """Pin credentials to Liara's documented project endpoint, before constructing an HTTP client."""
    if value is None or not value.strip():
        return None
    if not re.fullmatch(r"https://ai\.liara\.ir/api/v1/[A-Za-z0-9_-]+/?", value):
        raise ValueError("LIARA_BASE_URL must be https://ai.liara.ir/api/v1/<project-id>")
    return value.rstrip("/")


def validate_top_tools_url(value: str | None) -> str | None:
    """Allow only the explicit Top Tools API roots; credentials never follow a redirect."""
    if value is None or not value.strip():
        return None
    if not re.fullmatch(r"https://top-tools-ai\.com/(?:api/)?v1/?", value):
        raise ValueError("TOP_TOOLS_BASE_URL must be https://top-tools-ai.com/api/v1 or /v1")
    return value.rstrip("/")


def validate_gemini_url(value: str | None) -> str | None:
    """Allow only Google's OpenAI-compatible Gemini root; credentials never follow a redirect."""
    if value is None or not value.strip():
        return None
    if not re.fullmatch(r"https://generativelanguage\.googleapis\.com/v1beta/openai/?", value):
        raise ValueError("GEMINI_BASE_URL must be " + GEMINI_DEFAULT_URL)
    return value.rstrip("/")


def parse_token_prices(value: str) -> dict[str, dict[str, float]]:
    """Optional USD/million rates. Missing models are unpriced, represented by the existing zero."""
    if not value.strip():
        return {}
    parsed = None
    with suppress(ValueError, RecursionError):
        parsed = json.loads(value)
    valid = isinstance(parsed, dict)
    result: dict[str, dict[str, float]] = {}
    if valid:
        for model, rates in parsed.items():
            if (
                not model
                or not isinstance(rates, dict)
                or not {"input", "output"} <= rates.keys() <= {"input", "output", "cache_read"}
            ):
                valid = False
                break
            normalized = {}
            for key, rate in rates.items():
                if type(rate) in (int, float):
                    with suppress(OverflowError):
                        numeric = float(rate)
                        if math.isfinite(numeric) and numeric >= 0:
                            normalized[key] = numeric
            if len(normalized) != len(rates):
                valid = False
                break
            result[model] = normalized
            result[model].setdefault("cache_read", result[model]["input"])
    if not valid:
        raise ValueError("Token price settings require finite nonnegative input/output/cache_read rates")
    return result


# Compatibility for code that used the original Liara-only helper.
parse_liara_prices = parse_token_prices


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
