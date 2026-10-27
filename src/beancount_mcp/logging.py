"""Small stderr logger that never writes to the MCP stdout channel."""

from __future__ import annotations

import sys


def log_event(message: str, *, verbose: bool) -> None:
    """Print one startup or lifecycle event when verbose logging is enabled."""
    if verbose:
        print(f"[beancount-mcp] {message}", file=sys.stderr, flush=True)
