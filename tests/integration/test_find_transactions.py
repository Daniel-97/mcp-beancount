"""Integration tests for find_transactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from beancount_mcp.config import build_config
from beancount_mcp.entry_service import edit_transaction
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.find_transactions import find_transactions


def _service(ledger: Any, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger.main), **options))


def testFindTransactions_shouldReturnNewestFirst_whenNoFilters(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service)

    # Then
    assert result["ok"] is True
    assert [transaction["narration"] for transaction in result["transactions"]] == [
        "Dinner",
        "Lunch",
    ]
    assert result["total_matches"] == 2
    assert result["truncated"] is False


def testFindTransactions_shouldFilterByPayee_whenPayeeMatches(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, payee="Shop")

    # Then
    assert result["count"] == 2


def testFindTransactions_shouldFilterByNarrationCaseInsensitive_whenSubstringMatches(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, narration_contains="LUNCH")

    # Then
    assert result["count"] == 1
    assert result["transactions"][0]["narration"] == "Lunch"


def testFindTransactions_shouldFilterByAccountAndSubaccounts_whenAccountMatches(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, account="Expenses")

    # Then
    assert result["count"] == 2


def testFindTransactions_shouldFilterByInclusiveDateRange_whenDatesMatch(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(
        service,
        date_from="2026-01-02",
        date_to="2026-01-02",
    )

    # Then
    assert result["count"] == 1
    assert result["transactions"][0]["narration"] == "Lunch"


def testFindTransactions_shouldFilterByAbsoluteAmountRange_whenAmountsMatch(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(
        service,
        min_amount="15.00",
        max_amount="25.00",
    )

    # Then
    assert result["count"] == 1
    assert result["transactions"][0]["narration"] == "Dinner"


def testFindTransactions_shouldFilterByAllTags_whenTagsAreProvided(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, tags=["food", "travel"])

    # Then
    assert result["count"] == 1
    assert result["transactions"][0]["narration"] == "Dinner"


def testFindTransactions_shouldSetTruncatedAndTotalMatches_whenLimitIsSmaller(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, limit=1)

    # Then
    assert result["count"] == 1
    assert result["total_matches"] == 2
    assert result["truncated"] is True


def testFindTransactions_shouldReturnEntryIdUsableByEdit_whenReturned(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger, allow_edit_outside_inbox=True)
    found = find_transactions(service, narration_contains="Dinner")
    entry_id = found["transactions"][0]["entry_id"]

    # When
    result = edit_transaction(
        service,
        entry_id,
        '2026-01-03 * "Shop" "Dinner edited" #food #travel ^lunch\n'
        "  Expenses:Food   20.00 EUR\n"
        "  Assets:Cash    -20.00 EUR\n",
    )

    # Then
    assert result["ok"] is True
    assert "Dinner edited" in ledger.main.read_text(encoding="utf-8")


def testFindTransactions_shouldReturnValidationFailed_whenDateIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, date_from="not-a-date")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testFindTransactions_shouldReturnValidationFailed_whenAmountIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, min_amount="ten")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testFindTransactions_shouldReturnValidationFailed_whenRangeIsInverted(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(
        service,
        date_from="2026-02-01",
        date_to="2026-01-01",
    )

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testFindTransactions_shouldReturnLimitExceeded_whenLimitIsOutOfRange(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, limit=501)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LIMIT_EXCEEDED"


def testFindTransactions_shouldReturnEmptyList_whenNothingMatches(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, payee="Nobody")

    # Then
    assert result["ok"] is True
    assert result["transactions"] == []
    assert result["total_matches"] == 0


def testFindTransactions_shouldReturnTextAndPostings_whenFound(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = find_transactions(service, narration_contains="Lunch")

    # Then
    transaction = result["transactions"][0]
    assert transaction["text"].startswith('2026-01-02 * "Shop" "Lunch"')
    assert transaction["postings"] == [
        {"account": "Expenses:Food", "amount": "10.00 EUR"},
        {"account": "Assets:Cash", "amount": "-10.00 EUR"},
    ]


def testFindTransactions_shouldSearchIncludedFiles_whenTransactionIsInInclude(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "part.bean"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    (ledger.root / "part.bean").write_text(
        '2026-01-02 * "Shop" "Included"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
        encoding="utf-8",
    )
    service = _service(ledger)

    # When
    result = find_transactions(service)

    # Then
    assert result["count"] == 1
    assert result["transactions"][0]["entry_id"]["file"].endswith("part.bean")


def testFindTransactions_shouldReturnLedgerError_whenLedgerIsMissing(
    tmp_path: Path,
) -> None:
    # Given
    service = LedgerService(build_config(str(tmp_path / "missing.bean")))

    # When
    result = find_transactions(service)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"
