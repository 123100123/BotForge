"""Manager Copilot tools: bounded, read-only, deterministic.

Every number the Copilot quotes comes from one of these tools; each is a thin layer over the
Reporting Engine (``app.reporting``), the stored analysis runs and the team list. None calls an LLM,
none writes, and none returns raw records: results are aggregates, truncated lists and a few titles,
serialized to at most ``MAX_RESULT_BYTES``.

Handlers never raise: a bad argument (unknown capability key, period, metric, profile, date) is a
structured error ``{"ok": false, "error": <code>, "message": ..., "valid": [...]}`` the model can
read and correct. ``CopilotTools`` is built per request (it holds that request's session, spec and
store) and records one ``ToolCallOut`` per executed call with a Persian one-line summary.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import ToolDef, ToolOutcome
from app.botspec.models import AnyCapability, BotSpec, FieldType, RequestCapability
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot
from app.reporting import service as reporting
from app.reporting.metrics import capability_id, metrics_for
from app.reporting.periods import PERIOD_LABELS
from app.roles import service as roles
from app.runtime.formatting import get_tz, to_ascii_digits, to_persian_digits
from app.runtime.store import Store
from app.schemas.business import MetricValue, Period, ToolCallOut

log = logging.getLogger(__name__)

PERIODS: tuple[str, ...] = get_args(Period)
FINISH_TOOL = "finish"
MAX_RESULT_BYTES = 4096
MAX_ROWS = 10  # rows / points / anomalies per list
MAX_DATA_CALLS = 6  # data tool calls per question (``finish`` is not counted)
MAX_PENDING = 10
MAX_NAMES = 20
MAX_TEXT = 80
LIVE = "live"

LIMIT_ERROR = (
    "tool_limit",
    "سقف تعداد فراخوانی ابزارها برای این پرسش پر شده است؛ با داده‌های موجود پاسخ بدهید.",
)

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolError(Exception):
    """A rejected argument; becomes a structured tool error."""

    def __init__(self, code: str, message: str, valid: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.valid = valid


# --- compact result shaping -------------------------------------------------------------------


def _num(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 2)


def _compact_metric(m: MetricValue) -> dict[str, Any]:
    out: dict[str, Any] = {"id": m.id, "label": m.label, "kind": m.kind}
    if m.unit:
        out["unit"] = m.unit
    if m.kind == "scalar":
        out["value"] = _num(m.value)
        if m.previous is not None:
            out["previous"] = _num(m.previous)
    elif m.kind == "table":
        rows = m.rows or []
        out["rows"] = [_short_row(r) for r in rows[:MAX_ROWS]]
        out["rows_total"] = len(rows)
    else:  # series: the latest points; breakdown: the largest groups come first
        points = m.series or []
        chosen = points[-MAX_ROWS:] if m.kind == "series" else points[:MAX_ROWS]
        out["points"] = [{"label": p.label, "value": _num(p.value)} for p in chosen]
        out["points_total"] = len(points)
    return out


def _short_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (v[:MAX_TEXT] if isinstance(v, str) else _num(v) if isinstance(v, float) else v)
        for k, v in row.items()
        if isinstance(v, str | int | float | bool) or v is None
    }


def _lists(node: Any) -> list[list[Any]]:
    found: list[list[Any]] = []
    if isinstance(node, list):
        found.append(node)
        for item in node:
            found.extend(_lists(item))
    elif isinstance(node, dict):
        for item in node.values():
            found.extend(_lists(item))
    return found


def fit(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop trailing list items (from the longest list) until the JSON fits ``MAX_RESULT_BYTES``."""

    def size() -> int:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())

    if size() <= MAX_RESULT_BYTES:
        return payload
    payload["truncated"] = True
    while size() > MAX_RESULT_BYTES:
        longest = max((lst for lst in _lists(payload) if len(lst) > 1), key=len, default=None)
        if longest is None:
            break
        longest.pop()
    return payload


# --- argument validation ----------------------------------------------------------------------


def _period(args: dict[str, Any]) -> Period:
    value = args.get("period")
    if value not in PERIODS:
        raise ToolError("invalid_period", "دورهٔ گزارش معتبر نیست.", list(PERIODS))
    return value  # type: ignore[return-value]


