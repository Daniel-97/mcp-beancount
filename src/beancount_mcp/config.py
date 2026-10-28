"""Configuration and path resolution for the MCP server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LEDGER_PATH = Path("~/.beancount-mcp/ledger/main.bean")
DEFAULT_INBOX = "inbox.bean"
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 1000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_HTTP_PATH = "/mcp"
DEFAULT_TRANSPORT = "http"
TRANSPORTS = ("http", "stdio")
ENV_LEDGER = "BEANCOUNT_MCP_LEDGER"


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable configuration shared by the server, service, and tools."""

    ledger_path: Path
    inbox_path: Path
    read_only: bool = False
    allow_edit_outside_inbox: bool = False
    query_limit: int = DEFAULT_QUERY_LIMIT
    transport: str = DEFAULT_TRANSPORT
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    http_path: str = DEFAULT_HTTP_PATH
    verbose: bool = False
    allow_config_changes: bool = False
    allow_plugin_changes: bool = False
    allow_init: bool = False


def default_ledger_path() -> Path:
    """Return the default ledger path."""
    return Path(os.path.abspath(os.path.expanduser(DEFAULT_LEDGER_PATH)))


def resolve_ledger_path(explicit: str | None, env: Mapping[str, str] | None = None) -> Path:
    """Resolve the ledger path from CLI, environment, or default."""
    environ = os.environ if env is None else env
    value = explicit or environ.get(ENV_LEDGER) or str(default_ledger_path())
    return Path(os.path.abspath(os.path.expanduser(value)))


def resolve_inbox_path(ledger_path: Path, inbox: str = DEFAULT_INBOX) -> Path:
    """Resolve the inbox path relative to the ledger directory."""
    expanded = os.path.expanduser(inbox or DEFAULT_INBOX)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.path.dirname(ledger_path), expanded)
    return Path(os.path.abspath(expanded))


def build_config(
    ledger: str | None,
    *,
    inbox: str = DEFAULT_INBOX,
    read_only: bool = False,
    allow_edit_outside_inbox: bool = False,
    query_limit: int = DEFAULT_QUERY_LIMIT,
    transport: str = DEFAULT_TRANSPORT,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    http_path: str = DEFAULT_HTTP_PATH,
    verbose: bool = False,
    allow_config_changes: bool = False,
    allow_plugin_changes: bool = False,
    allow_init: bool = False,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Build and validate the server configuration."""
    if not 1 <= query_limit <= MAX_QUERY_LIMIT:
        raise ValueError(f"--query-limit deve essere tra 1 e {MAX_QUERY_LIMIT}")
    if transport not in TRANSPORTS:
        raise ValueError(f"Trasporto non supportato: {transport!r}")
    host = host.strip()
    http_path = http_path.strip()
    if not host:
        raise ValueError("--host non può essere vuoto")
    if not 1 <= port <= 65535:
        raise ValueError("--port deve essere tra 1 e 65535")
    if not http_path.startswith("/"):
        raise ValueError("--http-path deve iniziare con '/'")
    if transport == "stdio" and (
        host != DEFAULT_HOST or port != DEFAULT_PORT or http_path != DEFAULT_HTTP_PATH
    ):
        raise ValueError("--host, --port e --http-path richiedono --transport http")

    ledger_path = Path(os.path.realpath(resolve_ledger_path(ledger, env)))
    return Config(
        ledger_path=ledger_path,
        inbox_path=resolve_inbox_path(ledger_path, inbox),
        read_only=read_only,
        allow_edit_outside_inbox=allow_edit_outside_inbox,
        query_limit=query_limit,
        transport=transport,
        host=host,
        port=port,
        http_path=http_path,
        verbose=verbose,
        allow_config_changes=allow_config_changes,
        allow_plugin_changes=allow_plugin_changes,
        allow_init=allow_init,
    )
