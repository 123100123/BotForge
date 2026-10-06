"""The optional Persian summary of a run: one fast-tier structured call that sees ONLY the computed
metrics and anomalies (never the file's rows). Any failure returns ``None``; the run stays ``ok``."""

import json
import logging

from pydantic import BaseModel

from app.agent.llm import LLMClient
from app.schemas.business import AnalysisAnomaly, MetricValue
from app.spreadsheets.profile import load_prompt

log = logging.getLogger(__name__)

MAX_POINTS = 40  # series / breakdown points shown to the model per metric
MAX_ANOMALIES = 20
MAX_SUMMARY_CHARS = 1500


class NarrativeOut(BaseModel):
    summary: str


def narrative_payload(
    profile_name: str, metrics: list[MetricValue], anomalies: list[AnalysisAnomaly]
) -> dict[str, object]:
    shown = []
    for metric in metrics:
        entry = metric.model_dump(mode="json", exclude_none=True, exclude={"rows"})
        if metric.series is not None:
            entry["series"] = [p.model_dump(mode="json") for p in metric.series[:MAX_POINTS]]
        shown.append(entry)
    return {
        "report": profile_name,
        "metrics": shown,
        "anomalies": [a.model_dump(mode="json", exclude_none=True) for a in anomalies[:MAX_ANOMALIES]],
    }


async def narrate(
    llm: LLMClient, profile_name: str, metrics: list[MetricValue], anomalies: list[AnalysisAnomaly]
) -> str | None:
    payload = narrative_payload(profile_name, metrics, anomalies)
    try:
        result, _usage = await llm.structured(
            task="analysis_narrative",
            tier="fast",
            system=load_prompt("narrative"),
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            schema=NarrativeOut,
        )
        summary = NarrativeOut.model_validate(result).summary.strip()
    except Exception:
        log.warning("analysis narrative failed; the run keeps no summary", exc_info=True)
        return None
    return summary[:MAX_SUMMARY_CHARS] or None
