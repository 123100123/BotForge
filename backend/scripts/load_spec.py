"""Load a hand-written BotSpec file as the active revision of a bot.

Usage (from backend/, with DATABASE_URL set):
    uv run python scripts/load_spec.py --spec ../examples/workshop.botspec.json --owner-id <uuid> \
        [--bot-id <uuid>] [--name "..."]

Creates the bot when --bot-id is omitted, then creates a revision (parented on the bot's current
active revision) and activates it. Used before the agent exists, and handy for demos.
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.botspec.validate import check_spec, has_errors
from app.db.models import Bot
from app.db.session import dispose_engine, get_sessionmaker
from app.revisions.service import activate, create_draft


async def load_spec(spec_path: Path, owner_id: str, bot_id: uuid.UUID | None, name: str | None) -> int:
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    issues = check_spec(data)
    for issue in issues:
        print(f"{issue.severity}: {'/'.join(issue.path)}: [{issue.code}] {issue.message}", file=sys.stderr)
    if has_errors(issues):
        print("spec has errors; nothing was loaded", file=sys.stderr)
        return 1

    try:
        async with get_sessionmaker()() as session:
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
                parent_id=bot.active_revision_id,
            )
            await activate(session, revision.id)
            await session.commit()
            print(f"bot {bot.id}  revision {revision.id} (number {revision.number}) is active")
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
    args = parser.parse_args()
    return asyncio.run(load_spec(args.spec, args.owner_id, args.bot_id, args.name))


if __name__ == "__main__":
    raise SystemExit(main())
