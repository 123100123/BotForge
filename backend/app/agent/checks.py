"""Deterministic checks the agent applies to LLM output: acceptance scenarios and sample data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.agent.requirements import Requirements
from app.botspec.models import BookingCapability, BotSpec, FieldType, RequestCapability
from app.botspec.records import validate_record
from app.testing.scenario import Scenario, SeedRecord, resolve_relative

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(value: object) -> str:
    """Persian digits for owner-facing text."""
    return str(value).translate(_FA_DIGITS)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def validation_messages(exc: ValidationError, limit: int = 8) -> list[str]:
    out = []
    for err in exc.errors(include_url=False)[:limit]:
        loc = "/".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return out


def requirement_ids(req: Requirements | None) -> set[str]:
    return {r.id for r in req.items} if req else set()


def check_acceptance(raw: Any, *, req_ids: set[str], spec: BotSpec) -> tuple[Scenario | None, list[str]]:
    """Validate one LLM-authored acceptance scenario against the requirements and the spec.

    Returns the cleaned scenario (source forced to acceptance, unknown requirement ids dropped,
    capability_keys filled from the steps) or None with the reasons, in English for the model.
    """
    if not isinstance(raw, dict):
        return None, ["a scenario must be a JSON object"]
    data = {**raw, "source": "acceptance"}
    try:
        sc = Scenario.model_validate(data)
    except ValidationError as exc:
        return None, validation_messages(exc)

    issues: list[str] = []
    valid_ids = [r for r in sc.requirement_ids if r in req_ids]
    if not valid_ids:
        issues.append(
            f"requirement_ids must contain at least one existing requirement id (known: {sorted(req_ids)})"
        )
    caps = {c.key: c for c in spec.capabilities}
    for key in sc.capability_keys:
        if key not in caps:
            issues.append(f"capability_keys: '{key}' is not a capability (known: {sorted(caps)})")
    for seed in sc.seed:
        resource = spec.resource(seed.collection)
        if resource is None:
            issues.append(f"seed '{seed.ref}': collection '{seed.collection}' is not a resource")
            continue
        known = {f.key for f in resource.fields}
        unknown = [kv.key for kv in seed.values if kv.key not in known]
        if unknown:
            issues.append(f"seed '{seed.ref}': unknown fields {unknown} (fields: {sorted(known)})")
        missing = [
            f.key for f in resource.fields if f.required and f.key not in {kv.key for kv in seed.values}
        ]
        if missing:
            issues.append(f"seed '{seed.ref}': required fields missing {missing}")
    step_caps: list[str] = []
    for i, step in enumerate(sc.steps):
        if step.capability is not None:
            cap = caps.get(step.capability)
            if cap is None:
                issues.append(f"step {i}: capability '{step.capability}' does not exist")
                continue
            if step.capability not in step_caps:
                step_caps.append(step.capability)
            if step.do in ("book", "cancel", "expect_booking", "expect_counts") and not isinstance(
                cap, BookingCapability
            ):
                issues.append(f"step {i}: '{step.do}' needs a booking capability")
            if step.do in ("submit_request", "expect_request") and not isinstance(cap, RequestCapability):
                issues.append(f"step {i}: '{step.do}' needs a request capability")
            if step.do == "owner_action":
                if isinstance(cap, BookingCapability):
                    if step.action != "cancel" or step.item is None:
                        issues.append(f"step {i}: owner_action on a booking needs action 'cancel' and item")
                elif isinstance(cap, RequestCapability) and step.action not in {
                    a.key for a in cap.owner_actions
                }:
                    issues.append(f"step {i}: unknown owner action '{step.action}'")
            if (
                step.do == "expect_request"
                and isinstance(cap, RequestCapability)
                and step.expect not in {s.key for s in cap.statuses}
            ):
                issues.append(f"step {i}: '{step.expect}' is not a status of '{cap.key}'")
        if step.do == "expect_notified" and step.contains is not None:
            issues.append(f"step {i}: match notifications with 'event', never 'contains'")
    if issues:
        return None, issues
    keys = [k for k in sc.capability_keys if k in caps] or step_caps
    return sc.model_copy(update={"requirement_ids": valid_ids, "capability_keys": keys}), []


def check_sample_record(
    raw: Any, spec: BotSpec, now: datetime | None = None
) -> tuple[SeedRecord | None, str | None]:
    """One generated sample record: a resource record whose values validate (relative datetimes ok)."""
    try:
        seed = SeedRecord.model_validate(raw)
    except ValidationError as exc:
        return None, "; ".join(validation_messages(exc, 3))
    resource = spec.resource(seed.collection)
    if resource is None:
        return None, f"unknown resource '{seed.collection}'"
    now = now or datetime.now(UTC)
    dt_keys = {f.key for f in resource.fields if f.type == FieldType.datetime}
    known = {f.key for f in resource.fields}
    values = {
        kv.key: (resolve_relative(kv.value, now) if kv.key in dt_keys else kv.value) for kv in seed.values
    }
    absolute = [
        kv.key for kv in seed.values if kv.key in dt_keys and kv.value.strip() and values[kv.key] == kv.value
    ]
    if absolute:
        return None, f"datetime fields {absolute} must be relative like '+48h'"
    if set(values) - known:
        return None, f"unknown fields {sorted(set(values) - known)}"
    _, errors = validate_record(resource.fields, values)
    if errors:
        return None, " ".join(errors)
    return seed, None
