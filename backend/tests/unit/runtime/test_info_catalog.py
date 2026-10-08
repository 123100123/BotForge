from datetime import timedelta

from app.botspec.models import BotSpec
from app.runtime.ctx import Ctx
from app.runtime.texts import common
from app.runtime.texts import nav as nav_texts
from tests.unit.runtime.conftest import build_catalog_spec
from tests.unit.runtime.harness import T0, Harness, button_data, buttons, find_button, text


def iso(hours: float) -> str:
    return (T0 + timedelta(hours=hours)).isoformat()


async def seed_events(h: Harness, n: int, start_hours: float = 24) -> list[int]:
    return [
        await h.seed("event", {"title": f"رویداد {i}", "starts_at": iso(start_hours + i), "price": 1000 * i})
        for i in range(n)
    ]


# --- info -----------------------------------------------------------------------------------


async def test_info_multi_page_list_show_and_back(workshop: BotSpec) -> None:
    h = Harness(workshop)
    r = await h.tap("ali", "menu:open:about")
    assert text(r).startswith("دربارهٔ ما\n")
    assert button_data(r) == ["info:show:about", "info:show:address", "nav:go:home"]
    assert [b.label for b in buttons(r)][:2] == ["دربارهٔ آموزشگاه", "نشانی و تماس"]
    r = await h.tap("ali", "info:show:address")
    assert text(r).startswith("نشانی و تماس\n\nنشانی: تهران")
    assert r.messages[0].edit is True
    assert button_data(r) == ["nav:go:info", "nav:go:home"]
    assert find_button(r, common.BACK).data == "nav:go:info"


async def test_info_single_page_shown_directly() -> None:
    h = Harness(build_catalog_spec(info_pages=1))
    r = await h.tap("ali", "menu:open:about")
    assert text(r) == "صفحه 1\n\nمتن صفحه 1"
    assert button_data(r) == ["nav:go:home"]


async def test_info_page_removed_is_stale() -> None:
    h = Harness(build_catalog_spec(info_pages=2))
    r = await h.tap("ali", "info:show:p9")
    assert text(r) == nav_texts.STALE


# --- catalog --------------------------------------------------------------------------------


async def test_catalog_empty() -> None:
    h = Harness(build_catalog_spec())
    r = await h.tap("ali", "menu:open:events_menu")
    assert text(r) == "فهرست رویدادها\nدر حال حاضر موردی برای نمایش وجود ندارد."
    assert button_data(r) == ["nav:go:home"]


async def test_catalog_list_item_detail_and_back() -> None:
    h = Harness(build_catalog_spec())
    ids = await seed_events(h, 3)
    await h.store.update_record("event", ids[1], data={"online": True}, now=T0)
    r = await h.tap("ali", "menu:open:events_menu")
    assert text(r) == "فهرست رویدادها\nیکی از موارد زیر را انتخاب کنید:"
    assert button_data(r) == [f"events:item:{i}" for i in ids] + ["nav:go:home"]
    assert [b.label for b in buttons(r)][:3] == ["رویداد 0", "رویداد 1", "رویداد 2"]

    r = await h.tap("ali", f"events:item:{ids[1]}")
    # 2026-10-05 09:00 UTC = 12:30 Tehran, Monday 13 Mehr 1405
    assert text(r) == ("رویداد 1\n\nزمان شروع: دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۱۲:۳۰\nهزینه: ۱٬۰۰۰\nآنلاین: بله")
    assert button_data(r) == ["events:list:0", "nav:go:home"]
    r = await h.tap("ali", f"events:item:{ids[0]}")
    assert "هزینه: ۰" in text(r) and "آنلاین: —" in text(r)


async def test_catalog_pagination() -> None:
    h = Harness(build_catalog_spec())
    ids = await seed_events(h, 19)
    r = await h.tap("ali", "menu:open:events_menu")
    assert "صفحهٔ ۱ از ۳" in text(r)
    data = button_data(r)
    assert data[:8] == [f"events:item:{i}" for i in ids[:8]]
    assert data[8:] == ["events:list:1", "nav:go:home"]  # next only on the first page

    r = await h.tap("ali", "events:list:1")
    data = button_data(r)
    assert data[:8] == [f"events:item:{i}" for i in ids[8:16]]
    assert data[8:] == ["events:list:0", "events:list:2", "nav:go:home"]
    assert [b.label for b in buttons(r)][8:10] == [common.PREVIOUS, common.NEXT]

    r = await h.tap("ali", "events:list:2")
    assert "صفحهٔ ۳ از ۳" in text(r)
    assert button_data(r) == [f"events:item:{i}" for i in ids[16:]] + ["events:list:1", "nav:go:home"]

    r = await h.tap("ali", "events:list:99")  # clamped to the last page
    assert "صفحهٔ ۳ از ۳" in text(r)
    r = await h.tap("ali", "events:list:abc")
    assert "صفحهٔ ۱ از ۳" in text(r)

    r = await h.tap("ali", f"events:item:{ids[17]}")  # back goes to the item's page
    assert button_data(r) == ["events:list:2", "nav:go:home"]


