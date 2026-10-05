"""Notification pieces that need no database: outbox bookkeeping, texts, throttle, lifespan wiring."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI

import app.main as main
from app.botspec.models import BotSpec, FieldDef, FieldType
from app.config import get_settings
from app.db.models import OutboundMessageRow
from app.notifications import outbox
from app.notifications.generators import discover
from app.notifications.generators.reminders import reminder_text
from app.notifications.targets import chat_id_of
from app.notifications.ticker import NotificationTicker

REPO = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)


def test_backoff_doubles_and_failures_stop_after_five() -> None:
    assert [outbox.backoff(n).total_seconds() for n in (1, 2, 3, 4)] == [30, 60, 120, 240]
    row = OutboundMessageRow(attempts=0, status="queued", not_before=T0)
    for _ in range(4):
        outbox.mark_failed(row, "x" * 900, now=T0)
    assert row.status == "queued" and len(row.last_error or "") == outbox.MAX_ERROR_CHARS
    outbox.mark_failed(row, "x", now=T0)
    assert (row.status, row.attempts) == ("failed", 5)
    blocked = OutboundMessageRow(attempts=0, status="queued", not_before=T0)
    outbox.mark_failed(blocked, "Forbidden", now=T0, permanent=True)
    assert blocked.status == "failed"
    flooded = OutboundMessageRow(attempts=0, status="queued", not_before=T0)
    outbox.mark_failed(flooded, "429", now=T0, retry_after=90)
    assert flooded.not_before == T0 + timedelta(seconds=90)
    outbox.mark_sent(flooded, now=T0)
    assert (flooded.status, flooded.sent_at, flooded.last_error) == ("sent", T0, None)


def test_buttons_are_validated_outmessage_rows() -> None:
    assert outbox.buttons_json(None) is None and outbox.buttons_json([[]]) is None
    assert outbox.buttons_json([[{"label": "الف", "data": "a"}]]) == [[{"label": "الف", "data": "a"}]]
    with pytest.raises(ValueError):
        outbox.buttons_json([[{"label": "x", "data": "y" * 65}]])


def test_chat_ids_are_ascii_integers_only() -> None:
    assert chat_id_of("123") == 123 and chat_id_of("-100") == -100
    assert chat_id_of("demo-01") is None and chat_id_of("۱۲۳") is None and chat_id_of(None) is None


def test_reminder_text_is_jalali_in_bot_timezone_with_location() -> None:
    spec = BotSpec.model_validate_json(
        (REPO / "examples" / "workshop.botspec.json").read_text(encoding="utf-8")
    )
    resource = spec.resources[0].model_copy(
        update={
            "fields": [*spec.resources[0].fields, FieldDef(key="location", label="مکان", type=FieldType.text)]
        }
    )
    item = {"title": "عکاسی", "location": "سالن ۲"}
    text = reminder_text(spec, resource, item, T0)  # 08:00 UTC = 11:30 Tehran
    assert text.startswith("یادآوری: «عکاسی» ") and "۱۱:۳۰" in text and text.endswith("، مکان: سالن ۲")
    assert "مکان" not in reminder_text(spec, resource, {"title": "عکاسی"}, T0)


def test_generators_are_discovered() -> None:
    assert [g.name for g in discover()] == ["announcements", "reminders"]


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.t += seconds


async def test_throttle_global_rate_and_one_per_second_per_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_SEND_RATE_PER_SECOND", "10")
    get_settings.cache_clear()
    clock = FakeClock()
    ticker = NotificationTicker(None, lambda token: None, sleep=clock.sleep, clock=clock, generators=[])  # type: ignore[arg-type]
    get_settings.cache_clear()
    bot = uuid.uuid4()
    for chat in (1, 2, 1):
        await ticker._throttle(bot, chat)
    assert clock.slept == [0.1, 0.9]  # chat 2 waits for the global slot, chat 1 for its own second


async def test_lifespan_starts_the_ticker_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stub:
        stopped = False

        async def stop(self) -> None:
            Stub.stopped = True

    monkeypatch.setattr(main, "database_configured", lambda: True)
    monkeypatch.setattr(main, "get_sessionmaker", lambda: None)
    monkeypatch.setattr(main, "mark_interrupted_runs", _zero)
    monkeypatch.setattr(main.notification_ticker, "start_ticker", lambda *a, **k: Stub())
    monkeypatch.setattr(main, "dispose_engine", _zero)
    for enabled, expected in (("false", type(None)), ("true", Stub)):
        monkeypatch.setenv("NOTIFICATIONS_TICKER", enabled)
        get_settings.cache_clear()
        app = FastAPI()
        async with main.lifespan(app):
            assert isinstance(app.state.notification_ticker, expected)
    get_settings.cache_clear()
    assert Stub.stopped


async def _zero() -> int:
    return 0
