"""Unit tests for ledger versioning and inbox inspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp.config import build_config
from beancount_mcp.ledger import (
    LedgerError,
    LedgerService,
    compute_ledger_version,
    inspect_inbox,
)


def testComputeLedgerVersion_shouldBeDeterministic_whenFilesAreUnchanged(
    tmp_path: Path,
) -> None:
    # Given
    first_file = tmp_path / "a.bean"
    second_file = tmp_path / "b.bean"
    first_file.write_text("a\n", encoding="utf-8")
    second_file.write_text("b\n", encoding="utf-8")

    # When
    first = compute_ledger_version([first_file, second_file])
    second = compute_ledger_version([first_file, second_file])

    # Then
    assert first == second
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)


def testComputeLedgerVersion_shouldChange_whenFileContentChanges(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("a\n", encoding="utf-8")
    first = compute_ledger_version([ledger])

    # When
    ledger.write_text("b\n", encoding="utf-8")
    second = compute_ledger_version([ledger])

    # Then
    assert first != second


def testComputeLedgerVersion_shouldIgnoreInputOrder_whenFilesAreSame(
    tmp_path: Path,
) -> None:
    # Given
    first_file = tmp_path / "a.bean"
    second_file = tmp_path / "b.bean"
    first_file.write_text("a\n", encoding="utf-8")
    second_file.write_text("b\n", encoding="utf-8")

    # When
    first = compute_ledger_version([first_file, second_file])
    second = compute_ledger_version([second_file, first_file])

    # Then
    assert first == second


def testComputeLedgerVersion_shouldDependOnFilePath_whenContentsAreIdentical(
    tmp_path: Path,
) -> None:
    # Given
    first_file = tmp_path / "a.bean"
    second_file = tmp_path / "b.bean"
    first_file.write_text("same\n", encoding="utf-8")
    second_file.write_text("same\n", encoding="utf-8")

    # When
    first = compute_ledger_version([first_file])
    second = compute_ledger_version([second_file])

    # Then
    assert first != second


def testInspectInbox_shouldMarkIncluded_whenPathIsAmongFiles(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.write_text("", encoding="utf-8")
    inbox.write_text("", encoding="utf-8")

    # When
    status = inspect_inbox(inbox, ledger, [ledger, inbox])

    # Then
    assert status.exists is True
    assert status.included is True
    assert status.warning is None


def testInspectInbox_shouldWarnMissing_whenFileDoesNotExist(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.write_text("", encoding="utf-8")

    # When
    status = inspect_inbox(inbox, ledger, [ledger])

    # Then
    assert status.exists is False
    assert status.included is False
    assert status.warning is not None
    assert "Inbox non trovata" in status.warning
    assert 'include "inbox.bean"' in status.warning


def testInspectInbox_shouldWarnNotIncluded_whenFileExistsOutsideFiles(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.write_text("", encoding="utf-8")
    inbox.write_text("", encoding="utf-8")

    # When
    status = inspect_inbox(inbox, ledger, [ledger])

    # Then
    assert status.exists is True
    assert status.included is False
    assert status.warning is not None
    assert "Inbox non inclusa" in status.warning


def testLedgerService_shouldRaise_whenLedgerFileIsMissing(tmp_path: Path) -> None:
    # Given
    config = build_config(str(tmp_path / "missing.bean"))
    service = LedgerService(config)

    # When
    with pytest.raises(LedgerError, match="Ledger non trovato") as raised:
        service.load()

    # Then
    assert "missing.bean" in str(raised.value)
