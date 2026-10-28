"""Integration tests for safe inbox writes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.add_transactions import add_transactions
from beancount_mcp.tools.validate import build_validation
from beancount_mcp.writer import write_lock

VALID_TRANSACTION = (
    '2026-02-01 * "Shop" "Coffee" #food\n  Expenses:Food   3.50 EUR\n  Assets:Cash    -3.50 EUR\n'
)
UNBALANCED_TRANSACTION = (
    '2026-02-01 * "Shop" "Bad"\n  Expenses:Food   3.50 EUR\n  Assets:Cash    -2.00 EUR\n'
)


def _service(ledger: Any, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger.main), **options))


def testAddTransactions_shouldAppendValidTransaction_whenBalanced(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before_version = service.load().version

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is True
    assert result["entry_count"] == 1
    assert result["dry_run"] is False
    assert VALID_TRANSACTION.strip() in ledger.inbox.read_text(encoding="utf-8")
    assert result["ledger_version"] != before_version
    assert build_validation(service)["error_count"] == 0


def testAddTransactions_shouldNotModifyFiles_whenDryRun(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = add_transactions(service, VALID_TRANSACTION, dry_run=True)

    # Then
    assert result["ok"] is True
    assert result["would_write_text"] == VALID_TRANSACTION
    assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldNotModifyFiles_whenValidationFails(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = add_transactions(service, UNBALANCED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldReturnSyntaxError_whenTextIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = add_transactions(service, "2026-02-01 * broken")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "SYNTAX_ERROR"
    assert result["error"]["details"]


def testAddTransactions_shouldSuggestOpenAccount_whenAccountIsUnknown(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    text = (
        '2026-02-01 * "Shop" "Unknown"\n'
        "  Expenses:Travel   3.50 EUR\n"
        "  Assets:Cash       -3.50 EUR\n"
    )

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert "open_account" in result["error"]["hint"]


@pytest.mark.parametrize(
    "text",
    [
        "2026-02-01 pad Assets:Cash Equity:Opening-Balances\n",
        "2026-02-01 balance Assets:Cash 0.00 EUR\n",
    ],
)
def testAddTransactions_shouldRejectPadAndBalance_whenPresent(copy_fixture: Any, text: str) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("text", ['include "other.bean"\n', 'plugin "other"\n'])
def testAddTransactions_shouldRejectIncludeAndPlugin_whenPresent(
    copy_fixture: Any, text: str
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testAddTransactions_shouldReturnVersionConflict_whenExpectedVersionIsStale(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = add_transactions(
        service,
        VALID_TRANSACTION,
        expected_ledger_version="deadbeef",
    )

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VERSION_CONFLICT"
    assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldReturnLocked_whenLockExists(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    with write_lock(ledger.main):
        before = snapshot_bytes(ledger.root)

        # When
        result = add_transactions(service, VALID_TRANSACTION)

        # Then
        assert result["ok"] is False
        assert result["error"]["code"] == "LOCKED"
        assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldReturnReadOnly_whenServerIsReadOnly(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger, read_only=True)
    before = snapshot_bytes(ledger.root)

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "READ_ONLY"
    assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldReturnInboxNotIncluded_whenInboxIsMissing(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("no_inbox")
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "INBOX_NOT_INCLUDED"
    assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldPreservePreexistingErrors_whenAddingValidTransaction(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("with_errors")
    service = _service(ledger)
    before_errors = build_validation(service)["error_count"]
    text = '2026-01-04 * "Shop" "Valid"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n'

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is True
    assert build_validation(service)["error_count"] == before_errors


def testAddTransactions_shouldLeaveFilesIntact_whenAtomicReplaceFails(
    copy_fixture: Any, snapshot_bytes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"
    assert snapshot_bytes(ledger.root) == before
    with write_lock(ledger.main):
        pass
    assert list(ledger.root.glob(".*.tmp")) == []


def testAddTransactions_shouldAppendMultipleDirectivesInOrder_whenCalled(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    text = '2026-02-01 note Assets:Cash "first"\n2026-02-02 note Assets:Cash "second"\n'

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is True
    content = ledger.inbox.read_text(encoding="utf-8")
    assert content.index("first") < content.index("second")


def testAddTransactions_shouldNotDeduplicate_whenSameTextAddedTwice(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    first = add_transactions(service, VALID_TRANSACTION)
    second = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert first["ok"] is True
    assert second["ok"] is True
    assert ledger.inbox.read_text(encoding="utf-8").count("Coffee") == 2


def testAddTransactions_shouldReturnValidationFailed_whenUnbalanced(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = add_transactions(service, UNBALANCED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert "bilanciata" in result["error"]["hint"].lower()


def testAddTransactions_shouldReturnLedgerError_whenLedgerIsMissing(
    tmp_path: Path,
) -> None:
    # Given
    service = LedgerService(build_config(str(tmp_path / "missing.bean")))

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"


def testAddTransactions_shouldPreserveInboxSymlink_whenLedgerIncludesSymlink(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    real_inbox = ledger.root / "real-inbox.bean"
    real_inbox.write_text("", encoding="utf-8")
    ledger.inbox.unlink()
    ledger.inbox.symlink_to(real_inbox)
    service = _service(ledger)

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is True
    assert ledger.inbox.is_symlink() is True
    assert "Coffee" in real_inbox.read_text(encoding="utf-8")
    assert service.load().entries


def testAddTransactions_shouldWriteRealInbox_whenConfiguredInboxIsSymlink(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "real-inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n",
        inbox_text=None,
    )
    real_inbox = ledger.root / "real-inbox.bean"
    real_inbox.write_text("", encoding="utf-8")
    link = ledger.root / "link-inbox.bean"
    link.symlink_to(real_inbox)
    service = LedgerService(build_config(str(ledger.main), inbox="link-inbox.bean"))

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is True
    assert link.is_symlink() is True
    assert "Coffee" in real_inbox.read_text(encoding="utf-8")


def testAddTransactions_shouldValidate_whenLedgerHasRelativeDocument(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
        '2026-01-02 document Assets:Cash "receipt.pdf"\n'
    )
    (ledger.root / "receipt.pdf").write_text("receipt\n", encoding="utf-8")
    service = _service(ledger)

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is True


def testAddTransactions_shouldValidate_whenLedgerHasRelativeDocumentsOption(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'option "documents" "receipts"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    (ledger.root / "receipts").mkdir()
    service = _service(ledger)

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert result["ok"] is True


def testAddTransactions_shouldSubtractPreexistingMissingAbsoluteInclude_whenValidating(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    missing = tmp_path / "absolutely-missing.bean"
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        f'include "{missing}"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    service = _service(ledger)
    before_errors = build_validation(service)["error_count"]

    # When
    result = add_transactions(service, VALID_TRANSACTION)

    # Then
    assert before_errors == 1
    assert result["ok"] is True
    assert build_validation(service)["error_count"] == 1


def testAddTransactions_shouldRejectOptionDirective_whenPresent(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = add_transactions(service, 'option "operating_currency" "USD"\n')

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testAddTransactions_shouldRejectCommentOnly_whenTextHasNoDirectives(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = add_transactions(service, "; just a comment\n")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testAddTransactions_shouldExplainOpenDate_whenTransactionPrecedesOpening(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-02 open Assets:Cash EUR\n"
        "2026-01-02 open Expenses:Food\n"
    )
    service = _service(ledger)
    text = (
        '2026-01-01 * "Shop" "Too early"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n'
    )

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert "2026-01-02" in result["error"]["hint"]
    assert "open_account" not in result["error"]["hint"]


def testAddTransactions_shouldExplainActiveInterval_whenAccountOpenedAndClosed(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Expenses:Food\n"
        "2026-01-02 open Assets:Cash EUR\n"
        "2026-01-10 close Assets:Cash\n"
    )
    service = _service(ledger)
    text = (
        '2026-01-01 * "Shop" "Too early"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n'
    )

    # When
    result = add_transactions(service, text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert "2026-01-02" in result["error"]["hint"]
    assert "2026-01-10" in result["error"]["hint"]
