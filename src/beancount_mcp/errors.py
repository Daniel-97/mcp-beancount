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
