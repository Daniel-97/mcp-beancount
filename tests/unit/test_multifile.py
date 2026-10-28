"""Unit tests for the multi-file transaction journal."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from beancount_mcp import multifile
from beancount_mcp.multifile import (
    TransactionError,
    commit_files,
    recover_pending_transaction,
    transaction_dir,
)
from beancount_mcp.writer import atomic_write as original_atomic_write


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pending_journal(
    ledger: Path,
    files: dict[Path, str],
    *,
    committed: bool = False,
) -> tuple[Path, list[dict[str, str]]]:
    directory = transaction_dir(ledger)
    backup_dir = directory / "backup"
    backup_dir.mkdir(parents=True)
    entries: list[dict[str, str]] = []
    for index, (path, original) in enumerate(files.items()):
        backup = backup_dir / str(index)
        backup.write_text(original, encoding="utf-8")
        entries.append(
            {
                "path": str(path),
                "backup": str(backup),
                "original_sha256": _sha(original),
                "new_sha256": _sha(original.replace("old", "new")),
            }
        )
    (directory / "journal.json").write_text(
        json.dumps({"version": 2, "files": entries}),
        encoding="utf-8",
    )
    if committed:
        (directory / "committed").write_text("committed\n", encoding="utf-8")
    return directory, entries


def testCommitFiles_shouldWriteAllFiles_whenSuccessful(tmp_path: Path) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    first = tmp_path / "a.bean"
    second = tmp_path / "b.bean"
    first.write_text("old a\n")
    second.write_text("old b\n")

    # When
    commit_files(ledger, {first: "new a\n", second: "new b\n"})

    # Then
    assert first.read_text(encoding="utf-8") == "new a\n"
    assert second.read_text(encoding="utf-8") == "new b\n"
    assert not transaction_dir(ledger).exists()


def testCommitFiles_shouldNotRecoverImplicitly_whenJournalExists(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("old a\n")
    _pending_journal(ledger, {target: "old a\n"})

    # When
    with pytest.raises(TransactionError, match="Transazione pendente"):
        commit_files(ledger, {target: "new a\n"})

    # Then
    assert target.read_text(encoding="utf-8") == "old a\n"
    assert transaction_dir(ledger).exists()


def testCommitFiles_shouldRestoreAllFiles_whenReplaceFails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    first = tmp_path / "a.bean"
    second = tmp_path / "b.bean"
    first.write_text("old a\n")
    second.write_text("old b\n")
    real_replace = os.replace
    calls = 0

    def flaky_replace(source: str, destination: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("replace failed")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", flaky_replace)

    # When
    with pytest.raises(TransactionError, match="annullata"):
        commit_files(ledger, {first: "new a\n", second: "new b\n"})

    # Then
    assert first.read_text(encoding="utf-8") == "old a\n"
    assert second.read_text(encoding="utf-8") == "old b\n"
    assert not transaction_dir(ledger).exists()


def testCommitFiles_shouldSkipWrite_whenTargetWasNeverModified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("old a\n")

    def fail_write(path: Path, content: str) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(multifile, "atomic_write", fail_write)

    # When
    with pytest.raises(TransactionError, match="annullata"):
        commit_files(ledger, {target: "new a\n"})

    # Then
    assert target.read_text(encoding="utf-8") == "old a\n"
    assert not transaction_dir(ledger).exists()


def testRecoverPendingTransaction_shouldRestoreBackups_whenJournalExists(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    first = tmp_path / "a.bean"
    second = tmp_path / "b.bean"
    first.write_text("old a\n")
    second.write_text("old b\n")
    directory, _ = _pending_journal(
        ledger,
        {first: "old a\n", second: "old b\n"},
    )
    first.write_text("new a\n")
    second.write_text("new b\n")

    # When
    recovered = recover_pending_transaction(ledger)

    # Then
    assert recovered is True
    assert first.read_text(encoding="utf-8") == "old a\n"
    assert second.read_text(encoding="utf-8") == "old b\n"
    assert not directory.exists()


def testRecoverPendingTransaction_shouldOnlyCleanUp_whenCommitted(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("new a\n")
    directory, _ = _pending_journal(
        ledger,
        {target: "old a\n"},
        committed=True,
    )

    # When
    recovered = recover_pending_transaction(ledger)

    # Then
    assert recovered is True
    assert target.read_text(encoding="utf-8") == "new a\n"
    assert not directory.exists()


def testRecoverPendingTransaction_shouldRemoveDirectory_whenJournalMissing(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    directory = transaction_dir(ledger)
    (directory / "backup").mkdir(parents=True)

    # When
    recovered = recover_pending_transaction(ledger)

    # Then
    assert recovered is True
    assert not directory.exists()


def testRecoverPendingTransaction_shouldReturnFalse_whenNoJournal(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")

    # When
    recovered = recover_pending_transaction(ledger)

    # Then
    assert recovered is False


def testRecoverPendingTransaction_shouldRaise_whenJournalIsCorrupt(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    directory = transaction_dir(ledger)
    directory.mkdir()
    (directory / "journal.json").write_text("{not json", encoding="utf-8")

    # When
    with pytest.raises(TransactionError, match="Journal") as raised:
        recover_pending_transaction(ledger)

    # Then
    assert "Journal" in str(raised.value)


def testRecoverPendingTransaction_shouldRaise_whenBackupHashMismatch(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("new a\n")
    directory, entries = _pending_journal(ledger, {target: "old a\n"})
    entries[0]["original_sha256"] = "0" * 64
    (directory / "journal.json").write_text(
        json.dumps({"version": 2, "files": entries}),
        encoding="utf-8",
    )

    # When
    with pytest.raises(TransactionError, match="Recovery incompleto") as raised:
        recover_pending_transaction(ledger)

    # Then
    assert "Recovery incompleto" in str(raised.value)
    assert directory.exists()


def testCommitFiles_shouldCleanCommittedDirectory_whenPresent(tmp_path: Path) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("new a\n")
    directory, _ = _pending_journal(
        ledger,
        {target: "old a\n"},
        committed=True,
    )

    # When
    commit_files(ledger, {target: "newer a\n"})

    # Then
    assert target.read_text(encoding="utf-8") == "newer a\n"
    assert not directory.exists()


def testCommitFiles_shouldPreserveJournal_whenWrittenHashIsUnexpected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("old a\n")
    calls = 0

    def corrupt_once(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_atomic_write(path, "corrupt\n")
        else:
            original_atomic_write(path, content)

    monkeypatch.setattr("beancount_mcp.multifile.atomic_write", corrupt_once)

    # When
    with pytest.raises(TransactionError, match="ripristino incompleto"):
        commit_files(ledger, {target: "new a\n"})

    # Then
    assert target.read_text(encoding="utf-8") == "corrupt\n"
    assert transaction_dir(ledger).exists()


def testCommitFiles_shouldLeaveCommittedJournal_whenCleanupFails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    target = tmp_path / "a.bean"
    target.write_text("old a\n")
    real_rmtree = shutil.rmtree
    calls = 0

    def fail_cleanup(path: Path, ignore_errors: bool = False) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return
        real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(shutil, "rmtree", fail_cleanup)

    # When
    commit_files(ledger, {target: "new a\n"})

    # Then
    directory = transaction_dir(ledger)
    assert target.read_text(encoding="utf-8") == "new a\n"
    assert directory.exists()
    assert (directory / "committed").exists()
    assert recover_pending_transaction(ledger) is True
    assert target.read_text(encoding="utf-8") == "new a\n"
    assert not directory.exists()


def testCommitFiles_shouldPersistBackupsBeforeTargetsAndTargetsBeforeCommit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp import writer

    ledger = tmp_path / "main.bean"
    ledger.write_text("old\n")
    directory = transaction_dir(ledger)
    events: list[tuple[str, Path]] = []
    real_sync = writer.fsync_directory
    real_write = multifile._write_fsync

    def record_sync(path: Path) -> None:
        events.append(("sync", path))
        real_sync(path)

    def record_write(path: Path, content: str, *, mode: int = 0o600) -> None:
        events.append(("write", path))
        real_write(path, content, mode=mode)

    def record_target(path: Path, content: str) -> None:
        events.append(("target", path))
        original_atomic_write(path, content)

    monkeypatch.setattr(writer, "fsync_directory", record_sync)
    monkeypatch.setattr(multifile, "fsync_directory", record_sync)
    monkeypatch.setattr(multifile, "_write_fsync", record_write)
    monkeypatch.setattr(multifile, "atomic_write", record_target)
    commit_files(ledger, {ledger: "new\n"})
    target_index = events.index(("target", ledger))
    marker_index = events.index(("write", directory / "committed"))
    assert events.index(("sync", tmp_path)) < target_index
    assert events.index(("sync", directory / "backup")) < target_index
    assert events.index(("sync", directory)) < target_index
    assert ("sync", tmp_path) in events[target_index + 1 : marker_index]
    assert events[-1] == ("sync", tmp_path)
