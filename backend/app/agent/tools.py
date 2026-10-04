"""Deterministic tools the model uses inside the build and repair loops (roadmap: "Agent Tools").

Every tool works on the run's in-memory ``RunState`` only: no database, network, clock, other bots,
live records or tokens. Results are compact JSON (issue lists, failing step + message + a short
transcript tail), never full dumps. Invalid tool input comes back as issues so the model can
correct itself. Each call emits ``tool_call`` / ``tool_result`` events with short Persian summaries.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import ValidationError

from app.agent import events as ev
from app.agent.checks import check_acceptance, fa, requirement_ids, validation_messages
from app.agent.context import Emit
from app.agent.llm import ToolDef, ToolOutcome
from app.agent.modify import supersede_refusal, target_ids
from app.agent.state import RunState, ScenarioFix, SupersededScenario
from app.botspec.diff import diff_specs
from app.botspec.models import BotSpec
from app.botspec.outline import spec_outline
from app.botspec.patch import ROOT, PatchError, PatchOp, apply_patch, child
from app.botspec.validate import SpecIssue, check_spec, parse_spec, validate_spec
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario

Loop = Literal["build", "repair"]
MAX_ISSUES = 25
TRANSCRIPT_TAIL = 8
TEXT_CLIP = 300


def _issue(i: SpecIssue) -> dict[str, Any]:
    return {"path": "/".join(i.path), "code": i.code, "message": i.message, "severity": i.severity}


def compact_issues(issues: list[SpecIssue]) -> list[dict[str, Any]]:
    ordered = sorted(issues, key=lambda i: i.severity != "error")  # errors first
    return [_issue(i) for i in ordered[:MAX_ISSUES]]


def _errors(issues: list[SpecIssue]) -> list[SpecIssue]:
    return [i for i in issues if i.severity == "error"]


def _spec_schema() -> dict[str, Any]:
    schema = BotSpec.model_json_schema()
    defs = schema.pop("$defs", {})
    return {
        "type": "object",
        "properties": {"spec": schema},
        "required": ["spec"],
        "additionalProperties": False,
        "$defs": defs,
    }


def _scenario_schema() -> dict[str, Any]:
    schema = Scenario.model_json_schema()
    defs = schema.pop("$defs", {})
    return {
        "type": "object",
        "properties": {
            "scenario_id": {"type": "string"},
            "scenario": schema,
            "reason": {"type": "string", "description": "Persian, one sentence, shown to the owner"},
        },
        "required": ["scenario_id", "scenario", "reason"],
        "additionalProperties": False,
        "$defs": defs,
    }


_EMPTY = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

TOOL_DEFS: dict[str, ToolDef] = {
    "set_spec": ToolDef(
        "set_spec",
        "Replace the whole draft BotSpec. Runs schema and semantic validation and returns "
        "{ok, issues[]}. A schema-invalid spec is not stored; a schema-valid spec with semantic "
        "errors is stored so you can patch it.",
        _spec_schema(),
    ),
    "apply_spec_patch": ToolDef(
        "apply_spec_patch",
        "Apply key-addressed patch ops atomically to the draft and validate the result. Returns "
        "{ok, issues[], changed_paths[]} or {ok:false, error}. If the draft currently has several "
        "errors, fix them all in one call (the whole result must validate) or use set_spec.",
        {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["set", "add", "remove"]},
                            "path": {"type": "array", "items": {"type": "string"}},
                            "value": {"description": "set: new value; add: the new object with its key"},
                            "before": {"type": ["string", "null"]},
                        },
                        "required": ["op", "path"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["ops"],
            "additionalProperties": False,
        },
    ),
    "validate_spec": ToolDef(
        "validate_spec", "Re-run validation on the current draft. Returns {issues[]}.", _EMPTY, strict=True
    ),
    "get_spec": ToolDef(
        "get_spec",
        "Read the current draft, or the sub-tree at a key-addressed path (e.g. "
        '["capabilities","book_workshop","capacity"]). An empty path returns the whole spec.',
        {
            "type": "object",
            "properties": {"path": {"type": "array", "items": {"type": "string"}}},
            "required": ["path"],
            "additionalProperties": False,
        },
        strict=True,
    ),
    "run_tests": ToolDef(
        "run_tests",
        "Run every scenario (derived from the current draft, plus acceptance) in memory. Returns "
        "{total, passed, failed[{id, title, failed_step, message}]}.",
        _EMPTY,
        strict=True,
    ),
    "get_failure": ToolDef(
        "get_failure",
        "Explain one failing scenario from the last test run: the scenario, the failing step, its "
        "message, and the last lines of the bot transcript.",
        {
            "type": "object",
            "properties": {"scenario_id": {"type": "string"}},
            "required": ["scenario_id"],
            "additionalProperties": False,
        },
        strict=True,
    ),
    "fix_scenario": ToolDef(
        "fix_scenario",
        "Replace an acceptance scenario written in THIS run that misstates the owner's requirement. "
        "Refused for derived scenarios and for carried-forward scenarios. Give a one-sentence Persian "
        "reason; it is shown to the owner. Never use it to make a correct test pass a wrong spec.",
        _scenario_schema(),
    ),
    "supersede_scenario": ToolDef(
        "supersede_scenario",
        "Retire a CARRIED-FORWARD acceptance scenario that checks a requirement this change "
        "modifies or removes (its requirement_ids must intersect the changed or removed ids). It is "
        "removed from the test set and listed on the owner's review card with your reason. Refused "
        "for derived scenarios, for scenarios written in this run, and for scenarios whose "
        "requirements did not change: those failures are regressions to fix in the spec.",
        {
            "type": "object",
            "properties": {
                "scenario_id": {"type": "string"},
                "reason": {"type": "string", "description": "Persian, one sentence, shown to the owner"},
            },
            "required": ["scenario_id", "reason"],
            "additionalProperties": False,
        },
        strict=True,
    ),
    "finish": ToolDef(
        "finish",
        "Declare this phase complete. Accepted only when the draft has no validation errors "
        "(and, when changing a live bot, no data-compatibility errors).",
        {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "one short English sentence"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        strict=True,
    ),
}

BUILD_TOOLS = ("set_spec", "apply_spec_patch", "validate_spec", "get_spec", "finish")
BUILD_PATCH_TOOLS = ("apply_spec_patch", "validate_spec", "get_spec", "finish")  # modify: no set_spec
REPAIR_TOOLS = (
    "apply_spec_patch",
    "validate_spec",
    "get_spec",
    "run_tests",
    "get_failure",
    "fix_scenario",
    "finish",
)
MODIFY_REPAIR_TOOLS = (
    "apply_spec_patch",
    "validate_spec",
    "get_spec",
    "run_tests",
    "get_failure",
    "fix_scenario",
    "supersede_scenario",
    "finish",
)

CompatCheck = Callable[[BotSpec], list[SpecIssue]]


SUMMARY_LINES = 4


def change_summary(before: BotSpec, after: BotSpec) -> str:
    """Owner-readable ``tool_result`` summary of a spec edit: the diff's Persian lines."""
    labels = [c.label_fa for c in diff_specs(before, after)]
    if not labels:
        return "تغییری در مشخصات ایجاد نشد"
    text = "؛ ".join(labels[:SUMMARY_LINES])
    if len(labels) > SUMMARY_LINES:
        text += f" و {fa(len(labels) - SUMMARY_LINES)} مورد دیگر"
    return text


