"""Unit tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp import cli, server


def test_init_creates_ledger_and_reports_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expected_main_ledger: str
) -> None:
    ledger = tmp_path / "main.bean"

    exit_code = cli.main(["init", str(ledger), "--currency", "EUR"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Ledger creato: {ledger}" in captured.out
    assert f"Inbox creata: {tmp_path / 'inbox.bean'}" in captured.out
    assert ledger.read_text(encoding="utf-8") == expected_main_ledger


def test_init_refuses_existing_ledger_and_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "main.bean"
    assert cli.main(["init", str(ledger), "--currency", "EUR"]) == 0
    capsys.readouterr()
    before = ledger.read_bytes()

    exit_code = cli.main(["init", str(ledger), "--currency", "EUR"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Errore:" in captured.err
    assert "esiste già e non è vuoto" in captured.err
    assert ledger.read_bytes() == before


def test_init_requires_currency(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["init", str(tmp_path / "main.bean")])

    assert raised.value.code == 2


def test_init_without_path_uses_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "env-main.bean"
    monkeypatch.setenv("BEANCOUNT_MCP_LEDGER", str(ledger))

    exit_code = cli.main(["init", "--currency", "EUR"])

    assert exit_code == 0
    assert ledger.is_file()
    assert (tmp_path / "inbox.bean").is_file()


def test_server_runs_when_ledger_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "main.bean"
    ledger.touch()
    calls: list[None] = []
    monkeypatch.setattr(server, "run", lambda: calls.append(None))

    exit_code = cli.main([str(ledger)])

    assert exit_code == 0
    assert calls == [None]


def test_server_missing_explicit_ledger_suggests_same_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing" / "main.bean"
    calls: list[None] = []
    monkeypatch.setattr(server, "run", lambda: calls.append(None))

    exit_code = cli.main([str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert calls == []
    assert f"Ledger non trovato: {missing}" in captured.err
    assert f"beancount-mcp init {missing} --currency EUR" in captured.err
    assert "beancount-mcp /percorso/main.bean" not in captured.err


def test_server_missing_default_ledger_shows_both_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEANCOUNT_MCP_LEDGER", str(tmp_path / "missing.bean"))
    calls: list[None] = []
    monkeypatch.setattr(server, "run", lambda: calls.append(None))

    exit_code = cli.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert calls == []
    assert "beancount-mcp init --currency EUR" in captured.err
    assert "beancount-mcp /percorso/main.bean" in captured.err


def test_server_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])

    assert raised.value.code == 0
