"""Regression tests for snapshot consistency, recovery, renames, and retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from beancount import loader
from mcp.types import CallToolResult

from beancount_mcp.config import build_config
from beancount_mcp.entry_service import delete_transaction
from beancount_mcp.ledger import LedgerService
from beancount_mcp.multifile import (
    TransactionError,
    recover_pending_transaction,
    transaction_dir,
)
from beancount_mcp.server import create_server
from beancount_mcp.tools.add_transactions import add_transactions
from beancount_mcp.tools.find_transactions import find_transactions
from beancount_mcp.tools.rename import rename_account, rename_link, rename_tag

TRANSACTION = (
    '2026-01-01 * "Shop A" "Coffee" #food ^receipt\n  Assets:Cash -10 EUR\n  Expenses:Food 10 EUR\n'
)


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    main = tmp_path / "main.bean"
    main.write_text(
        'include "inbox.bean"\n2020-01-01 open Assets:Cash\n2020-01-01 open Expenses:Food\n'
    )
    (tmp_path / "inbox.bean").write_text(TRANSACTION)
    return LedgerService(build_config(str(main), allow_edit_outside_inbox=True))


def test_find_uses_snapshot_ids_when_file_changes_after_loading(service: LedgerService) -> None:
    class RacingService(LedgerService):
        def load(self) -> Any:
            snapshot = super().load()
            self.config.inbox_path.write_text(TRANSACTION.replace("Shop A", "Shop B"))
            return snapshot

    found = find_transactions(RacingService(service.config), payee="Shop A")
    transaction = found["transactions"][0]
    assert transaction["payee"] == "Shop A"
    assert '"Shop A"' in transaction["text"]
    result = delete_transaction(service, transaction["entry_id"])
    assert result["error"]["code"] == "ENTRY_CHANGED"
    assert "Shop B" in service.config.inbox_path.read_text()


def test_load_retries_when_file_changes_during_parse(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_load = loader.load_file
    calls = 0

    def racing_load(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            service.config.inbox_path.write_text(TRANSACTION.replace("Shop A", "Shop B"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(loader, "load_file", racing_load)
    snapshot = service.load()
    assert calls == 3
    assert b"Shop B" in snapshot.contents[service.config.inbox_path]
    found = find_transactions(service, payee="Shop B")
    assert found["count"] == 1


def test_load_retries_when_include_graph_changes(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_load = loader.load_file
    extra = service.config.ledger_path.parent / "extra.bean"
    calls = 0

    def racing_load(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            extra.write_text("; newly included\n")
            with service.config.ledger_path.open("a") as handle:
                handle.write('include "extra.bean"\n')
        return real_load(*args, **kwargs)

    monkeypatch.setattr(loader, "load_file", racing_load)
    snapshot = service.load()
    assert calls == 3
    assert snapshot.contents[extra] == b"; newly included\n"


def test_load_rejects_continuously_changing_files(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_load = loader.load_file

    def racing_load(*args: Any, **kwargs: Any) -> Any:
        result = real_load(*args, **kwargs)
        with service.config.inbox_path.open("a") as handle:
            handle.write("; concurrent edit\n")
        return result

    monkeypatch.setattr(loader, "load_file", racing_load)
    result = find_transactions(service)
    assert result["error"]["code"] == "LEDGER_ERROR"


@pytest.mark.parametrize("kind", ["account", "tag", "link"])
def test_rename_preserves_multiline_strings(service: LedgerService, kind: str) -> None:
    narration = (
        'first line \\"quoted\\"\n'
        "  Assets:Cash words\n"
        "2026-01-02 * #food ^receipt\n"
        "pushtag #food\n"
        "last line"
    )
    original = TRANSACTION.replace('"Coffee"', f'"{narration}"')
    service.config.inbox_path.write_text(original)
    assert not service.load().errors
    if kind == "account":
        result = rename_account(service, "Assets:Cash", "Assets:Bank")
    elif kind == "tag":
        result = rename_tag(service, "food", "meals")
    else:
        result = rename_link(service, "receipt", "invoice")
    assert result["ok"] is True
    assert narration in service.config.inbox_path.read_text()
    assert not service.load().errors


def test_retry_survives_restart_and_stale_version(service: LedgerService) -> None:
    version = service.load().version
    first = add_transactions(
        service, TRANSACTION, idempotency_key="request-1", expected_ledger_version=version
    )
    assert first["ok"] is True and first["replayed"] is False
    written = service.config.inbox_path.read_bytes()
    retry = add_transactions(
        LedgerService(service.config),
        TRANSACTION,
        idempotency_key="request-1",
        expected_ledger_version=version,
    )
    assert retry["ok"] is True and retry["replayed"] is True
    assert retry["ledger_version"] == first["ledger_version"]
    assert service.config.inbox_path.read_bytes() == written


def test_reused_key_rejects_different_payload(service: LedgerService) -> None:
    assert add_transactions(service, TRANSACTION, idempotency_key="request-1")["ok"]
    written = service.config.inbox_path.read_bytes()
    result = add_transactions(
        service, TRANSACTION.replace("Coffee", "Lunch"), idempotency_key="request-1"
    )
    assert result["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert service.config.inbox_path.read_bytes() == written


def test_dry_run_does_not_consume_key(service: LedgerService) -> None:
    before = service.config.inbox_path.read_bytes()
    result = add_transactions(service, TRANSACTION, idempotency_key="request-1", dry_run=True)
    assert result["ok"] is True
    assert service.config.inbox_path.read_bytes() == before
    result = add_transactions(service, TRANSACTION, idempotency_key="request-1")
    assert result["ok"] is True and result["replayed"] is False


@pytest.mark.parametrize("key", ["", "   ", "x" * 201])
def test_invalid_idempotency_key_is_rejected(service: LedgerService, key: str) -> None:
    result = add_transactions(service, TRANSACTION, idempotency_key=key)
    assert result["error"]["code"] == "VALIDATION_FAILED"


def test_mcp_exposes_idempotency_key(service: LedgerService) -> None:
    server = create_server(service.config)
    arguments = {"text": TRANSACTION, "idempotency_key": "request-1"}
    first = asyncio.run(server.call_tool("add_transactions", arguments))
    retry = asyncio.run(server.call_tool("add_transactions", arguments))
    assert isinstance(first, CallToolResult)
    assert isinstance(retry, CallToolResult)
    assert first.structured_content is not None
    assert retry.structured_content is not None
    assert first.structured_content["replayed"] is False
    assert retry.structured_content["replayed"] is True


def test_crashed_writer_releases_lock_and_startup_recovers(service: LedgerService) -> None:
    inbox = service.config.inbox_path
    before = inbox.read_bytes()
    code = """
