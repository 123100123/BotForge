"""Shared form collector for ``form_fields`` (booking and request engines) (WP1).

Usage inside an engine (the engine is the ``host``)::

    async def on_callback(self, ctx, cap, action, arg):
        if action in FORM_ACTIONS:
            return await forms.handle_callback(ctx, self, cap, action, arg)
        if action == ACT_BOOK:
            await forms.start(ctx, self, cap, data={"item_id": item.id})

    async def on_text(self, ctx, cap, text):
        await forms.handle_text(ctx, self, cap, text)

    async def on_form_done(self, ctx, cap, values, data):
        ...  # values: cleaned dict for every field (validate_record forms); data: what start() got

Behavior:
- Fields are asked in order, one message per field (text key ``ask_field`` with ``{label}``).
  ``choice`` fields get one button per choice and ``boolean`` fields get بله/خیر buttons, both with
  callback action ``ans`` (arg = choice index; for boolean 0 = بله, 1 = خیر); typed text is also
  accepted. Optional fields get a ``skip`` button; every question has a ``stop`` button.
- Each answer is validated with ``botspec.records.validate_record`` for that single field. Invalid
  input re-asks with ``invalid_answer`` (``{label}``, ``{error}``). Skip stores the field default
  (or None); skip on a required field is answered like an invalid empty answer.
- ``stop`` clears the session and replies ``form_stopped`` with the main menu.
- With no fields, ``start`` calls ``on_form_done`` immediately (no session is written).
- On completion the session is cleared *before* ``on_form_done`` runs, so the host may start a new
  form or set its own session from there.

Session shape (JSON-safe)::

    {"capability": cap.key, "step": "form",
     "vars": {"field": <key being asked>, "answers": {<key>: <cleaned value>}, "data": {...}}}

Fields are never stored in the session; the host passes them (default ``cap.form_fields``) on each
call, and progress is keyed by field key, so a spec change mid-form cannot misalign answers.
Answers that no longer validate at completion (e.g. a removed choice) are asked again.
Note: an ``ans`` tap on an old question message whose field is no longer current is applied to
the current field if its index is valid for it (callback args carry only the choice index).
"""

from collections.abc import Sequence
from typing import Any, Protocol

from app.botspec.models import FieldDef, FieldType
from app.botspec.records import validate_record
from app.runtime.callbacks import ACT_ANS, ACT_SKIP, ACT_STOP
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx, parse_int
from app.runtime.texts import common

FORM_STEP = "form"


class FormHost(Protocol):
    async def on_form_done(
        self, ctx: Ctx, cap: Any, values: dict[str, Any], data: dict[str, Any]
    ) -> None: ...


def _fields(cap: Any, fields: Sequence[FieldDef] | None) -> list[FieldDef]:
    return list(fields) if fields is not None else list(getattr(cap, "form_fields", None) or [])


def is_form_session(session: dict[str, Any] | None, cap: Any) -> bool:
    """True if ``session`` is a form in progress for ``cap``."""
    return (
        isinstance(session, dict)
        and session.get("capability") == cap.key
        and session.get("step") == FORM_STEP
        and isinstance(session.get("vars"), dict)
    )


async def start(
    ctx: Ctx,
    host: FormHost,
    cap: Any,
    *,
    data: dict[str, Any] | None = None,
    fields: Sequence[FieldDef] | None = None,
    intro: str | None = None,
) -> None:
    """Begin collecting ``fields`` (default ``cap.form_fields``). ``data`` (JSON-safe) is handed
    back unchanged to ``on_form_done``. ``intro`` is prepended to the first question."""
    fs = _fields(cap, fields)
    payload = dict(data or {})
    if not fs:
        await host.on_form_done(ctx, cap, {}, payload)
        return
    session = {
        "capability": cap.key,
        "step": FORM_STEP,
        "vars": {"field": None, "answers": {}, "data": payload},
    }
    await _advance(ctx, host, cap, fs, session, prefix=intro)


async def handle_text(
    ctx: Ctx, host: FormHost, cap: Any, text: str, *, fields: Sequence[FieldDef] | None = None
) -> None:
    session = await ctx.get_session()
    if not is_form_session(session, cap):
        ctx.stale()
        return
    assert session is not None
    fs = _fields(cap, fields)
    field = _current(fs, session)
    if field is None:
        await _advance(ctx, host, cap, fs, session)
        return
    await _accept(ctx, host, cap, fs, session, field, text)


