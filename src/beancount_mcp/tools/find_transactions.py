"""Implementation of the ``find_transactions`` tool."""

from __future__ import annotations

import os
from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from beancount.core.data import Transaction

from beancount_mcp.entries import (
    DirectiveSpan,
    entry_id_to_dict,
    extract_directive_spans,
)
from beancount_mcp.errors import tool_error
from beancount_mcp.ledger import LEDGER_ERROR_HINT, LedgerError, LedgerService

DEFAULT_FIND_LIMIT = 50
MAX_FIND_LIMIT = 500


def find_transactions(
    service: LedgerService,
    *,
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
    """Find transactions and return their Beancount text with entry ids."""
    if not 1 <= limit <= MAX_FIND_LIMIT:
        return tool_error(
            "LIMIT_EXCEEDED",
            f"limit deve essere tra 1 e {MAX_FIND_LIMIT} (ricevuto {limit}).",
            f"Usa un limit tra 1 e {MAX_FIND_LIMIT}.",
        )

    parsed_from = _parse_date(date_from, "date_from")
    if isinstance(parsed_from, dict):
        return parsed_from
    parsed_to = _parse_date(date_to, "date_to")
    if isinstance(parsed_to, dict):
        return parsed_to
    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        return tool_error(
            "VALIDATION_FAILED",
            "date_from è successiva a date_to.",
            "Correggi l'intervallo di date.",
        )

    parsed_min = _parse_amount(min_amount, "min_amount")
    if isinstance(parsed_min, dict):
        return parsed_min
    parsed_max = _parse_amount(max_amount, "max_amount")
    if isinstance(parsed_max, dict):
        return parsed_max
    if parsed_min is not None and parsed_max is not None and parsed_min > parsed_max:
        return tool_error(
            "VALIDATION_FAILED",
            "min_amount è maggiore di max_amount.",
            "Correggi l'intervallo degli importi.",
        )

    try:
        snapshot = service.load()
    except (LedgerError, OSError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)

    try:
        spans_by_file = _spans_by_file(snapshot.files)
    except LedgerError as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)

    matches: list[tuple[Transaction, DirectiveSpan]] = []
    for entry in reversed(snapshot.entries):
        if not isinstance(entry, Transaction):
            continue
        span = _span_for_entry(entry, spans_by_file)
        if span is None:
            continue
        if not _matches(
            entry,
            payee=payee,
            narration_contains=narration_contains,
            account=account,
            date_from=parsed_from,
            date_to=parsed_to,
            min_amount=parsed_min,
            max_amount=parsed_max,
            tags=tags,
        ):
            continue
        matches.append((entry, span))

    total_matches = len(matches)
    selected = matches[:limit]
    return {
        "ok": True,
        "transactions": [_transaction_payload(entry, span) for entry, span in selected],
        "count": len(selected),
        "total_matches": total_matches,
        "truncated": total_matches > len(selected),
        "limit": limit,
    }


def _spans_by_file(
    files: tuple[Path, ...],
) -> dict[str, dict[int, DirectiveSpan]]:
    spans_by_file: dict[str, dict[int, DirectiveSpan]] = {}
    for file in files:
        try:
            text = file.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerError(f"Impossibile leggere {file}: {exc}") from exc
        spans = {span.entry_id.line: span for span in extract_directive_spans(file, text)}
        spans_by_file[str(file)] = spans
        spans_by_file[str(Path(os.path.realpath(file)))] = spans
    return spans_by_file


def _span_for_entry(
    entry: Transaction,
    spans_by_file: dict[str, dict[int, DirectiveSpan]],
) -> DirectiveSpan | None:
    meta = entry.meta or {}
    filename = meta.get("filename")
    lineno = meta.get("lineno")
    if not isinstance(filename, str) or not isinstance(lineno, int):
        return None
    spans = spans_by_file.get(filename)
    if spans is None:
        spans = spans_by_file.get(str(Path(os.path.realpath(filename))))
    if spans is None:
        return None
    return spans.get(lineno)


def _matches(
    entry: Transaction,
    *,
    payee: str | None,
    narration_contains: str | None,
    account: str | None,
    date_from: date_type | None,
    date_to: date_type | None,
    min_amount: Decimal | None,
    max_amount: Decimal | None,
    tags: list[str] | None,
) -> bool:
    if payee is not None and entry.payee != payee:
        return False
    if (
        narration_contains is not None
        and narration_contains.casefold() not in (entry.narration or "").casefold()
    ):
        return False
    if account is not None and not any(
        _account_matches(posting.account, account) for posting in entry.postings
    ):
        return False
    if date_from is not None and entry.date < date_from:
        return False
    if date_to is not None and entry.date > date_to:
        return False
    if min_amount is not None or max_amount is not None:
        amounts = [
            abs(posting.units.number)
            for posting in entry.postings
            if posting.units is not None and posting.units.number is not None
        ]
        if not any(_amount_in_range(amount, min_amount, max_amount) for amount in amounts):
            return False
    return all(tag in entry.tags for tag in tags or [])


def _account_matches(posting_account: str, target: str) -> bool:
    return posting_account == target or posting_account.startswith(f"{target}:")


def _amount_in_range(
    amount: Decimal,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    if minimum is not None and amount < minimum:
        return False
    return not (maximum is not None and amount > maximum)


def _transaction_payload(
    entry: Transaction,
    span: DirectiveSpan,
) -> dict[str, Any]:
    return {
        "entry_id": entry_id_to_dict(span.entry_id),
        "text": span.text.rstrip("\n"),
        "date": entry.date.isoformat(),
        "payee": entry.payee,
        "narration": entry.narration,
        "flag": entry.flag,
        "tags": sorted(entry.tags),
        "links": sorted(entry.links),
        "postings": [
            {
                "account": posting.account,
                "amount": str(posting.units) if posting.units is not None else None,
            }
            for posting in entry.postings
        ],
    }


def _parse_date(
    value: str | None,
    name: str,
) -> date_type | None | dict[str, Any]:
    if value is None:
        return None
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        return tool_error(
            "VALIDATION_FAILED",
            f"{name} non valida: {value!r}.",
            "Usa il formato YYYY-MM-DD.",
        )


def _parse_amount(
    value: str | None,
    name: str,
) -> Decimal | None | dict[str, Any]:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return tool_error(
            "VALIDATION_FAILED",
            f"{name} non valido: {value!r}.",
            "Usa un numero decimale senza valuta, ad esempio 10.00.",
        )
    if not parsed.is_finite() or parsed < 0:
        return tool_error(
            "VALIDATION_FAILED",
            f"{name} deve essere un numero finito e non negativo.",
            "Usa un numero decimale non negativo, ad esempio 10.00.",
        )
    return parsed
