"""Command line: run scenarios (and/or derived ones) against a BotSpec and print the result.

    python -m app.testing.cli --spec bot.json [--scenarios scenarios.json] [--derived]

Prints each scenario's title, pass/fail and Persian step narratives, then
"N scenarios, P passed, F failed". Exit code 1 when any scenario fails (2 on unreadable input).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.botspec.models import BotSpec
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario, TestReport


def format_report(scenarios: list[Scenario], report: TestReport) -> str:
    titles = {s.id: s.title for s in scenarios}
    lines: list[str] = []
    for result in report.results:
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"[{mark}] {titles.get(result.scenario_id, '')} ({result.scenario_id})")
        for step in result.steps:
            lines.append(f"    {'✓' if step.passed else '✗'} {step.narrative}")
            if step.message:
                lines.append(f"      ↳ {step.message}")
    lines.append(f"{report.total} scenarios, {report.passed} passed, {report.failed} failed")
    return "\n".join(lines)


def _load(args: argparse.Namespace) -> tuple[BotSpec, list[Scenario]]:
    spec = BotSpec.model_validate(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    scenarios: list[Scenario] = []
    if args.scenarios:
        raw = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
        scenarios.extend(Scenario.model_validate(item) for item in raw)
    if args.derived:
        scenarios.extend(derive_scenarios(spec))
    return spec, scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.testing.cli", description=__doc__)
    parser.add_argument("--spec", required=True, help="BotSpec JSON file")
    parser.add_argument("--scenarios", help="scenarios JSON file (a list of Scenario)")
    parser.add_argument("--derived", action="store_true", help="also run the scenarios derived from the spec")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        spec, scenarios = _load(args)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"cannot load input: {exc}", file=sys.stderr)
        return 2
    if not scenarios:
        print("nothing to run: pass --scenarios and/or --derived", file=sys.stderr)
        return 2
    report = asyncio.run(run_scenarios(spec, scenarios))
    print(format_report(scenarios, report))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
