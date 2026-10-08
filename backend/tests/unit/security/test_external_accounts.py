"""Account rules for externally authenticated owners (AUTH_PROVIDER=supabase) that need no database:
placeholder emails, which provider emails are used, and that the constants are migration 0003's.
The database side (``ensure_external_user``): tests/integration/test_supabase_auth_api.py."""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest

from app.security.accounts import (
    LEGACY_PASSWORD_HASH,
    PLACEHOLDER_DOMAIN,
    external_email,
    is_placeholder_email,
    placeholder_email,
)
from app.security.passwords import verify_password_sync

MIGRATION_0003 = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0003_users_auth_sessions.py"
USER_ID = uuid.UUID("8d1d0d5e-8c33-4a39-9a3e-1f0c2b7c9a11")


def migration_0003() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0003_for_test", MIGRATION_0003)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_constants_are_migration_0003s() -> None:
    migration = migration_0003()
    assert migration.LEGACY_PASSWORD_HASH == LEGACY_PASSWORD_HASH
    assert migration.LEGACY_EMAIL_DOMAIN == PLACEHOLDER_DOMAIN
    # The migration writes 'legacy-' || owner_uuid::text || '@botforge.invalid'; uuid::text is the
    # lower-case hyphenated form, as str(uuid.UUID) is.
    assert placeholder_email(USER_ID) == "legacy-8d1d0d5e-8c33-4a39-9a3e-1f0c2b7c9a11@botforge.invalid"


def test_no_password_verifies_against_the_placeholder_hash() -> None:
    for password in ("", LEGACY_PASSWORD_HASH, "correct horse battery", "!legacy-owner-without-password"):
        assert verify_password_sync(LEGACY_PASSWORD_HASH, password) is False


@pytest.mark.parametrize(
    ("email", "placeholder"),
    [
        (placeholder_email(USER_ID), True),
        (placeholder_email(USER_ID, "-0a1b2c3d4e5f6071"), True),
        ("owner@example.com", False),
        ("legacy-x@example.com", False),
        ("someone@botforge.invalid", False),
    ],
)
def test_is_placeholder_email(email: str, placeholder: bool) -> None:
    assert is_placeholder_email(email) is placeholder


@pytest.mark.parametrize(
    ("raw", "used"),
    [
        ("owner@example.com", "owner@example.com"),
        ("  Owner@Example.COM ", "owner@example.com"),
        (None, None),
        ("", None),
        ("not an email", None),
        ("Ünïcode@example.com", None),  # the own login's rules: ASCII only
        ("a" * 65 + "@example.com", None),
        (placeholder_email(USER_ID), None),  # can never pass for one of our placeholders
        ("anyone@BOTFORGE.invalid", None),
    ],
)
def test_external_email(raw: str | None, used: str | None) -> None:
    assert external_email(raw) == used
