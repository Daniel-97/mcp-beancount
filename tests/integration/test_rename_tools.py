"""Integration tests for rename_account, rename_tag, and rename_link."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.multifile import transaction_dir
from beancount_mcp.server import create_server
from beancount_mcp.tools.rename import rename_account, rename_link, rename_tag
from beancount_mcp.tools.validate import build_validation


def _service(ledger: Any, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger.main), **options))


def _multifile_ledger(ledger_factory: Any) -> Any:
    return ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food EUR\n"
        '2026-01-02 * "Shop" "Main"\n'
        "  Expenses:Food   10.00 EUR\n"
        "  Assets:Cash    -10.00 EUR\n",
        inbox_text=(
            '2026-01-03 * "Shop" "Inbox"\n  Expenses:Food   5.00 EUR\n  Assets:Cash    -5.00 EUR\n'
        ),
    )


def testRenameAccount_shouldRenameInboxOnly_whenFlagIsOff(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\ninclude "inbox.bean"\n',
        inbox_text=(
            "2026-01-01 open Assets:Cash EUR\n"
            "2026-01-01 open Expenses:Food EUR\n"
            '2026-01-02 * "Shop" "Lunch"\n'
            "  Expenses:Food   10.00 EUR\n"
            "  Assets:Cash    -10.00 EUR\n"
        ),
    )
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    dry = rename_account(
        service,
        "Expenses:Food",
        "Expenses:Groceries",
        dry_run=True,
    )

    # Then
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert dry["change_count"] == 2
    assert snapshot_bytes(ledger.root) == before

    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")
    assert result["ok"] is True
    assert "Expenses:Groceries" in ledger.inbox.read_text(encoding="utf-8")
    assert "Expenses:Food" not in ledger.inbox.read_text(encoding="utf-8")
    assert build_validation(service)["valid"] is True


def testRenameAccount_shouldRenameAllFiles_whenFlagIsOn(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = _multifile_ledger(ledger_factory)
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is True
    assert result["files_changed"] == 2
    assert "Expenses:Groceries" in ledger.main.read_text(encoding="utf-8")
    assert "Expenses:Groceries" in ledger.inbox.read_text(encoding="utf-8")
    assert build_validation(service)["valid"] is True


def testRenameAccount_shouldReturnEntryNotInInbox_whenFlagIsOff(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = _multifile_ledger(ledger_factory)
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_IN_INBOX"
    assert snapshot_bytes(ledger.root) == before


def testRenameAccount_shouldRenameSubaccounts_whenRequested(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food EUR\n"
        "2026-01-01 open Expenses:Food:Dining\n"
        '2026-01-02 * "Shop" "Dining"\n'
        "  Expenses:Food:Dining   10.00 EUR\n"
        "  Assets:Cash           -10.00 EUR\n",
    )
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = rename_account(
        service,
        "Expenses:Food",
        "Expenses:Groceries",
        include_subaccounts=True,
    )

    # Then
    assert result["ok"] is True
    content = ledger.main.read_text(encoding="utf-8")
    assert "open Expenses:Groceries EUR" in content
    assert "open Expenses:Groceries:Dining" in content
    assert "Expenses:Food" not in content
    assert build_validation(service)["valid"] is True


def testRenameAccount_shouldReturnAccountExists_whenTargetIsOpen(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Expenses:Food EUR\n"
        "2026-01-01 open Expenses:Groceries EUR\n",
    )
    service = _service(ledger)

    # When
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ACCOUNT_EXISTS"


def testRenameAccount_shouldReturnValidationFailed_whenNewNameIsInvalid(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Expenses:Food EUR\n",
    )
    service = _service(ledger)

    # When
    result = rename_account(service, "Expenses:Food", "not-an-account")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testRenameAccount_shouldReturnEntryNotFound_whenAbsent(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Expenses:Food EUR\n",
    )
    service = _service(ledger)

    # When
    result = rename_account(service, "Expenses:Missing", "Expenses:Groceries")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_FOUND"


def testRenameAccount_shouldReturnReadOnly_whenReadOnly(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = _multifile_ledger(ledger_factory)
    service = _service(ledger, read_only=True)

    # When
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "READ_ONLY"


def testRenameAccount_shouldReturnPathNotAllowed_whenFileIsOutsideLedgerDir(
    ledger_factory: Any, tmp_path: Path
) -> None:
    # Given
    external = tmp_path / "external.bean"
    external.write_text(
        '2026-01-02 * "Shop" "External"\n  Expenses:Food   1.00 EUR\n  Assets:Cash    -1.00 EUR\n',
        encoding="utf-8",
    )
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "../external.bean"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food EUR\n",
    )
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"


def testRenameAccount_shouldRollback_whenAtomicReplaceFails(
    ledger_factory: Any, snapshot_bytes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = _multifile_ledger(ledger_factory)
    service = _service(ledger, allow_edit_outside_inbox=True)
    before = snapshot_bytes(ledger.root)
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
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"
    assert snapshot_bytes(ledger.root) == before
    assert not transaction_dir(ledger.main).exists()


def testRenameTag_shouldRenameAcrossFilesAndPreserveNarration_whenFlagIsOn(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "\n"
        "pushtag #food\n"
        "2026-01-01 open Assets:Cash EUR\n"
        "2026-01-01 open Expenses:Food EUR\n"
        '2026-01-02 * "Shop" "I like #food" #food\n'
        "  Expenses:Food   10.00 EUR\n"
        "  Assets:Cash    -10.00 EUR\n"
        "poptag #food\n",
        inbox_text=(
            '2026-01-03 * "Shop" "Inbox #food" #food ; #food\n'
            "  Expenses:Food   5.00 EUR\n"
            "  Assets:Cash    -5.00 EUR\n"
        ),
    )
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = rename_tag(service, "food", "meals")

    # Then
    assert result["ok"] is True
    assert result["files_changed"] == 2
    main = ledger.main.read_text(encoding="utf-8")
    inbox = ledger.inbox.read_text(encoding="utf-8")
    assert "pushtag #meals" in main
    assert "poptag #meals" in main
    assert '"I like #food" #meals' in main
    assert '"Inbox #food" #meals ; #food' in inbox
    assert build_validation(service)["valid"] is True


def testRenameTag_shouldReturnEntryNotInInbox_whenFlagIsOff(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        '2026-01-02 * "Shop" "Tagged" #food\n'
        "  Assets:Cash   1.00 EUR\n"
        "  Equity:Opening-Balances  -1.00 EUR\n"
        "2026-01-01 open Equity:Opening-Balances\n",
    )
    service = _service(ledger)
    before = snapshot_bytes(ledger.root)

    # When
    result = rename_tag(service, "food", "meals")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_IN_INBOX"
    assert snapshot_bytes(ledger.root) == before


def testRenameTag_shouldReturnEntryNotFound_whenAbsent(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n",
    )
    service = _service(ledger)

    # When
    result = rename_tag(service, "missing", "meals")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "ENTRY_NOT_FOUND"


def testRenameTag_shouldReturnValidationFailed_whenNewTagIsInvalid(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n",
    )
    service = _service(ledger)

    # When
    result = rename_tag(service, "food", "not a tag")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_FAILED"


def testRenameTag_shouldNotModifyFiles_whenDryRun(ledger_factory: Any, snapshot_bytes: Any) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        '2026-01-02 * "Shop" "Tagged" #food\n'
        "  Assets:Cash   1.00 EUR\n"
        "  Equity:Opening-Balances  -1.00 EUR\n"
        "2026-01-01 open Equity:Opening-Balances\n",
    )
    service = _service(ledger, allow_edit_outside_inbox=True)
    before = snapshot_bytes(ledger.root)

    # When
    result = rename_tag(service, "food", "meals", dry_run=True)

    # Then
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["change_count"] == 1
    assert snapshot_bytes(ledger.root) == before


def testRenameLink_shouldRenameAcrossFilesAndPreserveNarration_whenFlagIsOn(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n"
        '2026-01-02 * "Shop" "I like ^november" ^november\n'
        "  Assets:Cash   1.00 EUR\n"
        "  Equity:Opening-Balances  -1.00 EUR\n"
        "2026-01-01 open Equity:Opening-Balances\n",
        inbox_text=(
            '2026-01-03 * "Shop" "Inbox ^november" ^november\n'
            "  Assets:Cash   1.00 EUR\n"
            "  Equity:Opening-Balances  -1.00 EUR\n"
        ),
    )
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = rename_link(service, "november", "2026-11")

    # Then
    assert result["ok"] is True
    assert result["files_changed"] == 2
    main = ledger.main.read_text(encoding="utf-8")
    inbox = ledger.inbox.read_text(encoding="utf-8")
    assert '"I like ^november" ^2026-11' in main
    assert '"Inbox ^november" ^2026-11' in inbox
    assert build_validation(service)["valid"] is True


def testCreateServer_shouldRecoverPendingTransaction_whenJournalExists(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        'option "operating_currency" "EUR"\n'
        'include "inbox.bean"\n'
        "2026-01-01 open Assets:Cash EUR\n",
    )
    original = ledger.inbox.read_text(encoding="utf-8")
    modified = original + '\n2026-01-02 note Assets:Cash "pending"\n'
    ledger.inbox.write_text(modified, encoding="utf-8")
    directory = transaction_dir(ledger.main)
    backup_dir = directory / "backup"
    backup_dir.mkdir(parents=True)
    (backup_dir / "0").write_text(original, encoding="utf-8")
    journal = {
        "version": 1,
        "files": [
            {
                "path": str(ledger.inbox),
                "backup": str(backup_dir / "0"),
                "original_sha256": "x",
                "new_sha256": "y",
            }
        ],
    }
    (directory / "journal.json").write_text(json.dumps(journal), encoding="utf-8")

    # When
    create_server(build_config(str(ledger.main)))

    # Then
    assert ledger.inbox.read_text(encoding="utf-8") == original
    assert not directory.exists()
