"""Create a new Beancount ledger without overwriting user data."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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


def create_ledger(
    ledger_path: Path, currency: str, *, today: date | None = None
) -> InitResult:
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

    _check_target(resolved_ledger)
    _check_target(inbox_path)

    inbox_created = not inbox_path.exists()
    try:
        resolved_ledger.parent.mkdir(parents=True, exist_ok=True)
        if inbox_created:
            inbox_path.touch()
        _write_atomic(
            resolved_ledger,
            render_main_ledger(normalized_currency, opening_date),
        )
    except OSError as exc:
        if inbox_created:
            inbox_path.unlink(missing_ok=True)
        raise InitError(
            f"Impossibile creare il ledger in {resolved_ledger.parent}: {exc}"
        ) from exc

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
            f"Impossibile creare il ledger: {path} è un symlink. "
            "Nessun file è stato modificato."
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


def _write_atomic(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` without leaving a partial file."""
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
