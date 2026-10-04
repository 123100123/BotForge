from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "templates" / "hooks"


class HookTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config_dir)}
        for key in ("CONDUCTOR_GUARD", "CONDUCTOR_ALLOW_INHERIT", "CONDUCTOR_NUDGE_AFTER"):
            self.env.pop(key, None)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_hook(self, script: str, event: dict, **env: str) -> dict | None:
        proc = subprocess.run(
            [sys.executable, str(HOOKS / script)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env={**self.env, **env},
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def state(self, session: str) -> dict:
        path = self.config_dir / "conductor" / "state" / f"{session}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class AgentGuardTests(HookTestCase):
    def agent_event(self, **tool_input: str) -> dict:
        return {"session_id": "s1", "tool_name": "Agent", "tool_input": {"prompt": "x", **tool_input}}

    def decision(self, out: dict | None) -> str | None:
        return out and out["hookSpecificOutput"]["permissionDecision"]

    def test_named_role_without_model_is_allowed(self) -> None:
        self.assertIsNone(self.run_hook("agent_guard.py", self.agent_event(subagent_type="executor")))
        self.assertEqual(self.state("s1")["delegations"], 1)

    def test_named_role_with_model_is_denied(self) -> None:
        out = self.run_hook("agent_guard.py", self.agent_event(subagent_type="executor", model="opus"))
        self.assertEqual(self.decision(out), "deny")

    def test_adhoc_without_model_is_denied(self) -> None:
        for agent_type in ("general-purpose", ""):
            out = self.run_hook("agent_guard.py", self.agent_event(subagent_type=agent_type))
            self.assertEqual(self.decision(out), "deny", agent_type)

    def test_adhoc_with_model_is_allowed(self) -> None:
        out = self.run_hook("agent_guard.py", self.agent_event(subagent_type="general-purpose", model="sonnet"))
        self.assertIsNone(out)

    def test_self_pinned_builtin_and_allowlist(self) -> None:
        self.assertIsNone(self.run_hook("agent_guard.py", self.agent_event(subagent_type="claude-code-guide")))
        out = self.run_hook(
            "agent_guard.py", self.agent_event(subagent_type="Plan"), CONDUCTOR_ALLOW_INHERIT="Plan, other"
        )
        self.assertIsNone(out)

    def test_guard_off_and_subagent_context(self) -> None:
        event = self.agent_event(subagent_type="general-purpose")
        self.assertIsNone(self.run_hook("agent_guard.py", event, CONDUCTOR_GUARD="off"))
        self.assertIsNone(self.run_hook("agent_guard.py", {**event, "agent_id": "a1"}))

    def test_garbage_input_fails_open(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(HOOKS / "agent_guard.py")],
            input="not json",
            capture_output=True,
            text=True,
            env=self.env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")


class InlineEditNudgeTests(HookTestCase):
    def edit(self, **extra: str) -> dict | None:
        return self.run_hook("inline_edit_nudge.py", {"session_id": "s2", "tool_name": "Edit", **extra})

    def test_nudges_at_threshold_and_resets_on_delegation(self) -> None:
        outs = [self.edit() for _ in range(4)]
        self.assertEqual(outs[:3], [None, None, None])
        self.assertIn("additionalContext", outs[3]["hookSpecificOutput"])

        self.run_hook(
            "agent_guard.py",
            {"session_id": "s2", "tool_name": "Agent", "tool_input": {"subagent_type": "executor"}},
        )
        self.assertEqual(self.state("s2")["inline_edits"], 0)

    def test_custom_threshold_and_subagent_edits_ignored(self) -> None:
        out = self.run_hook(
            "inline_edit_nudge.py", {"session_id": "s3", "tool_name": "Write"}, CONDUCTOR_NUDGE_AFTER="1"
        )
        self.assertIsNotNone(out)
        self.assertIsNone(self.edit(agent_id="a1"))
        self.assertEqual(self.state("s2"), {})


class LedgerTests(HookTestCase):
    def test_appends_entry_with_usage_from_transcript(self) -> None:
        transcript = self.config_dir / "agent.jsonl"
        lines = [
            {"message": {"role": "assistant", "id": "m1", "model": "claude-sonnet-5-5",
                         "usage": {"input_tokens": 10, "output_tokens": 5}}},
            {"message": {"role": "assistant", "id": "m1", "model": "claude-sonnet-5-5",
                         "usage": {"input_tokens": 10, "output_tokens": 5}}},
            {"message": {"role": "user", "content": "hi"}},
            "not-a-dict",
        ]
        transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\nbroken{", encoding="utf-8")

        self.run_hook(
            "subagent_ledger.py",
            {"session_id": "s4", "agent_type": "executor", "agent_id": "a9",
             "agent_transcript_path": str(transcript)},
        )
        ledger = (self.config_dir / "conductor" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        entry = json.loads(ledger[-1])
        self.assertEqual(entry["agent_type"], "executor")
        usage = entry["usage_by_model"]["claude-sonnet-5-5"]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (10, 5))


class StatusLineTests(HookTestCase):
    def test_renders_with_and_without_fields(self) -> None:
        def render(payload: str) -> str:
            return subprocess.run(
                [sys.executable, str(ROOT / "templates" / "statusline.py")],
                input=payload, capture_output=True, text=True, env=self.env, timeout=30,
            ).stdout

        full = render(json.dumps({"session_id": "s5", "model": {"display_name": "Fable 5.1"},
                                  "cost": {"total_cost_usd": 1.234},
                                  "context_window": {"used_percentage": 41.6}}))
        self.assertEqual(full, "Fable 5.1 · $1.23 · ctx 42% · delegated 0")
        self.assertEqual(render("garbage"), "claude")


if __name__ == "__main__":
    unittest.main()
