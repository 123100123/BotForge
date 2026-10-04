"""Deterministic scenario runner (WP3): business scenarios through the real ``BotRuntime``.

For each scenario: a fresh ``MemoryStore(owner_actor_id="owner")``, the fixed ``START_CLOCK``,
``capacity_override`` applied to a copy of the spec, the seed loaded (relative datetimes resolved,
values coerced with ``validate_record``), then the steps executed in order by the drivers; the
first failing step stops the scenario. A seed problem fails the scenario at step ``-1``.

The runner never raises for a bad scenario or an engine error: an exception inside a step is a
failed step whose message carries the exception summary. Every step gets a one-sentence Persian
narrative («علی در «کارگاه سفال» ثبت‌نام می‌کند ← تأیید شد»).
"""

import inspect
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.botspec.models import BookingCapability, BotSpec
from app.botspec.records import validate_record
from app.runtime import formatting
from app.runtime.memory_store import MemoryStore
from app.runtime.store import Store
from app.testing.drivers import RunContext, StepFailure, describe_step, execute_step, narrative
from app.testing.scenario import (
    OWNER,
    Scenario,
    ScenarioResult,
    StepResult,
    TestReport,
    TranscriptEntry,
    resolve_relative,
)

# Builds the fresh store a scenario runs on (sync or async). Default: an in-memory store; the
# Postgres integration tests pass a factory that returns a PgStore bound to a new bot.
StoreFactory = Callable[[], Store | Awaitable[Store]]

START_CLOCK = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)  # the clock every scenario starts at
SEED_STEP = -1  # index reported for a failure while loading the seed


class SeedError(Exception):
    """The scenario's seed could not be loaded (Persian message)."""


def apply_capacity_override(spec: BotSpec, override: int | None) -> BotSpec:
    """A copy of ``spec`` with every fixed-mode booking capacity set to ``override``."""
    copied = spec.model_copy(deep=True)
    if override is not None:
        for cap in copied.capabilities:
            if isinstance(cap, BookingCapability) and cap.capacity.mode == "fixed":
                cap.capacity.value = override
    return copied


async def _load_seed(ctx: RunContext, scenario: Scenario) -> None:
    for seed in scenario.seed:
        resource = ctx.spec.resource(seed.collection)
        if resource is None:
            raise SeedError(
                f"داده‌های اولیه: منبع «{seed.collection}» (ref «{seed.ref}») در مشخصات وجود ندارد."
            )
        known = {f.key for f in resource.fields}
        unknown = [kv.key for kv in seed.values if kv.key not in known]
        if unknown:
            raise SeedError(
                f"داده‌های اولیه «{seed.ref}»: فیلد {'، '.join(f'«{k}»' for k in unknown)} "
                f"در منبع «{resource.key}» وجود ندارد (فیلدها: {'، '.join(sorted(known))})."
            )
        try:
            values = {kv.key: resolve_relative(kv.value, ctx.now) for kv in seed.values}
        except ValueError as exc:
            raise SeedError(f"داده‌های اولیه «{seed.ref}»: {exc}") from exc
        cleaned, errors = validate_record(resource.fields, values)
        if errors:
            raise SeedError(f"داده‌های اولیه «{seed.ref}» نامعتبر است: {' '.join(errors)}")
        record = await ctx.store.create_record(seed.collection, cleaned, now=ctx.now)
        ctx.refs[seed.ref] = record.id
        title_field = next((f for f in resource.fields if f.key == resource.title_field), None)
        title_value = cleaned.get(resource.title_field)
        if title_field is not None and title_value is not None and title_value != "":
            ctx.titles[seed.ref] = formatting.format_field_value(
                title_field, title_value, ctx.spec.bot.timezone
            )
        else:
            ctx.titles[seed.ref] = seed.ref


def _failure_summary(exc: BaseException) -> str:
    return f"خطای غیرمنتظره هنگام اجرای گام: {type(exc).__name__}: {exc}"


async def run_scenario(
    spec: BotSpec, scenario: Scenario, *, store_factory: StoreFactory | None = None
) -> ScenarioResult:
    """Run one scenario. Never raises."""
    try:
        run_spec = apply_capacity_override(spec, scenario.capacity_override)
        store = store_factory() if store_factory is not None else MemoryStore(owner_actor_id=OWNER)
        if inspect.isawaitable(store):
            store = await store
        ctx = RunContext(run_spec, store, START_CLOCK)
    except Exception as exc:  # defensive: a malformed spec object
        return _setup_failure(scenario, _failure_summary(exc), [])
    try:
        await _load_seed(ctx, scenario)
    except SeedError as exc:
        return _setup_failure(scenario, str(exc), ctx.transcript)
    except Exception as exc:
        return _setup_failure(scenario, _failure_summary(exc), ctx.transcript)

    results: list[StepResult] = []
    failed_step: int | None = None
    for index, step in enumerate(scenario.steps):
        try:
            sentence = describe_step(ctx, step)
        except Exception:
            sentence = f"گام {index + 1}: {step.do}"
        passed = True
        message: str | None = None
        try:
            result = await execute_step(ctx, step)
        except StepFailure as failure:
            passed, message, result = False, failure.message, failure.result or "ناموفق"
        except Exception as exc:
            passed, message, result = False, _failure_summary(exc), "خطا"
        results.append(
            StepResult(index=index, passed=passed, message=message, narrative=narrative(sentence, result))
        )
        if not passed:
            failed_step = index
            break
    return ScenarioResult(
        scenario_id=scenario.id,
        passed=failed_step is None,
        failed_step=failed_step,
        steps=results,
        transcript=ctx.transcript,
    )


def _setup_failure(scenario: Scenario, message: str, transcript: list[TranscriptEntry]) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario.id,
        passed=False,
        failed_step=SEED_STEP,
        steps=[
            StepResult(
                index=SEED_STEP, passed=False, message=message, narrative="آماده‌سازی داده‌های اولیه ← ناموفق"
            )
        ],
        transcript=transcript,
    )


async def run_scenarios(
    spec: BotSpec, scenarios: list[Scenario], *, store_factory: StoreFactory | None = None
) -> TestReport:
    """Run every scenario (each on a fresh store) and summarize. Never raises."""
    started = time.perf_counter()
    results = [await run_scenario(spec, s, store_factory=store_factory) for s in scenarios]
    passed = sum(1 for r in results if r.passed)
    return TestReport(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
