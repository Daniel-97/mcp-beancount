"""Read-only BQL execution with pagination and JSON-safe serialization."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from beancount.core.amount import Amount
from beancount.core.inventory import Inventory
from beancount.core.position import Position
from beanquery import connect
from beanquery.parser import ast

from beancount_mcp.config import MAX_QUERY_LIMIT
from beancount_mcp.errors import ErrorInfo, error_response
from beancount_mcp.ledger import (
    LEDGER_ERROR_HINT,
    LedgerError,
    LedgerService,
)

READ_STATEMENTS = (ast.Select, ast.Balances, ast.Journal)
QUERY_HINT = (
    "Usa uno statement di lettura tabellare: SELECT, BALANCES o JOURNAL. "
    "PRINT, CREATE TABLE e INSERT non sono ammessi. "
    "Esempio: SELECT account, SUM(position) GROUP BY account"
)
LIMIT_HINT = "Usa limit tra 1 e 1000 e offset >= 0."


def run_bql(
    service: LedgerService,
    bql: str,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Execute a read-only BQL statement and return a paginated result."""
    effective_limit = service.config.query_limit if limit is None else limit
    if not 1 <= effective_limit <= MAX_QUERY_LIMIT:
        return _error(
            "LIMIT_EXCEEDED",
            f"limit deve essere tra 1 e {MAX_QUERY_LIMIT} (ricevuto {effective_limit}).",
            LIMIT_HINT,
        )
    if offset < 0:
        return _error(
            "LIMIT_EXCEEDED",
            f"offset deve essere >= 0 (ricevuto {offset}).",
            LIMIT_HINT,
        )

    try:
        snapshot = service.load()
    except (LedgerError, OSError) as exc:
        return _error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)

    try:
        connection = connect(
            "beancount:",
            entries=list(snapshot.entries),
            errors=[],
            options=snapshot.options,
        )
        statement = connection.parse(bql)
        if not isinstance(statement, READ_STATEMENTS):
            return _error(
                "QUERY_ERROR",
                f"Statement non supportato: {type(statement).__name__}.",
                QUERY_HINT,
            )

        cursor = connection.execute(bql)
        try:
            total_rows = cursor.rowcount if cursor.rowcount >= 0 else None
            columns = [
                {
                    "name": column.name,
                    "type": _type_name(column.datatype),
                }
                for column in (cursor.description or ())
            ]
            raw_rows = _fetch_page(cursor, effective_limit, offset)
        finally:
            cursor.close()
    except Exception as exc:
        return _error("QUERY_ERROR", str(exc), QUERY_HINT)

    truncated = len(raw_rows) > effective_limit
    rows = raw_rows[:effective_limit]
    return {
        "ok": True,
        "columns": columns,
        "rows": [[_serialize(value) for value in row] for row in rows],
        "limit": effective_limit,
        "offset": offset,
        "truncated": truncated,
        "total_rows": total_rows,
    }


def _fetch_page(cursor: Any, limit: int, offset: int) -> list[tuple[Any, ...]]:
    """Skip ``offset`` rows, then fetch at most ``limit + 1`` rows."""
    remaining = offset
    while remaining > 0:
        batch = cursor.fetchmany(min(remaining, MAX_QUERY_LIMIT))
        if not batch:
            break
        remaining -= len(batch)

    rows: list[tuple[Any, ...]] = []
    while len(rows) <= limit:
        batch = cursor.fetchmany(limit + 1 - len(rows))
        if not batch:
            break
        rows.extend(batch)
    return rows


def _type_name(datatype: Any) -> str:
    mapping = {
        str: "string",
        int: "integer",
        Decimal: "decimal",
        date: "date",
        datetime: "datetime",
        bool: "boolean",
        Amount: "amount",
        Position: "position",
        Inventory: "inventory",
    }
    return mapping.get(datatype, getattr(datatype, "__name__", str(datatype)))


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Amount):
        return str(value)
    if isinstance(value, (Position, Inventory)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted((_serialize(item) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, float):
        return str(value)
    return str(value)


def _error(code: str, message: str, hint: str) -> dict[str, Any]:
    return error_response(ErrorInfo(code=code, message=message, hint=hint))
