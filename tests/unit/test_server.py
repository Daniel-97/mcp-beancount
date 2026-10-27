"""Unit tests for the MCP server registration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp.server import MCPServer
from mcp.types import CallToolResult

from beancount_mcp import __version__
from beancount_mcp.config import build_config
from beancount_mcp.server import create_server


def testCreateServer_shouldUseProjectName_whenServerIsCreated(tmp_path: Path) -> None:
    # Given
    expected_name = "beancount-mcp"
    config = build_config(str(tmp_path / "main.bean"))

    # When
    mcp_server = create_server(config)

    # Then
    assert isinstance(mcp_server, MCPServer)
    assert mcp_server.name == expected_name


def testCreateServer_shouldUsePackageVersion_whenServerIsCreated(
    tmp_path: Path,
) -> None:
    # Given
    expected_version = __version__
    config = build_config(str(tmp_path / "main.bean"))

    # When
    mcp_server = create_server(config)

    # Then
    assert mcp_server.version == expected_version


def testCreateServer_shouldExposeAllTools_whenWritable(tmp_path: Path) -> None:
    # Given
    config = build_config(str(tmp_path / "main.bean"))
    mcp_server = create_server(config)

    # When
    tools = asyncio.run(mcp_server.list_tools())

    # Then
    assert [tool.name for tool in tools] == [
        "ledger_info",
        "query",
        "validate",
        "add_transactions",
        "open_account",
        "edit_transaction",
        "delete_transaction",
        "rename_account",
        "rename_tag",
        "rename_link",
        "find_transactions",
    ]


def testCreateServer_shouldExposeOnlyReadTools_whenReadOnly(tmp_path: Path) -> None:
    # Given
    config = build_config(str(tmp_path / "main.bean"), read_only=True)
    mcp_server = create_server(config)

    # When
    tools = asyncio.run(mcp_server.list_tools())

    # Then
    assert [tool.name for tool in tools] == [
        "ledger_info",
        "query",
        "validate",
        "find_transactions",
    ]


def testCreateServer_shouldReturnOkFromLedgerInfo_whenToolIsCalled(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("", encoding="utf-8")
    mcp_server = create_server(build_config(str(ledger)))

    # When
    result = asyncio.run(mcp_server.call_tool("ledger_info", {}))

    # Then
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["ok"] is True


def testCreateServer_shouldReturnStructuredError_whenLedgerDisappears(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("", encoding="utf-8")
    mcp_server = create_server(build_config(str(ledger)))
    ledger.unlink()

    # When
    result = asyncio.run(mcp_server.call_tool("ledger_info", {}))

    # Then
    assert isinstance(result, CallToolResult)
    assert result.structured_content is not None
    assert result.structured_content["ok"] is False
    assert result.structured_content["error"]["code"] == "LEDGER_ERROR"


def testCreateServer_shouldLogToolCalls_whenVerbose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("", encoding="utf-8")
    mcp_server = create_server(build_config(str(ledger), verbose=True))

    # When
    asyncio.run(mcp_server.call_tool("ledger_info", {}))

    # Then
    captured = capsys.readouterr()
    assert "[beancount-mcp] -> ledger_info" in captured.err
    assert "[beancount-mcp] <- ledger_info ok=True" in captured.err
    assert "[beancount-mcp]" not in captured.out


def testCreateServer_shouldLogStartupPhases_whenVerbose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("", encoding="utf-8")

    # When
    create_server(build_config(str(ledger), verbose=True))

    # Then
    captured = capsys.readouterr()
    assert "startup: creating MCP server" in captured.err
    assert "startup: no pending transaction" in captured.err
    assert "startup: loading ledger for diagnostics" in captured.err
    assert "startup: ledger loaded:" in captured.err
    assert "startup: tools registered" in captured.err
    assert "startup: server initialized" in captured.err
    assert "[beancount-mcp]" not in captured.out


def testRun_shouldLogTransportLifecycle_whenVerbose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    ledger = tmp_path / "main.bean"
    ledger.write_text("", encoding="utf-8")
    config = build_config(str(ledger), verbose=True)

    class FakeServer:
        def run(self) -> None:
            pass

    monkeypatch.setattr(
        "beancount_mcp.server.create_server",
        lambda current: FakeServer(),
    )

    # When
    import beancount_mcp.server as server_module

    server_module.run(config)

    # Then
    captured = capsys.readouterr()
    assert "startup: starting stdio transport" in captured.err
    assert "shutdown: server stopped" in captured.err


def testRun_shouldHandleKeyboardInterrupt_whenServerIsInterrupted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    config = build_config(str(tmp_path / "main.bean"), verbose=True)

    class InterruptingServer:
        def run(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        "beancount_mcp.server.create_server",
        lambda current: InterruptingServer(),
    )

    # When
    import beancount_mcp.server as server_module

    server_module.run(config)

    # Then
    captured = capsys.readouterr()
    assert "shutdown: SIGINT received; stopping server" in captured.err
    assert "shutdown: server stopped" in captured.err
    assert "Traceback" not in captured.err
