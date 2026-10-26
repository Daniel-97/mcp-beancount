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


def testLedgerService_shouldReloadIncludedFile_whenInboxChanges(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    # Given
    ledger_dir = tmp_path / "ledger"
    shutil.copytree(fixtures_dir / "minimal", ledger_dir)
    service = LedgerService(build_config(str(ledger_dir / "main.bean")))
    first = service.load()

    # When
    (ledger_dir / "inbox.bean").write_text('2026-01-04 note Assets:Cash "test"\n', encoding="utf-8")
    second = service.load()

    # Then
    assert second.version != first.version
    assert len(second.entries) == len(first.entries) + 1


def testLedgerService_shouldLoad_whenInboxIsIncludedButMissing(tmp_path: Path) -> None:
    # Given
    main = tmp_path / "main.bean"
    main.write_text(
        'include "inbox.bean"\n2026-01-01 open Assets:Cash EUR\n',
        encoding="utf-8",
    )

    # When
    snapshot = LedgerService(build_config(str(main))).load()

    # Then
    assert snapshot.inbox.exists is False
    assert snapshot.inbox.included is False
    assert snapshot.inbox.warning is not None
    assert "se non è già inclusa" in snapshot.inbox.warning
    assert len(snapshot.errors) == 1


def testLedgerService_shouldIncludeGlobFilesAndVersion_whenGlobMatches(
    tmp_path: Path,
) -> None:
    # Given
    main = tmp_path / "main.bean"
    parts = tmp_path / "parts"
    parts.mkdir()
    main.write_text(
        'include "parts/*.bean"\n2026-01-01 open Assets:Cash EUR\n',
        encoding="utf-8",
    )
    first_part = parts / "a.bean"
    first_part.write_text("2026-01-01 open Expenses:Food\n", encoding="utf-8")
    (parts / "b.bean").write_text("2026-01-01 open Income:Salary\n", encoding="utf-8")
    service = LedgerService(build_config(str(main)))
    first = service.load()

    # When
    first_part.write_text(
        first_part.read_text(encoding="utf-8") + '2026-01-02 note Expenses:Food "test"\n',
        encoding="utf-8",
    )
    second = service.load()

    # Then
    assert {path.name for path in first.files} == {"main.bean", "a.bean", "b.bean"}
    assert second.version != first.version


def testLedgerService_shouldResolveMainSymlink_whenLedgerIsSymlinked(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    # Given
    real = tmp_path / "real"
    shutil.copytree(fixtures_dir / "minimal", real)
    link_dir = tmp_path / "linkdir"
    link_dir.mkdir()
    link = link_dir / "main.bean"
    link.symlink_to(real / "main.bean")

    # When
    snapshot = LedgerService(build_config(str(link))).load()

    # Then
    assert snapshot.errors == ()
    assert snapshot.inbox.included is True
    assert snapshot.ledger_path == real / "main.bean"
