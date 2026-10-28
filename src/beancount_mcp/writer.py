"""Generic file locking and atomic writing."""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class LockError(Exception):
    """Raised when the write lock cannot be acquired."""


def lock_path_for(ledger_path: Path) -> Path:
    """Return the lock file path next to the ledger."""
    return ledger_path.parent / f"{ledger_path.name}.lock"


@contextmanager
def write_lock(ledger_path: Path) -> Iterator[None]:
    """Acquire a non-blocking exclusive lock next to the ledger."""
    path = lock_path_for(ledger_path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LockError(f"Impossibile aprire il lock {path}: {exc}") from exc

    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockError(f"Lock di scrittura già acquisito: {path}") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        yield
    finally:
        # Keep the inode: unlinking allows another process to lock a different
        # inode while a waiter still holds this one. Closing releases the lock,
        # including when the process is killed.
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    """Persist directory entry changes, or report failure to the caller."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append_text(existing: str, text: str) -> str:
    """Append a block of directives while keeping a blank-line separator."""
    block = text.strip("\n")
    if not block:
        return existing
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    return existing + block + "\n"


def atomic_write(path: Path, content: str) -> None:
    """Write ``content`` atomically, preserving an existing file mode."""
    mode = _target_mode(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _target_mode(path: Path) -> int:
    if path.exists():
        return path.stat().st_mode & 0o777
    current_umask = os.umask(0)
    os.umask(current_umask)
    return 0o666 & ~current_umask
