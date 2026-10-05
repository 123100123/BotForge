"""File storage for uploaded spreadsheets.

``FileStorage`` is the seam (so the bytes can later move to object storage); ``LocalFileStorage`` keeps
them in a directory on the server (``UPLOAD_DIR``, a Docker volume in compose).

SECURITY: storage keys are generated here, server-side (``new_key``): ``<bot uuid>/<uuid4 hex>.<ext>``
with ``ext`` in xlsx/csv. Nothing from a request (file name, content type) ever becomes part of a path.
``LocalFileStorage`` accepts only keys of exactly that shape and also checks that the resolved path is
under the root, so a key read back from the database cannot leave the root either, symlinks included.
Directories it creates are 0700 and files 0600; files are created with ``O_EXCL | O_NOFOLLOW``, so an
existing file is never overwritten and a planted symlink is never written through.
"""

import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Literal, Protocol

from app.config import Settings

FileKind = Literal["xlsx", "csv"]
FILE_KINDS: tuple[FileKind, ...] = ("xlsx", "csv")

_KEY_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # the bot's uuid (canonical form)
    r"/[0-9a-f]{32}\.(?:xlsx|csv)"  # uuid4 hex and the sniffed kind
)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_BINARY = getattr(os, "O_BINARY", 0)  # Windows only


class StorageKeyError(ValueError):
    """A key ``new_key`` cannot have produced, or one whose path would leave the storage root."""


def new_key(bot_id: uuid.UUID, kind: FileKind) -> str:
    """A fresh storage key for one file of ``bot_id``. The only way keys are made."""
    if kind not in FILE_KINDS:
        raise ValueError(f"unknown file kind {kind!r}")
    return f"{uuid.UUID(str(bot_id))}/{uuid.uuid4().hex}.{kind}"


def key_kind(key: str) -> FileKind:
    """The file kind encoded in a key made by ``new_key``."""
    if not isinstance(key, str) or _KEY_RE.fullmatch(key) is None:
        raise StorageKeyError("invalid storage key")
    return "xlsx" if key.endswith(".xlsx") else "csv"


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class LocalFileStorage:
    """Files under one root directory, one subdirectory per bot. File I/O runs in worker threads."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()

    def path_for(self, key: str) -> Path:
        """The absolute path of ``key``; ``StorageKeyError`` unless it is a well-formed key whose
        resolved path is exactly two levels under the root."""
        key_kind(key)  # shape check
        path = (self.root / key).resolve()
        if path.parent.parent != self.root or not path.is_relative_to(self.root):
            raise StorageKeyError("storage key leaves the storage root")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self.path_for(key)
        await asyncio.to_thread(self._write, path, bytes(data))

    async def get(self, key: str) -> bytes:
        path = self.path_for(key)
        return await asyncio.to_thread(self._read, path)

    async def delete(self, key: str) -> None:
        path = self.path_for(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    def _write(self, path: Path, data: bytes) -> None:
        self._ensure_root()
        self._ensure_dir(path.parent)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _BINARY, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
        except BaseException:
            os.close(fd)
            path.unlink(missing_ok=True)
            raise
        os.close(fd)

    @staticmethod
    def _read(path: Path) -> bytes:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW | _BINARY)
        with open(fd, "rb") as handle:
            return handle.read()

    def _ensure_root(self) -> None:
        """Create the root (and missing parents) if needed; a root this creates is 0700. An existing
        root keeps its permissions: the per-bot directories inside it are 0700 either way."""
        if self.root.is_dir():
            return
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)  # mkdir's mode is filtered by the umask

    @staticmethod
    def _ensure_dir(directory: Path) -> None:
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if directory.is_symlink() or not directory.is_dir():
                raise StorageKeyError("storage directory is not a plain directory") from None
            return
        os.chmod(directory, 0o700)


def get_storage(settings: Settings) -> FileStorage:
    """The file storage configured by ``UPLOAD_DIR``."""
    return LocalFileStorage(settings.UPLOAD_DIR)
