"""Implementation of the ``query`` tool."""

from __future__ import annotations

from typing import Any

from beancount_mcp.ledger import LedgerService
from beancount_mcp.queries import run_bql


def run_query(
    service: LedgerService,
    bql: str,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Execute a read-only BQL query through the ledger service."""
    return run_bql(service, bql, limit=limit, offset=offset)
