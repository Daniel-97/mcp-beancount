"""Account metadata derived from Beancount directives."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from beancount.core.data import Close, Directive, Open

_ROOT_OPTIONS = (
    ("name_assets", "Assets"),
    ("name_liabilities", "Liabilities"),
    ("name_equity", "Equity"),
    ("name_income", "Income"),
    ("name_expenses", "Expenses"),
)


def allowed_roots(options: Mapping[str, Any]) -> set[str]:
    """Return the account root names configured by the ledger options."""
    return {options.get(option, default) for option, default in _ROOT_OPTIONS}


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """Open/close dates and currencies for one account."""

    account: str
    open_date: date | None = None
    close_date: date | None = None
    currencies: tuple[str, ...] | None = None

    @property
    def is_open(self) -> bool:
        """Return whether the account has no close directive."""
        return self.close_date is None


def account_infos(entries: Iterable[Directive]) -> dict[str, AccountInfo]:
    """Build account metadata from open and close directives."""
    infos: dict[str, AccountInfo] = {}
    for entry in entries:
        if isinstance(entry, Open):
            existing = infos.get(entry.account, AccountInfo(account=entry.account))
            infos[entry.account] = AccountInfo(
                account=entry.account,
                open_date=entry.date,
                close_date=existing.close_date,
                currencies=tuple(entry.currencies) if entry.currencies else None,
            )
        elif isinstance(entry, Close):
            existing = infos.get(entry.account, AccountInfo(account=entry.account))
            infos[entry.account] = AccountInfo(
                account=entry.account,
                open_date=existing.open_date,
                close_date=entry.date,
                currencies=existing.currencies,
            )
    return infos
