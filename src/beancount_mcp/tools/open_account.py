"""Implementation of the ``open_account`` tool."""

from __future__ import annotations

import re
from datetime import date as date_type
from difflib import get_close_matches
from typing import Any

from beancount.core import account as beancount_account
from beancount.core.amount import CURRENCY_RE

from beancount_mcp.accounts import account_infos
from beancount_mcp.errors import ErrorInfo, error_response
from beancount_mcp.ledger import LEDGER_ERROR_HINT, LedgerError, LedgerService
from beancount_mcp.write_service import write_inbox_text

_CURRENCY_PATTERN = re.compile(CURRENCY_RE)
_ROOT_OPTIONS = (
    ("name_assets", "Assets"),
    ("name_liabilities", "Liabilities"),
    ("name_equity", "Equity"),
    ("name_income", "Income"),
    ("name_expenses", "Expenses"),
)


def open_account(
    service: LedgerService,
    account: str,
    currencies: list[str] | None = None,
    date: str | None = None,
    confirm_new: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Open a new account by appending an open directive to the inbox."""
    if service.config.read_only:
        return _error(
            "READ_ONLY",
            "Il server è in modalità sola lettura.",
            "Riavvia il server senza --read-only per abilitare le scritture.",
        )

    try:
        snapshot = service.load()
    except (LedgerError, OSError) as exc:
        return _error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)

    if not beancount_account.is_valid(account):
        return _error(
            "VALIDATION_FAILED",
            f"Nome account non valido: {account!r}.",
            "Usa il formato Root:Sottoconto, ad esempio Expenses:Restaurant.",
        )

    root = beancount_account.split(account)[0]
    allowed_roots = {snapshot.options.get(option, default) for option, default in _ROOT_OPTIONS}
    if root not in allowed_roots:
        return _error(
            "VALIDATION_FAILED",
            f"Radice account non ammessa: {root}.",
            f"Radici ammesse: {', '.join(sorted(allowed_roots))}.",
        )

    infos = account_infos(snapshot.entries)
    existing = infos.get(account)
    if existing is not None and existing.is_open:
        return _error(
            "ACCOUNT_EXISTS",
            f"L'account {account} è già aperto.",
            "Usa l'account esistente oppure scegli un nome diverso.",
            details=[{"account": account}],
        )

    open_names = [name for name, info in infos.items() if info.is_open]
    similar = get_close_matches(account, open_names, n=5, cutoff=0.8)
    if similar and not confirm_new:
        return _error(
            "ACCOUNT_SIMILAR_EXISTS",
            f"Esiste già un account simile: {', '.join(similar)}.",
            "Usa uno degli account esistenti oppure passa confirm_new=true se "
            "è davvero un nuovo account.",
            details=[{"account": name} for name in similar],
        )

    if date is None:
        opening_date = date_type.today()
    else:
        try:
            opening_date = date_type.fromisoformat(date)
        except ValueError:
            return _error(
                "VALIDATION_FAILED",
                f"Data non valida: {date!r}.",
                "Usa il formato YYYY-MM-DD.",
            )

    normalized_currencies: list[str] | None = None
    if currencies:
        normalized_currencies = []
        for currency in currencies:
            value = currency.strip().upper()
            if not _CURRENCY_PATTERN.fullmatch(value):
                return _error(
                    "VALIDATION_FAILED",
                    f"Valuta non valida: {currency!r}.",
                    "Usa codici valuta Beancount, ad esempio EUR o USD.",
                )
            normalized_currencies.append(value)

    suffix = f" {','.join(normalized_currencies)}" if normalized_currencies else ""
    text = f"{opening_date.isoformat()} open {account}{suffix}\n"
    result = write_inbox_text(
        service,
        text,
        expected_ledger_version=snapshot.version,
        dry_run=dry_run,
    )
    if result.get("ok"):
        result["account"] = account
        result["available_for_transactions"] = not dry_run
    return result


def _error(
    code: str,
    message: str,
    hint: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return error_response(
        ErrorInfo(
            code=code,
            message=message,
            details=details or [],
            hint=hint,
        )
    )
