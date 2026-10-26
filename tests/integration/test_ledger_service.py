"""Integration tests for LedgerService."""

from __future__ import annotations

import shutil
from pathlib import Path

from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService


def testLedgerService_shouldLoadMinimalLedger_whenFilesAreValid(
    fixtures_dir: Path,
) -> None:
    # Given
    config = build_config(str(fixtures_dir / "minimal" / "main.bean"))

    # When
    snapshot = LedgerService(config).load()

    # Then
    assert len(snapshot.entries) == 4
    assert snapshot.errors == ()
    assert {path.name for path in snapshot.files} == {"main.bean", "inbox.bean"}


def testLedgerService_shouldReportNestedIncludes_whenLedgerIsMultifile(
    fixtures_dir: Path,
) -> None:
    # Given
    config = build_config(str(fixtures_dir / "multifile" / "main.bean"))

    # When
    snapshot = LedgerService(config).load()

    # Then
    assert {path.name for path in snapshot.files} == {
        "main.bean",
        "accounts.bean",
        "cash.bean",
        "inbox.bean",
    }


def testLedgerService_shouldReloadFromDisk_whenFileChanges(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    # Given
    ledger_dir = tmp_path / "ledger"
    shutil.copytree(fixtures_dir / "minimal", ledger_dir)
    main = ledger_dir / "main.bean"
    service = LedgerService(build_config(str(main)))
    first = service.load()

    # When
    main.write_text(
        main.read_text(encoding="utf-8") + "\n2026-01-04 open Income:Salary\n",
        encoding="utf-8",
    )
    second = service.load()

    # Then
    assert second.version != first.version
    assert len(second.entries) == len(first.entries) + 1


def testLedgerService_shouldKeepVersionStable_whenIncludedFileIsUnchanged(
    fixtures_dir: Path,
) -> None:
    # Given
    service = LedgerService(build_config(str(fixtures_dir / "minimal" / "main.bean")))

    # When
    first = service.load()
    second = service.load()

    # Then
    assert first.version == second.version


def testLedgerService_shouldReportEmptyLedger_whenMainHasOnlyComments(
    fixtures_dir: Path,
) -> None:
    # Given
    config = build_config(str(fixtures_dir / "empty" / "main.bean"))

    # When
    snapshot = LedgerService(config).load()

    # Then
    assert snapshot.is_empty is True
    assert snapshot.entries == ()
    assert snapshot.errors == ()


def testLedgerService_shouldReportInboxIncluded_whenInboxIsIncluded(
    fixtures_dir: Path,
) -> None:
    # Given
    config = build_config(str(fixtures_dir / "minimal" / "main.bean"))

    # When
    snapshot = LedgerService(config).load()

    # Then
    assert snapshot.inbox.exists is True
    assert snapshot.inbox.included is True
    assert snapshot.inbox.warning is None


def testLedgerService_shouldReportInboxMissing_whenInboxDoesNotExist(
    fixtures_dir: Path,
) -> None:
    # Given
    config = build_config(str(fixtures_dir / "no_inbox" / "main.bean"))

    # When
    snapshot = LedgerService(config).load()

    # Then
    assert snapshot.inbox.exists is False
    assert snapshot.inbox.included is False
    assert snapshot.inbox.warning is not None
    assert "Inbox non trovata" in snapshot.inbox.warning


def testLedgerService_shouldReportInboxNotIncluded_whenInboxExistsButIsNotIncluded(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    # Given
    ledger_dir = tmp_path / "ledger"
    shutil.copytree(fixtures_dir / "no_inbox", ledger_dir)
    (ledger_dir / "inbox.bean").write_text("", encoding="utf-8")
    config = build_config(str(ledger_dir / "main.bean"))

    # When
    snapshot = LedgerService(config).load()

    # Then
    assert snapshot.inbox.exists is True
    assert snapshot.inbox.included is False
    assert snapshot.inbox.warning is not None
    assert "Inbox non inclusa" in snapshot.inbox.warning
