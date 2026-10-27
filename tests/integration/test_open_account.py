"""Integration tests for the open_account tool."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from beancount_mcp.config import build_config
from beancount_mcp.init import create_ledger
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.add_transactions import add_transactions
from beancount_mcp.tools.open_account import open_account
from beancount_mcp.tools.validate import build_validation


def _service(ledger: Any, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger.main), **options))


def testOpenAccount_shouldWriteOpenDirective_whenAccountIsNew(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Travel", ["EUR"])

    # Then
    assert result["ok"] is True
    assert result["account"] == "Expenses:Travel"
    assert result["available_for_transactions"] is True
    assert "open Expenses:Travel EUR" in ledger.inbox.read_text(encoding="utf-8")
    assert build_validation(service)["error_count"] == 0


def testOpenAccount_shouldReturnAccountExists_whenAccountIsAlreadyOpen(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert open_account(service, "Expenses:Travel", ["EUR"])["ok"] is True

    # When
    result = open_account(service, "Expenses:Travel", ["EUR"])

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ACCOUNT_EXISTS"


def testOpenAccount_shouldReturnSimilarExists_whenSimilarAccountExists(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Expenses:Restaurant\n"
    )
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Resturant", ["EUR"])

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ACCOUNT_SIMILAR_EXISTS"
    assert result["error"]["details"] == [{"account": "Expenses:Restaurant"}]


def testOpenAccount_shouldProceed_whenConfirmNewIsTrue(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Expenses:Restaurant\n"
    )
    service = _service(ledger)

    # When
    result = open_account(
        service,
        "Expenses:Resturant",
        ["EUR"],
        confirm_new=True,
        dry_run=True,
    )

    # Then
    assert result["ok"] is True
    assert result["account"] == "Expenses:Resturant"


def testOpenAccount_shouldNotModifyFiles_whenDryRun(copy_fixture: Any, snapshot_bytes: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = open_account(service, "Expenses:Travel", ["EUR"], dry_run=True)

    # Then
    assert result["ok"] is True
    assert result["available_for_transactions"] is False
    assert snapshot_bytes(ledger.root) == before


def testOpenAccount_shouldReturnValidationFailed_whenNameIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Assets:cash")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testOpenAccount_shouldReturnValidationFailed_whenRootIsNotAllowed(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Foo:Bar")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert "Radici ammesse" in result["error"]["hint"]


def testOpenAccount_shouldReturnValidationFailed_whenDateIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Travel", date="not-a-date")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testOpenAccount_shouldReturnValidationFailed_whenCurrencyIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Travel", ["EU R"])

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testOpenAccount_shouldReturnReadOnly_whenServerIsReadOnly(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger, read_only=True)

    # When
    result = open_account(service, "Expenses:Travel")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "READ_ONLY"


def testOpenAccount_shouldWriteMultipleCurrencies_whenProvided(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Travel", ["EUR", "USD"])

    # Then
    assert result["ok"] is True
    assert "open Expenses:Travel EUR,USD" in ledger.inbox.read_text(encoding="utf-8")


def testOpenAccount_shouldUseToday_whenDateIsOmitted(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Travel")

    # Then
    assert result["ok"] is True
    assert date.today().isoformat() in ledger.inbox.read_text(encoding="utf-8")


def testOpenAccount_shouldSupportInitToFirstTransaction_whenStartingFromInit(
    tmp_path: Path,
) -> None:
    # Given
    ledger_path = tmp_path / "main.bean"
    create_ledger(ledger_path, "EUR")
    service = LedgerService(build_config(str(ledger_path)))
    day = date.today().isoformat()

    # When
    cash = open_account(service, "Assets:Cash", ["EUR"], date=day)
    food = open_account(service, "Expenses:Food", ["EUR"], date=day)
    transaction = add_transactions(
        service,
        f'{day} * "Shop" "First"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
    )

    # Then
    assert cash["ok"] is True
    assert food["ok"] is True
    assert transaction["ok"] is True
    assert build_validation(service)["error_count"] == 0


def testOpenAccount_shouldReturnInboxNotIncluded_whenInboxIsMissing(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("no_inbox")
    service = _service(ledger)

    # When
    result = open_account(service, "Expenses:Travel", ["EUR"])

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "INBOX_NOT_INCLUDED"


def testOpenAccount_shouldReturnLedgerError_whenLedgerIsMissing(
    tmp_path: Path,
) -> None:
    # Given
    service = LedgerService(build_config(str(tmp_path / "missing.bean")))

    # When
    result = open_account(service, "Expenses:Travel", ["EUR"])

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"
