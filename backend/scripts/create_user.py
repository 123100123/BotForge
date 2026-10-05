"""Create an owner account, or reset an account's password (OPERATOR TOOL).

Usage, inside the backend container (or from backend/ with DATABASE_URL set):
    docker compose exec backend python scripts/create_user.py --email owner@example.com
    docker compose exec backend python scripts/create_user.py --email owner@example.com --reset-password
    printf '%s\\n' "$NEW_PASSWORD" | docker compose exec -T backend \\
        python scripts/create_user.py --email owner@example.com --password-stdin

The password never goes on the command line, where shell history and the process list would keep it.
It is read from a hidden prompt (asked twice), or with --password-stdin as the first line of standard
input (only the line break is removed; `docker compose exec` needs -T for piped input).

--reset-password sets a new password for an existing account and ends all of its sessions (every
browser signed in to it is signed out). Without it the account must not exist yet. The rules are the
API's: the email is normalized (trimmed, lowercased) and must be valid; the password needs 10 to 256
characters. Accounts created here work even when AUTH_ALLOW_SIGNUP is false.

Exit code 0 on success, 1 when refused (invalid email, weak password, account exists or is missing).
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import dispose_engine, get_sessionmaker
from app.security.accounts import (
    EmailTaken,
    InvalidEmail,
    UnknownAccount,
    WeakPassword,
    create_user,
    normalize_email,
    reset_password,
)
from app.security.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class Refused(Exception):
    """The request cannot be carried out; the message says why."""


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        line = sys.stdin.readline()
        if not line:
            raise Refused("no password on standard input")
        return line.removesuffix("\n").removesuffix("\r")
    if not sys.stdin.isatty():
        raise Refused("standard input is not a terminal; pipe the password in with --password-stdin")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Password again: ") != first:
        raise Refused("the two passwords differ")
    return first


async def run(email: str, password: str, reset: bool) -> str:
    """Create the account or reset its password; returns what to print. Raises ``Refused``."""
    try:
        async with get_sessionmaker()() as session:
            try:
                if reset:
                    user, ended = await reset_password(session, email, password)
                    message = f"password reset for {user.email} ({user.id}); {ended} session(s) ended"
                else:
                    user = await create_user(session, email, password)
                    message = f"created {user.email} ({user.id})"
            except InvalidEmail:
                raise Refused(f"not a valid email address: {normalize_email(email)!r}") from None
            except WeakPassword:
                raise Refused(
                    f"the password must have {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters"
                ) from None
            except EmailTaken:
                raise Refused("an account with this email exists; use --reset-password") from None
            except UnknownAccount:
                raise Refused("no account with this email; omit --reset-password to create one") from None
            await session.commit()
            return message
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,  # "--password <value>" must not pass as an abbreviation of --password-stdin
    )
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password-stdin", action="store_true", help="read the password from the first line of stdin"
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="set a new password for an existing account and end all of its sessions",
    )
    args = parser.parse_args(argv)
    try:
        password = read_password(args.password_stdin)
        print(asyncio.run(run(args.email, password, args.reset_password)))
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
