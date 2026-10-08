"""PgStore's optional extensions for the Telegram manager screens (runtime/manager_team.py):
``display_names`` and ``team_overview``. Needs a test database."""

import uuid

from app.db.models import Bot
from app.roles.service import set_role
from app.runtime.contracts import Actor
from app.runtime.pg_store import PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory


async def test_display_names_are_scoped_to_the_bot_and_env(
    session_factory: SessionFactory, make_bot: MakeBot
) -> None:
    bot_id = (await make_bot(active=False))[0]
    other_id = (await make_bot("bob", active=False))[0]
    async with session_factory() as session:
        await PgStore(session, bot_id, "live").upsert_user(Actor(id="1", display_name="علی"))
        await PgStore(session, bot_id, "sandbox").upsert_user(Actor(id="2", display_name="سارا"))
        await PgStore(session, other_id, "live").upsert_user(Actor(id="2", display_name="غریبه"))
        store = PgStore(session, bot_id, "live")
        assert await store.display_names(["1", "2", "3"]) == {"1": "علی"}
        assert await store.display_names([]) == {}


async def test_team_overview_is_the_team_api_view(session_factory: SessionFactory, make_bot: MakeBot) -> None:
    bot_id = (await make_bot(active=False))[0]
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        bot.owner_actor_id = "100"
        bot.tg_username = "cafe_bot"
        bot.tg_token_enc = "enc"
        bot.staff_link_code = f"code{uuid.uuid4().hex}"
        store = PgStore(session, bot_id, "live", "100")
        for actor_id, name in (("100", "مالک"), ("200", "سام"), ("300", "علی")):
            await store.upsert_user(Actor(id=actor_id, display_name=name))
        await set_role(session, bot_id, "live", "200", "staff")
        await session.flush()
        team = await store.team_overview()
        assert team is not None
        assert [(m.display_name, m.role) for m in team.members] == [("مالک", "manager"), ("سام", "staff")]
        assert team.counts == {"customer": 1, "staff": 1, "manager": 1}
        assert team.staff_link == f"https://t.me/cafe_bot?start=staff_{bot.staff_link_code}"
        assert await PgStore(session, uuid.uuid4(), "live").team_overview() is None
