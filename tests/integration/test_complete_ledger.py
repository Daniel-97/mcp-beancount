"""End-to-end workflows for the complete-ledger MCP interface."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult

from beancount_mcp.change_service import apply_changes
from beancount_mcp.cli import main
from beancount_mcp.config import Config, build_config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.multifile import transaction_dir
from beancount_mcp.server import create_server
from beancount_mcp.source_service import find_entries, get_entry, ledger_config
from beancount_mcp.tools.init_ledger import init_ledger

TX = '2026-01-02 * "Shop" "Coffee"\n  Assets:Cash -10 EUR\n  Expenses:Food 10 EUR\n'


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    (tmp_path / "main.bean").write_text(
        'option "operating_currency" "EUR"\ninclude "inbox.bean"\n'
        "2020-01-01 open Assets:Cash\n2020-01-01 open Expenses:Food\n"
        "2026-01-03 balance Assets:Cash -10 EUR\n"
    )
    (tmp_path / "inbox.bean").write_text(TX + "2026-01-01 price GOLD 2000 USD\n")
    return LedgerService(build_config(str(tmp_path / "main.bean")))


def enabled(service: LedgerService, **flags: Any) -> LedgerService:
    return LedgerService(build_config(str(service.config.ledger_path), **flags))


def batch(service: LedgerService, changes: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    return apply_changes(service, changes, service.load().version, **kwargs)


def entry_id(service: LedgerService, kind: str) -> dict[str, Any]:
    result: dict[str, Any] = find_entries(service, types=[kind])["entries"][0]["entry_id"]
    return result


def test_source_directives_can_be_read_paged_and_filtered(service: LedgerService) -> None:
    first = find_entries(service, limit=2)
    second = find_entries(
        service,
        limit=2,
        offset=first["next_offset"],
        expected_ledger_version=first["ledger_version"],
    )
    assert first["ok"] and second["ok"]
    assert {e["entry_id"]["hash"] for e in first["entries"]}.isdisjoint(
        e["entry_id"]["hash"] for e in second["entries"]
    )
    prices = find_entries(
        service,
        types=["price"],
        file="inbox.bean",
        date_from="2026-01-01",
        date_to="2026-01-01",
        text_contains="GOLD",
    )
    assert prices["count"] == 1
    assert get_entry(service, prices["entries"][0]["entry_id"])["entry"] == prices["entries"][0]
    assert find_entries(service, account="Assets", types=["transaction"])["count"] == 1
    assert find_entries(service, offset=1000)["entries"] == []


def test_source_pages_and_ids_reject_changes(service: LedgerService) -> None:
    first = find_entries(service)
    price = entry_id(service, "price")
    path = service.config.inbox_path
    path.write_text(path.read_text().replace("2000 USD", "2100 USD"))
    assert (
        find_entries(service, expected_ledger_version=first["ledger_version"])["error"]["code"]
        == "VERSION_CONFLICT"
    )
    assert get_entry(service, price)["error"]["code"] == "ENTRY_CHANGED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"offset": -1},
        {"date_from": "bad"},
        {"date_from": "2026-02-01", "date_to": "2026-01-01"},
    ],
)
def test_source_filter_errors_are_structured(
    service: LedgerService, kwargs: dict[str, Any]
) -> None:
    assert find_entries(service, **kwargs)["ok"] is False


def test_multiline_directive_stays_whole_and_can_be_replaced(service: LedgerService) -> None:
    narration = 'first\n2026-01-03 * "pretend"\nlast'
    # Escape inner quotes in a valid multiline narration.
    narration = narration.replace('"', '\\"')
    service.config.inbox_path.write_text(TX.replace('"Coffee"', f'"{narration}"'))
    found = find_entries(service, types=["transaction"])["entries"]
    assert len(found) == 1 and narration in found[0]["text"]
    assert batch(service, [{"op": "replace", "entry_id": found[0]["entry_id"], "text": TX}])["ok"]
    assert not service.load().errors


def test_prices_can_be_corrected_and_deleted(service: LedgerService) -> None:
    result = batch(
        service,
        [
            {
                "op": "replace",
                "entry_id": entry_id(service, "price"),
                "text": "2026-01-01 price GOLD 2100 USD",
            }
        ],
    )
    assert result["ok"] is True
    assert "2100 USD" in find_entries(service, types=["price"])["entries"][0]["text"]
    assert batch(service, [{"op": "delete", "entry_id": entry_id(service, "price")}])["ok"]
    assert find_entries(service, types=["price"])["count"] == 0


def test_split_preserves_assertion_by_validating_only_final_state(service: LedgerService) -> None:
    old = entry_id(service, "transaction")
    before = service.config.inbox_path.read_bytes()
    deleted = batch(service, [{"op": "delete", "entry_id": old}])
    assert deleted["error"]["code"] == "VALIDATION_FAILED"
    assert service.config.inbox_path.read_bytes() == before
    replacement = TX.replace('"Coffee"', '"Part 1"').replace("10 EUR", "4 EUR")
    replacement += TX.replace('"Coffee"', '"Part 2"').replace("10 EUR", "6 EUR")
    changes: list[dict[str, Any]] = [
        {"op": "delete", "entry_id": old},
        {"op": "append", "text": replacement},
    ]
    preview = batch(service, changes, dry_run=True)
    assert preview["ok"] and preview["files"][0]["before"] is not None
    assert service.config.inbox_path.read_bytes() == before
    assert batch(service, changes)["ok"] is True
    assert find_entries(service, types=["transaction"])["count"] == 2
    assert not service.load().errors


def test_balance_assertions_require_explicit_opt_in_and_observed_amount(
    service: LedgerService,
) -> None:
    text = "2026-01-04 balance Assets:Cash -10 EUR"
    assert batch(service, [{"op": "append", "text": text}])["error"]["code"] == "BALANCE_PROTECTED"
    assert batch(service, [{"op": "append", "text": text}], allow_balance_changes=True)["ok"]
    incorrect = text.replace("-10", "-20")
    assert (
        batch(service, [{"op": "append", "text": incorrect}], allow_balance_changes=True)["error"][
            "code"
        ]
        == "VALIDATION_FAILED"
    )
    service = enabled(service, allow_edit_outside_inbox=True)
    balance = entry_id(service, "balance")
    assert (
        batch(service, [{"op": "delete", "entry_id": balance}])["error"]["code"]
        == "BALANCE_PROTECTED"
    )
    assert batch(service, [{"op": "delete", "entry_id": balance}], allow_balance_changes=True)["ok"]


def test_padding_remains_protected(service: LedgerService) -> None:
    result = batch(
        service,
        [{"op": "append", "text": "2026-01-01 pad Assets:Cash Equity:Opening-Balances"}],
        allow_balance_changes=True,
    )
    assert result["error"]["code"] == "PAD_PROTECTED"


def test_create_include_and_archive_are_one_atomic_batch(service: LedgerService) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    old_id = entry_id(service, "transaction")
    version = service.load().version
    changes: list[dict[str, Any]] = [
        {"op": "create_file", "file": "2026/journal.bean"},
        {"op": "add_include", "file": "2026/journal.bean"},
        {"op": "move", "entry_id": old_id, "file": "2026/journal.bean"},
    ]
    preview = apply_changes(service, changes, version, dry_run=True)
    assert preview["ok"] is True
    target = service.config.ledger_path.parent / "2026/journal.bean"
    assert not target.parent.exists()
    result = apply_changes(service, changes, version)
    assert result["ok"] is True
    assert target.read_text() == TX
    assert "Coffee" not in service.config.inbox_path.read_text()
    assert find_entries(service, types=["transaction"])["entries"][0]["entry_id"]["file"] == str(
        target
    )
    assert not service.load().errors


def test_attach_existing_data_and_remove_include_without_deleting_data(
    service: LedgerService,
) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    target = service.config.ledger_path.parent / "prices.bean"
    target.write_text("2026-01-01 price SILVER 20 USD\n")
    assert batch(service, [{"op": "add_include", "file": "prices.bean"}])["ok"]
    assert find_entries(service, types=["price"])["count"] == 2
    assert batch(service, [{"op": "remove_include", "pattern": "prices.bean"}])["ok"]
    assert find_entries(service, types=["price"])["count"] == 1
    assert target.read_text() == "2026-01-01 price SILVER 20 USD\n"


def test_config_and_plugin_permissions_are_independent(service: LedgerService) -> None:
    option = {"op": "set_option", "name": "operating_currency", "values": ["USD", "EUR"]}
    assert batch(service, [option])["error"]["code"] == "CONFIG_NOT_ALLOWED"
    service = enabled(service, allow_config_changes=True)
    assert batch(service, [option])["ok"]
    assert service.load().options["operating_currency"] == ["USD", "EUR"]
    assert (
        batch(service, [{"op": "set_plugins", "plugins": []}])["error"]["code"]
        == "PLUGIN_NOT_ALLOWED"
    )
    result = ledger_config(service)
    assert result["capabilities"]["config_changes"] is True
    assert result["capabilities"]["plugin_changes"] is False
    assert len([s for s in result["statements"] if s["name"] == "operating_currency"]) == 2
    assert batch(service, [{**option, "values": None}])["ok"]
    assert service.load().options["operating_currency"] == []


def test_installed_plugins_can_be_added_and_removed_explicitly(service: LedgerService) -> None:
    service = enabled(service, allow_plugin_changes=True)
    assert batch(
        service, [{"op": "set_plugins", "plugins": [{"name": "beancount.plugins.auto_accounts"}]}]
    )["ok"]
    assert any(s["type"] == "plugin" for s in ledger_config(service)["statements"])
    assert batch(service, [{"op": "set_plugins", "plugins": []}])["ok"]
    assert not any(s["type"] == "plugin" for s in ledger_config(service)["statements"])


@pytest.mark.parametrize(
    "changes,code",
    [
        ([{"op": "create_file", "file": "new.bean"}], "ENTRY_NOT_IN_INBOX"),
        ([{"op": "append", "file": "main.bean", "text": TX}], "ENTRY_NOT_IN_INBOX"),
        ([{"op": "append", "text": 'option "title" "bad"'}], "VALIDATION_FAILED"),
        ([{"op": "unknown"}], "VALIDATION_FAILED"),
        ([{"op": "append", "text": TX, "unknown": 1}], "VALIDATION_FAILED"),
        ([{"op": "append", "text": 5}], "VALIDATION_FAILED"),
        ([{"op": "set_option", "name": "title", "values": "bad"}], "CONFIG_NOT_ALLOWED"),
    ],
)
def test_batch_rejections_do_not_touch_user_data(
    service: LedgerService, changes: list[dict[str, Any]], code: str
) -> None:
    before = {p: p.read_bytes() for p in service.config.ledger_path.parent.glob("*.bean")}
    result = batch(service, changes)
    assert result["error"]["code"] == code
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize(
    "file", ["../outside.bean", ".main.bean.txn/evil.bean", "code.py", "main.bean"]
)
def test_file_creation_cannot_escape_or_overwrite(service: LedgerService, file: str) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    result = batch(service, [{"op": "create_file", "file": file}])
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"


def test_symlink_escape_is_rejected(service: LedgerService, tmp_path: Path) -> None:
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    service = enabled(service, allow_edit_outside_inbox=True)
    result = batch(service, [{"op": "create_file", "file": "escape/new.bean"}])
    assert result["error"]["code"] == "PATH_NOT_ALLOWED"
    assert not (outside / "new.bean").exists()


def test_new_file_must_be_included_and_inbox_cannot_be_detached(service: LedgerService) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    assert batch(service, [{"op": "create_file", "file": "unreachable.bean"}])["ok"] is False
    assert not (service.config.ledger_path.parent / "unreachable.bean").exists()
    assert batch(service, [{"op": "remove_include", "pattern": "inbox.bean"}])["ok"] is False


def test_duplicate_ids_and_stale_versions_reject_entire_batch(service: LedgerService) -> None:
    price = entry_id(service, "price")
    duplicate = [{"op": "delete", "entry_id": price}, {"op": "delete", "entry_id": price}]
    assert batch(service, duplicate)["error"]["code"] == "CHANGE_CONFLICT"
    assert (
        apply_changes(service, [{"op": "delete", "entry_id": price}], "stale")["error"]["code"]
        == "VERSION_CONFLICT"
    )
    assert get_entry(service, price)["ok"] is True


def test_crlf_files_can_be_modified(service: LedgerService) -> None:
    path = service.config.inbox_path
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = batch(service, [{"op": "delete", "entry_id": entry_id(service, "price")}])
    assert result["ok"] is True
    assert not service.load().errors


def test_crash_rolls_back_existing_files_and_removes_created_files(service: LedgerService) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    main_path = service.config.ledger_path
    before = main_path.read_bytes()
    code = """
