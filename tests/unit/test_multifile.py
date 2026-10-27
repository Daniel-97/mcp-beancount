"""Unit tests for the multi-file transaction journal."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from beancount_mcp.multifile import (
    TransactionError,
    commit_files,
    recover_pending_transaction,
    transaction_dir,
)


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


def testRecoverPendingTransaction_shouldRestoreBackups_whenJournalExists(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("main\n")
    first = tmp_path / "a.bean"
    second = tmp_path / "b.bean"
    first.write_text("new a\n")
    second.write_text("new b\n")
    directory = transaction_dir(ledger)
    backup_dir = directory / "backup"
    backup_dir.mkdir(parents=True)
    (backup_dir / "0").write_text("old a\n", encoding="utf-8")
    (backup_dir / "1").write_text("old b\n", encoding="utf-8")
    journal = {
        "version": 1,
        "files": [
            {
                "path": str(first),
                "backup": str(backup_dir / "0"),
                "original_sha256": "x",
                "new_sha256": "y",
            },
            {
                "path": str(second),
                "backup": str(backup_dir / "1"),
                "original_sha256": "x",
                "new_sha256": "y",
            },
        ],
    }
    (directory / "journal.json").write_text(
        json.dumps(journal),
        encoding="utf-8",
    )

    # When
    recovered = recover_pending_transaction(ledger)

    # Then
    assert recovered is True
    assert first.read_text(encoding="utf-8") == "old a\n"
    assert second.read_text(encoding="utf-8") == "old b\n"
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
