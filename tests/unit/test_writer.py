"""Unit tests for locking and atomic writing."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from beancount_mcp.writer import (
    LockError,
    append_text,
    atomic_write,
    lock_path_for,
    write_lock,
)


def testAppendText_shouldReturnBlockWithNewline_whenExistingIsEmpty() -> None:
    # Given
    # an empty inbox

    # When
    result = append_text("", "2026-01-01 open Assets:Cash\n")

    # Then
    assert result == "2026-01-01 open Assets:Cash\n"


def testAppendText_shouldSeparateBlocksWithBlankLine_whenExistingHasContent() -> None:
    # Given
    existing = "2026-01-01 open Assets:Cash\n"

    # When
    result = append_text(existing, '2026-01-02 note Assets:Cash "x"\n')

    # Then
    assert result == ('2026-01-01 open Assets:Cash\n\n2026-01-02 note Assets:Cash "x"\n')


def testAppendText_shouldNotAddExtraBlankLine_whenExistingEndsWithBlankLine() -> None:
    # Given
    existing = "2026-01-01 open Assets:Cash\n\n"

    # When
    result = append_text(existing, '2026-01-02 note Assets:Cash "x"\n')

    # Then
    assert result == ('2026-01-01 open Assets:Cash\n\n2026-01-02 note Assets:Cash "x"\n')


def testAppendText_shouldReturnExisting_whenTextIsEmpty() -> None:
    # Given
    existing = "existing\n"

    # When
    result = append_text(existing, "\n")

    # Then
    assert result == "existing\n"


def testLockPathFor_shouldPlaceLockNextToLedger_whenCalled() -> None:
    # Given
    ledger = Path("/tmp/ledger/main.bean")

    # When
    result = lock_path_for(ledger)

    # Then
    assert result == Path("/tmp/ledger/main.bean.lock")


def testWriteLock_shouldKeepReusableInode_whenReleased(tmp_path: Path) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    lock = lock_path_for(ledger)

    # When
    with write_lock(ledger):
        inside = lock.exists()

    # Then
    assert inside is True
    assert lock.exists() is True
    inode = lock.stat().st_ino
    with write_lock(ledger):
        assert lock.stat().st_ino == inode


def testWriteLock_shouldRaiseLockError_whenLockAlreadyExists(tmp_path: Path) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    # When
    with (
        write_lock(ledger),
        pytest.raises(LockError, match="Lock di scrittura") as raised,
        write_lock(ledger),
    ):
        pass

    # Then
    assert "Lock di scrittura" in str(raised.value)


def testAtomicWrite_shouldWriteContent_whenTargetIsNew(tmp_path: Path) -> None:
    # Given
    target = tmp_path / "main.bean"

    # When
    atomic_write(target, "content\n")

    # Then
    assert target.read_text(encoding="utf-8") == "content\n"


def testAtomicWrite_shouldPreserveMode_whenTargetExists(tmp_path: Path) -> None:
    # Given
    target = tmp_path / "main.bean"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o640)

    # When
    atomic_write(target, "new\n")

    # Then
    assert target.read_text(encoding="utf-8") == "new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def testAtomicWrite_shouldRespectUmask_whenTargetIsNew(tmp_path: Path) -> None:
    # Given
    target = tmp_path / "main.bean"
    previous_umask = os.umask(0o077)

    # When
    try:
        atomic_write(target, "content\n")
    finally:
        os.umask(previous_umask)

    # Then
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def testAtomicWrite_shouldLeaveOriginalUntouched_whenReplaceFails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    target = tmp_path / "main.bean"
    target.write_text("old\n", encoding="utf-8")

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    # When
    with pytest.raises(OSError, match="replace failed"):
        atomic_write(target, "new\n")

    # Then
    assert target.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def testAtomicWrite_shouldSyncDirectoryAfterReplace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "main.bean"
    target.write_text("old\n")
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def record_fsync(descriptor: int) -> None:
        events.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")
        real_fsync(descriptor)

    def record_replace(source: str, destination: str) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(os, "replace", record_replace)
    atomic_write(target, "new\n")
    assert events == ["file", "replace", "directory"]


def testAtomicWrite_shouldReportDirectorySyncFailure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "main.bean"
    target.write_text("old\n")
    real_fsync = os.fsync

    def fail_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("directory sync failed")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_sync)
    with pytest.raises(OSError, match="directory sync failed"):
        atomic_write(target, "new\n")
    # Replacement happened, but durability was not acknowledged to the caller.
    assert target.read_text() == "new\n"