import os,sys
from pathlib import Path
from beancount_mcp import multifile
from beancount_mcp.writer import atomic_write,write_lock
main=Path(sys.argv[1]); new=main.parent/'2026/new.bean'
calls=0
def crash(path,content):
    global calls
    atomic_write(path,content)
    calls+=1
    if calls==2: os._exit(23)
multifile.atomic_write=crash
with write_lock(main):
    multifile.commit_files(main,{new:'; new\\n',main:main.read_text()+'; modified\\n'})
"""
    result = subprocess.run([sys.executable, "-c", code, str(main_path)], timeout=10, check=False)
    assert result.returncode == 23
    created = main_path.parent / "2026/new.bean"
    assert created.exists()
    create_server(service.config)
    assert main_path.read_bytes() == before
    assert not created.exists()
    assert not transaction_dir(main_path).exists()


def test_init_preview_creation_and_refusal_to_overwrite(tmp_path: Path) -> None:
    config = build_config(str(tmp_path / "new/main.bean"), inbox="inbox/new.bean", allow_init=True)
    assert init_ledger(config, "EUR", dry_run=True)["ok"]
    assert not config.ledger_path.parent.exists()
    assert init_ledger(config, "EUR")["ok"]
    assert not LedgerService(config).load().errors
    assert init_ledger(config, "EUR")["error"]["code"] == "ALREADY_INITIALIZED"
    assert (
        init_ledger(build_config(str(tmp_path / "other.bean")), "EUR")["error"]["code"]
        == "INIT_NOT_ALLOWED"
    )


def test_mcp_read_only_and_bootstrap_registration(tmp_path: Path) -> None:
    config = build_config(str(tmp_path / "new.bean"), allow_init=True)
    server = create_server(config)
    result = asyncio.run(server.call_tool("init_ledger", {"currency": "EUR"}))
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None and result.structured_content["ok"]
    readonly = create_server(build_config(str(config.ledger_path), read_only=True, allow_init=True))
    names = [tool.name for tool in asyncio.run(readonly.list_tools())]
    assert "find_entries" in names and "get_entry" in names and "ledger_config" in names
    assert "apply_changes" not in names and "init_ledger" not in names
    read_result = asyncio.run(readonly.call_tool("find_entries", {"types": ["open"]}))
    assert isinstance(read_result, CallToolResult)
    assert read_result.structured_content is not None
    assert read_result.structured_content["count"] == 1


def test_cli_can_start_missing_ledger_only_with_allow_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs: list[Config] = []
    monkeypatch.setattr("beancount_mcp.cli.server.run", configs.append)
    path = str(tmp_path / "missing.bean")
    assert main([path]) == 2
    assert main(["--allow-init", "--allow-config-changes", "--allow-plugin-changes", path]) == 0
    assert (
        configs[0].allow_init
        and configs[0].allow_config_changes
        and configs[0].allow_plugin_changes
    )


def test_mcp_batch_changes_nontransaction_directive(service: LedgerService) -> None:
    server = create_server(service.config)
    result = asyncio.run(
        server.call_tool(
            "apply_changes",
            {
                "changes": [{"op": "delete", "entry_id": entry_id(service, "price")}],
                "expected_ledger_version": service.load().version,
            },
        )
    )
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None and result.structured_content["ok"]
    assert find_entries(service, types=["price"])["count"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"op": "set_option", "name": "title", "values": "bad"},
        {"op": "set_option", "name": "title", "values": [1]},
        {"op": "set_option", "name": 'title"\nplugin', "values": ["bad"]},
        {"op": "set_plugins", "plugins": "bad"},
        {"op": "set_plugins", "plugins": [{"name": "bad;module"}]},
        {"op": "set_plugins", "plugins": [{"name": "module", "config": 1}]},
        {"op": "set_plugins", "plugins": [{"name": "module", "extra": "bad"}]},
        {"op": "replace", "entry_id": [], "text": TX},
        {"op": "create_file", "file": "new.bean", "text": 'plugin "module"'},
    ],
)
def test_malformed_changes_cannot_bypass_planner_checks(
    service: LedgerService, change: dict[str, Any]
) -> None:
    service = enabled(
        service, allow_config_changes=True, allow_plugin_changes=True, allow_edit_outside_inbox=True
    )
    before = service.config.ledger_path.read_bytes()
    assert batch(service, [change])["error"]["code"] == "VALIDATION_FAILED"
    assert service.config.ledger_path.read_bytes() == before


def test_config_repeated_target_rejects_ambiguous_batch(service: LedgerService) -> None:
    service = enabled(service, allow_config_changes=True)
    change = {"op": "set_option", "name": "title", "values": ["one"]}
    assert (
        batch(service, [change, {**change, "values": ["two"]}])["error"]["code"]
        == "CHANGE_CONFLICT"
    )


def test_unknown_option_or_plugin_cannot_be_committed(service: LedgerService) -> None:
    service = enabled(service, allow_config_changes=True, allow_plugin_changes=True)
    before = service.config.ledger_path.read_bytes()
    invalid_changes: list[dict[str, Any]] = [
        {"op": "set_option", "name": "imaginary_setting", "values": ["bad"]},
        {"op": "set_plugins", "plugins": [{"name": "imaginary_beancount_plugin"}]},
    ]
    for change in invalid_changes:
        assert batch(service, [change])["ok"] is False
        assert service.config.ledger_path.read_bytes() == before


def test_move_rejects_scoped_metadata_files(service: LedgerService) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    path = service.config.inbox_path
    path.write_text("pushtag #trip\n" + TX + "poptag #trip\n")
    changes: list[dict[str, Any]] = [
        {"op": "create_file", "file": "new.bean"},
        {"op": "add_include", "file": "new.bean"},
        {"op": "move", "entry_id": entry_id(service, "transaction"), "file": "new.bean"},
    ]
    assert batch(service, changes)["error"]["code"] == "MOVE_CONTEXT_DEPENDENT"
    assert not (path.parent / "new.bean").exists()


def test_created_file_rolls_back_after_later_write_failure(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp import multifile
    from beancount_mcp.writer import atomic_write

    service = enabled(service, allow_edit_outside_inbox=True)
    inbox_before = service.config.inbox_path.read_bytes()
    main_before = service.config.ledger_path.read_bytes()
    calls = 0

    def fail_second(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("write failed")
        atomic_write(path, content)

    monkeypatch.setattr(multifile, "atomic_write", fail_second)
    changes: list[dict[str, Any]] = [
        {"op": "create_file", "file": "new.bean"},
        {"op": "add_include", "file": "new.bean"},
        {"op": "move", "entry_id": entry_id(service, "transaction"), "file": "new.bean"},
    ]
    assert batch(service, changes)["error"]["code"] == "LEDGER_ERROR"
    assert service.config.inbox_path.read_bytes() == inbox_before
    assert service.config.ledger_path.read_bytes() == main_before
    assert not (service.config.ledger_path.parent / "new.bean").exists()
    assert not transaction_dir(service.config.ledger_path).exists()


def test_recovery_keeps_external_changes_to_new_file(service: LedgerService) -> None:
    import hashlib
    import json

    main_path = service.config.ledger_path
    directory = transaction_dir(main_path)
    (directory / "backup").mkdir(parents=True)
    created = main_path.parent / "new.bean"
    created.write_text("; external correction\n")
    journal = {
        "version": 3,
        "files": [
            {
                "path": str(created),
                "backup": str(directory / "backup/0"),
                "original_sha256": None,
                "new_sha256": hashlib.sha256(b"; new\n").hexdigest(),
            }
        ],
    }
    (directory / "journal.json").write_text(json.dumps(journal))
    with pytest.raises(RuntimeError, match="Recovery"):
        create_server(service.config)
    assert created.read_text() == "; external correction\n"
    assert (directory / "journal.json").exists()


def test_new_file_created_externally_before_commit_is_not_overwritten(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp.multifile import commit_files

    service = enabled(service, allow_edit_outside_inbox=True)
    target = service.config.ledger_path.parent / "new.bean"
    before = service.config.ledger_path.read_bytes()

    def racing_commit(*args: Any, **kwargs: Any) -> None:
        target.write_text("; external data\n")
        commit_files(*args, **kwargs)

    monkeypatch.setattr("beancount_mcp.change_service.commit_files", racing_commit)
    changes: list[dict[str, Any]] = [
        {"op": "create_file", "file": "new.bean"},
        {"op": "add_include", "file": "new.bean"},
    ]
    assert batch(service, changes)["ok"] is False
    assert target.read_text() == "; external data\n"
    assert service.config.ledger_path.read_bytes() == before


def test_bootstrap_failure_restores_absent_main_and_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp import multifile
    from beancount_mcp.writer import atomic_write

    config = build_config(str(tmp_path / "main.bean"), allow_init=True)
    calls = 0

    def fail_second(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("write failed")
        atomic_write(path, content)

    monkeypatch.setattr(multifile, "atomic_write", fail_second)
    assert init_ledger(config, "EUR")["error"]["code"] == "LEDGER_ERROR"
    assert not config.ledger_path.exists() and not config.inbox_path.exists()
    assert not transaction_dir(config.ledger_path).exists()


def test_reads_cannot_observe_intermediate_multifile_state(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from beancount_mcp import multifile
    from beancount_mcp.ledger import LedgerError
    from beancount_mcp.writer import atomic_write

    service = enabled(service, allow_edit_outside_inbox=True)
    observations = []

    def read_during_commit(path: Path, content: str) -> None:
        atomic_write(path, content)
        with pytest.raises(LedgerError, match="Transazione multi-file"):
            service.load()
        observations.append(path)

    monkeypatch.setattr(multifile, "atomic_write", read_during_commit)
    changes: list[dict[str, Any]] = [
        {"op": "create_file", "file": "new.bean"},
        {"op": "add_include", "file": "new.bean"},
        {"op": "move", "entry_id": entry_id(service, "transaction"), "file": "new.bean"},
    ]
    assert batch(service, changes)["ok"] is True
    assert len(observations) == 3
    assert not service.load().errors


@pytest.mark.parametrize(
    "kind,text",
    [
        ("open", "2026-01-01 open Assets:Unused"),
        ("close", "2026-12-01 close Assets:Cash"),
        ("commodity", '2026-01-01 commodity GOLD\n  name: "Gold"'),
        ("note", '2026-01-01 note Assets:Cash "Memo"'),
        ("event", '2026-01-01 event "location" "Rome"'),
        ("custom", '2026-01-01 custom "example" "value"'),
        ("query", '2026-01-01 query "example" "SELECT account"'),
    ],
)
def test_generic_read_write_delete_covers_other_dated_types(
    service: LedgerService, kind: str, text: str
) -> None:
    assert batch(service, [{"op": "append", "text": text}])["ok"]
    entries = find_entries(service, types=[kind], file="inbox.bean")["entries"]
    assert len(entries) == 1
    assert get_entry(service, entries[0]["entry_id"])["entry"]["type"] == kind
    assert batch(service, [{"op": "delete", "entry_id": entries[0]["entry_id"]}])["ok"]
    assert find_entries(service, types=[kind], file="inbox.bean")["count"] == 0
    assert not service.load().errors


def test_document_move_keeps_original_reference(service: LedgerService) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    receipt = service.config.ledger_path.parent / "receipt.pdf"
    receipt.write_bytes(b"original document")
    assert batch(
        service, [{"op": "append", "text": '2026-01-01 document Assets:Cash "receipt.pdf"'}]
    )["ok"]
    document = entry_id(service, "document")
    changes: list[dict[str, Any]] = [
        {"op": "create_file", "file": "archive/documents.bean"},
        {"op": "add_include", "file": "archive/documents.bean"},
        {"op": "move", "entry_id": document, "file": "archive/documents.bean"},
    ]
    assert batch(service, changes)["ok"]
    from beancount.core.data import Document

    documents = [entry for entry in service.load().entries if isinstance(entry, Document)]
    assert len(documents) == 1 and documents[0].filename == str(receipt)
    moved = entry_id(service, "document")
    assert batch(service, [{"op": "delete", "entry_id": moved}])["ok"]
    assert receipt.read_bytes() == b"original document"


def test_org_heading_quotes_do_not_hide_source_entries(service: LedgerService) -> None:
    path = service.config.inbox_path
    path.write_text('* Unmatched "quote in an org heading\n' + TX)
    assert not service.load().errors
    found = find_entries(service, types=["transaction"])
    assert found["count"] == 1 and found["entries"][0]["text"] == TX


def test_new_file_can_satisfy_previously_empty_absolute_include_glob(
    service: LedgerService,
) -> None:
    service = enabled(service, allow_edit_outside_inbox=True)
    root = service.config.ledger_path.parent
    with service.config.ledger_path.open("a") as handle:
        handle.write(f'include "{root}/archive/*.bean"\n')
    assert batch(service, [{"op": "create_file", "file": "archive/new.bean"}])["ok"]
    assert not service.load().errors
