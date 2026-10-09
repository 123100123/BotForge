"""The messengers a bot can run on: Telegram (default) and Bale («بله», https://docs.bale.ai).

Bale's Bot API mirrors Telegram's (same method names, update shape, inline keyboards and
``callback_data``) under another host, so one client and one update path serve both. The
differences live here and in ``client.py``:

- API host ``tapi.bale.ai`` instead of ``api.telegram.org``; deep links ``ble.ir`` instead of ``t.me``;
- ``setWebhook`` takes only ``url`` (no secret header exists, so the secret is in the webhook path,
  ``POST /bale/{bot_id}/{secret}``); ``allowed_updates`` and ``drop_pending_updates`` are not
  documented and never sent;
- no ``parse_mode``: Bale always parses Markdown and documents no escaping, so outbound text is plain
  text with the Markdown control characters replaced by look-alikes (``render_bale``), which keeps
  user content from injecting links or formatting;
- an invalid token is answered with HTTP 403 "Token not found" (Telegram: 401/404).

Supported for Bale: the private-chat bot (customers, staff and manager screens, owner notifications,
owner link, staff link, outbox messages) by webhook. Telegram-only: polling mode (a Bale bot always
registers its webhook), the cross-server connect checks (``getWebhookInfo`` and the ``getUpdates``
probe) and the command menu (``setMyCommands``, ``setChatMenuButton``). Group cards and staff
documents run through the same code against Bale's API but are unverified there (see the roadmap's
Decision Log, "Bale platform").
"""

from typing import Literal, get_args

Platform = Literal["telegram", "bale"]
PLATFORMS: tuple[str, ...] = get_args(Platform)
DEFAULT_PLATFORM: Platform = "telegram"

API_BASES: dict[str, str] = {"telegram": "https://api.telegram.org", "bale": "https://tapi.bale.ai"}
LINK_BASES: dict[str, str] = {"telegram": "https://t.me", "bale": "https://ble.ir"}
# How the Persian texts name the messenger. Bale's name is also the word "yes", hence the quotes.
DISPLAY_NAMES: dict[str, str] = {"telegram": "تلگرام", "bale": "«بله»"}
TELEGRAM_NAME = DISPLAY_NAMES["telegram"]
# Bale ports setWebhook accepts (https only).
BALE_WEBHOOK_PORTS = frozenset({443, 88})

# Markdown control characters and the look-alikes that replace them in Bale text: bold, italic,
# strike-through, code and the link brackets. Without "[" and "]" no "[text](url)" link can form.
_BALE_MARKDOWN = str.maketrans(
    {
        "*": "∗",  # ∗ asterisk operator
        "_": "＿",  # ＿ fullwidth low line
        "`": "ˋ",  # ˋ modifier letter grave accent
        "~": "∼",  # ∼ tilde operator
        "[": "［",  # ［ fullwidth left square bracket
        "]": "］",  # ］ fullwidth right square bracket
    }
)


def as_platform(value: object) -> Platform:
    """``value`` when it names a supported platform, else Telegram (rows written before 0007)."""
    return "bale" if value == "bale" else "telegram"


def bot_link(platform: str, username: str, start: str | None = None) -> str:
    """The public link of a bot, with a ``?start=`` deep-link payload when given."""
    link = f"{LINK_BASES[as_platform(platform)]}/{username}"
    return f"{link}?start={start}" if start else link


def localize(text: str, platform: str) -> str:
    """A fixed Persian text (never user content) naming the bot's own messenger instead of Telegram."""
    if as_platform(platform) == "telegram":
        return text
    return text.replace(TELEGRAM_NAME, DISPLAY_NAMES[as_platform(platform)])


def render_bale(text: str) -> str:
    """Plain text that Bale's always-on Markdown shows as written (see the module docstring)."""
    return text.translate(_BALE_MARKDOWN)


def is_invalid_token(platform: str, error_code: int | None) -> bool:
    """Whether a failed ``getMe`` means the token itself is wrong."""
    if error_code in (401, 404):
        return True
    return as_platform(platform) == "bale" and error_code == 403
