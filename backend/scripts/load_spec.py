"""Load a hand-written BotSpec file as the active revision of a bot.

Usage (from backend/, with DATABASE_URL set):
    uv run python scripts/load_spec.py --spec ../examples/workshop.botspec.json --owner-id <uuid> \
        [--bot-id <uuid>] [--name "..."] [--sample-data <file>]

Creates the bot when --bot-id is omitted, then creates a revision (parented on the bot's current
active revision) and activates it. Used before the agent exists, and handy for demos.

Sample data: like the agent's review phase, the revision stores ``sample_data`` and the script loads
it into the sandbox, so the simulator has something to show at once (and gets it back on reset).
``--sample-data`` takes a JSON file with either a list of seed records
(``{"ref", "collection", "values"}``) or a list of scenarios, whose ``seed`` records are used. Without
it, ``<name>.scenarios.json`` next to a ``<name>.botspec.json`` spec is used when it exists (for
``examples/workshop.botspec.json`` that is ``examples/workshop.scenarios.json``). Sample data never
reaches the live environment.
"""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.validate import check_spec, has_errors
from app.db.models import Bot
from app.db.session import dispose_engine, get_sessionmaker
from app.revisions.service import InvalidSampleData, activate, create_draft, load_sample_data
from app.testing.scenario import SeedRecord

SPEC_SUFFIX = ".botspec.json"
SCENARIOS_SUFFIX = ".scenarios.json"


class LoadError(Exception):
    """The spec cannot be loaded; the message says why."""


@dataclass
class Loaded:
    bot_id: uuid.UUID
    revision_id: uuid.UUID
    number: int
    sample_records: int


def default_sample_data_path(spec_path: Path) -> Path | None:
    """``<name>.scenarios.json`` beside a ``<name>.botspec.json`` spec, if that file exists."""
    if not spec_path.name.endswith(SPEC_SUFFIX):
        return None
    candidate = spec_path.with_name(spec_path.name[: -len(SPEC_SUFFIX)] + SCENARIOS_SUFFIX)
    return candidate if candidate.is_file() else None


def read_sample_data(path: Path) -> list[SeedRecord]:
    """Seed records from a list of seed records or from the ``seed`` lists of a list of scenarios.

    Records with the same collection and values (scenarios often seed the same item) are kept once,
    and refs are renumbered so they stay unique.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise LoadError(f"{path.name}: expected a JSON list of seed records or scenarios")
    items: list[Any] = []
    for entry in raw:
        if isinstance(entry, dict) and "seed" in entry:
            items.extend(entry["seed"] or [])
        else:
            items.append(entry)
    seeds: list[SeedRecord] = []
    seen: set[str] = set()
    for item in items:
        try:
            seed = SeedRecord.model_validate(item)
        except ValidationError as exc:
            raise LoadError(f"{path.name}: invalid seed record: {exc}") from None
        identity = json.dumps(
            [seed.collection, [[kv.key, kv.value] for kv in seed.values]], ensure_ascii=False
        )
        if identity in seen:
            continue
        seen.add(identity)
        seeds.append(seed.model_copy(update={"ref": f"s{len(seeds) + 1}"}))
    return seeds


async def load_into(
    session: AsyncSession,
    data: dict[str, Any],
    *,
    owner_id: str,
    bot_id: uuid.UUID | None,
    name: str | None,
    change_request: str,
    sample_data: list[SeedRecord],
    now: datetime | None = None,
) -> Loaded:
    """Create (or reuse) the bot, write and activate the revision, load its sample data into the
    sandbox. The caller commits; nothing is written when ``LoadError`` is raised and rolled back."""
    if bot_id is None:
        bot = Bot(owner_id=owner_id, name=name or data["bot"]["name"], status="draft")
        session.add(bot)
        await session.flush()
    else:
        found = await session.get(Bot, bot_id)
        if found is None or found.owner_id != owner_id:
            raise LoadError("bot not found for this owner")
        bot = found
        if name:
            bot.name = name
    revision = await create_draft(
        session,
        bot.id,
        spec=data,
        change_request=change_request,
        sample_data=sample_data,
        parent_id=bot.active_revision_id,
    )
    try:
        loaded = await load_sample_data(session, bot.id, revision, now or datetime.now(UTC))
    except InvalidSampleData as exc:
        raise LoadError(f"sample data does not fit the spec: {exc.message}") from None
    await activate(session, revision.id)
    return Loaded(bot.id, revision.id, revision.number, len(loaded))


async def load_spec(
    spec_path: Path,
    owner_id: str,
    bot_id: uuid.UUID | None,
    name: str | None,
    sample_data_path: Path | None = None,
) -> int:
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    issues = check_spec(data)
    for issue in issues:
        print(f"{issue.severity}: {'/'.join(issue.path)}: [{issue.code}] {issue.message}", file=sys.stderr)
    if has_errors(issues):
        print("spec has errors; nothing was loaded", file=sys.stderr)
        return 1

    source = sample_data_path or default_sample_data_path(spec_path)
    try:
        sample_data = read_sample_data(source) if source else []
    except LoadError as exc:
        print(f"{exc}; nothing was loaded", file=sys.stderr)
        return 1

    try:
        async with get_sessionmaker()() as session:
            try:
                result = await load_into(
                    session,
                    data,
                    owner_id=owner_id,
                    bot_id=bot_id,
                    name=name,
                    change_request=f"loaded from {spec_path.name}",
                    sample_data=sample_data,
                )
            except LoadError as exc:
                await session.rollback()
                print(f"{exc}; nothing was loaded", file=sys.stderr)
                return 1
            await session.commit()
            print(f"bot {result.bot_id}  revision {result.revision_id} (number {result.number}) is active")
            where = f" from {source.name}" if source else ""
            print(f"{result.sample_records} sample records loaded into the sandbox{where}")
    finally:
        await dispose_engine()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--bot-id", type=uuid.UUID)
    parser.add_argument("--name")
    parser.add_argument(
        "--sample-data",
        type=Path,
        help="JSON list of seed records or scenarios (default: <name>.scenarios.json beside the spec)",
    )
    args = parser.parse_args()
    return asyncio.run(load_spec(args.spec, args.owner_id, args.bot_id, args.name, args.sample_data))


if __name__ == "__main__":
    raise SystemExit(main())
