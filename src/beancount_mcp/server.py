"""MCP server entry point."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from beancount_mcp import __version__
from beancount_mcp.config import Config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.ledger_info import build_ledger_info
from beancount_mcp.tools.query import run_query


def create_server(config: Config) -> MCPServer:
    """Create the MCP server with the ledger tools registered."""
    mcp = MCPServer("beancount-mcp", version=__version__)
    service = LedgerService(config)

    @mcp.tool()
    def ledger_info() -> dict[str, Any]:
        """Return a compact overview of the Beancount ledger.

        Call this at the start of a session, before querying or writing.
        Returns included files, ledger version, operating currencies, accounts,
        transaction date range, preexisting error count, top tags/links, inbox
        status, read-only mode, and whether edits outside the inbox are allowed.

        Examples:
        - Call with no arguments to discover the accounts available.
        - Use ledger_version when calling a write tool with
          expected_ledger_version.
        - Check inbox.included before attempting any write.
        """
        return build_ledger_info(service)

    @mcp.tool()
    def query(
        bql: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Execute a read-only BQL query against the current ledger.

        Only tabular read statements are accepted: SELECT, BALANCES, JOURNAL.
        PRINT, CREATE TABLE and INSERT are rejected. Rows are paginated with
        limit (1-1000, default from server configuration) and offset.

        Examples:
        - SELECT account, SUM(position) WHERE date >= 2026-01-01 GROUP BY account
        - SELECT date, payee, narration, position WHERE account = 'Expenses:Food' ORDER BY date DESC
        - SELECT date, payee, narration WHERE payee = 'Shop'
        - SELECT filename, lineno, date, payee ORDER BY date DESC
        """
        return run_query(service, bql=bql, limit=limit, offset=offset)

    return mcp


def run(config: Config) -> None:
    """Run the MCP server over stdio."""
    create_server(config).run()
