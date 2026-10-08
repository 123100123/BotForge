"""Bot commands /menu, /panel and /help (U9): role homes, help text, ``/cmd@botname``, sessions."""

import pytest

from app.runtime import nav
from app.runtime.contracts import Actor
from app.runtime.runtime import bot_command
from app.runtime.texts import commands as cmd_tx
from app.runtime.texts import nav as tx
from tests.unit.runtime.harness import Harness, button_data, load_example, text

OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)
ALI = Actor(id="ali", display_name="علی")


@pytest.fixture
def h() -> Harness:
    return Harness(load_example("workshop.botspec.json"))


@pytest.mark.parametrize(
    ("raw", "command"),
    [
        ("/menu", "/menu"),
        ("/menu@my_bot", "/menu"),
        ("/PANEL@My_Bot", "/panel"),
        ("  /help  ", "/help"),
        ("/help please", "/help"),
        ("/start", None),
        ("/menus", None),
        ("menu", None),
        ("", None),
        ("   ", None),
    ],
)
def test_bot_command_parsing(raw: str, command: str | None) -> None:
    assert bot_command(raw) == command


@pytest.mark.parametrize("raw", ["/menu", "/menu@workshop_bot"])
async def test_menu_shows_the_customer_home(h: Harness, raw: str) -> None:
    home = await h.start(ALI)
    resp = await h.send(ALI, raw)
    (msg,) = resp.messages
    assert msg.edit is False
    assert msg.text.startswith(f"🏠 {h.spec.bot.name}")
    assert button_data(resp) == [b.data for row in home.messages[-1].buttons for b in row]
    assert all(d.startswith("nav:go:") for d in button_data(resp))


async def test_menu_is_the_manager_home_for_the_owner(h: Harness) -> None:
    resp = await h.send(OWNER, "/menu")
    assert text(resp).startswith("🧭 مدیریت ")
    assert button_data(resp)[-1] == nav.nav_data(nav.CUST)


async def test_panel_opens_the_manager_home_for_managers(h: Harness) -> None:
    resp = await h.send(OWNER, "/panel@workshop_bot")
    assert text(resp).startswith("🧭 مدیریت ")
    assert button_data(resp) == button_data(await h.tap(OWNER, "nav:go:mgr"))


async def test_panel_for_a_customer_is_their_role_home_not_a_stale_notice(h: Harness) -> None:
    home = await h.send(ALI, "/menu")
    resp = await h.send(ALI, "/panel")
    assert button_data(resp) == button_data(home)
    assert tx.STALE not in text(resp)
    assert "🧭" not in text(resp)


async def test_help_for_a_customer_lists_the_home_entries_and_a_home_button(h: Harness) -> None:
    home = await h.send(ALI, "/menu")
    resp = await h.send(ALI, "/help")
    (msg,) = resp.messages
    assert msg.edit is False
    assert msg.text.startswith(cmd_tx.HELP_HEADING.format(business=h.spec.bot.name))
    for entry in nav.compile_home(h.spec, "customer"):
        assert f"• {entry.label}" in msg.text
    assert cmd_tx.HELP_MENU in msg.text and cmd_tx.HELP_START in msg.text
    assert cmd_tx.HELP_PANEL not in msg.text
    assert [(b.label, b.data) for row in msg.buttons for b in row] == [(tx.HOME, "nav:go:home")]
    assert home.messages  # sanity: the same spec has a non-empty home


async def test_help_for_a_manager_lists_the_manager_entries_and_panel(h: Harness) -> None:
    resp = await h.send(OWNER, "/help")
    (msg,) = resp.messages
    assert cmd_tx.HELP_ENTRIES_MANAGER in msg.text and cmd_tx.HELP_PANEL in msg.text
    for entry in nav.compile_home(h.spec, "manager"):
        if entry.key != nav.CUST:
            assert f"• {entry.label}" in msg.text
    assert nav.compile_home(h.spec, "manager")[-1].label not in msg.text  # no customer-view line


async def test_commands_abandon_a_form_in_progress(h: Harness) -> None:
    await h.store.set_session("ali", {"capability": "book_workshop", "step": "x"})
    resp = await h.send(ALI, "/menu")
    assert await h.store.get_session("ali") is None
    assert button_data(resp)


async def test_commands_are_ignored_in_groups(h: Harness) -> None:
    from app.runtime.contracts import RuntimeEvent

    event = RuntimeEvent(
        bot_id="b1", env="live", actor=ALI, kind="text", text="/menu", now=h.now, chat_type="group"
    )
    resp = await h.runtime.handle(event, h.spec, h.store)
    assert resp.messages == []
