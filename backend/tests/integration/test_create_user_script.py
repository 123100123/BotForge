"""scripts/create_user.py: create an account or reset its password. Needs a database.

The command-line path runs the script as an operator would (a subprocess with DATABASE_URL set);
refusals and the interactive prompt are checked in process.
"""

import importlib.util
import io
import os
import subprocess
import sys
import uuid
from types import ModuleType

import pytest
from sqlalchemy import func, select

from app.db.models import AuthSession, User
from app.security.accounts import authenticate, create_user
from app.security.sessions import create_session
from tests.integration.helpers import BACKEND, SessionFactory

PASSWORD = "first password 123"


def _load_script() -> ModuleType:
    path = BACKEND / "scripts" / "create_user.py"
    spec = importlib.util.spec_from_file_location("create_user_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def new_email() -> str:
    return f"operator-{uuid.uuid4().hex[:12]}@example.com"


def run_script(migrated_db: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/create_user.py", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": migrated_db},
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def in_process(monkeypatch: pytest.MonkeyPatch, session_factory: SessionFactory) -> ModuleType:
    async def no_dispose() -> None:
        return None

    monkeypatch.setattr(script, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(script, "dispose_engine", no_dispose)
    return script


async def count_users(session_factory: SessionFactory, email: str) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(User).where(User.email == email)
        return (await session.execute(stmt)).scalar_one()


async def test_creates_an_account_with_the_password_from_stdin(
    migrated_db: str, session_factory: SessionFactory
) -> None:
    email = new_email()
    password = "  spaces count too  "
    result = run_script(
        migrated_db, "--email", f" {email.upper()} ", "--password-stdin", stdin=password + "\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"created {email} (")
    assert password.strip() not in result.stdout + result.stderr
    async with session_factory() as session:
        assert await authenticate(session, email, password) is not None
        assert await authenticate(session, email, password.strip()) is None  # nothing was trimmed

    again = run_script(migrated_db, "--email", email, "--password-stdin", stdin="another password 1\n")
    assert again.returncode == 1 and "use --reset-password" in again.stderr
    assert await count_users(session_factory, email) == 1


async def test_reset_password_ends_every_session(migrated_db: str, session_factory: SessionFactory) -> None:
    email = new_email()
    async with session_factory() as session:
        user = await create_user(session, email, PASSWORD)
        for _ in range(2):
            await create_session(session, user.id)
        await session.commit()

    result = run_script(
        migrated_db, "--email", email, "--reset-password", "--password-stdin", stdin="second password 456\r\n"
    )
    assert result.returncode == 0, result.stderr
    assert f"password reset for {email}" in result.stdout and "2 session(s) ended" in result.stdout
    async with session_factory() as session:
        left = select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)
        assert (await session.execute(left)).scalar_one() == 0
        assert await authenticate(session, email, PASSWORD) is None
        assert await authenticate(session, email, "second password 456") is not None


async def test_the_password_is_never_a_command_line_argument(
    migrated_db: str, session_factory: SessionFactory
) -> None:
    email = new_email()
    for flag in ("--password", "--pass", "--password-std"):  # no option or abbreviation takes a value
        result = run_script(migrated_db, "--email", email, flag, "secret password 1", stdin="")
        assert result.returncode == 2, (flag, result.stdout, result.stderr)
    empty = run_script(migrated_db, "--email", email, "--password-stdin", stdin="")
    assert empty.returncode == 1 and "no password on standard input" in empty.stderr
    assert await count_users(session_factory, email) == 0


async def test_refusals_change_nothing(in_process: ModuleType, session_factory: SessionFactory) -> None:
    email = new_email()
    with pytest.raises(in_process.Refused, match="10 to 256 characters"):
        await in_process.run(email, "short", False)
    with pytest.raises(in_process.Refused, match="not a valid email"):
        await in_process.run("not-an-email", PASSWORD, False)
    with pytest.raises(in_process.Refused, match="no account with this email"):
        await in_process.run(email, PASSWORD, True)
    assert await count_users(session_factory, email) == 0

    assert (await in_process.run(email, PASSWORD, False)).startswith(f"created {email}")
    with pytest.raises(in_process.Refused, match="10 to 256 characters"):
        await in_process.run(email, "short", True)
    async with session_factory() as session:
        assert await authenticate(session, email, PASSWORD) is not None  # the failed reset changed nothing


def test_interactive_password_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["typed password 1", "typed password 1", "typed password 1", "typo password 1"])
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(script.Refused, match="not a terminal"):
        script.read_password(False)  # piped input without --password-stdin is refused, not echoed

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert script.read_password(False) == "typed password 1"
    with pytest.raises(script.Refused, match="differ"):
        script.read_password(False)
