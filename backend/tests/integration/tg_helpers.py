"""Helpers for Telegram-facing integration tests: bot setup, update builders, fake-call inspection."""

import copy
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.db.models import Bot
from app.integrations.telegram.client import FakeTelegramClient
from app.revisions.service import activate, create_draft
from app.security.crypto import encrypt_token, generate_webhook_secret
from tests.integration.helpers import SessionFactory

ALICE = {"X-Test-User": "alice"}
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
CAP = "book_workshop"


@dataclass
class LiveBot:
    id: uuid.UUID
    secret: str
    token: str
    tg_bot_id: int
    revision_id: uuid.UUID | None
    owner_link_code: str


def new_token() -> tuple[int, str]:
    tg_id = uuid.uuid4().int % 10**9 + 10**9
    return tg_id, f"{tg_id}:AA{uuid.uuid4().hex}{uuid.uuid4().hex[:6]}"


def capacity_spec(golden: dict[str, Any], capacity: int) -> dict[str, Any]:
    spec = copy.deepcopy(golden)
    for cap in spec["capabilities"]:
        if cap["key"] == CAP:
            cap["capacity"]["value"] = capacity
    return spec


async def make_live_bot(
    session_factory: SessionFactory,
    spec: dict[str, Any] | None,
    *,
    owner_id: str = "alice",
    owner_actor_id: str | None = None,
) -> LiveBot:
    """A bot with an encrypted token, a webhook secret and (if ``spec``) an active revision."""
    tg_id, token = new_token()
    secret = generate_webhook_secret()
    code = f"code{uuid.uuid4().hex[:10]}"
    async with session_factory() as session:
        bot = Bot(
            owner_id=owner_id,
            name="ربات تست",
            status="live",
            tg_bot_id=tg_id,
            tg_username="workshop_test_bot",
            tg_token_enc=encrypt_token(token),
            tg_webhook_secret=secret,
            owner_link_code=code,
            owner_actor_id=owner_actor_id,
        )
        session.add(bot)
        await session.flush()
        revision_id = None
        if spec is not None:
            revision = await create_draft(session, bot.id, spec=spec)
            await activate(session, revision.id)
            revision_id = revision.id
        await session.commit()
        return LiveBot(bot.id, secret, token, tg_id, revision_id, code)


def user(user_id: int, name: str = "کاربر") -> dict[str, Any]:
    return {"id": user_id, "is_bot": False, "first_name": name}


def message_update(update_id: int, user_id: int, text: str, *, chat_type: str = "private") -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": user(user_id),
            "chat": {"id": user_id, "type": chat_type},
            "date": 1,
            "text": text,
        },
    }


def callback_update(update_id: int, user_id: int, data: str, *, message_id: int = 77) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cbq-{update_id}",
            "from": user(user_id),
            "message": {"message_id": message_id, "chat": {"id": user_id, "type": "private"}, "date": 1},
            "data": data,
        },
    }


class Chat:
    """Drives one Telegram user through the webhook and reads what the fake client sent back."""

    def __init__(self, client: httpx.AsyncClient, bot: LiveBot, fake: FakeTelegramClient, user_id: int):
        self.client, self.bot, self.fake, self.user_id = client, bot, fake, user_id
        self._next = uuid.uuid4().int % 10**6 * 1000

    def _id(self) -> int:
        self._next += 1
        return self._next

    async def post(self, update: dict[str, Any], secret: str | None = None) -> httpx.Response:
        headers = {SECRET_HEADER: secret if secret is not None else self.bot.secret}
        return await self.client.post(f"/tg/{self.bot.id}", json=update, headers=headers)

    async def say(self, text: str) -> httpx.Response:
        return await self.post(message_update(self._id(), self.user_id, text))

    async def press(self, data: str) -> httpx.Response:
        return await self.post(callback_update(self._id(), self.user_id, data))

    # --- what the user sees ------------------------------------------------------------------

    def shown(self) -> list[dict[str, Any]]:
        """sendMessage / editMessageText calls addressed to this user, oldest first."""
        return [
            k
            for n, k in self.fake.calls
            if n in ("sendMessage", "editMessageText") and str(k["chat_id"]) == str(self.user_id)
        ]

    def last_text(self) -> str:
        return self.shown()[-1]["text"]

    def buttons(self) -> list[dict[str, str]]:
        markup = self.shown()[-1].get("reply_markup") or {}
        return [b for row in markup.get("inline_keyboard", []) for b in row]

    def data_with(self, prefix: str) -> str:
        found = [b["callback_data"] for b in self.buttons() if b["callback_data"].startswith(prefix)]
        assert found, f"no button starting with {prefix!r} in {self.buttons()}"
        return found[0]
