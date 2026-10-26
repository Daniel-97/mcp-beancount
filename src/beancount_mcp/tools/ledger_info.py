"""Implementation of the ``ledger_info`` tool."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from beancount.core.data import Close, Directive, Open, Transaction

from beancount_mcp.ledger import LedgerService, LedgerSnapshot

TOP_VALUES_LIMIT = 10


def build_ledger_info(service: LedgerService) -> dict[str, Any]:
    """Build the compact ledger overview returned by the MCP tool."""
    snapshot = service.load()
    transactions = [entry for entry in snapshot.entries if isinstance(entry, Transaction)]
    tags = (tag for transaction in transactions for tag in transaction.tags)
    links = (link for transaction in transactions for link in transaction.links)
    first_date = min((transaction.date for transaction in transactions), default=None)
    last_date = max((transaction.date for transaction in transactions), default=None)

    return {
        "ok": True,
        "ledger_path": str(snapshot.ledger_path),
        "files": [str(path) for path in snapshot.files],
        "ledger_version": snapshot.version,
        "operating_currency": list(snapshot.options.get("operating_currency", [])),
        "accounts": _accounts(snapshot.entries),
        "first_transaction_date": first_date.isoformat() if first_date else None,
        "last_transaction_date": last_date.isoformat() if last_date else None,
        "transaction_count": len(transactions),
        "error_count": len(snapshot.errors),
        "top_tags": _top_values(tags),
        "top_links": _top_values(links),
        "inbox": {
            "path": str(snapshot.inbox.path),
            "exists": snapshot.inbox.exists,
            "included": snapshot.inbox.included,
            "warning": snapshot.inbox.warning,
        },
        "read_only": service.config.read_only,
        "is_empty": snapshot.is_empty,
        "warnings": _warnings(snapshot),
    }


def _accounts(entries: Iterable[Directive]) -> list[dict[str, Any]]:
    accounts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, Open):
            info = accounts.setdefault(
                entry.account,
                {
                    "account": entry.account,
                    "open_date": None,
                    "close_date": None,
                    "currencies": None,
                    "is_open": True,
                },
            )
            info["open_date"] = entry.date.isoformat()
            info["currencies"] = list(entry.currencies) if entry.currencies else None
        elif isinstance(entry, Close):
            info = accounts.setdefault(
                entry.account,
                {
                    "account": entry.account,
                    "open_date": None,
                    "close_date": None,
                    "currencies": None,
                    "is_open": True,
                },
            )
            info["close_date"] = entry.date.isoformat()

    result: list[dict[str, Any]] = []
    for account in sorted(accounts):
        info = accounts[account]
        info["is_open"] = info["close_date"] is None
        result.append(info)
    return result


def _top_values(values: Iterable[str]) -> list[dict[str, Any]]:
    counts = Counter(values)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"name": name, "count": count} for name, count in ordered[:TOP_VALUES_LIMIT]]


def _warnings(snapshot: LedgerSnapshot) -> list[str]:
    warnings: list[str] = []
    if snapshot.is_empty:
        warnings.append("Il ledger è vuoto. Apri gli account necessari con open_account.")
    if snapshot.inbox.warning is not None:
        warnings.append(snapshot.inbox.warning)
    if snapshot.errors:
        warnings.append(f"Il ledger contiene {len(snapshot.errors)} errori preesistenti.")
    return warnings