async def handle_callback(
    ctx: Ctx,
    host: FormHost,
    cap: Any,
    action: str,
    arg: str,
    *,
    fields: Sequence[FieldDef] | None = None,
) -> None:
    """Handle ``ans`` / ``skip`` / ``stop`` for ``cap``'s form."""
    session = await ctx.get_session()
    if not is_form_session(session, cap):
        ctx.stale()
        return
    assert session is not None
    if action == ACT_STOP:
        await ctx.clear_session()
        ctx.reply(ctx.t(cap, "form_stopped"), ctx.menu_buttons())
        return
    fs = _fields(cap, fields)
    field = _current(fs, session)
    if field is None:
        await _advance(ctx, host, cap, fs, session)
        return
    if action == ACT_SKIP:
        await _accept(ctx, host, cap, fs, session, field, None)
        return
    if action == ACT_ANS:
        value = _choice_value(field, arg)
        if value is None:
            _ask(ctx, cap, field, prefix=common.STALE)
            return
        await _accept(ctx, host, cap, fs, session, field, value)
        return
    ctx.stale()


# --- internals -------------------------------------------------------------------------------


def _current(fields: list[FieldDef], session: dict[str, Any]) -> FieldDef | None:
    key = session["vars"].get("field")
    return next((f for f in fields if f.key == key), None)


def _choice_value(field: FieldDef, arg: str) -> str | bool | None:
    idx = parse_int(arg)
    if idx is None:
        return None
    if field.type == FieldType.boolean:
        return {0: True, 1: False}.get(idx)
    if field.type == FieldType.choice and idx < len(field.choices or []):
        return (field.choices or [])[idx]
    return None


def _field_buttons(cap: Any, field: FieldDef) -> list[list[Button]]:
    rows: list[list[Button]] = []
    if field.type == FieldType.choice:
        rows += [[Ctx.button(choice, cap, ACT_ANS, i)] for i, choice in enumerate(field.choices or [])]
    elif field.type == FieldType.boolean:
        rows.append([Ctx.button(common.YES, cap, ACT_ANS, 0), Ctx.button(common.NO, cap, ACT_ANS, 1)])
    if not field.required:
        rows.append([Ctx.button(common.SKIP, cap, ACT_SKIP)])
    rows.append([Ctx.button(common.STOP, cap, ACT_STOP)])
    return rows


def _ask(ctx: Ctx, cap: Any, field: FieldDef, prefix: str | None = None) -> None:
    lines = [prefix] if prefix else []
    lines.append(ctx.t(cap, "ask_field", label=field.label))
    if field.type in (FieldType.choice, FieldType.boolean):
        lines.append(common.CHOOSE_HINT)
    if not field.required:
        lines.append(common.OPTIONAL_HINT)
    ctx.reply("\n".join(lines), _field_buttons(cap, field))


async def _accept(
    ctx: Ctx,
    host: FormHost,
    cap: Any,
    fields: list[FieldDef],
    session: dict[str, Any],
    field: FieldDef,
    raw: Any,
) -> None:
    cleaned, errors = validate_record([field], {field.key: raw})
    if errors:
        ctx.reply(
            ctx.t(cap, "invalid_answer", label=field.label, error=errors[0]),
            _field_buttons(cap, field),
        )
        return
    session["vars"]["answers"][field.key] = cleaned[field.key]
    await _advance(ctx, host, cap, fields, session)


async def _advance(
    ctx: Ctx,
    host: FormHost,
    cap: Any,
    fields: list[FieldDef],
    session: dict[str, Any],
    prefix: str | None = None,
) -> None:
    """Ask the first unanswered field, or finish."""
    answers: dict[str, Any] = session["vars"]["answers"]
    for field in fields:
        if field.key not in answers:
            session["vars"]["field"] = field.key
            await ctx.set_session(session)
            _ask(ctx, cap, field, prefix=prefix)
            return
    values, errors = validate_record(fields, answers)
    if errors:  # stored answers no longer valid for the current spec: ask those again
        for field in fields:
            _, field_errors = validate_record([field], {field.key: answers.get(field.key)})
            if field_errors:
                answers.pop(field.key, None)
        await _advance(ctx, host, cap, fields, session, prefix=prefix)
        return
    await ctx.clear_session()
    await host.on_form_done(ctx, cap, values, dict(session["vars"].get("data") or {}))
