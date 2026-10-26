"""Implementation of the ``add_transactions`` tool."""

from __future__ import annotations

from typing import Any

from beancount_mcp.ledger import LedgerService
from beancount_mcp.write_service import write_inbox_text


def add_transactions(
    service: LedgerService,
    text: str,
    *,
    dry_run: bool = False,
    expected_ledger_version: str | None = None,
) -> dict[str, Any]:
    """Append validated directives to the inbox."""
    return write_inbox_text(
        service,
        text,
        expected_ledger_version=expected_ledger_version,
        dry_run=dry_run,
    )
