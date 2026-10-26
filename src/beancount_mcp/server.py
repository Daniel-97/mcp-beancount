"""MCP server entry point."""

from __future__ import annotations

from mcp.server import MCPServer

from beancount_mcp import __version__
from beancount_mcp.config import Config


def create_server() -> MCPServer:
    """Create the MCP server. Tools are registered in later milestones."""
    return MCPServer("beancount-mcp", version=__version__)


def run(config: Config) -> None:
    """Run the MCP server over stdio."""
    create_server().run()
