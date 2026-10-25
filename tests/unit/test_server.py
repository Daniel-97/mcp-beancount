"""Unit tests for the minimal MCP server."""

from __future__ import annotations

from mcp.server import MCPServer

from beancount_mcp import __version__
from beancount_mcp.server import create_server


def test_create_server_uses_project_name_and_version() -> None:
    mcp_server = create_server()

    assert isinstance(mcp_server, MCPServer)
    assert mcp_server.name == "beancount-mcp"
    assert mcp_server.version == __version__
