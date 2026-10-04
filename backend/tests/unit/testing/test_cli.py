"""The command line: output shape and exit codes."""

import json
from pathlib import Path

import pytest

from app.testing.cli import main
from tests.unit.testing.helpers import EXAMPLES, scenario, seed_item, step


def test_golden_spec_with_derived_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--spec",
            str(EXAMPLES / "workshop.botspec.json"),
            "--scenarios",
            str(EXAMPLES / "workshop.scenarios.json"),
            "--derived",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[-1] == "20 scenarios, 20 passed, 0 failed"
    assert "[PASS]" in out
    assert "علی در «کارگاه عکاسی» ثبت‌نام می‌کند ← تأیید شد" in out


def test_failing_scenario_exits_one_and_shows_the_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = scenario([step("book", actor="ali", item="w1", expect="waitlisted")], seed=[seed_item()])
    path = tmp_path / "s.json"
    path.write_text(json.dumps([bad.model_dump(mode="json")], ensure_ascii=False), encoding="utf-8")
    code = main(["--spec", str(EXAMPLES / "workshop.botspec.json"), "--scenarios", str(path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "[FAIL]" in out
    assert "waitlisted" in out
    assert out.splitlines()[-1] == "1 scenarios, 0 passed, 1 failed"


def test_bad_input_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--spec", str(tmp_path / "missing.json"), "--derived"]) == 2
    assert main(["--spec", str(EXAMPLES / "workshop.botspec.json")]) == 2  # nothing to run
    capsys.readouterr()
