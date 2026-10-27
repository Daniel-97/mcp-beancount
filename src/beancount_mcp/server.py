"""MCP server entry point."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from beancount_mcp import __version__
from beancount_mcp.config import Config
from beancount_mcp.entry_service import (
    delete_transaction as delete_transaction_service,
)
from beancount_mcp.entry_service import (
    edit_transaction as edit_transaction_service,
)
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.add_transactions import add_transactions as add_transactions_tool
from beancount_mcp.tools.find_transactions import (
    DEFAULT_FIND_LIMIT,
)
from beancount_mcp.tools.find_transactions import (
    find_transactions as find_transactions_tool,
)
from beancount_mcp.tools.ledger_info import build_ledger_info
from beancount_mcp.tools.open_account import open_account as open_account_tool
from beancount_mcp.tools.query import run_query
from beancount_mcp.tools.validate import build_validation


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

    @mcp.tool()
    def validate() -> dict[str, Any]:
        """Run a full validation of the current ledger.

        Returns all current Beancount errors with file, line, type, and message.
        Preexisting errors do not block reads or writes; use this tool to inspect
        them. The response also contains the ledger version.

        Examples:
        - Call after editing files outside the server.
        - Call after ledger_info reports a nonzero error_count.
        """
        return build_validation(service)

    @mcp.tool()
    def add_transactions(
        text: str,
        dry_run: bool = False,
        expected_ledger_version: str | None = None,
    ) -> dict[str, Any]:
        """Append one or more Beancount directives to the inbox.

        The write is atomic, serialized by a lock, and validated before/after:
        only new errors block it. Use dry_run to inspect the text without
        writing. Pass expected_ledger_version from ledger_info to detect
        concurrent changes. pad and balance directives are rejected.

        Examples:
        - Add a balanced transaction between two already-open accounts.
        - Use dry_run=true to check a candidate transaction before writing.
        - Add several directives in one call; they are appended in order.
        """
        return add_transactions_tool(
            service,
            text,
            dry_run=dry_run,
            expected_ledger_version=expected_ledger_version,
        )

    @mcp.tool()
    def open_account(
        account: str,
        currencies: list[str] | None = None,
        date: str | None = None,
        confirm_new: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Open a new Beancount account by writing an open directive to the inbox.

        The account name must be valid and use an allowed root. An existing open
        account produces ACCOUNT_EXISTS; a similar open account produces
        ACCOUNT_SIMILAR_EXISTS unless confirm_new is true. Date defaults to
        today. Use dry_run to validate without writing.

        Examples:
        - open_account("Expenses:Restaurant", ["EUR"])
        - open_account("Assets:Bank:Checking", date="2026-01-01")
        - open_account("Expenses:Resturant", confirm_new=true) to override a
          similar-name warning.
        """
        return open_account_tool(
            service,
            account,
            currencies=currencies,
            date=date,
            confirm_new=confirm_new,
            dry_run=dry_run,
        )

    @mcp.tool()
    def edit_transaction(
        entry_id: dict[str, Any],
        new_text: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Replace one ledger directive identified by a stable entry_id.

        entry_id is the object returned by find_transactions:
        {"file": str, "line": int, "hash": str}. By default only inbox entries
        can be edited; other included files require --allow-edit-outside-inbox.
        The change is validated before/after and written atomically. If the
        directive changed since the id was issued, the tool returns
        ENTRY_CHANGED with the current text.

        Examples:
        - Change the narration of an inbox transaction.
        - Correct a posting amount, keeping the transaction balanced.
        - Use dry_run=true to preview the replacement.
        """
        return edit_transaction_service(
            service,
            entry_id,
            new_text,
            dry_run=dry_run,
        )

    @mcp.tool()
    def delete_transaction(
        entry_id: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Delete one transaction identified by a stable entry_id.

        Only transactions can be deleted; open, close, balance, and pad are
        rejected. By default only inbox entries are eligible; other included
        files require --allow-edit-outside-inbox. The write is atomic and
        validated before/after.

        Examples:
        - Delete a transaction previously added to the inbox.
        - Use dry_run=true to inspect the transaction that would be removed.
        """
        return delete_transaction_service(service, entry_id, dry_run=dry_run)

    @mcp.tool()
    def find_transactions(
        payee: str | None = None,
        narration_contains: str | None = None,
        account: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_amount: str | None = None,
        max_amount: str | None = None,
        tags: list[str] | None = None,
        limit: int = DEFAULT_FIND_LIMIT,
    ) -> dict[str, Any]:
        """Find transactions and return their full Beancount text with entry ids.

        All filters are optional and combined with AND. account matches the
        account and its subaccounts. min_amount/max_amount are absolute posting
        amounts without currency, for example "10.00". tags requires all listed
        tags. Results are newest first and include entry_id for edit/delete.

        Examples:
        - find_transactions(payee="Shop")
        - find_transactions(narration_contains="coffee", date_from="2026-01-01")
        - find_transactions(account="Expenses:Food", min_amount="10.00", max_amount="50.00")
        - find_transactions(tags=["food"], limit=20)
        """
        return find_transactions_tool(
            service,
            payee=payee,
            narration_contains=narration_contains,
            account=account,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            tags=tags,
            limit=limit,
        )

    return mcp


def run(config: Config) -> None:
    """Run the MCP server over stdio."""
    create_server(config).run()
