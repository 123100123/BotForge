from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    # role: (model, effort)
    "scout": ("sonnet", "medium"),
    "Explore": ("sonnet", "medium"),
    "mech-executor": ("sonnet", "medium"),
    "executor": ("sonnet", "high"),
    "senior-executor": ("opus", "high"),
    "security-executor": ("opus", "max"),
    "integrator": ("sonnet", "high"),
    "verifier": ("opus", "medium"),
}
ALLOWED_EFFORTS = {"medium", "high", "xhigh", "max"}
MODEL_WORDS = re.compile(r"\b(fable|opus|sonnet|haiku)\b", re.IGNORECASE)


def frontmatter(role: str) -> str:
    text = (ROOT / "templates" / "agents" / f"{role}.md").read_text(encoding="utf-8")
    return text.split("---", 2)[1]


def policy() -> str:
    return (ROOT / "templates" / "claude-md.orchestration.md").read_text(encoding="utf-8")


class PolicyContractTests(unittest.TestCase):
    def test_version_stamp_matches(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(f"<!-- conductor v{version} -->", policy())
        self.assertIn(f"## v{version}", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_agent_files_match_role_set(self) -> None:
        files = {p.stem for p in (ROOT / "templates" / "agents").glob("*.md")}
        self.assertEqual(files, set(ROLES))

    def test_every_role_owns_its_model_and_effort(self) -> None:
        for role, (model, effort) in ROLES.items():
            fm = frontmatter(role)
            self.assertRegex(fm, rf"(?m)^name:\s*{re.escape(role)}\s*$", role)
            self.assertRegex(fm, rf"(?m)^model:\s*{model}\s*$", role)
            self.assertRegex(fm, rf"(?m)^effort:\s*{effort}\s*$", role)
            self.assertIn(effort, ALLOWED_EFFORTS, role)

    def test_no_role_binds_to_the_frontier_model(self) -> None:
        for role in ROLES:
            self.assertNotRegex(frontmatter(role), r"(?mi)^model:\s*(fable|best|inherit)", role)

    def test_roles_are_leaves(self) -> None:
        for role in ROLES:
            fm = frontmatter(role)
            leaf_by_allowlist = re.search(r"(?m)^tools:\s*Read, Glob, Grep\s*$", fm)
            leaf_by_denylist = re.search(r"(?m)^disallowedTools:.*\bAgent\b.*\bWorkflow\b", fm)
            self.assertTrue(leaf_by_allowlist or leaf_by_denylist, role)

    def test_verifier_cannot_write(self) -> None:
        fm = frontmatter("verifier")
        for tool in ("Write", "Edit", "NotebookEdit"):
            self.assertRegex(fm, rf"(?m)^disallowedTools:.*\b{tool}\b")

    def test_policy_names_roles_not_models(self) -> None:
        text = policy()
        for role in ROLES:
            self.assertIn(f"`{role}`", text, role)
        self.assertIsNone(MODEL_WORDS.search(text), "policy prose must stay model-free")
        self.assertIn("omit the `model` argument", text)

    def test_policy_markers(self) -> None:
        text = policy()
        self.assertTrue(text.startswith("<!-- conductor:begin -->"))
        self.assertTrue(text.rstrip().endswith("<!-- conductor:end -->"))

    def test_settings_snippet(self) -> None:
        settings = json.loads((ROOT / "templates" / "settings.snippet.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["model"], "best")
        self.assertNotIn("fable", [m.lower() for m in settings["fallbackModel"]])
        for model_id, conf in settings["modelSettings"].items():
            self.assertIn(conf["effortLevel"], ALLOWED_EFFORTS, model_id)
        self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL", settings.get("env", {}))
        hook_scripts = json.dumps(settings["hooks"])
        for script in ("agent_guard.py", "inline_edit_nudge.py", "subagent_ledger.py"):
            self.assertIn(script, hook_scripts)
            self.assertTrue((ROOT / "templates" / "hooks" / script).exists(), script)

    def test_hook_role_list_matches(self) -> None:
        common = (ROOT / "templates" / "hooks" / "conductor_common.py").read_text(encoding="utf-8")
        for role in ROLES:
            self.assertIn(f'"{role}"', common, role)

    def test_workflow_routes_through_roles(self) -> None:
        script = (ROOT / "templates" / "workflows" / "execute-plan.js").read_text(encoding="utf-8")
        self.assertTrue(script.startswith("export const meta = {"))
        self.assertNotRegex(script, r"\bmodel\s*:", "workflow must let role definitions own models")
        for forbidden in ("Date.now(", "Math.random(", "new Date()"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
