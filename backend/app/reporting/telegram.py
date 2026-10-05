"""Persian text rendering of reports for the Telegram manager panel and scheduled reports.

Pure functions over the REST models; Persian digits throughout; output is capped at
``MAX_CHARS`` (Telegram allows 4096 per message) and cut at a line boundary with an ellipsis.
"""

from app.reporting.periods import PERIOD_LABELS
from app.runtime.formatting import EMPTY_VALUE, format_datetime, format_decimal, to_persian_digits
from app.schemas.business import CapabilityReportOut, MetricValue, OverviewOut

MAX_CHARS = 3500
MAX_SERIES_LINES = 10
MAX_TABLE_ROWS = 5
ELLIPSIS = "…"


def format_value(value: float | None, unit: str | None) -> str:
    if value is None:
        return EMPTY_VALUE
    text = format_decimal(value)
    return f"{text}{unit}" if unit == "٪" else (f"{text} {unit}" if unit else text)


def _change(metric: MetricValue) -> str:
    if metric.value is None or metric.previous is None:
        return ""
    if metric.previous == 0:
        return "" if metric.value == 0 else " (جدید)"
    pct = (metric.value - metric.previous) / abs(metric.previous) * 100
    if round(pct) == 0:
        return " (بدون تغییر)"
    arrow = "▲" if pct > 0 else "▼"
    return f" ({arrow} {to_persian_digits(abs(round(pct)))}٪)"


def _metric_lines(metric: MetricValue) -> list[str]:
    if metric.kind == "scalar":
        return [f"• {metric.label}: {format_value(metric.value, metric.unit)}{_change(metric)}"]
    lines = [f"• {metric.label}:"]
    if metric.kind == "table":
        rows = (metric.rows or [])[:MAX_TABLE_ROWS]
        for i, row in enumerate(rows, 1):
            name, value = row.get("label", EMPTY_VALUE), format_value(row.get("value"), None)
            lines.append(f"   {to_persian_digits(i)}. {name}: {value}")
        if not rows:
            lines.append("   —")
        return lines
    points = metric.series or []
    shown = points[-MAX_SERIES_LINES:] if metric.kind == "series" else points[:MAX_SERIES_LINES]
    for p in shown:
        lines.append(f"   {p.label}: {format_value(p.value, metric.unit)}")
    if not points:
        lines.append("   —")
    return lines


def _cap(lines: list[str]) -> str:
    text = "\n".join(lines)
    if len(text) <= MAX_CHARS:
        return text
    kept: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > MAX_CHARS - 2:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept) + "\n" + ELLIPSIS


def render_report_text(report: CapabilityReportOut) -> str:
    lines = [f"📊 گزارش {report.label}", f"بازه: {PERIOD_LABELS.get(report.period, report.period)}", ""]
    if not report.metrics:
        lines.append("برای این بخش هنوز شاخصی تعریف نشده است.")
    for metric in report.metrics:
        lines.extend(_metric_lines(metric))
    return _cap(lines)


def render_overview_text(overview: OverviewOut) -> str:
    lines = ["📈 نمای کلی کسب‌وکار", f"بازه: {PERIOD_LABELS.get(overview.period, overview.period)}", ""]
    if not overview.kpis:
        lines.append("هنوز داده‌ای برای نمایش وجود ندارد.")
    for kpi in overview.kpis:
        lines.extend(_metric_lines(kpi))
    if overview.activity:
        lines += ["", "آخرین رویدادها:"]
        for item in overview.activity:
            lines.append(f"– {item.text} ({format_datetime(item.at)})")
    return _cap(lines)
