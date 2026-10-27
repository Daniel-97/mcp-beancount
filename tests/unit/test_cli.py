"""Unit tests for the command-line interface."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from beancount_mcp import __version__, cli, server
from beancount_mcp.config import Config


def testMainInit_shouldCreateLedgerAndReportPaths_whenPathIsExplicit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], expected_main_ledger: str
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    exit_code = cli.main(["init", str(ledger), "--currency", "EUR"])

    # Then
    captured = capsys.readouterr()
    expected = expected_main_ledger.replace("2026-10-25", date.today().isoformat())
    assert exit_code == 0
    assert f"Ledger creato: {ledger}" in captured.out
    assert f"Inbox creata: {tmp_path / 'inbox.bean'}" in captured.out
    assert ledger.read_text(encoding="utf-8") == expected


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
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger)])

    # Then
    assert exit_code == 0
    assert len(configs) == 1
    assert configs[0].ledger_path == ledger


def testMainServer_shouldSuggestSamePath_whenExplicitLedgerIsMissing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    missing = tmp_path / "missing" / "main.bean"
    calls: list[Config] = []
    monkeypatch.setattr(server, "run", calls.append)

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
    calls: list[Config] = []
    monkeypatch.setattr(server, "run", calls.append)

    # When
    exit_code = cli.main([])

    # Then
    captured = capsys.readouterr()
    assert exit_code == 2
    assert calls == []
    assert "beancount-mcp init --currency EUR" in captured.err
    assert "beancount-mcp /percorso/main.bean" in captured.err


def testMainServer_shouldPassReadOnlyConfig_whenReadOnlyFlagIsPresent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--read-only"])

    # Then
    assert exit_code == 0
    assert configs[0].read_only is True


def testMainServer_shouldPassResolvedInbox_whenInboxOptionIsPresent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "ledger" / "main.bean"
    ledger.parent.mkdir()
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--inbox", "sub/inbox.bean"])

    # Then
    assert exit_code == 0
    assert configs[0].inbox_path == ledger.parent / "sub" / "inbox.bean"


def testMainServer_shouldRejectInvalidQueryLimit_whenLimitIsOutsideRange(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main([str(ledger), "--query-limit", "0"])

    # Then
    assert raised.value.code == 2


def testMainServer_shouldPassStdioTransport_whenTransportIsSpecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--transport", "stdio"])

    # Then
    assert exit_code == 0
    assert configs[0].transport == "stdio"


def testMainServer_shouldPassAllowEditOutsideInbox_whenFlagIsPresent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--allow-edit-outside-inbox"])

    # Then
    assert exit_code == 0
    assert configs[0].allow_edit_outside_inbox is True


def testMainServer_shouldPassQueryLimit_whenValidLimitIsProvided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--query-limit", "250"])

    # Then
    assert exit_code == 0
    assert configs[0].query_limit == 250


def testMainServer_shouldExitCleanly_whenHelpIsRequested() -> None:
    # Given
    arguments = ["--help"]

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)

    # Then
    assert raised.value.code == 0


def testMainServer_shouldPassVerboseConfig_whenVerboseFlagIsPresent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--verbose"])

    # Then
    assert exit_code == 0
    assert configs[0].verbose is True


def testMainServer_shouldLogConfig_whenVerbose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    monkeypatch.setattr(server, "run", lambda config: None)

    # When
    exit_code = cli.main([str(ledger), "--verbose"])

    # Then
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "config: ledger=" in captured.err
    assert "startup: launching MCP server" in captured.err


def testMainServer_shouldDefaultToHttpTransport_whenTransportIsNotSpecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger)])

    # Then
    assert exit_code == 0
    assert configs[0].transport == "http"


def testMainServer_shouldPassHttpTransport_whenRequested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main([str(ledger), "--transport", "http"])

    # Then
    assert exit_code == 0
    assert configs[0].transport == "http"


def testMainServer_shouldRejectLegacyTransportName_whenRequested(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main([str(ledger), "--transport", "streamable-http"])

    # Then
    assert raised.value.code == 2


def testMainServer_shouldPassHttpSettings_whenProvided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    configs: list[Config] = []
    monkeypatch.setattr(server, "run", configs.append)

    # When
    exit_code = cli.main(
        [
            str(ledger),
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "8765",
            "--http-path",
            "/beancount/mcp",
        ]
    )

    # Then
    assert exit_code == 0
    assert configs[0].host == "0.0.0.0"
    assert configs[0].port == 8765
    assert configs[0].http_path == "/beancount/mcp"


def testMainServer_shouldRejectHttpSettings_whenTransportIsStdio(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main([str(ledger), "--transport", "stdio", "--port", "8765"])

    # Then
    assert raised.value.code == 2


def testMainServer_shouldPrintVersion_whenRequested(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given
    arguments = ["--version"]

    # When
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)

    # Then
    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert f"beancount-mcp {__version__}" in captured.out


def testMainServer_shouldWarn_whenHttpHostIsNotLoopback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.touch()
    monkeypatch.setattr(server, "run", lambda config: None)

    # When
    exit_code = cli.main(
        [
            str(ledger),
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
        ]
    )

    # Then
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "non ha autenticazione" in captured.err
