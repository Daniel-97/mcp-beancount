"""Unit tests for safe ledger initialization."""

from __future__ import annotations

import os
import stat
from datetime import date
from pathlib import Path

import pytest

from beancount_mcp.init import InitError, create_ledger, render_main_ledger


def testRenderMainLedger_shouldInterpolateCurrencyAndDate_whenValuesAreProvided() -> None:
    # Given
    currency = "USD"
    opening_date = date(2025, 1, 2)

    # When
    result = render_main_ledger(currency, opening_date)

    # Then
    assert result == (
        'option "title" "Beancount MCP Ledger"\n'
        'option "operating_currency" "USD"\n'
        "\n"
        'include "inbox.bean"\n'
        "\n"
        "2025-01-02 open Equity:Opening-Balances\n"
    )


def testCreateLedger_shouldWriteMainLedgerAndEmptyInbox_whenTargetIsNew(
    tmp_path: Path, expected_main_ledger: str
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    result = create_ledger(ledger, "EUR", today=date(2026, 10, 25))

    # Then
    assert result.ledger_path == ledger
    assert result.inbox_path == tmp_path / "inbox.bean"
    assert result.currency == "EUR"
    assert result.opening_date == date(2026, 10, 25)
    assert ledger.read_text(encoding="utf-8") == expected_main_ledger
    assert (tmp_path / "inbox.bean").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(("raw", "expected"), [("eur", "EUR"), (" usd ", "USD")])
def testCreateLedger_shouldNormalizeCurrency_whenCurrencyHasDifferentCaseOrSpaces(
    tmp_path: Path, raw: str, expected: str
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    result = create_ledger(ledger, raw)

    # Then
    assert result.currency == expected
    assert f'option "operating_currency" "{expected}"' in ledger.read_text(encoding="utf-8")


@pytest.mark.parametrize("currency", ["", "EU R", "EUR\nX", "E", "1EUR", "EUR\tX"])
def testCreateLedger_shouldRefuseInvalidCurrency_whenCurrencyIsMalformed(
    tmp_path: Path, currency: str
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    with pytest.raises(InitError, match="Valuta non valida"):
        create_ledger(ledger, currency)

    # Then
    assert list(tmp_path.iterdir()) == []


def testCreateLedger_shouldRefuseInitialization_whenMainLedgerIsNotEmpty(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("existing\n", encoding="utf-8")

    # When
    with pytest.raises(InitError, match="esiste già e non è vuoto"):
        create_ledger(ledger, "EUR")

    # Then
    assert ledger.read_text(encoding="utf-8") == "existing\n"
    assert not (tmp_path / "inbox.bean").exists()


def testCreateLedger_shouldRefuseInitialization_whenInboxIsNotEmpty(
    tmp_path: Path,
) -> None:
    # Given
    inbox = tmp_path / "inbox.bean"
    inbox.write_text("existing\n", encoding="utf-8")

    # When
    with pytest.raises(InitError, match="esiste già e non è vuoto"):
        create_ledger(tmp_path / "main.bean", "EUR")

    # Then
    assert not (tmp_path / "main.bean").exists()
    assert inbox.read_text(encoding="utf-8") == "existing\n"


def testCreateLedger_shouldLeaveExistingFilesUnchanged_whenInitializationIsRefused(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.write_text("main\n", encoding="utf-8")
    inbox.write_text("inbox\n", encoding="utf-8")
    before = (ledger.read_bytes(), inbox.read_bytes())

    # When
    with pytest.raises(InitError):
        create_ledger(ledger, "EUR")

    # Then
    assert (ledger.read_bytes(), inbox.read_bytes()) == before


def testCreateLedger_shouldRefuseInitialization_whenMainLedgerIsSymlink(
    tmp_path: Path,
) -> None:
    # Given
    target = tmp_path / "target.bean"
    target.write_text("target\n", encoding="utf-8")
    link = tmp_path / "main.bean"
    link.symlink_to(target)

    # When
    with pytest.raises(InitError, match="symlink"):
        create_ledger(link, "EUR")

    # Then
    assert target.read_text(encoding="utf-8") == "target\n"


def testCreateLedger_shouldRefuseInitialization_whenInboxIsSymlink(
    tmp_path: Path,
) -> None:
    # Given
    target = tmp_path / "target.bean"
    target.write_text("target\n", encoding="utf-8")
    (tmp_path / "inbox.bean").symlink_to(target)

    # When
    with pytest.raises(InitError, match="symlink"):
        create_ledger(tmp_path / "main.bean", "EUR")

    # Then
    assert not (tmp_path / "main.bean").exists()
    assert target.read_text(encoding="utf-8") == "target\n"


def testCreateLedger_shouldRefuseInitialization_whenMainLedgerIsNotRegularFile(
    tmp_path: Path,
) -> None:
    # Given
    (tmp_path / "main.bean").mkdir()

    # When
    with pytest.raises(InitError, match="non è un file regolare"):
        create_ledger(tmp_path / "main.bean", "EUR")

    # Then
    assert not (tmp_path / "inbox.bean").exists()


def testCreateLedger_shouldRefuseInitialization_whenInboxIsNotRegularFile(
    tmp_path: Path,
) -> None:
    # Given
    (tmp_path / "inbox.bean").mkdir()

    # When
    with pytest.raises(InitError, match="non è un file regolare"):
        create_ledger(tmp_path / "main.bean", "EUR")

    # Then
    assert not (tmp_path / "main.bean").exists()


def testCreateLedger_shouldRefuseInitialization_whenMainLedgerPathIsInboxBean(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "inbox.bean"

    # When
    with pytest.raises(InitError, match="inbox stessa"):
        create_ledger(ledger, "EUR")

    # Then
    assert list(tmp_path.iterdir()) == []


def testCreateLedger_shouldAcceptExistingEmptyFiles_whenInitializing(
    tmp_path: Path, expected_main_ledger: str
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.touch()
    inbox.touch()

    # When
    result = create_ledger(ledger, "EUR", today=date(2026, 10, 25))

    # Then
    assert result.ledger_path.read_text(encoding="utf-8") == expected_main_ledger
    assert result.inbox_path.read_text(encoding="utf-8") == ""


def testCreateLedger_shouldPreserveFileModes_whenFilesAlreadyExistEmpty(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.touch()
    inbox.touch()
    ledger.chmod(0o640)
    inbox.chmod(0o640)

    # When
    create_ledger(ledger, "EUR", today=date(2026, 10, 25))

    # Then
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o640
    assert stat.S_IMODE(inbox.stat().st_mode) == 0o640


def testCreateLedger_shouldRespectUmask_whenCreatingNewFiles(tmp_path: Path) -> None:
    # Given
    previous_umask = os.umask(0o077)

    # When
    try:
        result = create_ledger(tmp_path / "main.bean", "EUR")
    finally:
        os.umask(previous_umask)

    # Then
    assert stat.S_IMODE(result.ledger_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.inbox_path.stat().st_mode) == 0o600


def testCreateLedger_shouldCreateParentDirectories_whenTheyAreMissing(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "nested" / "directory" / "main.bean"

    # When
    result = create_ledger(ledger, "EUR")

    # Then
    assert result.ledger_path.is_file()
    assert result.inbox_path.is_file()


def testCreateLedger_shouldLeaveNoFiles_whenAtomicReplaceFails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    # When
    with pytest.raises(InitError, match="replace failed"):
        create_ledger(ledger, "EUR")

    # Then
    assert not ledger.exists()
    assert list(tmp_path.iterdir()) == []


def testCreateLedger_shouldPreserveEmptyMainLedger_whenAtomicReplaceFails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    # When
    with pytest.raises(InitError, match="replace failed"):
        create_ledger(ledger, "EUR")

    # Then
    assert ledger.exists()
    assert ledger.read_text(encoding="utf-8") == ""
    assert list(tmp_path.iterdir()) == [ledger]


def testCreateLedger_shouldPreserveEmptyInbox_whenAtomicReplaceFails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    inbox = tmp_path / "inbox.bean"
    inbox.touch()

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    # When
    with pytest.raises(InitError, match="replace failed"):
        create_ledger(tmp_path / "main.bean", "EUR")

    # Then
    assert not (tmp_path / "main.bean").exists()
    assert inbox.exists()
    assert list(tmp_path.iterdir()) == [inbox]
