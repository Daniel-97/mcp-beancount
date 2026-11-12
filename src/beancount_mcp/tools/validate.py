"""Implementation of the ``validate`` tool."""

from __future__ import annotations

from typing import Any

from beancount_mcp.ledger import LedgerError, LedgerService, ledger_error
from beancount_mcp.validation import issue_to_dict, issues_from_errors


def build_validation(service: LedgerService) -> dict[str, Any]:
    """Run a full validation and return all current ledger errors."""
    try:
        snapshot = service.load()
    except (LedgerError, OSError) as exc:
        return ledger_error(exc)

    issues = issues_from_errors(snapshot.errors)
    return {
        "ok": True,
        "valid": not issues,
        "ledger_version": snapshot.version,
        "error_count": len(issues),
        "errors": [issue_to_dict(issue) for issue in issues],
    }
