"""Outbox generators: modules in this package that expose ``async def generate(session, now)``.

Each tick the ticker runs every generator in its own transaction (it commits after ``generate``
returns and rolls back if it raises). A generator only inserts outbox rows through
``app.notifications.outbox`` and must be idempotent through dedupe keys, because it runs again on
every tick and after every restart. Generators never change business records. Modules whose name
starts with ``_`` are not generators.

Adding a generator is adding a module here; nothing else needs editing.
"""

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec
from app.db.models import Bot
from app.services.specs import load_active_spec

log = logging.getLogger(__name__)

GenerateFn = Callable[[AsyncSession, datetime], Awaitable[None]]


@dataclass(frozen=True)
class Generator:
    name: str
    generate: GenerateFn


def discover() -> list[Generator]:
    """Every generator module of this package, by module name."""
    found: list[Generator] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        fn = getattr(module, "generate", None)
        if fn is not None and inspect.iscoroutinefunction(fn):
            found.append(Generator(info.name, fn))
    return found


async def active_spec(session: AsyncSession, bot: Bot) -> BotSpec | None:
    """The bot's active spec (loaded like the adapters do), or ``None`` when it has none or it no
    longer validates (logged; the bot is skipped rather than failing the whole generator)."""
    try:
        loaded = await load_active_spec(session, bot)
    except ValidationError:
        log.warning("bot %s: active spec does not validate; skipped by notification generators", bot.id)
        return None
    return None if loaded is None else loaded[1]