def _limit(value: Any, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("invalid_limit", f"limit باید عددی بین ۱ و {maximum} باشد.")
    return min(value, maximum)


# --- the toolbox ------------------------------------------------------------------------------


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _key_property(spec: BotSpec | None, doc: str) -> dict[str, Any]:
    keys = [c.key for c in spec.capabilities if c.enabled and metrics_for(c)] if spec is not None else []
    prop: dict[str, Any] = {"type": "string", "description": doc}
    if keys:
        prop["enum"] = keys
    return prop


class CopilotTools:
    """The Copilot's tools for one request. ``calls`` collects what the model asked for."""

    def __init__(
        self,
        session: AsyncSession,
        bot: Bot,
        spec: BotSpec | None,
        store: Store,
        now: datetime,
    ) -> None:
        self.session = session
        self.bot = bot
        self.spec = spec
        self.store = store
        self.now = now
        self.calls: list[ToolCallOut] = []
        self.answer: str | None = None  # the text of ``finish``
        self._data_calls = 0
        self._handlers: dict[str, ToolHandler] = {
            "get_business_summary": self._business_summary,
            "get_capability_report": self._capability_report,
            "compare_periods": self._compare_periods,
            "list_pending_approvals": self._pending_approvals,
            "get_spreadsheet_report": self._spreadsheet_report,
            "who_submitted": self._who_submitted,
        }

    # --- definitions

    def definitions(self) -> list[ToolDef]:
        period = {"type": "string", "enum": list(PERIODS), "description": "دورهٔ گزارش"}
        key = _key_property(self.spec, "کلید قابلیت (capability_key) از فهرست قابلیت‌های فعال")
        return [
            ToolDef(
                "get_business_summary",
                "شاخص‌های کلیدی کل کسب‌وکار (سفارش، فروش، رزرو، درخواست، مشتریان) با مقدار دورهٔ قبل "
                "و فهرست قابلیت‌های فعال.",
                _schema({"period": period}, ["period"]),
                strict=True,
            ),
            ToolDef(
                "get_capability_report",
                "همهٔ شاخص‌های یک قابلیت (مثلاً سفارش‌ها) در یک دوره: مقدارها با دورهٔ قبل و "
                f"حداکثر {MAX_ROWS} ردیف برتر هر جدول، مثل پرفروش‌ترین محصولات.",
                _schema({"capability_key": key, "period": period}, ["capability_key", "period"]),
                strict=True,
            ),
            ToolDef(
                "compare_periods",
                "مقایسهٔ یک شاخص عددی یک قابلیت با دورهٔ قبل: مقدار فعلی، قبلی و درصد تغییر.",
                _schema(
                    {
                        "capability_key": key,
                        "metric_id": {"type": "string", "description": "شناسهٔ شاخص از get_capability_report"},
                        "period": period,
                    },
                    ["capability_key", "metric_id", "period"],
                ),
                strict=True,
            ),
            ToolDef(
                "list_pending_approvals",
                "درخواست‌های منتظر تصمیم مدیر (مرخصی، تعمیر و مانند آن) در همهٔ قابلیت‌های درخواست: "
                "عنوان، وضعیت و زمان ثبت.",
                _schema({"limit": {"type": ["integer", "null"], "description": f"حداکثر {MAX_PENDING}"}}, []),
            ),
            ToolDef(
                "get_spreadsheet_report",
                "آخرین نتیجهٔ تحلیل فایل اکسل (شاخص‌های عددی و موارد غیرعادی) برای یک پروفایل تحلیل؛ "
                "بدون نام پروفایل، آخرین تحلیل ثبت‌شده و فهرست نام پروفایل‌ها برگردانده می‌شود.",
                _schema(
                    {
                        "profile_name": {"type": ["string", "null"], "description": "نام پروفایل تحلیل"},
                        "latest": {
                            "type": "boolean",
                            "description": "true: فقط آخرین تحلیل؛ false: چند تحلیل اخیر به‌صورت خلاصه",
                        },
                    },
                    [],
                ),
            ),
            ToolDef(
                "who_submitted",
                "کدام همکاران در یک روز (به وقت تهران) فایل گزارش یک پروفایل تحلیل را فرستاده‌اند و "
                "کدام‌ها نفرستاده‌اند.",
                _schema(
                    {
                        "profile_name": {"type": "string", "description": "نام پروفایل تحلیل"},
                        "date": {"type": "string", "description": "today یا تاریخ میلادی YYYY-MM-DD"},
                    },
                    ["profile_name", "date"],
                ),
                strict=True,
            ),
            ToolDef(
                FINISH_TOOL,
                "پایان کار: پاسخ نهایی فارسی به مدیر را اینجا بنویسید (پس از فراخوانی ابزارهای لازم).",
                _schema({"reply": {"type": "string", "description": "متن پاسخ"}}, ["reply"]),
                strict=True,
            ),
        ]

    # --- dispatch

    async def handle(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        if name == FINISH_TOOL:
            reply = args.get("reply")
            self.answer = reply.strip() if isinstance(reply, str) and reply.strip() else None
            return ToolOutcome({"ok": True}, stop=True)
        handler = self._handlers.get(name)
        if handler is None:
            return ToolOutcome(
                {"ok": False, "error": "unknown_tool", "message": f"ابزار «{name}» وجود ندارد."}, True
            )
        self._data_calls += 1
        self.calls.append(ToolCallOut(name=name, arguments=args, summary=self.summarize(name, args)))
        if self._data_calls > MAX_DATA_CALLS:
            code, message = LIMIT_ERROR
            return ToolOutcome({"ok": False, "error": code, "message": message}, True)
        try:
            return ToolOutcome(fit({"ok": True, **await handler(args)}))
        except ToolError as exc:
            out: dict[str, Any] = {"ok": False, "error": exc.code, "message": exc.message}
            if exc.valid is not None:
                out["valid"] = exc.valid
            return ToolOutcome(out, True)
        except Exception:
            log.exception("copilot tool failed: %s", name)
            return ToolOutcome({"ok": False, "error": "internal_error", "message": "خطای داخلی ابزار."}, True)

    # --- summaries (Persian, one line, safe for any argument shape)

    def summarize(self, name: str, args: dict[str, Any]) -> str:
        period = PERIOD_LABELS.get(str(args.get("period")), "")
        title = self._title(args.get("capability_key"))
        if name == "get_business_summary":
            return f"خلاصهٔ کسب‌وکار برای {period}".strip()
        if name == "get_capability_report":
            return f"گزارش {title} برای {period}".strip()
        if name == "compare_periods":
            return f"مقایسهٔ «{str(args.get('metric_id'))[:40]}» در {title} با دورهٔ قبل".strip()
        if name == "list_pending_approvals":
            return "فهرست درخواست‌های منتظر تصمیم"
        if name == "get_spreadsheet_report":
            profile = args.get("profile_name")
            return f"آخرین تحلیل فایل «{str(profile)[:40]}»" if profile else "آخرین تحلیل فایل اکسل"
        if name == "who_submitted":
            profile = str(args.get("profile_name"))[:40]
            return f"بررسی ارسال گزارش «{profile}» برای {self._day_label(args.get('date'))}"
        return name

    def _title(self, key: Any) -> str:
        cap = self.spec.capability(key) if self.spec is not None and isinstance(key, str) else None
        return cap.title if cap is not None else "قابلیت"

    def _day_label(self, value: Any) -> str:
        return "امروز" if value in (None, "today") else to_persian_digits(str(value)[:10])

    # --- capability lookup

    def _capability(self, args: dict[str, Any]) -> AnyCapability:
        if self.spec is None:
            raise ToolError("no_active_revision", "این ربات هنوز نسخهٔ فعالی ندارد.")
        reportable = [c for c in self.spec.capabilities if metrics_for(c)]
        key = args.get("capability_key")
        cap = next((c for c in reportable if c.key == key), None)
        if cap is None:
            raise ToolError(
                "invalid_capability_key",
                "این کلید قابلیت وجود ندارد یا گزارش‌پذیر نیست.",
                [c.key for c in reportable if c.enabled],
            )
        if not cap.enabled:
            raise ToolError("capability_disabled", f"قابلیت «{cap.title}» غیرفعال است.")
        return cap

    # --- tools

    async def _business_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        period = _period(args)
        if self.spec is None:
            raise ToolError("no_active_revision", "این ربات هنوز نسخهٔ فعالی ندارد.")
        extra = await reporting.collect_overview_sources(self.bot.id, self.session)
        out = await reporting.overview(self.store, self.spec, period, self.now, extra_kpis=extra)
        return {
            "period": period,
            "kpis": [_compact_metric(k) for k in out.kpis if k.kind == "scalar"],
            "enabled_capabilities": out.enabled_capabilities,
            "capabilities": [
                {"key": c.key, "title": c.title, "kind": capability_id(c)}
                for c in self.spec.capabilities
                if c.enabled
            ],
        }

    async def _report(self, cap: AnyCapability, period: Period) -> Any:
        assert self.spec is not None
        return await reporting.capability_report(self.store, self.spec, cap, period, self.now)

    async def _capability_report(self, args: dict[str, Any]) -> dict[str, Any]:
        period = _period(args)
        cap = self._capability(args)
        report = await self._report(cap, period)
        return {
            "capability_key": cap.key,
            "label": report.label,
            "period": period,
            "metrics": [_compact_metric(m) for m in report.metrics],
        }

    async def _compare_periods(self, args: dict[str, Any]) -> dict[str, Any]:
        period = _period(args)
        cap = self._capability(args)
        report = await self._report(cap, period)
        scalars = {m.id: m for m in report.metrics if m.kind == "scalar"}
        metric = scalars.get(str(args.get("metric_id")))
        if metric is None:
            raise ToolError("invalid_metric_id", "این شاخص عددی در این قابلیت وجود ندارد.", list(scalars))
        change = None
        if metric.value is not None and metric.previous not in (None, 0):
            assert metric.previous is not None
            change = round((metric.value - metric.previous) / abs(metric.previous) * 100, 1)
        return {
            "capability_key": cap.key,
            "metric_id": metric.id,
            "label": metric.label,
            "unit": metric.unit,
            "period": period,
            "current": _num(metric.value),
            "previous": _num(metric.previous),
            "change_pct": change,
        }

    async def _pending_approvals(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args.get("limit"), MAX_PENDING, MAX_PENDING)
        if self.spec is None:
            raise ToolError("no_active_revision", "این ربات هنوز نسخهٔ فعالی ندارد.")
        items: list[dict[str, Any]] = []
        total = 0
        for cap in self.spec.capabilities:
            if not isinstance(cap, RequestCapability) or not cap.enabled:
                continue
            open_statuses = _open_statuses(cap)
            total += await self.store.count_records(cap.key, status_in=open_statuses)
            labels = {s.key: s.label for s in cap.statuses}
            for rec in await self.store.list_records(
                cap.key, status_in=open_statuses, order_by="-id", limit=limit
            ):
                items.append(
                    {
                        "capability_key": cap.key,
                        "capability": cap.title,
                        "title": _record_title(cap, rec.data),
                        "status": labels.get(rec.status or "", rec.status),
                        "created_at": rec.created_at.isoformat(),
                    }
                )
        items.sort(key=lambda i: i["created_at"], reverse=True)
        return {"total_pending": total, "items": items[:limit]}

    async def _profile_names(self) -> list[str]:
        stmt = select(AnalysisProfileRow.name).where(AnalysisProfileRow.bot_id == self.bot.id)
        return list((await self.session.execute(stmt.order_by(AnalysisProfileRow.name))).scalars())

    async def _profile(self, name: Any) -> AnalysisProfileRow:
        stmt = select(AnalysisProfileRow).where(
            AnalysisProfileRow.bot_id == self.bot.id, AnalysisProfileRow.name == name
        )
        profile = (await self.session.execute(stmt)).scalars().first() if isinstance(name, str) else None
        if profile is None:
            raise ToolError(
                "invalid_profile_name", "پروفایل تحلیلی با این نام وجود ندارد.", await self._profile_names()
            )
        return profile

    async def _spreadsheet_report(self, args: dict[str, Any]) -> dict[str, Any]:
        latest = args.get("latest", True)
        if not isinstance(latest, bool):
            raise ToolError("invalid_latest", "latest باید true یا false باشد.")
        name = args.get("profile_name")
        stmt = select(AnalysisRunRow, AnalysisProfileRow.name).join(
            AnalysisProfileRow, AnalysisProfileRow.id == AnalysisRunRow.profile_id
        )
        stmt = stmt.where(AnalysisRunRow.bot_id == self.bot.id)
        if name is not None:
            profile = await self._profile(name)
            stmt = stmt.where(AnalysisRunRow.profile_id == profile.id)
        rows = (
            await self.session.execute(stmt.order_by(AnalysisRunRow.created_at.desc()).limit(MAX_ROWS))
        ).all()
        profiles = await self._profile_names()
        if not rows:
            return {"profiles": profiles, "runs": [], "note": "هنوز هیچ تحلیلی ثبت نشده است."}
        good = [r for r in rows if r[0].status == "ok"] or rows  # prefer the newest usable run
        if latest:
            return {"profiles": profiles, "run": _run_summary(*good[0], detail=True)}
        return {"profiles": profiles, "runs": [_run_summary(*r, detail=False) for r in rows[:3]]}

    async def _who_submitted(self, args: dict[str, Any]) -> dict[str, Any]:
        profile = await self._profile(args.get("profile_name"))
        tz = get_tz(self.spec.bot.timezone if self.spec is not None else None)
        day = self._parse_day(args.get("date"), tz)
        start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        stmt = select(AnalysisRunRow.submitted_by).where(
            AnalysisRunRow.bot_id == self.bot.id,
            AnalysisRunRow.profile_id == profile.id,
            AnalysisRunRow.submitted_by.is_not(None),
            AnalysisRunRow.created_at >= start,
            AnalysisRunRow.created_at < end,
        )
        senders = {s for s in (await self.session.execute(stmt)).scalars() if s}
        owner = self.bot.owner_actor_id
        members = [
            m for m in await roles.list_members(self.session, self.bot.id, LIVE, owner) if m.actor_id != owner
        ]
        done = [m.display_name or m.actor_id for m in members if m.actor_id in senders]
        missing = [m.display_name or m.actor_id for m in members if m.actor_id not in senders]
        return {
            "profile": profile.name,
            "date": day.isoformat(),
            "total_staff": len(members),
            "submitted": done[:MAX_NAMES],
            "not_submitted": missing[:MAX_NAMES],
        }

    def _parse_day(self, value: Any, tz: Any) -> date:
        if value in (None, "today"):
            return self.now.astimezone(tz).date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(to_ascii_digits(value.strip()))
            except ValueError:
                pass
        raise ToolError("invalid_date", "تاریخ باید today یا به شکل YYYY-MM-DD (میلادی) باشد.")


# --- helpers ----------------------------------------------------------------------------------


def _open_statuses(cap: RequestCapability) -> list[str]:
    """Statuses a manager can still act on: the initial one and every status an owner action leaves."""
    keys = {cap.initial_status} | {s for a in cap.owner_actions for s in a.from_statuses}
    return [s.key for s in cap.statuses if s.key in keys]


def _record_title(cap: RequestCapability, data: dict[str, Any]) -> str:
    """The first text-like field with a value (never a phone number), cut to ``MAX_TEXT``."""
    text_like = (FieldType.text, FieldType.long_text, FieldType.choice)
    fields = [f for f in cap.form_fields if f.type != FieldType.phone]
    for f in sorted(fields, key=lambda f: f.type not in text_like):  # stable: spec order within a group
        value = data.get(f.key)
        if value not in (None, ""):
            return str(value)[:MAX_TEXT]
    return cap.title


def _run_summary(run: AnalysisRunRow, profile_name: str, *, detail: bool) -> dict[str, Any]:
    result = run.result or {}
    metrics = [m for m in result.get("metrics", []) if isinstance(m, dict) and m.get("kind") == "scalar"]
    out: dict[str, Any] = {
        "profile": profile_name,
        "status": run.status,
        "at": run.created_at.isoformat(),
        "metrics": [
            {
                k: (_num(v) if isinstance(v, float) else v)
                for k, v in m.items()
                if k in ("id", "label", "value", "previous", "unit") and v is not None
            }
            for m in metrics[:MAX_ROWS]
        ],
    }
    if detail:
        out["anomalies"] = [
            {k: v for k, v in a.items() if k in ("label", "field", "group", "value", "expected", "severity")}
            for a in result.get("anomalies", [])[:MAX_ROWS]
            if isinstance(a, dict)
        ]
        if run.status != "ok":
            out["error"] = (run.error or "")[: MAX_TEXT * 2] or None
            out["schema_diff"] = run.schema_diff
    else:
        out["anomaly_count"] = len(result.get("anomalies", []))
    return out
