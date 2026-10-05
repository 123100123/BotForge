"""Load a hand-written BotSpec file as the active revision of a bot.

Usage (from backend/, with DATABASE_URL set):
    uv run python scripts/load_spec.py --spec ../examples/workshop.botspec.json --owner-id <uuid> \
        [--bot-id <uuid>] [--name "..."] [--sample-data scripts/workshop.sample_data.json]

The owner is an existing account: --owner-id takes its user id (the "id" of GET /me), --owner-email
its email instead (create accounts with scripts/create_user.py). Creates the bot when --bot-id is
omitted, then creates a revision (parented on the bot's current active revision) and activates it.
Used before the agent exists, and handy for demos.

--sample-data takes a JSON file holding a list of SeedRecord objects (the same shape as a scenario's
"seed"; ``scripts/workshop.sample_data.json`` fits the workshop spec). Like the agent flow, the records
are stored with the revision and loaded into the bot's simulator sandbox, replacing what was there.
They are never copied to live data.
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import TypeAdapter, ValidationError

from app.botspec.validate import check_spec, has_errors
from app.db.models import Bot, User
from app.db.session import dispose_engine, get_sessionmaker
from app.revisions.service import InvalidSampleData, activate, create_draft, load_sample_data
from app.security.accounts import get_user_by_email
from app.testing.scenario import SeedRecord


async def load_spec(
    spec_path: Path,
    owner: uuid.UUID | str,
    bot_id: uuid.UUID | None,
    name: str | None,
    sample_data_path: Path | None = None,
) -> int:
    """Load the spec for the account ``owner`` (a user id, or an account email). Returns the exit code."""
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    issues = check_spec(data)
    for issue in issues:
        print(f"{issue.severity}: {'/'.join(issue.path)}: [{issue.code}] {issue.message}", file=sys.stderr)
    if has_errors(issues):
        print("spec has errors; nothing was loaded", file=sys.stderr)
        return 1

    sample_data: list[SeedRecord] = []
    if sample_data_path is not None:
        try:
            sample_data = TypeAdapter(list[SeedRecord]).validate_json(
                sample_data_path.read_text(encoding="utf-8")
            )
        except ValidationError as exc:
            print(f"{sample_data_path} is not a list of SeedRecord objects:\n{exc}", file=sys.stderr)
            return 1

    try:
        async with get_sessionmaker()() as session:
            user = (
                await session.get(User, owner)
                if isinstance(owner, uuid.UUID)
                else await get_user_by_email(session, owner)
            )
            if user is None:
                print("no such account; create one with scripts/create_user.py", file=sys.stderr)
                return 1
            owner_id = user.id
            if bot_id is None:
                bot = Bot(owner_id=owner_id, name=name or data["bot"]["name"], status="draft")
                session.add(bot)
                await session.flush()
            else:
                bot = await session.get(Bot, bot_id)
                if bot is None or bot.owner_id != owner_id:
                    print("bot not found for this owner", file=sys.stderr)
                    return 1
                if name:
                    bot.name = name
            revision = await create_draft(
                session,
                bot.id,
                spec=data,
                change_request=f"loaded from {spec_path.name}",
                sample_data=sample_data or None,
                parent_id=bot.active_revision_id,
            )
            loaded = 0
            if sample_data:
                try:
                    loaded = len(await load_sample_data(session, bot.id, revision, datetime.now(UTC)))
                except InvalidSampleData as exc:
                    await session.rollback()
                    print(f"invalid sample data; nothing was loaded: {exc.message}", file=sys.stderr)
                    return 1
            await activate(session, revision.id)
            await session.commit()
            print(f"bot {bot.id}  revision {revision.id} (number {revision.number}) is active")
            if sample_data:
                print(f"{loaded} sample records loaded into the sandbox")
    finally:
        await dispose_engine()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--spec", required=True, type=Path)
    owner = parser.add_mutually_exclusive_group(required=True)
    owner.add_argument("--owner-id", type=uuid.UUID, help="the owner's user id")
    owner.add_argument("--owner-email", help="the owner's account email")
    parser.add_argument("--bot-id", type=uuid.UUID)
    parser.add_argument("--name")
    parser.add_argument("--sample-data", type=Path, help="JSON file: a list of SeedRecord objects")
    args = parser.parse_args()
    owner = args.owner_id if args.owner_id is not None else args.owner_email
    return asyncio.run(load_spec(args.spec, owner, args.bot_id, args.name, args.sample_data))


if __name__ == "__main__":
    raise SystemExit(main())
