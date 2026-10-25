"""Unit tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp import cli, server


def testMainInit_shouldCreateLedgerAndReportPaths_whenPathIsExplicit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expected_main_ledger: str
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    exit_code = cli.main(["init", str(ledger), "--currency", "EUR"])

    # Then
    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"Ledger creato: {ledger}" in captured.out
    assert f"Inbox creata: {tmp_path / 'inbox.bean'}" in captured.out
    assert ledger.read_text(encoding="utf-8") == expected_main_ledger


def testMainInit_shouldReturnErrorAndKeepLedger_whenLedgerAlreadyExists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    assert cli.main(["init", str(ledger), "--currency", "EUR"]) == 0
    capsys.readouterr()
    before = ledger.read_bytes()

    # When
    exit_code = cli.main(["init", str(ledger), "--currency", "EUR"])

    # Then
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Errore:" in captured.err
    assert "esiste già e non è vuoto" in captured.err
    assert ledger.read_bytes() == before


def testMainInit_shouldExitWithUsageError_whenCurrencyIsMissing(tmp_path: Path) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main(["init", str(ledger)])

    # Then
    assert raised.value.code == 2


def testMainInit_shouldUseEnvironmentPath_whenPathIsMissing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "env-main.bean"
    monkeypatch.setenv("BEANCOUNT_MCP_LEDGER", str(ledger))

    # When
    exit_code = cli.main(["init", "--currency", "EUR"])

    # Then
    assert exit_code == 0
    assert ledger.is_file()
    assert (tmp_path / "inbox.bean").is_file()


def testMainServer_shouldStartServer_whenLedgerExists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    calls: list[None] = []
    monkeypatch.setattr(server, "run", lambda: calls.append(None))

    # When
    exit_code = cli.main([str(ledger)])

    # Then
    assert exit_code == 0
    assert calls == [None]


def testMainServer_shouldSuggestSamePath_whenExplicitLedgerIsMissing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    missing = tmp_path / "missing" / "main.bean"
    calls: list[None] = []
    monkeypatch.setattr(server, "run", lambda: calls.append(None))

    # When
    exit_code = cli.main([str(missing)])

    # Then
    captured = capsys.readouterr()
    assert exit_code == 2
    assert calls == []
    assert f"Ledger non trovato: {missing}" in captured.err
    assert f"beancount-mcp init {missing} --currency EUR" in captured.err
    assert "beancount-mcp /percorso/main.bean" not in captured.err


def testMainServer_shouldShowBothStartingPaths_whenDefaultLedgerIsMissing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    monkeypatch.setenv("BEANCOUNT_MCP_LEDGER", str(tmp_path / "missing.bean"))
    calls: list[None] = []
    monkeypatch.setattr(server, "run", lambda: calls.append(None))

    # When
    exit_code = cli.main([])

    # Then
    captured = capsys.readouterr()
    assert exit_code == 2
    assert calls == []
    assert "beancount-mcp init --currency EUR" in captured.err
    assert "beancount-mcp /percorso/main.bean" in captured.err


def testMainServer_shouldExitCleanly_whenHelpIsRequested() -> None:
    # Given
    arguments = ["--help"]

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)

    # Then
    assert raised.value.code == 0
