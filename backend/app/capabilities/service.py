"""Capability Center service (W1-REG): list, toggle (enable/disable with dependencies), configure.

Spec-kind changes always become a revision through ``revisions.toggle.apply_capability_ops``;
module-kind changes upsert ``bot_modules`` rows. A plan mixing both writes the modules first and
then ONE revision with every spec op, all in the caller's transaction, so a failing revision rolls
the module rows back too. A plan in which any spec capability needs the agent (``default_ops`` is
None) applies nothing and returns the ``handoff_prompt``.

Errors are ``CapabilityError`` (code, Persian message, HTTP status, optional details) or the
``RevisionError`` subclasses of the toggle pipeline; the API maps both to the error envelope.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BookingCapability, BotSpec
from app.botspec.patch import PatchOp
from app.capabilities.registry import (
    CATEGORY_NAMES,
    CATEGORY_ORDER,
    REGISTRY,
    CapabilityDef,
    get_capability,
)
from app.capabilities.resolve import Plan, plan_disable, plan_enable
from app.db.models import Bot, BotModuleRow
from app.revisions.toggle import (
    NoActiveRevision,
    active_revision,
    apply_capability_ops,
    lock_and_refresh,
    patch_spec,
    preview_ops,
)
from app.schemas.business import (
    CapabilityCategoryOut,
    CapabilityListOut,
    CapabilityOut,
    CapabilityToggleOut,
    CapabilityTogglePlan,
)

Action = Literal["enable", "disable"]
SPEC_CONFIG_FIELDS = ("audience", "reminder_hours_before", "enabled")
AUDIENCES = ("everyone", "staff", "managers")
MAX_REMINDER_HOURS = 720


class CapabilityError(Exception):
    """Domain error of the Capability Center. ``message`` is Persian."""

    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def _not_found(cap_id: str) -> CapabilityError:
    return CapabilityError(404, "capability_not_found", f"قابلیت «{cap_id}» پیدا نشد.")


def _unavailable(cap: CapabilityDef) -> CapabilityError:
    return CapabilityError(
        409,
        "capability_unavailable",
        f"قابلیت «{cap.name}» در این نسخه در دسترس نیست و در نسخه‌های بعدی اضافه می‌شود.",
        {"capability": cap.id},
    )


def require_capability(cap_id: str) -> CapabilityDef:
    cap = get_capability(cap_id)
    if cap is None:
        raise _not_found(cap_id)
    return cap


# --------------------------------------------------------------------------- state


ModuleRows = dict[str, BotModuleRow]


def module_enabled(cap: CapabilityDef, rows: ModuleRows) -> bool:
    if not cap.available:
        return False
    row = rows.get(cap.id)
    return row.enabled if row is not None else cap.default_enabled


def is_enabled(cap: CapabilityDef, spec: BotSpec | None, rows: ModuleRows) -> bool:
    if cap.kind == "module":
        return module_enabled(cap, rows)
    if spec is None:
        return False
    return any((c := spec.capability(k)) is not None and c.enabled for k in cap.matches(spec))


def enabled_ids(spec: BotSpec | None, rows: ModuleRows) -> set[str]:
    return {cap.id for cap in REGISTRY if is_enabled(cap, spec, rows)}


async def load_spec(session: AsyncSession, bot: Bot) -> BotSpec | None:
    revision = await active_revision(session, bot)
    if revision is None:
        return None
    try:
        return BotSpec.model_validate(revision.spec)
    except ValidationError:
        return None


async def load_module_rows(session: AsyncSession, bot: Bot) -> ModuleRows:
    rows = (await session.execute(select(BotModuleRow).where(BotModuleRow.bot_id == bot.id))).scalars()
    return {r.module: r for r in rows}


# --------------------------------------------------------------------------- listing


def _spec_config(cap: CapabilityDef, spec: BotSpec | None) -> tuple[str | None, dict[str, Any]]:
    keys = cap.matches(spec)
    first = spec.capability(keys[0]) if spec is not None and keys else None
    if first is None:
        return cap.audience, {}
    config: dict[str, Any] = {"audience": first.audience, "enabled": first.enabled}
    if isinstance(first, BookingCapability):
        config["reminder_hours_before"] = first.reminder_hours_before
    return first.audience, config


def _needs_agent(cap: CapabilityDef, spec: BotSpec | None) -> bool:
    if cap.kind != "spec" or not cap.available:
        return False
    if spec is None:
        return True
    if cap.matches(spec):
        return False
    return cap.default_ops(spec) is None


def capability_out(cap: CapabilityDef, spec: BotSpec | None, rows: ModuleRows) -> CapabilityOut:
    if cap.kind == "module":
        row = rows.get(cap.id)
        audience = cap.audience
        config = {**cap.module_default_config, **(row.config if row is not None else {})}
    else:
        audience, config = _spec_config(cap, spec)
    return CapabilityOut(
        id=cap.id,
        name=cap.name,
        description=cap.description,
        category=cap.category,
        kind=cap.kind,
        enabled=is_enabled(cap, spec, rows),
        configurable=cap.configurable,
        requires=list(cap.requires),
        requires_any=list(cap.requires_any),
        conflicts=list(cap.conflicts),
        features=list(cap.features),
        metrics=list(cap.metrics),
        audience=audience,
        spec_keys=cap.matches(spec),
        config=config,
        needs_agent=_needs_agent(cap, spec),
        handoff_prompt=cap.handoff_prompt,
    )


def list_capabilities(
    spec: BotSpec | None, module_rows: ModuleRows | list[BotModuleRow]
) -> CapabilityListOut:
    rows = module_rows if isinstance(module_rows, dict) else {r.module: r for r in module_rows}
    return CapabilityListOut(
        categories=[
            CapabilityCategoryOut(
                id=category,
                name=CATEGORY_NAMES[category],
                capabilities=[capability_out(c, spec, rows) for c in REGISTRY if c.category == category],
            )
            for category in CATEGORY_ORDER
        ]
    )


async def list_for_bot(session: AsyncSession, bot: Bot) -> CapabilityListOut:
    return list_capabilities(await load_spec(session, bot), await load_module_rows(session, bot))


# --------------------------------------------------------------------------- toggle


async def _upsert_module(
    session: AsyncSession,
    bot: Bot,
    cap: CapabilityDef,
    *,
    enabled: bool | None = None,
    config: dict | None = None,
) -> None:
    values: dict[str, Any] = {"bot_id": bot.id, "module": cap.id}
    update: dict[str, Any] = {}
    if enabled is not None:
        values["enabled"] = update["enabled"] = enabled
    else:
        values["enabled"] = cap.default_enabled
    if config is not None:
        values["config"] = update["config"] = config
    stmt = pg_insert(BotModuleRow).values(**values)
    if update:
        stmt = stmt.on_conflict_do_update(
            index_elements=[BotModuleRow.bot_id, BotModuleRow.module], set_=update
        )
    else:
        stmt = stmt.on_conflict_do_nothing()
    await session.execute(stmt)


def _set_enabled_ops(spec: BotSpec, cap: CapabilityDef, value: bool) -> list[PatchOp]:
    return [
        PatchOp(op="set", path=["capabilities", key, "enabled"], value=value)
        for key in cap.matches(spec)
        if (c := spec.capability(key)) is not None and c.enabled != value
    ]


def _plan_out(
    plan: Plan,
    *,
    needs_agent: bool = False,
    handoff_prompt: str | None = None,
    compat_warnings: list[str] | None = None,
) -> CapabilityTogglePlan:
    return CapabilityTogglePlan(
        capability=plan.target,
        action=plan.action,
        will_enable=list(plan.will_enable),
        will_disable=list(plan.will_disable),
        blocked_by=list(plan.blocked_by),
        needs_agent=needs_agent,
        handoff_prompt=handoff_prompt,
        compat_warnings=compat_warnings or [],
    )


def _names(ids: list[str]) -> str:
    return "، ".join(f"«{require_capability(i).name}»" for i in ids)


class _EnableOps:
    """Spec ops for an enable plan, built sequentially so each default sees the previous ones."""

    def __init__(self, spec: BotSpec | None) -> None:
        self.spec = spec
        self.working = spec
        self.ops: list[PatchOp] = []
        self.needs_agent: list[str] = []
        self.keys_changed: set[str] = set()

    def add(self, cap: CapabilityDef) -> None:
        if self.working is None:
            self.needs_agent.append(cap.id)
            return
        before = {c.key: c.enabled for c in self.working.capabilities}
        if cap.matches(self.working):
            ops = _set_enabled_ops(self.working, cap, True)
        else:
            default = cap.default_ops(self.working)
            if default is None:
                self.needs_agent.append(cap.id)
                return
            ops = default
        if not ops:
            return
        self.working = patch_spec(self.working, ops)
        self.ops.extend(ops)
        self.keys_changed |= {c.key for c in self.working.capabilities if before.get(c.key) is not True}


async def toggle(
    session: AsyncSession, bot: Bot, cap_id: str, action: Action, dry_run: bool = False
) -> CapabilityToggleOut:
    cap = require_capability(cap_id)
    if action == "enable" and not cap.available:
        raise _unavailable(cap)
    if not dry_run:
        await lock_and_refresh(session, bot)
    spec = await load_spec(session, bot)
    rows = await load_module_rows(session, bot)
    on = enabled_ids(spec, rows)

    if action == "enable":
        if cap.id in on:
            plan = Plan(target=cap.id, action="enable")
            return _out(plan, applied=False, message=f"«{cap.name}» از قبل فعال است.")
        plan = plan_enable(REGISTRY, on, cap.id)
        for dep in plan.will_enable:
            if not require_capability(dep).available:
                raise _unavailable(require_capability(dep))
        if plan.blocked_by:
            message = (
                f"«{cap.name}» با {_names(plan.blocked_by)} هم‌زمان قابل "
                "استفاده نیست؛ ابتدا آن را غیرفعال کنید."
            )
            if dry_run:
                return _out(plan, applied=False, message=message)
            raise CapabilityError(409, "capability_conflict", message, {"blocked_by": plan.blocked_by})
        builder = _EnableOps(spec)
        modules: list[CapabilityDef] = []
        for dep_id in plan.will_enable:
            dep = require_capability(dep_id)
            if dep.kind == "module":
                modules.append(dep)
            else:
                builder.add(dep)
        if builder.needs_agent:
            first = builder.needs_agent[0]
            prompt_cap = cap if cap.id in builder.needs_agent else require_capability(first)
            prompt = prompt_cap.handoff_prompt
            if spec is None:
                message = "ابتدا ربات را با دستیار بسازید؛ سپس این قابلیت را فعال کنید."
            else:
                message = (
                    f"افزودن {_names(builder.needs_agent)} به چند تصمیم شما نیاز دارد؛ "
                    "با «پیکربندی با دستیار» ادامه دهید."
                )
            return _out(plan, applied=False, message=message, needs_agent=True, handoff_prompt=prompt)
        spec_ops, keys_changed = builder.ops, builder.keys_changed
        module_writes = [(m, True) for m in modules]
        verb = "فعال‌سازی"
    else:
        if cap.id not in on:
            plan = Plan(target=cap.id, action="disable")
            return _out(plan, applied=False, message=f"«{cap.name}» از قبل غیرفعال است.")
        plan = plan_disable(REGISTRY, on, cap.id)
        spec_ops = []
        keys_changed = set()
        module_writes = []
        for dep_id in plan.will_disable:
            dep = require_capability(dep_id)
            if dep.kind == "module":
                module_writes.append((dep, False))
            elif spec is not None:
                ops = _set_enabled_ops(spec, dep, False)
                spec_ops.extend(ops)
                keys_changed |= {op.path[1] for op in ops}
        verb = "غیرفعال‌سازی"

    warnings: list[str] = []
    if spec_ops:
        if spec is None:
            raise NoActiveRevision()
        _, warnings = await preview_ops(session, bot, spec, spec_ops)

    if dry_run:
        return _out(
            plan, applied=False, message="پیش‌نمایش تغییرات؛ هنوز چیزی اعمال نشده است.", warnings=warnings
        )

    for module_cap, value in module_writes:
        await _upsert_module(session, bot, module_cap, enabled=value)
    revision = None
    if spec_ops:
        revision = await apply_capability_ops(
            session,
            bot,
            spec_ops,
            change_request=f"{verb} قابلیت «{cap.name}» از مرکز قابلیت‌ها",
            enabled_keys_changed=keys_changed,
        )
    done = "فعال شد" if action == "enable" else "غیرفعال شد"
    message = f"«{cap.name}» {done}."
    if revision is not None:
        message += f" نسخهٔ {revision.number} ربات فعال است."
    return _out(plan, applied=True, message=message, warnings=warnings, revision=revision)


def _out(
    plan: Plan,
    *,
    applied: bool,
    message: str,
    needs_agent: bool = False,
    handoff_prompt: str | None = None,
    warnings: list[str] | None = None,
    revision: Any = None,
) -> CapabilityToggleOut:
    return CapabilityToggleOut(
        plan=_plan_out(
            plan, needs_agent=needs_agent, handoff_prompt=handoff_prompt, compat_warnings=warnings
        ),
        applied=applied,
        revision_id=revision.id if revision is not None else None,
        revision_number=revision.number if revision is not None else None,
        message=message,
    )


# --------------------------------------------------------------------------- config


def _invalid_config(message: str, details: Any) -> CapabilityError:
    return CapabilityError(422, "invalid_config", message, details)


def _check_module_config(cap: CapabilityDef, config: dict[str, Any]) -> None:
    unknown = sorted(set(config) - set(cap.module_default_config))
    if unknown:
        raise _invalid_config(
            f"تنظیمات ناشناخته برای «{cap.name}»: {'، '.join(unknown)}",
            {"unknown_keys": unknown, "allowed_keys": sorted(cap.module_default_config)},
        )
    for key, value in config.items():
        default = cap.module_default_config[key]
        expected = type(default)
        ok = isinstance(value, expected) and not (expected is int and isinstance(value, bool))
        if ok and expected is int and value < 0:
            ok = False
        if not ok:
            raise _invalid_config(f"مقدار «{key}» نامعتبر است.", {"key": key, "expected": expected.__name__})


def _spec_config_ops(cap: CapabilityDef, spec: BotSpec, config: dict[str, Any]) -> list[PatchOp]:
    unknown = sorted(set(config) - set(SPEC_CONFIG_FIELDS))
    if unknown:
        raise _invalid_config(
            f"تنظیمات ناشناخته برای «{cap.name}»: {'، '.join(unknown)}",
            {"unknown_keys": unknown, "allowed_keys": list(SPEC_CONFIG_FIELDS)},
        )
    if "audience" in config and config["audience"] not in AUDIENCES:
        raise _invalid_config("مخاطب نامعتبر است.", {"key": "audience", "allowed": list(AUDIENCES)})
    if "enabled" in config and not isinstance(config["enabled"], bool):
        raise _invalid_config("مقدار «enabled» باید درست یا نادرست باشد.", {"key": "enabled"})
    if "reminder_hours_before" in config:
        hours = config["reminder_hours_before"]
        valid = hours is None or (
            isinstance(hours, int) and not isinstance(hours, bool) and 1 <= hours <= MAX_REMINDER_HOURS
        )
        if not valid:
            raise _invalid_config(
                f"یادآوری باید بین ۱ تا {MAX_REMINDER_HOURS} ساعت پیش از شروع باشد.",
                {"key": "reminder_hours_before"},
            )
    keys = cap.matches(spec)
    if not keys:
        raise CapabilityError(
            409,
            "capability_not_configured",
            f"«{cap.name}» هنوز در ربات ساخته نشده است؛ ابتدا آن را فعال کنید.",
        )
    ops: list[PatchOp] = []
    for key in keys:
        current = spec.capability(key)
        assert current is not None
        for field_name, value in config.items():
            if field_name == "reminder_hours_before" and not isinstance(current, BookingCapability):
                raise _invalid_config(
                    "یادآوری فقط برای رزرو و رویداد قابل تنظیم است.", {"key": "reminder_hours_before"}
                )
            if getattr(current, field_name) == value:
                continue
            if value is None:
                ops.append(PatchOp(op="remove", path=["capabilities", key, field_name]))
            else:
                ops.append(PatchOp(op="set", path=["capabilities", key, field_name], value=value))
    return ops


async def update_config(
    session: AsyncSession, bot: Bot, cap_id: str, config: dict[str, Any]
) -> CapabilityToggleOut:
    cap = require_capability(cap_id)
    if not cap.available:
        raise _unavailable(cap)
    await lock_and_refresh(session, bot)
    if cap.kind == "module":
        _check_module_config(cap, config)
        rows = await load_module_rows(session, bot)
        row = rows.get(cap.id)
        merged = {**cap.module_default_config, **(row.config if row is not None else {}), **config}
        await _upsert_module(session, bot, cap, config=merged)
        enabled = module_enabled(cap, rows)
        plan = Plan(target=cap.id, action="enable" if enabled else "disable")
        return _out(plan, applied=True, message=f"تنظیمات «{cap.name}» ذخیره شد.")

    spec = await load_spec(session, bot)
    if spec is None:
        raise NoActiveRevision()
    ops = _spec_config_ops(cap, spec, config)
    enabled_after = config.get("enabled", is_enabled(cap, spec, {}))
    plan = Plan(target=cap.id, action="enable" if enabled_after else "disable")
    if not ops:
        return _out(plan, applied=False, message="تغییری برای اعمال وجود نداشت.")
    _, warnings = await preview_ops(session, bot, spec, ops)
    revision = await apply_capability_ops(
        session,
        bot,
        ops,
        change_request=f"تغییر تنظیمات قابلیت «{cap.name}» از مرکز قابلیت‌ها",
        enabled_keys_changed={op.path[1] for op in ops if op.path[-1] == "enabled"},
    )
    return _out(
        plan,
        applied=True,
        message=f"تنظیمات «{cap.name}» ذخیره شد. نسخهٔ {revision.number} ربات فعال است.",
        warnings=warnings,
        revision=revision,
    )


# --------------------------------------------------------------------------- agent catalog


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def catalog_markdown() -> str:
    """The registry as a markdown table for the agent's catalog prompt (W2-AGENT)."""
    lines = [
        "| id | name (fa) | category | kind | realised by | requires | default ops | description (fa) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cap in REGISTRY:
        if not cap.available:
            ops = "unavailable"
        elif cap.kind == "module":
            ops = "module toggle"
        elif cap.ops_builder.__name__ == "_no_ops":
            ops = "needs agent"
        else:
            ops = "deterministic (when unambiguous)"
        requires = ", ".join(cap.requires) or "-"
        if cap.requires_any:
            requires += f"; any of {', '.join(cap.requires_any)}"
        lines.append(
            "| "
            + " | ".join(
                _cell(v)
                for v in (
                    cap.id,
                    cap.name,
                    f"{cap.category} ({CATEGORY_NAMES[cap.category]})",
                    cap.kind,
                    cap.realised_by,
                    requires,
                    ops,
                    cap.description,
                )
            )
            + " |"
        )
    return "\n".join(lines)
