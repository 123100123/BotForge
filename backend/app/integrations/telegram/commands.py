"""The bot's slash commands as Telegram shows them (``setMyCommands`` + the commands menu button).

Default scope: ``/start`` ``/menu`` ``/help``. The owner's private chat adds ``/panel`` through a
``BotCommandScopeChat`` (set when the owner links, ``api/webhook.py``). The runtime handles the
commands (``runtime/runtime.py``). Registration is best effort: a Telegram failure is logged and
swallowed, so it can never break connecting a bot or linking its owner.
"""

import logging

from app.integrations.telegram.client import TelegramApi, TelegramError

log = logging.getLogger(__name__)

DEFAULT_COMMANDS: list[dict[str, str]] = [
    {"command": "start", "description": "شروع"},
    {"command": "menu", "description": "منوی اصلی"},
    {"command": "help", "description": "راهنما"},
]
OWNER_COMMANDS: list[dict[str, str]] = [*DEFAULT_COMMANDS, {"command": "panel", "description": "پنل مدیریت"}]
MENU_BUTTON: dict[str, str] = {"type": "commands"}


async def register_default_commands(client: TelegramApi) -> None:
    """Default-scope commands and the default menu button (every private chat). Never raises
    ``TelegramError``."""
    try:
        await client.set_my_commands(DEFAULT_COMMANDS)
    except TelegramError as exc:
        log.warning("registering the default bot commands failed: %s", exc.description)
    try:
        await client.set_chat_menu_button(menu_button=MENU_BUTTON)
    except TelegramError as exc:
        log.warning("setting the commands menu button failed: %s", exc.description)


async def register_owner_commands(client: TelegramApi, chat_id: int) -> None:
    """The default commands plus ``/panel`` for the owner's private chat only. Never raises
    ``TelegramError``."""
    try:
        await client.set_my_commands(OWNER_COMMANDS, scope={"type": "chat", "chat_id": chat_id})
    except TelegramError as exc:
        log.warning("registering the owner bot commands failed: %s", exc.description)
