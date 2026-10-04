"""Prompt files. ``SYSTEM`` is identical across every call (role + catalog), so it caches."""

from functools import cache
from pathlib import Path

from app.botspec.text_keys import TEXT_KEYS

_DIR = Path(__file__).resolve().parent


@cache
def load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def _text_keys_section() -> str:
    lines = ["## Text override keys (key: allowed placeholders)"]
    for cap_type in sorted(TEXT_KEYS):
        entries = ", ".join(
            f"{key}{{{','.join(sorted(ph))}}}" if ph else key
            for key, ph in sorted(TEXT_KEYS[cap_type].items())
        )
        lines.append(f"- {cap_type}: {entries}")
    return "\n".join(lines)


@cache
def system_prompt() -> str:
    return "\n\n".join([load("system"), load("catalog"), _text_keys_section()]) + "\n"


TASKS = (
    "understand",
    "build",
    "testgen",
    "repair",
    "sample_data",
    # modify (a change to a live bot)
    "triage",
    "understand_change",
    "build_change",
    "testgen_change",
    "repair_change",
)
