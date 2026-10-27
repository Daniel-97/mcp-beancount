"""Integration tests for edit_transaction and delete_transaction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from beancount_mcp.config import build_config
from beancount_mcp.entries import entry_id_to_dict, extract_directive_spans
from beancount_mcp.entry_service import delete_transaction, edit_transaction
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.add_transactions import add_transactions
from beancount_mcp.tools.open_account import open_account
from beancount_mcp.writer import lock_path_for

VALID_TRANSACTION = (
    '2026-02-01 * "Shop" "Coffee"\n  Expenses:Food   3.50 EUR\n  Assets:Cash    -3.50 EUR\n'
)
EDITED_TRANSACTION = (
    '2026-02-01 * "Shop" "Tea"\n  Expenses:Food   3.50 EUR\n  Assets:Cash    -3.50 EUR\n'
)


def _service(ledger: Any, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger.main), **options))


def _entry_id(path: Path, needle: str | None = None) -> dict[str, Any]:
    spans = extract_directive_spans(path, path.read_text(encoding="utf-8"))
    if needle is None:
        return entry_id_to_dict(spans[0].entry_id)
    for span in spans:
        if needle in span.text:
            return entry_id_to_dict(span.entry_id)
    raise AssertionError(f"span containing {needle!r} not found")


def testEditTransaction_shouldReplaceInboxEntry_whenHashMatches(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    before_version = service.load().version

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is True
    assert "Tea" in ledger.inbox.read_text(encoding="utf-8")
    assert result["entry_id"]["hash"] != entry_id["hash"]
    assert result["ledger_version"] != before_version


def testEditTransaction_shouldNotModifyFile_whenDryRun(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    before = snapshot_bytes(ledger.root)

    # When
    result = edit_transaction(
        service,
        entry_id,
        EDITED_TRANSACTION,
        dry_run=True,
    )

    # Then
    assert result["ok"] is True
    assert result["would_write_text"] == EDITED_TRANSACTION
    assert snapshot_bytes(ledger.root) == before


def testEditTransaction_shouldReturnEntryChanged_whenHashIsStale(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    stale_id = _entry_id(ledger.inbox)
    assert edit_transaction(service, stale_id, EDITED_TRANSACTION)["ok"] is True

    # When
    result = edit_transaction(service, stale_id, VALID_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_CHANGED"
    assert "Tea" in result["error"]["details"][0]["current_text"]


def testEditTransaction_shouldReturnEntryNotFound_whenLineDoesNotExist(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    entry_id = {
        "file": str(ledger.inbox),
        "line": 999,
        "hash": "a" * 64,
    }

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_FOUND"


def testEditTransaction_shouldReturnEntryNotFound_whenEntryIdIsMalformed(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)

    # When
    result = edit_transaction(service, {"file": str(ledger.inbox)}, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_FOUND"


def testEditTransaction_shouldReturnSyntaxError_whenNewTextIsInvalid(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)

    # When
    result = edit_transaction(service, entry_id, "not valid")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "SYNTAX_ERROR"


def testEditTransaction_shouldRejectMultipleDirectives_whenNewTextHasTwo(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    text = '2026-02-01 note Assets:Cash "one"\n2026-02-02 note Assets:Cash "two"\n'

    # When
    result = edit_transaction(service, entry_id, text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testEditTransaction_shouldReturnValidationFailed_whenNewTextAddsError(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    before = snapshot_bytes(ledger.root)
    unbalanced = (
        '2026-02-01 * "Shop" "Broken"\n  Expenses:Food   3.50 EUR\n  Assets:Cash    -2.00 EUR\n'
    )

    # When
    result = edit_transaction(service, entry_id, unbalanced)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert snapshot_bytes(ledger.root) == before


def testEditTransaction_shouldReturnEntryNotInInbox_whenFlagIsOff(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    entry_id = _entry_id(ledger.main, needle="Dinner")
    before = snapshot_bytes(ledger.root)

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_IN_INBOX"
    assert snapshot_bytes(ledger.root) == before


def testEditTransaction_shouldEditIncludedFile_whenFlagIsOn(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(ledger.main, needle="Dinner")

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is True
    assert "Tea" in ledger.main.read_text(encoding="utf-8")


def testEditTransaction_shouldReturnPathNotAllowed_whenFileIsOutsideLedgerDir(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    external = tmp_path / "external.bean"
    external.write_text(
        '2026-01-02 * "X" "Y"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
        encoding="utf-8",
    )
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "../external.bean"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(external, needle="X")

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"


def testEditTransaction_shouldReturnPathNotAllowed_whenSymlinkEscapesLedgerDir(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    external = tmp_path / "external.bean"
    external.write_text(
        '2026-01-02 * "X" "Y"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
        encoding="utf-8",
    )
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "link.bean"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    (ledger.root / "link.bean").symlink_to(external)
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(external, needle="X")

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"


def testDeleteTransaction_shouldDeleteInboxTransaction_whenHashMatches(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    before_version = service.load().version

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is True
    assert ledger.inbox.read_text(encoding="utf-8") == ""
    assert result["ledger_version"] != before_version


def testDeleteTransaction_shouldNotModifyFile_whenDryRun(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    before = snapshot_bytes(ledger.root)

    # When
    result = delete_transaction(service, entry_id, dry_run=True)

    # Then
    assert result["ok"] is True
    assert result["would_delete"] is True
    assert snapshot_bytes(ledger.root) == before


def testDeleteTransaction_shouldReturnValidationFailed_whenEntryIsNotTransaction(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert open_account(service, "Expenses:Travel", ["EUR"])["ok"] is True
    entry_id = _entry_id(ledger.inbox, needle="open Expenses:Travel")

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testDeleteTransaction_shouldReturnEntryChanged_whenHashIsStale(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    stale_id = _entry_id(ledger.inbox)
    assert edit_transaction(service, stale_id, EDITED_TRANSACTION)["ok"] is True

    # When
    result = delete_transaction(service, stale_id)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_CHANGED"


def testDeleteTransaction_shouldReturnEntryNotInInbox_whenFlagIsOff(
    copy_fixture: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    entry_id = _entry_id(ledger.main, needle="Dinner")
    before = snapshot_bytes(ledger.root)

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_IN_INBOX"
    assert snapshot_bytes(ledger.root) == before


def testDeleteTransaction_shouldDeleteIncludedFileEntry_whenFlagIsOn(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(ledger.main, needle="Dinner")

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is True
    assert "Dinner" not in ledger.main.read_text(encoding="utf-8")


def testDeleteTransaction_shouldReturnPathNotAllowed_whenFileIsOutsideLedgerDir(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    external = tmp_path / "external.bean"
    external.write_text(
        '2026-01-02 * "X" "Y"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
        encoding="utf-8",
    )
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "../external.bean"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(external, needle="X")

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"


def testDeleteTransaction_shouldRollback_whenDeletionAddsError(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
        "2026-01-03 balance Assets:Cash -10.00 EUR\n",
        inbox_text=(
            '2026-01-02 * "Shop" "Lunch"\n'
            "  Expenses:Food   10.00 EUR\n"
            "  Assets:Cash    -10.00 EUR\n"
        ),
    )
    service = _service(ledger)
    entry_id = _entry_id(ledger.inbox)
    before = snapshot_bytes(ledger.root)

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert snapshot_bytes(ledger.root) == before


def testAddThenDelete_shouldRestoreInboxAndVersion_whenOnlyTransaction(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    before_inbox = ledger.inbox.read_bytes()
    before_version = service.load().version
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is True
    assert ledger.inbox.read_bytes() == before_inbox
    assert result["ledger_version"] == before_version


def testEditTransaction_shouldReturnLocked_whenLockExists(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    lock = lock_path_for(ledger.main)
    lock.write_text("held\n", encoding="utf-8")

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LOCKED"
    lock.unlink()


def testEditTransaction_shouldValidateModifiedSymlinkTarget_whenIncludedFileIsSymlink(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "link.bean"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    real = ledger.root / "real.bean"
    real.write_text(
        '2026-01-02 * "X" "Y"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
        encoding="utf-8",
    )
    (ledger.root / "link.bean").symlink_to(real)
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(real, needle="X")
    before = real.read_bytes()
    unbalanced = (
        '2026-01-02 * "X" "Broken"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -0.50 EUR\n'
    )

    # When
    result = edit_transaction(service, entry_id, unbalanced)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert real.read_bytes() == before


def testEditTransaction_shouldReturnInboxNotIncluded_whenInboxIsMissing(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("no_inbox")
    service = _service(ledger)
    entry_id = _entry_id(ledger.main, needle="Lunch")

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "INBOX_NOT_INCLUDED"


def testDeleteTransaction_shouldReturnInboxNotIncluded_whenInboxIsMissing(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("no_inbox")
    service = _service(ledger)
    entry_id = _entry_id(ledger.main, needle="Lunch")

    # When
    result = delete_transaction(service, entry_id)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "INBOX_NOT_INCLUDED"


def testEditTransaction_shouldRejectBalanceTarget_whenEntryIsBalance(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n",
        inbox_text="2026-01-02 balance Assets:Cash 0.00 EUR\n",
    )
    service = _service(ledger)
    entry_id = _entry_id(ledger.inbox, needle="balance")
    before = snapshot_bytes(ledger.root)

    # When
    result = edit_transaction(service, entry_id, '2026-01-02 note Assets:Cash "x"\n')

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert snapshot_bytes(ledger.root) == before


def testEditTransaction_shouldRejectOptionDirective_whenNewTextContainsIt(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)

    # When
    result = edit_transaction(
        service,
        entry_id,
        'option "operating_currency" "USD"\n',
    )

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "new_text",
    [
        'include "other.bean"\n',
        'plugin "other"\n',
        "2026-02-01 pad Assets:Cash Equity:Opening-Balances\n",
        "2026-02-01 balance Assets:Cash 0.00 EUR\n",
        "\n",
    ],
)
def testEditTransaction_shouldRejectForbiddenOrEmptyText_whenProvided(
    copy_fixture: Any, new_text: str
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)

    # When
    result = edit_transaction(service, entry_id, new_text)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] in {"SYNTAX_ERROR", "VALIDATION_FAILED"}


def testEditTransaction_shouldReturnUsableEntryId_whenNewTextHasLeadingComment(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger)
    assert add_transactions(service, VALID_TRANSACTION)["ok"] is True
    entry_id = _entry_id(ledger.inbox)
    new_text = "; leading comment\n" + EDITED_TRANSACTION

    # When
    result = edit_transaction(service, entry_id, new_text)

    # Then
    assert result["ok"] is True
    assert result["entry_id"]["line"] == entry_id["line"] + 1
    follow_up = edit_transaction(service, result["entry_id"], VALID_TRANSACTION)
    assert follow_up["ok"] is True


def testEditTransaction_shouldAllowInboxOutsideLedgerDir_whenFlagIsOn(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    outside = tmp_path / "outside-inbox.bean"
    outside.write_text(VALID_TRANSACTION, encoding="utf-8")
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "../outside-inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n",
        inbox_text=None,
    )
    service = LedgerService(
        build_config(
            str(ledger.main),
            inbox="../outside-inbox.bean",
            allow_edit_outside_inbox=True,
        )
    )
    entry_id = _entry_id(outside)

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is True
    assert "Tea" in outside.read_text(encoding="utf-8")


def testEditTransaction_shouldReturnPathNotAllowed_whenFileIsNotIncluded(
    tmp_path: Path, ledger_factory: Any
) -> None:
    # Given
    other = tmp_path / "other.bean"
    other.write_text(VALID_TRANSACTION, encoding="utf-8")
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food\n"
    )
    service = _service(ledger, allow_edit_outside_inbox=True)
    entry_id = _entry_id(other)

    # When
    result = edit_transaction(service, entry_id, EDITED_TRANSACTION)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"
