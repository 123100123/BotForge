"""Report periods: Jalali-aware bounds in the bot's timezone (Tehran by default).

``period_bounds`` returns ``(since, until, prev_since, prev_until)`` in UTC, ``since`` inclusive and
``until`` exclusive. Open periods (today, 7d, 30d, this week, this month) end at ``now``; the
previous window has the same length as the elapsed part of the current one and starts one natural
unit (day, 7 days, 30 days, week, Jalali month) earlier, so "this week so far" is compared with
"last week over the same stretch". ``all`` has no start and no previous window.
"""

from datetime import UTC, datetime, timedelta, tzinfo

from app.runtime.formatting import get_tz, gregorian_to_jalali
from app.schemas.business import Period

Bounds = tuple[datetime | None, datetime, datetime | None, datetime | None]

PERIOD_LABELS: dict[str, str] = {
    "today": "امروز",
    "yesterday": "دیروز",
    "7d": "۷ روز گذشته",
    "30d": "۳۰ روز گذشته",
    "this_week": "این هفته",
    "last_week": "هفتهٔ گذشته",
    "this_month": "این ماه",
    "all": "کل دوره",
}


def _midnight(now: datetime, tz: tzinfo) -> datetime:
    return now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)


def _saturday(midnight: datetime) -> datetime:
    return midnight - timedelta(days=(midnight.weekday() + 2) % 7)


def _jalali_month_start(midnight: datetime) -> datetime:
    _, _, jd = gregorian_to_jalali(midnight.date())
    return midnight - timedelta(days=jd - 1)


def period_bounds(period: Period, now: datetime, tz: str | tzinfo | None = None) -> Bounds:
    zone = tz if isinstance(tz, tzinfo) else get_tz(tz)
    today = _midnight(now, zone)
    until: datetime = now
    unit = timedelta(days=1)

    if period == "all":
        return None, now.astimezone(UTC), None, None
    if period == "today":
        since = today
    elif period == "yesterday":
        since, until = today - timedelta(days=1), today
    elif period == "7d":
        since, unit = today - timedelta(days=6), timedelta(days=7)
    elif period == "30d":
        since, unit = today - timedelta(days=29), timedelta(days=30)
    elif period == "this_week":
        since, unit = _saturday(today), timedelta(days=7)
    elif period == "last_week":
        until = _saturday(today)
        since, unit = until - timedelta(days=7), timedelta(days=7)
    elif period == "this_month":
        since = _jalali_month_start(today)
        unit = since - _jalali_month_start(since - timedelta(days=1))
    else:  # pragma: no cover - Period is a closed Literal
        raise ValueError(f"unknown period {period!r}")

    prev_since = since - unit
    prev_until = min(prev_since + (until - since), since)
    return (
        since.astimezone(UTC),
        until.astimezone(UTC),
        prev_since.astimezone(UTC),
        prev_until.astimezone(UTC),
    )
