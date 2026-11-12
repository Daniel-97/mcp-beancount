"""Regression tests for entry/span pairing, rename completeness, and batch protection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from beancount import loader

from beancount_mcp import renames
from beancount_mcp.change_service import apply_changes
from beancount_mcp.config import build_config
from beancount_mcp.entries import extract_directive_spans, span_matches_directive, split_lines
from beancount_mcp.entry_service import delete_transaction, edit_transaction
from beancount_mcp.ledger import LedgerService
from beancount_mcp.multifile import commit_files, transaction_dir
from beancount_mcp.source_service import find_entries
from beancount_mcp.tools import rename as rename_tool
from beancount_mcp.tools.find_transactions import find_transactions
from beancount_mcp.tools.rename import rename_account, rename_link, rename_tag
from beancount_mcp.write_service import write_inbox_text

MAIN = (
    'option "operating_currency" "EUR"\n'
    'include "inbox.bean"\n'
    "2020-01-01 open Assets:Cash\n"
    "2020-01-01 open Expenses:Food\n"
)
# Characters str.splitlines treats as line breaks but Beancount does not.
FOREIGN_LINE_BREAKS = ["\r", "\x0b", "\x0c", "\x1c", "\x85", " ", " "]


def _service(ledger: Any, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger.main), **options))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _ledger_with_separator(ledger_factory: Any, separator: str) -> Any:
    ledger = ledger_factory(MAIN)
    _write(
        ledger.inbox,
        f'2024-01-01 * "Shop" "milk{separator}bread"\n'
        "  Assets:Cash  -1 EUR\n"
        "  Expenses:Food  1 EUR\n"
        "\n"
        "2024-01-02 price EUR 1.10 USD\n"
        "2024-01-03 balance Assets:Cash  -1 EUR\n"
        '2024-01-04 * "Shop" "second"\n'
        "  Assets:Cash  -2 EUR\n"
        "  Expenses:Food  2 EUR\n",
    )
    return ledger


@pytest.mark.parametrize("separator", FOREIGN_LINE_BREAKS)
def testSplitLines_shouldBreakOnlyOnLineFeed_whenTextHasOtherSeparators(separator: str) -> None:
    # Given
    text = f"a{separator}b\nc\r\nd"

    # When
    lines = split_lines(text)

    # Then
    assert lines == [f"a{separator}b\n", "c\r\n", "d"]


@pytest.mark.parametrize("separator", FOREIGN_LINE_BREAKS)
def testFindEntries_shouldPairEveryDirectiveWithItsOwnText_whenStringHasForeignLineBreak(
    ledger_factory: Any, separator: str
) -> None:
    # Given
    service = _service(_ledger_with_separator(ledger_factory, separator))

    # When
    result = find_entries(service, file="inbox.bean")

    # Then
    assert result["ok"] is True
    assert [(entry["type"], entry["entry_id"]["line"]) for entry in result["entries"]] == [
        ("transaction", 1),
        ("price", 5),
        ("balance", 6),
        ("transaction", 7),
    ]
    for entry in result["entries"]:
        assert entry["text"].startswith(entry["date"])
    assert "balance" in result["entries"][2]["text"]


@pytest.mark.parametrize("separator", FOREIGN_LINE_BREAKS)
def testFindTransactions_shouldReturnOwnText_whenStringHasForeignLineBreak(
    ledger_factory: Any, separator: str
) -> None:
    # Given
    service = _service(_ledger_with_separator(ledger_factory, separator))

    # When
    result = find_transactions(service)

    # Then
    assert result["total_matches"] == 2
    for transaction in result["transactions"]:
        assert transaction["narration"] in transaction["text"]


def testApplyChanges_shouldProtectBalance_whenEarlierStringHasForeignLineBreak(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = _ledger_with_separator(ledger_factory, " ")
    service = _service(ledger)
    listing = find_entries(service, types=["balance"])
    before = snapshot_bytes(ledger.root)

    # When
    result = apply_changes(
        service,
        [{"op": "delete", "entry_id": listing["entries"][0]["entry_id"]}],
        listing["ledger_version"],
    )

    # Then
    assert result["error"]["code"] == "BALANCE_PROTECTED"
    assert snapshot_bytes(ledger.root) == before


def testSpanMatchesDirective_shouldRejectPairing_whenTextBelongsToAnotherDirective(
    tmp_path: Path,
) -> None:
    # Given
    file = tmp_path / "ledger.bean"
    text = "2024-01-02 price EUR 1.10 USD\n2024-01-03 balance Assets:Cash  -1 EUR\n"
    _write(file, "2020-01-01 open Assets:Cash\n" + text)
    entries, _, _ = loader.load_file(str(file))
    price_span, balance_span = extract_directive_spans(file, text)
    balance = next(entry for entry in entries if type(entry).__name__ == "Balance")

    # When / Then
    assert span_matches_directive(balance_span, balance) is True
    assert span_matches_directive(price_span, balance) is False


def testRenameTag_shouldRenameContinuationLinesAndNotes_whenTagIsOutsideHeader(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        MAIN,
        inbox_text=(
            '2024-01-01 * "Shop" "header" #trip\n'
            "  Assets:Cash  -1 EUR\n"
            "  Expenses:Food  1 EUR\n"
            "\n"
            '2024-01-02 * "Shop" "continuation #trip"\n'
            "  #trip ^trip\n"
            "  Assets:Cash  -1 EUR  ; #trip\n"
            "  Expenses:Food  1 EUR\n"
            "\n"
            '2024-01-03 note Assets:Cash "note" #trip\n'
        ),
    )
    service = _service(ledger)

    # When
    result = rename_tag(service, "trip", "holiday")

    # Then
    assert result["ok"] is True
    assert result["change_count"] == 3
    text = ledger.inbox.read_text(encoding="utf-8")
    assert '"header" #holiday\n' in text
    assert "  #holiday ^trip\n" in text
    assert '"note" #holiday\n' in text
    assert '"continuation #trip"' in text
    assert "; #trip\n" in text
    entries, errors, _ = loader.load_file(str(ledger.main))
    assert not errors
    assert not any("trip" in (getattr(entry, "tags", None) or ()) for entry in entries)


def testRenameLink_shouldRenameContinuationLine_whenLinkIsBelowHeader(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        MAIN,
        inbox_text=(
            '2024-01-02 * "Shop" "x"\n'
            "  ^inv-1 #inv-1\n"
            "  Assets:Cash  -1 EUR\n"
            "  Expenses:Food  1 EUR\n"
        ),
    )

    # When
    result = rename_link(_service(ledger), "inv-1", "invoice-1")

    # Then
    assert result["ok"] is True
    assert "  ^invoice-1 #inv-1\n" in ledger.inbox.read_text(encoding="utf-8")


def testRenameAccount_shouldRenameCustomAndMetadataValues_whenAccountIsNotAPosting(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(
        MAIN,
        inbox_text=(
            '2024-01-01 * "Shop" "about Expenses:Food"\n'
            "  paired: Expenses:Food\n"
            '  quoted: "Expenses:Food"\n'
            "  Assets:Cash  -1 EUR\n"
            "  Expenses:Food  1 EUR  ; Expenses:Food\n"
            "\n"
            '2024-01-04 custom "budget" Expenses:Food "monthly" 10 EUR\n'
        ),
    )
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = rename_account(service, "Expenses:Food", "Expenses:Groceries")

    # Then
    assert result["ok"] is True
    text = ledger.inbox.read_text(encoding="utf-8")
    assert '2024-01-04 custom "budget" Expenses:Groceries "monthly" 10 EUR\n' in text
    assert "  paired: Expenses:Groceries\n" in text
    assert '  quoted: "Expenses:Food"\n' in text
    assert '"about Expenses:Food"' in text
    assert "  Expenses:Groceries  1 EUR  ; Expenses:Food\n" in text
    assert "open Expenses:Groceries" in ledger.main.read_text(encoding="utf-8")


def testRenameTag_shouldRefuseAndWriteNothing_whenRewriteWouldLeaveOldTag(
    ledger_factory: Any, snapshot_bytes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a rewriter that misses tags below the transaction header
    ledger = ledger_factory(
        MAIN,
        inbox_text=(
            '2024-01-01 * "Shop" "a" #trip\n'
            "  Assets:Cash  -1 EUR\n"
            "  Expenses:Food  1 EUR\n"
            "\n"
            '2024-01-02 * "Shop" "b"\n'
            "  #trip\n"
            "  Assets:Cash  -1 EUR\n"
            "  Expenses:Food  1 EUR\n"
        ),
    )
    monkeypatch.setattr(
        renames,
        "_line_can_contain_token",
        lambda line, marker: line.startswith("2024-01-01"),
    )
    before = snapshot_bytes(ledger.root)

    # When
    result = rename_tag(_service(ledger), "trip", "holiday")

    # Then
    assert result["error"]["code"] == "RENAME_INCOMPLETE"
    assert result["error"]["details"] == [
        {"type": "transaction", "date": "2024-01-02", "file": str(ledger.inbox), "line": 5}
    ]
    assert snapshot_bytes(ledger.root) == before


def testRenameAccount_shouldRefuseAndWriteNothing_whenRewriteWouldLeaveOldAccount(
    ledger_factory: Any, snapshot_bytes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a rewriter that skips custom directives
    ledger = ledger_factory(
        MAIN,
        inbox_text=(
            '2024-01-01 * "Shop" "a"\n'
            "  Assets:Cash  -1 EUR\n"
            "  Expenses:Food  1 EUR\n"
            '2024-01-04 custom "budget" Expenses:Food "monthly" 10 EUR\n'
        ),
    )
    monkeypatch.setattr(renames, "_line_can_contain_account", lambda line: "custom" not in line)
    before = snapshot_bytes(ledger.root)

    # When
    result = rename_account(
        _service(ledger, allow_edit_outside_inbox=True),
        "Expenses:Food",
        "Expenses:Groceries",
    )

    # Then
    assert result["error"]["code"] == "RENAME_INCOMPLETE"
    assert [detail["type"] for detail in result["error"]["details"]] == ["custom"]
    assert snapshot_bytes(ledger.root) == before


def testRenameTag_shouldKeepExternalEdit_whenFileChangesBeforeCommit(
    ledger_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given an external editor saving after the last version check
    ledger = ledger_factory(
        MAIN,
        inbox_text='2024-01-01 * "Shop" "a" #trip\n  Assets:Cash  -1 EUR\n  Expenses:Food  1 EUR\n',
    )
    external = ledger.inbox.read_text(encoding="utf-8") + "; saved by an editor\n"

    def commit_after_external_edit(*args: Any, **kwargs: Any) -> None:
        _write(ledger.inbox, external)
        commit_files(*args, **kwargs)

    monkeypatch.setattr(rename_tool, "commit_files", commit_after_external_edit)

    # When
    result = rename_tag(_service(ledger), "trip", "holiday")

    # Then
    assert result["error"]["code"] == "LEDGER_ERROR"
    assert ledger.inbox.read_text(encoding="utf-8") == external
    assert not transaction_dir(ledger.main).exists()


def _ledger_with_included_checks(ledger_factory: Any, checks: str) -> Any:
    ledger = ledger_factory(MAIN + 'include "checks.bean"\n')
    _write(ledger.root / "checks.bean", checks)
    return ledger


def testApplyChanges_shouldProtectBalance_whenRemovedIncludeHoldsOne(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = _ledger_with_included_checks(ledger_factory, "2024-06-01 balance Assets:Cash  0 EUR\n")
    service = _service(ledger, allow_edit_outside_inbox=True)
    before = snapshot_bytes(ledger.root)
    changes = [{"op": "remove_include", "pattern": "checks.bean"}]

    # When
    refused = apply_changes(service, changes, service.load().version)
    preview = apply_changes(service, changes, service.load().version, dry_run=True)

    # Then
    assert refused["error"]["code"] == "BALANCE_PROTECTED"
    assert preview["error"]["code"] == "BALANCE_PROTECTED"
    assert snapshot_bytes(ledger.root) == before


def testApplyChanges_shouldRemoveInclude_whenBalanceChangesAreAllowed(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = _ledger_with_included_checks(ledger_factory, "2024-06-01 balance Assets:Cash  0 EUR\n")
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = apply_changes(
        service,
        [{"op": "remove_include", "pattern": "checks.bean"}],
        service.load().version,
        allow_balance_changes=True,
    )

    # Then
    assert result["ok"] is True
    assert "checks.bean" not in ledger.main.read_text(encoding="utf-8")


def testApplyChanges_shouldProtectPad_whenRemovedIncludeHoldsOne(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = _ledger_with_included_checks(
        ledger_factory,
        "2020-01-01 open Equity:Opening\n2024-06-01 pad Assets:Cash Equity:Opening\n",
    )
    service = _service(ledger, allow_edit_outside_inbox=True)

    # When
    result = apply_changes(
        service,
        [{"op": "remove_include", "pattern": "checks.bean"}],
        service.load().version,
        allow_balance_changes=True,
    )

    # Then
    assert result["error"]["code"] == "PAD_PROTECTED"


def testApplyChanges_shouldRemoveInclude_whenProtectedEntriesWereMovedOutFirst(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = _ledger_with_included_checks(ledger_factory, "2024-06-01 balance Assets:Cash  0 EUR\n")
    service = _service(ledger, allow_edit_outside_inbox=True)
    listing = find_entries(service, types=["balance"])

    # When
    result = apply_changes(
        service,
        [
            {"op": "move", "entry_id": listing["entries"][0]["entry_id"], "file": "main.bean"},
            {"op": "remove_include", "pattern": "checks.bean"},
        ],
        listing["ledger_version"],
    )

    # Then
    assert result["ok"] is True
    assert "balance Assets:Cash" in ledger.main.read_text(encoding="utf-8")


def testApplyChanges_shouldKeepBlankLineSeparator_whenReplacingDirective(
    ledger_factory: Any,
) -> None:
    # Given
    second = '2024-01-02 * "b"\n  Assets:Cash  -1 EUR\n  Expenses:Food  1 EUR\n'
    ledger = ledger_factory(
        MAIN,
        inbox_text='2024-01-01 * "a"\n  Assets:Cash  -1 EUR\n  Expenses:Food  1 EUR\n\n' + second,
    )
    service = _service(ledger)
    listing = find_entries(service, types=["transaction"])
    replacement = '2024-01-01 * "a2"\n  Assets:Cash  -1 EUR\n  Expenses:Food  1 EUR'

    # When
    result = apply_changes(
        service,
        [{"op": "replace", "entry_id": listing["entries"][0]["entry_id"], "text": replacement}],
        listing["ledger_version"],
    )

    # Then
    assert result["ok"] is True
    assert ledger.inbox.read_text(encoding="utf-8") == replacement + "\n\n" + second


def testEditTransaction_shouldRejectReceiptComment_whenNewTextForgesIdempotency(
    ledger_factory: Any, snapshot_bytes: Any
) -> None:
    # Given
    ledger = ledger_factory(
        MAIN,
        inbox_text='2024-01-01 * "Shop" "a"\n  Assets:Cash  -1 EUR\n  Expenses:Food  1 EUR\n',
    )
    service = _service(ledger)
    transaction = find_transactions(service)["transactions"][0]
    forged = "; beancount-mcp-idempotency: " + "0" * 64 + " " + "0" * 64
    before = snapshot_bytes(ledger.root)

    # When
    result = edit_transaction(service, transaction["entry_id"], forged + "\n" + transaction["text"])

    # Then
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert snapshot_bytes(ledger.root) == before


def testAddTransactions_shouldNotTreatStringContentAsReceipt_whenNarrationHasForeignLineBreak(
    ledger_factory: Any,
) -> None:
    # Given a narration whose second "line" imitates a receipt for key "k"
    ledger = ledger_factory(MAIN)
    service = _service(ledger)
    text = '2024-02-02 * "new"\n  Assets:Cash  -5 EUR\n  Expenses:Food  5 EUR\n'
    first = write_inbox_text(service, text, idempotency_key="k")
    receipt = ledger.inbox.read_text(encoding="utf-8").split("\n")[0]
    other = '2024-03-03 * "other"\n  Assets:Cash  -7 EUR\n  Expenses:Food  7 EUR\n'
    _write(
        ledger.inbox,
        f'2024-01-01 * "x {receipt[:-1]}0"\n  Assets:Cash  -1 EUR\n  Expenses:Food  1 EUR\n',
    )

    # When
    result = write_inbox_text(service, other, idempotency_key="k")

    # Then
    assert first["ok"] is True
    assert result["ok"] is True
    assert result["replayed"] is False
    assert '"other"' in ledger.inbox.read_text(encoding="utf-8")


NEW_TRANSACTION = '2024-02-02 * "new"\n  Assets:Cash  -5 EUR\n  Expenses:Food  5 EUR\n'


def testAddTransactions_shouldReplay_whenWrittenDirectivesAreUntouched(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(MAIN)
    service = _service(ledger)
    write_inbox_text(service, NEW_TRANSACTION, idempotency_key="k")
    write_inbox_text(service, NEW_TRANSACTION.replace("new", "later"))
    before = ledger.inbox.read_bytes()

    # When
    retry = write_inbox_text(service, NEW_TRANSACTION, idempotency_key="k")

    # Then
    assert retry["ok"] is True and retry["replayed"] is True
    assert ledger.inbox.read_bytes() == before


def testAddTransactions_shouldReturnConflict_whenReplayedDirectivesWereDeleted(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(MAIN)
    service = _service(ledger)
    write_inbox_text(service, NEW_TRANSACTION, idempotency_key="k")
    transaction = find_transactions(service)["transactions"][0]
    assert delete_transaction(service, transaction["entry_id"])["ok"] is True
    before = ledger.inbox.read_bytes()

    # When
    retry = write_inbox_text(service, NEW_TRANSACTION, idempotency_key="k")

    # Then
    assert retry["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert retry["error"]["details"] == [{"reason": "entries_changed"}]
    assert ledger.inbox.read_bytes() == before


def testAddTransactions_shouldReturnConflict_whenReplayedDirectivesWereEdited(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(MAIN)
    service = _service(ledger)
    write_inbox_text(service, NEW_TRANSACTION, idempotency_key="k")
    transaction = find_transactions(service)["transactions"][0]
    edited = transaction["text"].replace('"new"', '"edited"')
    assert edit_transaction(service, transaction["entry_id"], edited)["ok"] is True

    # When
    retry = write_inbox_text(service, NEW_TRANSACTION, idempotency_key="k")

    # Then
    assert retry["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def testLoad_shouldParseOnce_whenIncludeListIsUnchanged(
    ledger_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given a service that already knows the included files
    service = _service(ledger_factory(MAIN))
    first = service.load()
    real_load = loader.load_file
    calls = 0

    def counting_load(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(loader, "load_file", counting_load)

    # When
    second = service.load()

    # Then
    assert calls == 1
    assert second.version == first.version
    assert second.contents == first.contents


def testLoad_shouldFollowIncludeGraph_whenKnownFileIsDetachedAndDeleted(
    ledger_factory: Any,
) -> None:
    # Given
    ledger = ledger_factory(MAIN + 'include "extra.bean"\n')
    extra = ledger.root / "extra.bean"
    _write(extra, "2020-01-01 open Equity:Opening\n")
    service = _service(ledger)
    assert extra in service.load().files

    # When
    _write(ledger.main, MAIN)
    extra.unlink()
    snapshot = service.load()

    # Then
    assert set(snapshot.files) == {ledger.main, ledger.inbox}
    assert set(snapshot.contents) == {ledger.main, ledger.inbox}
    assert not snapshot.errors
