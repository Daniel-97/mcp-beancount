"""MCP server entry point."""

from __future__ import annotations

from mcp.server import MCPServer


def create_server() -> MCPServer:
    """Create the MCP server. Tools are registered in later milestones."""
    return MCPServer("beancount-mcp")


def run() -> None:
    """Run the MCP server over stdio."""
    create_server().run()
