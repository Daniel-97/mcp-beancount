"""Unit tests for the MCP server registration."""

from __future__ import annotations

import asyncio
from pathlib import Path

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


def testCreateServer_shouldExposeLedgerInfoTool_whenCreated(tmp_path: Path) -> None:
    # Given
    config = build_config(str(tmp_path / "main.bean"))
    mcp_server = create_server(config)

    # When
    tools = asyncio.run(mcp_server.list_tools())

    # Then
    assert [tool.name for tool in tools] == ["ledger_info"]


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