async def test_catalog_upcoming_only_with_injected_now() -> None:
    h = Harness(build_catalog_spec({"upcoming_only_field": "starts_at"}))
    past = await h.seed("event", {"title": "گذشته", "starts_at": iso(-1)})
    soon = await h.seed("event", {"title": "نزدیک", "starts_at": iso(2)})
    later = await h.seed("event", {"title": "بعدی", "starts_at": iso(48)})
    r = await h.tap("ali", "menu:open:events_menu")
    assert button_data(r) == [f"events:item:{soon}", f"events:item:{later}", "nav:go:home"]
    assert text(await h.tap("ali", f"events:item:{past}")) == nav_texts.STALE

    h.advance(hours=3)  # "soon" has started now
    r = await h.tap("ali", "events:list:0")
    assert button_data(r) == [f"events:item:{later}", "nav:go:home"]

    h.advance(hours=100)
    r = await h.tap("ali", "events:list:0")
    assert text(r).endswith("در حال حاضر موردی برای نمایش وجود ندارد.")


async def test_catalog_upcoming_boundary_is_inclusive() -> None:
    h = Harness(build_catalog_spec({"upcoming_only_field": "starts_at"}))
    now_item = await h.seed("event", {"title": "اکنون", "starts_at": iso(0)})
    r = await h.tap("ali", "menu:open:events_menu")
    assert f"events:item:{now_item}" in button_data(r)


async def test_catalog_sort_field_and_desc() -> None:
    h = Harness(build_catalog_spec({"sort_field": "price"}))
    a = await h.seed("event", {"title": "الف", "starts_at": iso(1), "price": 300})
    b = await h.seed("event", {"title": "ب", "starts_at": iso(1), "price": None})
    c = await h.seed("event", {"title": "ج", "starts_at": iso(1), "price": 100})
    d = await h.seed("event", {"title": "د", "starts_at": iso(1), "price": 300})
    r = await h.tap("ali", "menu:open:events_menu")
    assert button_data(r)[:4] == [f"events:item:{i}" for i in (c, a, d, b)]

    h.spec = build_catalog_spec({"sort_field": "price", "sort_desc": True})
    r = await h.tap("ali", "menu:open:events_menu")
    assert button_data(r)[:4] == [f"events:item:{i}" for i in (a, d, c, b)]  # None last, ties stable

    h.spec = build_catalog_spec({"sort_field": "starts_at"})
    await h.store.update_record("event", a, data={"starts_at": iso(-5)}, now=T0)
    r = await h.tap("ali", "menu:open:events_menu")
    assert button_data(r)[0] == f"events:item:{a}"


async def test_catalog_missing_item_and_bad_arg_are_stale() -> None:
    h = Harness(build_catalog_spec())
    for data in ("events:item:999", "events:item:abc", "events:item:"):
        assert text(await h.tap("ali", data)) == nav_texts.STALE


async def test_catalog_title_fallback_and_long_label() -> None:
    h = Harness(build_catalog_spec())
    rid = await h.seed("event", {"title": "", "starts_at": iso(1)})
    long_id = await h.seed("event", {"title": "خیلی " * 30, "starts_at": iso(1)})
    r = await h.tap("ali", "menu:open:events_menu")
    labels = {b.data: b.label for b in buttons(r)}
    assert labels[f"events:item:{rid}"] == "#" + "۰۱۲۳۴۵۶۷۸۹"[rid]
    assert len(labels[f"events:item:{long_id}"]) <= 60 and labels[f"events:item:{long_id}"].endswith("…")


# --- texts ----------------------------------------------------------------------------------


async def test_catalog_text_override_and_placeholders() -> None:
    spec = build_catalog_spec(
        {
            "texts": [
                {"key": "list_header", "value": "«{title}» — فهرست کامل {unknown}"},
                {"key": "item_detail", "value": "[{title}]\n{details}"},
            ]
        },
        validate=False,  # validate_spec would (rightly) reject the {unknown} placeholder
    )
    h = Harness(spec)
    rid = await h.seed("event", {"title": "کنسرت {details}", "starts_at": iso(1), "price": 5})
    r = await h.tap("ali", "menu:open:events_menu")
    assert text(r) == "«فهرست رویدادها» — فهرست کامل {unknown}"  # unknown placeholder stays literal
    r = await h.tap("ali", f"events:item:{rid}")
    # substituted values are never re-scanned: "{details}" inside the title stays literal
    assert text(r).startswith("[کنسرت {details}]\nزمان شروع: ")
    assert "هزینه: ۵" in text(r)
    # empty-list text was not overridden, so the default applies
    h2 = Harness(spec)
    assert text(await h2.tap("ali", "menu:open:events_menu")).endswith("موردی برای نمایش وجود ندارد.")


async def test_ctx_t_falls_back_to_defaults_and_raises_for_unknown_key() -> None:
    import pytest

    from app.runtime.contracts import RuntimeEvent
    from app.runtime.memory_store import MemoryStore

    spec = build_catalog_spec()
    ev = RuntimeEvent(bot_id="b", env="sandbox", actor=Harness.actor("ali"), kind="text", now=T0)
    ctx = await Ctx.create(ev, spec, MemoryStore())
    cap = spec.capability("events")
    info = spec.capability("info")
    assert cap is not None and info is not None
    assert ctx.t(cap, "empty", title="X") == "X\nدر حال حاضر موردی برای نمایش وجود ندارد."
    assert ctx.t(info, "list_header", title="Y").startswith("Y\n")
    assert ctx.t(cap, "ask_field", label="نام") == "لطفاً «نام» را وارد کنید:"  # common form fallback
    with pytest.raises(KeyError):
        ctx.t(cap, "no_such_key")