def _call_summary(name: str, args: dict[str, Any]) -> str:
    if name == "set_spec":
        return "نوشتن مشخصات کامل ربات"
    if name == "apply_spec_patch":
        ops = args.get("ops") if isinstance(args.get("ops"), list) else []
        return f"اعمال {fa(len(ops))} تغییر روی مشخصات"
    if name == "validate_spec":
        return "اعتبارسنجی مشخصات"
    if name == "get_spec":
        path = args.get("path") if isinstance(args.get("path"), list) else []
        return "خواندن مشخصات" + (f" ({'/'.join(map(str, path))})" if path else "")
    if name == "run_tests":
        return "اجرای همهٔ آزمون‌ها"
    if name == "get_failure":
        return f"بررسی آزمون ناموفق «{args.get('scenario_id', '')}»"
    if name == "fix_scenario":
        return f"اصلاح آزمون «{args.get('scenario_id', '')}»"
    if name == "supersede_scenario":
        return f"کنار گذاشتن آزمون قبلی «{args.get('scenario_id', '')}»"
    if name == "finish":
        return "اعلام پایان مرحله"
    return name


class AgentTools:
    """Tool handler bound to one run's state and one loop."""

    def __init__(
        self,
        state: RunState,
        *,
        loop: Loop,
        emit: Emit,
        names: tuple[str, ...],
        compat: CompatCheck | None = None,
    ) -> None:
        self.state = state
        self.loop = loop
        self.emit = emit
        self.names = names
        self.compat = compat  # modify: data-compatibility check against the live spec
        self.finished_summary: str | None = None
        self.spec_changes = 0

    def compat_errors(self) -> list[SpecIssue]:
        if self.compat is None or self.state.draft_spec is None:
            return []
        return _errors(self.compat(self.state.draft_spec))

    def defs(self) -> list[ToolDef]:
        return [TOOL_DEFS[n] for n in self.names]

    async def handle(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        await self.emit(ev.tool_call(self.loop, name, _call_summary(name, args)))
        if name not in self.names:
            outcome = ToolOutcome(
                {"ok": False, "error": f"tool '{name}' is not available here"}, is_error=True
            )
            summary = "ابزار در این مرحله در دسترس نیست"
        else:
            outcome, summary = await getattr(self, f"_t_{name}")(args)
        ok = not outcome.is_error
        if ok and isinstance(outcome.content, dict):
            ok = bool(outcome.content.get("ok", True))
        await self.emit(ev.tool_result(name, ok, summary))
        return outcome

    async def _spec_changed(self) -> None:
        self.spec_changes += 1
        assert self.state.draft_spec is not None
        await self.emit(ev.spec_updated(spec_outline(self.state.draft_spec)))

    def _issue_summary(self, issues: list[SpecIssue]) -> str:
        errors = _errors(issues)
        if errors:
            return f"{fa(len(errors))} خطای اعتبارسنجی"
        return "مشخصات معتبر است"

    # -- tools ---------------------------------------------------------------------------------

    async def _t_set_spec(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        raw = args.get("spec")
        if not isinstance(raw, dict):
            return ToolOutcome(
                {
                    "ok": False,
                    "issues": [
                        {
                            "path": "spec",
                            "code": "schema_missing",
                            "message": "'spec' must be the full BotSpec object",
                        }
                    ],
                },
                is_error=True,
            ), "ورودی نامعتبر"
        spec, schema_issues = parse_spec(raw)
        if spec is None:
            return ToolOutcome({"ok": False, "stored": False, "issues": compact_issues(schema_issues)}), (
                f"{fa(len(schema_issues))} خطای ساختاری؛ ذخیره نشد"
            )
        issues = validate_spec(spec)
        before = self.state.draft_spec
        self.state.draft_spec = spec
        await self._spec_changed()
        ok = not _errors(issues)
        if before is None:
            summary = f"مشخصات کامل ربات نوشته شد؛ {self._issue_summary(issues)}"
        else:
            summary = f"{change_summary(before, spec)}؛ {self._issue_summary(issues)}"
        return ToolOutcome({"ok": ok, "stored": True, "issues": compact_issues(issues)}), summary

    async def _t_apply_spec_patch(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        if self.state.draft_spec is None:
            return ToolOutcome({"ok": False, "error": "there is no draft yet; call set_spec first"}, True), (
                "هنوز پیش‌نویسی وجود ندارد"
            )
        raw_ops = args.get("ops")
        if not isinstance(raw_ops, list) or not raw_ops:
            return ToolOutcome({"ok": False, "error": "'ops' must be a non-empty list of patch ops"}, True), (
                "ورودی نامعتبر"
            )
        try:
            ops = [PatchOp.model_validate(o) for o in raw_ops]
        except ValidationError as exc:
            return ToolOutcome(
                {"ok": False, "error": {"code": "invalid_op", "issues": validation_messages(exc)}}, True
            ), "تغییر نامعتبر"
        try:
            new = apply_patch(self.state.draft_spec, ops)
        except PatchError as exc:
            detail = exc.to_dict()
            detail["issues"] = detail["issues"][:MAX_ISSUES]
            if _errors(validate_spec(self.state.draft_spec)):
                detail["hint"] = (
                    "the current draft already has errors; fix all of them in one call or use set_spec"
                )
            return ToolOutcome({"ok": False, "error": detail}), "تغییر رد شد"
        before = self.state.draft_spec
        self.state.draft_spec = new
        if self.state.kind == "modify":
            self.state.patch_ops.extend(ops)
        await self._spec_changed()
        issues = validate_spec(new)
        content: dict[str, Any] = {
            "ok": True,
            "issues": compact_issues(issues),
            "changed_paths": ["/".join(o.path) for o in ops],
        }
        compat = self.compat_errors()
        if compat:
            content["compat_errors"] = compact_issues(compat)
        return ToolOutcome(content), change_summary(before, new)

    async def _t_validate_spec(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        if self.state.draft_spec is None:
            return ToolOutcome({"ok": False, "error": "there is no draft yet; call set_spec first"}, True), (
                "هنوز پیش‌نویسی وجود ندارد"
            )
        issues = validate_spec(self.state.draft_spec)
        return ToolOutcome(
            {"ok": not _errors(issues), "issues": compact_issues(issues)}
        ), self._issue_summary(issues)

    async def _t_get_spec(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        if self.state.draft_spec is None:
            return ToolOutcome(
                {"ok": False, "error": "there is no draft yet"}, True
            ), "هنوز پیش‌نویسی وجود ندارد"
        node: Any = self.state.draft_spec.model_dump(mode="json")
        shape = ROOT
        path = args.get("path") or []
        if not isinstance(path, list):
            return ToolOutcome(
                {"ok": False, "error": "'path' must be a list of strings"}, True
            ), "مسیر نامعتبر"
        for seg in path:
            try:
                node, shape = child(shape, node, str(seg))
            except (LookupError, TypeError) as exc:
                return ToolOutcome(
                    {"ok": False, "error": f"{'/'.join(map(str, path))}: {exc}"}
                ), "مسیر پیدا نشد"
        return ToolOutcome({"ok": True, "path": path, "value": node}), "مشخصات خوانده شد"

    async def run_all(self) -> dict[str, Any]:
        """Re-derive scenarios from the draft and run everything; updates state.test_report."""
        assert self.state.draft_spec is not None
        self.state.derived = derive_scenarios(self.state.draft_spec)
        scenarios = self.state.all_scenarios()
        report = await run_scenarios(self.state.draft_spec, scenarios)
        self.state.test_report = report
        titles = {s.id: s.title for s in scenarios}
        failed = []
        for r in report.results:
            if r.passed:
                continue
            step = next((s for s in r.steps if not s.passed), None)
            failed.append(
                {
                    "id": r.scenario_id,
                    "title": titles.get(r.scenario_id, r.scenario_id),
                    "failed_step": r.failed_step,
                    "message": step.message if step else None,
                }
            )
        return {"total": report.total, "passed": report.passed, "failed": failed}

    async def _t_run_tests(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        if self.state.draft_spec is None:
            return ToolOutcome(
                {"ok": False, "error": "there is no draft yet"}, True
            ), "هنوز پیش‌نویسی وجود ندارد"
        result = await self.run_all()
        return ToolOutcome(
            {"ok": True, **result}
        ), f"{fa(result['passed'])} از {fa(result['total'])} آزمون موفق"

    async def _t_get_failure(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        sid = args.get("scenario_id")
        report = self.state.test_report
        result = next((r for r in report.results if r.scenario_id == sid), None) if report else None
        scenario = next((s for s in self.state.all_scenarios() if s.id == sid), None)
        if result is None or scenario is None:
            return ToolOutcome(
                {"ok": False, "error": f"no result for scenario '{sid}' in the last test run"}
            ), ("آزمون پیدا نشد")
        if result.passed:
            return ToolOutcome({"ok": True, "passed": True}), "این آزمون موفق است"
        step = next((s for s in result.steps if not s.passed), None)
        tail = [
            {
                "actor": t.actor,
                "dir": t.direction,
                "text": t.text[:TEXT_CLIP],
                **({"buttons": t.buttons[:8]} if t.buttons else {}),
            }
            for t in result.transcript[-TRANSCRIPT_TAIL:]
        ]
        content = {
            "ok": True,
            "scenario": scenario.model_dump(mode="json", exclude_defaults=True),
            "source": scenario.source,
            "fixable": scenario.id in self.state.new_scenario_ids,
            "failed_step": result.failed_step,
            "message": step.message if step else None,
            "steps": [s.narrative for s in result.steps],
            "transcript_tail": tail,
        }
        return ToolOutcome(content), "جزئیات خطا خوانده شد"

    async def _t_fix_scenario(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        sid = args.get("scenario_id")
        reason = (args.get("reason") or "").strip()
        existing = next((s for s in self.state.all_scenarios() if s.id == sid), None)
        if existing is None:
            return ToolOutcome({"ok": False, "error": f"unknown scenario '{sid}'"}), "آزمون پیدا نشد"
        if existing.source == "derived":
            return ToolOutcome(
                {
                    "ok": False,
                    "refused": True,
                    "error": "derived scenarios come from the spec and cannot be edited; fix the spec",
                }
            ), "اصلاح آزمون مشتق‌شده مجاز نیست"
        if sid not in self.state.new_scenario_ids:
            return ToolOutcome(
                {
                    "ok": False,
                    "refused": True,
                    "error": "only acceptance scenarios written in this run can be fixed (carried forward)",
                }
            ), "اصلاح آزمون قبلی مجاز نیست"
        if not reason:
            return ToolOutcome(
                {"ok": False, "error": "a Persian 'reason' is required"}
            ), "دلیل اصلاح لازم است"
        assert self.state.draft_spec is not None
        raw = args.get("scenario")
        if isinstance(raw, dict):
            raw = {**raw, "id": sid}
        fixed, problems = check_acceptance(
            raw, req_ids=requirement_ids(self.state.requirements), spec=self.state.draft_spec
        )
        if fixed is not None and self.state.kind == "modify":
            targets = target_ids(self.state.delta)
            if not set(fixed.requirement_ids) & targets:
                fixed, problems = (
                    None,
                    [f"requirement_ids must include an added or changed requirement ({sorted(targets)})"],
                )
        if fixed is None:
            return ToolOutcome({"ok": False, "issues": problems}), "آزمون اصلاح‌شده نامعتبر است"
        self.state.scenarios = [fixed if s.id == sid else s for s in self.state.scenarios]
        self.state.scenario_fixes.append(ScenarioFix(scenario_id=sid, reason=reason))  # type: ignore[arg-type]
        await self.emit(ev.agent_message(f"آزمون «{existing.title}» را اصلاح کردم: {reason}"))
        return ToolOutcome({"ok": True}), "آزمون اصلاح شد"

    async def _t_supersede_scenario(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        """The supersede guard (roadmap "Modification Workflow" item 6); see modify.supersede_refusal."""
        sid = args.get("scenario_id")
        reason = (args.get("reason") or "").strip()
        state = self.state
        if state.kind != "modify":
            return ToolOutcome(
                {"ok": False, "refused": True, "error": "superseding exists only when changing a live bot"}
            ), "کنار گذاشتن آزمون مجاز نیست"
        scenario = next((s for s in state.all_scenarios() if s.id == sid), None)
        refusal = supersede_refusal(
            scenario, carried_ids=state.carried_ids, new_ids=state.new_scenario_ids, delta=state.delta
        )
        if refusal is not None:
            return ToolOutcome({"ok": False, "refused": True, "error": refusal}), "کنار گذاشتن آزمون رد شد"
        if not reason:
            return ToolOutcome({"ok": False, "error": "a Persian 'reason' is required"}), "دلیل لازم است"
        assert scenario is not None
        state.scenarios = [s for s in state.scenarios if s.id != sid]
        state.carried_ids = [i for i in state.carried_ids if i != sid]
        state.superseded.append(SupersededScenario(scenario=scenario, reason=reason))
        await self.emit(ev.agent_message(f"آزمون قبلی «{scenario.title}» کنار گذاشته شد: {reason}"))
        return ToolOutcome(
            {"ok": True, "remaining_carried": len(state.carried_ids)}
        ), "آزمون قبلی کنار گذاشته شد"

    async def _t_finish(self, args: dict[str, Any]) -> tuple[ToolOutcome, str]:
        if self.state.draft_spec is None:
            return ToolOutcome({"ok": False, "error": "there is no draft yet; call set_spec first"}), (
                "هنوز پیش‌نویسی وجود ندارد"
            )
        issues = check_spec(self.state.draft_spec.model_dump(mode="json"))
        errors = _errors(issues)
        if errors:
            return ToolOutcome(
                {
                    "ok": False,
                    "error": "the draft still has validation errors",
                    "issues": compact_issues(errors),
                }
            ), "هنوز خطا وجود دارد"
        compat = self.compat_errors()
        if compat:
            return ToolOutcome(
                {
                    "ok": False,
                    "error": "the draft is incompatible with the live bot's existing records; fix these "
                    "data-compatibility errors first",
                    "compat_errors": compact_issues(compat),
                }
            ), "ناسازگاری با داده‌های موجود"
        self.finished_summary = str(args.get("summary") or "")
        return ToolOutcome({"ok": True}, stop=True), "مرحله تمام شد"
