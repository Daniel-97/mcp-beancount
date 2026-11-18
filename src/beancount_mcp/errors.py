"""Structured tool error responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """Error data returned to the MCP client."""

    code: str
    message: str
    details: list[dict[str, Any]] = field(default_factory=list)
    hint: str | None = None


def error_response(error: ErrorInfo) -> dict[str, Any]:
    """Render an error as the structured tool response."""
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "hint": error.hint,
        },
    }


def read_only_error() -> dict[str, Any]:
    """Build the response of a write tool called on a read-only server."""
    return tool_error(
        "READ_ONLY",
        "Il server è in modalità sola lettura.",
        "Riavvia il server senza --read-only per abilitare le scritture.",
    )


def locked_error(error: Exception, lock_path: object) -> dict[str, Any]:
    """Build the response for a write lock held by another writer."""
    return tool_error(
        "LOCKED",
        str(error),
        "Un'altra scrittura è in corso. Riprova tra poco; se il processo è "
        f"terminato, riprova: il lock viene rilasciato dal sistema operativo ({lock_path}).",
    )


def version_conflict_error(
    expected: str,
    actual: str,
    *,
    during_validation: bool = False,
) -> dict[str, Any]:
    """Build the response for a ledger that is not at the expected version."""
    message = (
        "Il ledger è cambiato durante la validazione."
        if during_validation
        else "La versione del ledger non coincide con expected_ledger_version."
    )
    return tool_error(
        "VERSION_CONFLICT",
        message,
        "Rileggi i dati e riprova con la ledger_version corrente.",
        details=[{"expected": expected, "actual": actual}],
    )


def tool_error(
    code: str,
    message: str,
    hint: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a tool error response."""
    return error_response(
        ErrorInfo(
            code=code,
            message=message,
            details=details or [],
            hint=hint,
        )
    )
