"""Create a new Beancount ledger without overwriting user data."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from beancount_mcp.writer import atomic_write

_CURRENCY_RE = re.compile(r"[A-Z][A-Z0-9'._-]{0,22}[A-Z0-9]")


class InitError(Exception):
    """Raised when ``init`` cannot create the ledger safely."""


@dataclass(frozen=True, slots=True)
class InitResult:
    """Files and values created by ``init``."""

    ledger_path: Path
    inbox_path: Path
    currency: str
    opening_date: date


def render_main_ledger(currency: str, opening_date: date) -> str:
    """Render the content of a newly initialized main ledger file."""
    return (
        'option "title" "Beancount MCP Ledger"\n'
        f'option "operating_currency" "{currency}"\n'
        "\n"
        'include "inbox.bean"\n'
        "\n"
        f"{opening_date.isoformat()} open Equity:Opening-Balances\n"
    )


def create_ledger(ledger_path: Path, currency: str, *, today: date | None = None) -> InitResult:
    """Create a main ledger and an empty inbox next to it.

    Existing non-empty files, symlinks, and non-regular files are refused.
    """
    normalized_currency = currency.strip().upper()
    if _CURRENCY_RE.fullmatch(normalized_currency) is None:
        raise InitError(
            f"Valuta non valida: {currency!r}. "
            "Usa un codice valuta Beancount, ad esempio EUR o USD."
        )

    opening_date = today if today is not None else date.today()
    resolved_ledger = Path(os.path.abspath(os.path.expanduser(ledger_path)))
    inbox_path = resolved_ledger.parent / "inbox.bean"

    if os.path.realpath(resolved_ledger) == os.path.realpath(inbox_path):
        raise InitError(
            f"Impossibile creare il ledger: {resolved_ledger} è l'inbox stessa e "
            "la includerebbe da sé. Usa un nome diverso per il file principale. "
            "Nessun file è stato modificato."
        )

    _check_target(resolved_ledger)
    _check_target(inbox_path)

    inbox_created = not inbox_path.exists()
    try:
        resolved_ledger.parent.mkdir(parents=True, exist_ok=True)
        if inbox_created:
            inbox_path.touch()
        atomic_write(resolved_ledger, render_main_ledger(normalized_currency, opening_date))
    except OSError as exc:
        # A directory fsync can fail after the main file was replaced. Keep
        # its included inbox in that case so a retry/manual check sees a valid tree.
        if inbox_created and (not resolved_ledger.exists() or resolved_ledger.stat().st_size == 0):
            inbox_path.unlink(missing_ok=True)
        raise InitError(f"Impossibile creare il ledger in {resolved_ledger.parent}: {exc}") from exc

    return InitResult(
        ledger_path=resolved_ledger,
        inbox_path=inbox_path,
        currency=normalized_currency,
        opening_date=opening_date,
    )


def _check_target(path: Path) -> None:
    """Refuse anything that ``init`` could overwrite or follow."""
    if path.is_symlink():
        raise InitError(
            f"Impossibile creare il ledger: {path} è un symlink. Nessun file è stato modificato."
        )
    if path.exists() and not path.is_file():
        raise InitError(
            f"Impossibile creare il ledger: {path} non è un file regolare. "
            "Nessun file è stato modificato."
        )
    if path.exists() and path.stat().st_size > 0:
        raise InitError(
            f"Impossibile creare il ledger: {path} esiste già e non è vuoto. "
            "Nessun file è stato modificato."
        )
