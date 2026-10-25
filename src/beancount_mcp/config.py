"""Configuration and path resolution for the MCP server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_LEDGER_PATH = Path("~/.beancount-mcp/ledger/main.bean")
ENV_LEDGER = "BEANCOUNT_MCP_LEDGER"


def default_ledger_path() -> Path:
    """Return the default ledger path."""
    return Path(os.path.abspath(os.path.expanduser(DEFAULT_LEDGER_PATH)))


def resolve_ledger_path(
    explicit: str | None, env: Mapping[str, str] | None = None
) -> Path:
    """Resolve the ledger path from CLI, environment, or default."""
    environ = os.environ if env is None else env
    value = explicit or environ.get(ENV_LEDGER) or str(default_ledger_path())
    return Path(os.path.abspath(os.path.expanduser(value)))