import os, sys
from pathlib import Path
from beancount_mcp import multifile
from beancount_mcp.writer import atomic_write, write_lock
main, inbox = map(Path, sys.argv[1:])
def crash_after_replace(path, content):
    atomic_write(path, content)
    os._exit(23)
multifile.atomic_write = crash_after_replace
with write_lock(main):
    multifile.commit_files(main, {inbox: inbox.read_text() + "; pending\\n"})
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(service.config.ledger_path), str(inbox)],
        timeout=10,
        check=False,
    )
    assert result.returncode == 23
    assert inbox.read_bytes() != before
    assert transaction_dir(service.config.ledger_path).exists()
    create_server(service.config)
    assert inbox.read_bytes() == before
    assert not transaction_dir(service.config.ledger_path).exists()
    assert add_transactions(service, TRANSACTION)["ok"] is True


@pytest.mark.parametrize("external", ["external correction\n", None])
def test_recovery_preserves_external_changes_and_all_backups(
    service: LedgerService, external: str | None
) -> None:
    main = service.config.ledger_path
    inbox = service.config.inbox_path
    directory = transaction_dir(main)
    backups = directory / "backup"
    backups.mkdir(parents=True)
    entries = []
    for index, path in enumerate([main, inbox]):
        original = path.read_text()
        modified = original + "; pending\n"
        backup = backups / str(index)
        backup.write_text(original)
        path.write_text(modified)
        entries.append(
            {
                "path": str(path),
                "backup": str(backup),
                "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                "new_sha256": hashlib.sha256(modified.encode()).hexdigest(),
            }
        )
    (directory / "journal.json").write_text(json.dumps({"version": 2, "files": entries}))
    if external is None:
        inbox.unlink()
    else:
        inbox.write_text(external)
    before_main = main.read_bytes()
    with pytest.raises(TransactionError, match="modificato esternamente"):
        recover_pending_transaction(main)
    assert main.read_bytes() == before_main
    assert inbox.exists() is (external is not None)
    if external is not None:
        assert inbox.read_text() == external
    assert (backups / "0").exists() and (backups / "1").exists()
    assert (directory / "journal.json").exists()


def test_retry_recognizes_write_after_sync_failure(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp import writer

    real_sync = writer.fsync_directory

    def fail_sync(path: Path) -> None:
        raise OSError("directory sync failed")

    monkeypatch.setattr(writer, "fsync_directory", fail_sync)
    first = add_transactions(service, TRANSACTION, idempotency_key="request-1")
    assert first["error"]["code"] == "LEDGER_ERROR"
    written = service.config.inbox_path.read_bytes()
    monkeypatch.setattr(writer, "fsync_directory", real_sync)
    retry = add_transactions(service, TRANSACTION, idempotency_key="request-1")
    assert retry["ok"] is True and retry["replayed"] is True
    assert service.config.inbox_path.read_bytes() == written


def test_init_keeps_inbox_when_sync_fails_after_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp.init import InitError, create_ledger

    def fail_sync(path: Path) -> None:
        raise OSError("directory sync failed")

    monkeypatch.setattr("beancount_mcp.init.fsync_directory", fail_sync)
    main = tmp_path / "main.bean"
    with pytest.raises(InitError, match="directory sync failed"):
        create_ledger(main, "EUR")
    assert (tmp_path / "inbox.bean").exists()
    assert not LedgerService(build_config(str(main))).load().errors
