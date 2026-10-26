"""Integration tests for the ``ledger_info`` tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.ledger_info import build_ledger_info


def _info(path: Path, **config_options: Any) -> dict[str, Any]:
    config = build_config(str(path / "main.bean"), **config_options)
    return build_ledger_info(LedgerService(config))


def testBuildLedgerInfo_shouldListAccountsWithDatesAndCurrencies_whenLedgerHasOpenAndClose(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "main.bean").write_text(
        'option "operating_currency" "EUR"\n'
        "2026-01-01 open Assets:Cash EUR,USD\n"
        "2026-02-01 open Expenses:Food\n"
        "2026-03-01 close Expenses:Food\n",
        encoding="utf-8",
    )

    # When
    info = _info(ledger)

    # Then
    accounts = {account["account"]: account for account in info["accounts"]}
    assert accounts["Assets:Cash"] == {
        "account": "Assets:Cash",
        "open_date": "2026-01-01",
        "close_date": None,
        "currencies": ["EUR", "USD"],
        "is_open": True,
    }
    assert accounts["Expenses:Food"] == {
        "account": "Expenses:Food",
        "open_date": "2026-02-01",
        "close_date": "2026-03-01",
        "currencies": None,
        "is_open": False,
    }


def testBuildLedgerInfo_shouldReturnOperatingCurrencies_whenOptionsAreSet(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "minimal"

    # When
    info = _info(ledger)

    # Then
    assert info["operating_currency"] == ["EUR"]


def testBuildLedgerInfo_shouldReturnTransactionRange_whenTransactionsExist(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "minimal"

    # When
    info = _info(ledger)

    # Then
    assert info["first_transaction_date"] == "2026-01-02"
    assert info["last_transaction_date"] == "2026-01-03"
    assert info["transaction_count"] == 2


def testBuildLedgerInfo_shouldReturnNullTransactionDates_whenLedgerIsEmpty(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "empty"

    # When
    info = _info(ledger)

    # Then
    assert info["first_transaction_date"] is None
    assert info["last_transaction_date"] is None
    assert info["transaction_count"] == 0


def testBuildLedgerInfo_shouldCountPreexistingErrors_whenLedgerHasErrors(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "main.bean").write_text(
        'option "operating_currency" "EUR"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 * "Shop" "Lunch"\n'
        "  Expenses:Food   10.00 EUR\n"
        "  Assets:Cash     -5.00 EUR\n",
        encoding="utf-8",
    )

    # When
    info = _info(ledger)

    # Then
    assert info["ok"] is True
    assert info["error_count"] >= 1
    assert any("errore" in warning for warning in info["warnings"])


def testBuildLedgerInfo_shouldSortTopTagsAndLinks_whenValuesRepeat(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "minimal"

    # When
    info = _info(ledger)

    # Then
    assert info["top_tags"] == [
        {"name": "food", "count": 2},
        {"name": "travel", "count": 1},
    ]
    assert info["top_links"] == [{"name": "lunch", "count": 2}]


def testBuildLedgerInfo_shouldReportInboxStatus_whenInboxIsIncluded(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "minimal"

    # When
    info = _info(ledger)

    # Then
    assert info["inbox"]["exists"] is True
    assert info["inbox"]["included"] is True
    assert info["inbox"]["warning"] is None


def testBuildLedgerInfo_shouldWarnAboutMissingInbox_whenInboxIsAbsent(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "no_inbox"

    # When
    info = _info(ledger)

    # Then
    assert info["inbox"]["exists"] is False
    assert info["inbox"]["included"] is False
    assert "Inbox non trovata" in info["inbox"]["warning"]


def testBuildLedgerInfo_shouldReportReadOnly_whenConfigIsReadOnly(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "minimal"

    # When
    info = _info(ledger, read_only=True)

    # Then
    assert info["read_only"] is True


def testBuildLedgerInfo_shouldReportEmpty_whenLedgerHasNoEntries(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "empty"

    # When
    info = _info(ledger)

    # Then
    assert info["is_empty"] is True
    assert any("open_account" in warning for warning in info["warnings"])


def testBuildLedgerInfo_shouldReturnServiceVersion_whenLedgerIsLoaded(
    fixtures_dir: Path,
) -> None:
    # Given
    ledger = fixtures_dir / "minimal"
    config = build_config(str(ledger / "main.bean"))

    # When
    info = build_ledger_info(LedgerService(config))

    # Then
    assert info["ledger_version"] == LedgerService(config).load().version
