"""Unit tests for the minimal MCP server."""

from __future__ import annotations

from mcp.server import MCPServer

from beancount_mcp import __version__
from beancount_mcp.server import create_server


def testCreateServer_shouldUseProjectName_whenServerIsCreated() -> None:
    # Given
    expected_name = "beancount-mcp"

    # When
    mcp_server = create_server()

    # Then
    assert isinstance(mcp_server, MCPServer)
    assert mcp_server.name == expected_name


def testCreateServer_shouldUsePackageVersion_whenServerIsCreated() -> None:
    # Given
    expected_version = __version__

    # When
    mcp_server = create_server()

    # Then
    assert mcp_server.version == expected_version
