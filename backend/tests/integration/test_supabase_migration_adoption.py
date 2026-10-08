"""The hosted Supabase database's path: it is at revision 0002, where ``bots.owner_id`` holds Supabase
user ids as text. ``alembic upgrade head`` (migration 0003) adopts each owner as a placeholder account
with the same UUID; served with AUTH_PROVIDER=supabase, a token whose ``sub`` is that id then lists and
opens exactly that owner's bots, and any other ``sub`` gets none of them (404 on each). Runs in a
scratch database on the test server (the shared test schema is never touched). Needs a database."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.main import create_app
from app.security import supabase_auth
from app.security.accounts import LEGACY_PASSWORD_HASH, placeholder_email
from tests.integration.helpers import BACKEND, make_client, use_test_database
from tests.unit.security.tokens import SUPABASE_URL, mint, new_secret

SECRET = new_secret()
OWNER = "8d1d0d5e-8c33-4a39-9a3e-1f0c2b7c9a11"  # Supabase user ids, as 0002 stored them (text)
OTHER_OWNER = "3f2b8c1e-0d4a-4e6b-9c7d-2a1b0c9d8e7f"
OWNER_EMAIL = "owner@example.com"


@pytest.fixture
def scratch_db(test_db_url: str) -> Iterator[str]:
    name = f"migration_{uuid.uuid4().hex[:12]}"

    async def admin(statement: str) -> None:
        engine = create_async_engine(test_db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.exec_driver_sql(statement)
        await engine.dispose()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(test_db_url).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def bearer(sub: str, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(SECRET, 'HS256', sub=sub, email=email)}"}


async def test_existing_owners_keep_their_bots_under_supabase_sign_in(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    alembic(scratch_db, "upgrade", "0002")
    engine = create_async_engine(scratch_db, poolclass=NullPool)
    try:
        bots = {uuid.uuid4(): OWNER, uuid.uuid4(): OWNER, uuid.uuid4(): OTHER_OWNER}
        async with engine.begin() as conn:  # the hosted data before the upgrade
            for bot_id, owner in bots.items():
                await conn.execute(
                    text("INSERT INTO app.bots (id, owner_id, name) VALUES (:id, :owner, :name)"),
                    {"id": bot_id, "owner": owner, "name": f"bot of {owner[:8]}"},
                )
        alembic(scratch_db, "upgrade", "head")

        monkeypatch.setenv("AUTH_PROVIDER", "supabase")
        monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
        monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
        monkeypatch.setenv("SUPABASE_JWKS_URL", "")
        get_settings.cache_clear()
        supabase_auth.reset_verifier()
        app = create_app()
        use_test_database(app, async_sessionmaker(engine, expire_on_commit=False))
        owners_bots = {str(b) for b, o in bots.items() if o == OWNER}
        other_bot = next(str(b) for b, o in bots.items() if o == OTHER_OWNER)

        async with make_client(app) as api:
            owner = bearer(OWNER, OWNER_EMAIL)
            listed = await api.get("/bots", headers=owner)
            assert listed.status_code == 200, listed.text
            assert {b["id"] for b in listed.json()} == owners_bots
            for bot_id in owners_bots:
                opened = await api.get(f"/bots/{bot_id}", headers=owner)
                assert opened.status_code == 200 and opened.json()["id"] == bot_id
                assert (await api.get(f"/bots/{bot_id}/capabilities", headers=owner)).status_code == 200
            assert (await api.get(f"/bots/{other_bot}", headers=owner)).status_code == 404
            me = await api.get("/me", headers=owner)
            assert me.json() == {"id": OWNER, "email": OWNER_EMAIL}  # the placeholder took the email
            upper = await api.get("/bots", headers=bearer(OWNER.upper(), OWNER_EMAIL))
            assert {b["id"] for b in upper.json()} == owners_bots  # the same user id

            stranger = bearer(str(uuid.uuid4()), "stranger@example.com")
            assert (await api.get("/bots", headers=stranger)).json() == []
            for bot_id in [*owners_bots, other_bot]:
                for method, path in (
                    ("GET", f"/bots/{bot_id}"),
                    ("PATCH", f"/bots/{bot_id}"),
                    ("DELETE", f"/bots/{bot_id}"),
                    ("GET", f"/bots/{bot_id}/capabilities"),
                ):
                    response = await api.request(method, path, json={"name": "هک"}, headers=stranger)
                    assert response.status_code == 404, (method, path)
                    assert response.json()["error"]["code"] == "bot_not_found"

            other = await api.get("/bots", headers=bearer(OTHER_OWNER, "other@example.com"))
            assert [b["id"] for b in other.json()] == [other_bot]

        async with engine.connect() as conn:
            rows = {
                str(row.id): row
                for row in await conn.execute(text("SELECT id, email, password_hash FROM app.users"))
            }
            names = (await conn.execute(text("SELECT count(*) FROM app.bots WHERE name = 'هک'"))).scalar_one()
            kept = (await conn.execute(text("SELECT count(*) FROM app.bots"))).scalar_one()
        assert rows[OWNER].email == OWNER_EMAIL
        assert rows[OTHER_OWNER].email == "other@example.com"
        assert all(row.password_hash == LEGACY_PASSWORD_HASH for row in rows.values())
        assert names == 0 and kept == 3  # the stranger changed and deleted nothing
        assert placeholder_email(uuid.UUID(OWNER)) not in {row.email for row in rows.values()}
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        supabase_auth.reset_verifier()
