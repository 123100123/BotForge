"""File storage: server-generated keys, confinement to the root, permissions (app/spreadsheets/storage.py)."""

import os
import stat
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.spreadsheets.storage import LocalFileStorage, StorageKeyError, get_storage, key_kind, new_key

BOT = uuid.UUID("12345678-1234-5678-1234-567812345678")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_keys_are_generated_server_side() -> None:
    first, second = new_key(BOT, "xlsx"), new_key(BOT, "csv")
    assert first.startswith(f"{BOT}/") and first.endswith(".xlsx") and second.endswith(".csv")
    assert first != new_key(BOT, "xlsx")
    assert key_kind(first) == "xlsx" and key_kind(second) == "csv"
    with pytest.raises(ValueError):
        new_key(BOT, "exe")  # type: ignore[arg-type]


async def test_round_trip_and_permissions(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "uploads"
    storage = LocalFileStorage(root)
    key = new_key(BOT, "csv")
    await storage.put(key, b"a,b\n1,2\n")
    assert await storage.get(key) == b"a,b\n1,2\n"
    path = storage.path_for(key)
    assert path.parent.parent == root.resolve()
    assert mode(root) == 0o700 and mode(path.parent) == 0o700 and mode(path) == 0o600
    await storage.delete(key)
    assert not path.exists()
    await storage.delete(key)  # deleting twice is fine
    with pytest.raises(FileNotFoundError):
        await storage.get(key)


async def test_an_existing_root_keeps_its_permissions(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    storage = LocalFileStorage(tmp_path)
    key = new_key(BOT, "xlsx")
    await storage.put(key, b"PK")
    assert mode(tmp_path) == 0o755 and mode(storage.path_for(key).parent) == 0o700


async def test_a_file_is_never_overwritten(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    key = new_key(BOT, "csv")
    await storage.put(key, b"first")
    with pytest.raises(FileExistsError):
        await storage.put(key, b"second")
    assert await storage.get(key) == b"first"


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "/etc/passwd",
        f"{BOT}/../../etc/passwd.csv",
        f"{BOT}/{uuid.uuid4().hex}.exe",
        f"{BOT}/{uuid.uuid4().hex.upper()}.csv",
        f"{BOT}/sub/{uuid.uuid4().hex}.csv",
        f"ABCDEF12-1234-5678-1234-567812345678/{uuid.uuid4().hex}.csv",  # not the canonical form
        f"{uuid.uuid4().hex}.csv",
        "",
    ],
)
async def test_keys_that_new_key_cannot_make_are_refused(tmp_path: Path, key: str) -> None:
    storage = LocalFileStorage(tmp_path)
    operations = (lambda: storage.put(key, b"x"), lambda: storage.get(key), lambda: storage.delete(key))
    for operation in operations:
        with pytest.raises(StorageKeyError):
            await operation()
    assert list(tmp_path.iterdir()) == []


async def test_a_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    os.symlink(outside, root / str(BOT))  # a planted bot directory pointing elsewhere
    storage = LocalFileStorage(root)
    key = new_key(BOT, "csv")
    with pytest.raises(StorageKeyError):
        await storage.put(key, b"x")
    with pytest.raises(StorageKeyError):
        await storage.get(key)
    assert list(outside.iterdir()) == []


async def test_a_symlinked_file_is_not_written_through(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    key = new_key(BOT, "csv")
    path = storage.path_for(key)
    path.parent.mkdir(mode=0o700)
    target = tmp_path / "target.txt"
    target.write_bytes(b"original")
    os.symlink(target, path)
    with pytest.raises(StorageKeyError):  # the resolved path is not two levels under the root
        await storage.put(key, b"evil")
    assert target.read_bytes() == b"original"


def test_get_storage_uses_upload_dir(tmp_path: Path) -> None:
    storage = get_storage(Settings(UPLOAD_DIR=str(tmp_path / "u")))
    assert isinstance(storage, LocalFileStorage) and storage.root == (tmp_path / "u").resolve()
