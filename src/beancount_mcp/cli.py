"""Command-line interface for beancount-mcp."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from beancount_mcp import __version__, server
from beancount_mcp.config import (
    DEFAULT_HOST,
    DEFAULT_HTTP_PATH,
    DEFAULT_INBOX,
    DEFAULT_PORT,
    DEFAULT_QUERY_LIMIT,
    DEFAULT_TRANSPORT,
    build_config,
    resolve_ledger_path,
)
from beancount_mcp.init import InitError, create_ledger
from beancount_mcp.logging import log_event

SERVER_DESCRIPTION = "MCP server for querying and safely editing Beancount ledgers."


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch between the ``init`` command and the MCP server."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "init":
        return _run_init(arguments[1:])
    return _run_server(arguments)


def _run_init(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="beancount-mcp init",
        description="Create a new Beancount ledger and an empty inbox next to it.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path of the main ledger file. Defaults to BEANCOUNT_MCP_LEDGER or "
        "~/.beancount-mcp/ledger/main.bean.",
    )
    parser.add_argument(
        "--currency",
        required=True,
        help="Operating currency of the new ledger, for example EUR.",
    )
    args = parser.parse_args(argv)

    ledger_path = resolve_ledger_path(args.path)
    try:
        result = create_ledger(ledger_path, args.currency)
    except InitError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    print(f"Ledger creato: {result.ledger_path}")
    print(f"Inbox creata: {result.inbox_path}")
    print(f"Valuta: {result.currency}")
    return 0


def _run_server(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="beancount-mcp",
        description=SERVER_DESCRIPTION,
    )
    parser.add_argument(
        "ledger",
        nargs="?",
        help="Path of the main ledger file. Defaults to BEANCOUNT_MCP_LEDGER or "
        "~/.beancount-mcp/ledger/main.bean.",
    )
    parser.add_argument(
        "--inbox",
        default=DEFAULT_INBOX,
        help="Inbox path, relative to the ledger directory (default: inbox.bean).",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable all write tools.",
    )
    parser.add_argument(
        "--allow-edit-outside-inbox",
        action="store_true",
        help="Allow edits, batch appends and file organization outside the inbox.",
    )
    parser.add_argument(
        "--allow-config-changes",
        action="store_true",
        help="Allow explicit ledger option changes through MCP.",
    )
    parser.add_argument(
        "--allow-plugin-changes",
        action="store_true",
        help="Allow plugin configuration changes (executes Python plugins).",
    )
    parser.add_argument(
        "--allow-init",
        action="store_true",
        help="Allow MCP initialization of the configured missing ledger.",
    )
    parser.add_argument(
        "--query-limit",
        type=int,
        default=DEFAULT_QUERY_LIMIT,
        help=f"Default row limit for queries (default: {DEFAULT_QUERY_LIMIT}).",
    )
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default=DEFAULT_TRANSPORT,
        help="MCP transport (default: http). http listens on the configured "
        "host/port/path in stateless mode.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind host for the HTTP transport (default: {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port for the HTTP transport (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--http-path",
        default=DEFAULT_HTTP_PATH,
        help=f"HTTP endpoint path (default: {DEFAULT_HTTP_PATH}).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log tool calls to stderr (stdout is reserved for MCP).",
    )
    args = parser.parse_args(argv)

    try:
        config = build_config(
            args.ledger,
            inbox=args.inbox,
            read_only=args.read_only,
            allow_edit_outside_inbox=args.allow_edit_outside_inbox,
            query_limit=args.query_limit,
            transport=args.transport,
            host=args.host,
            port=args.port,
            http_path=args.http_path,
            verbose=args.verbose,
            allow_config_changes=args.allow_config_changes,
            allow_plugin_changes=args.allow_plugin_changes,
            allow_init=args.allow_init,
        )
    except ValueError as exc:
        parser.error(str(exc))

    log_event(
        "config: "
        f"ledger={config.ledger_path} inbox={config.inbox_path} "
        f"read_only={config.read_only} "
        f"allow_edit_outside_inbox={config.allow_edit_outside_inbox} "
        f"allow_config_changes={config.allow_config_changes} "
        f"allow_plugin_changes={config.allow_plugin_changes} allow_init={config.allow_init} "
        f"query_limit={config.query_limit} transport={config.transport} "
        f"host={config.host} port={config.port} http_path={config.http_path} "
        f"verbose={config.verbose}",
        verbose=config.verbose,
    )
    if config.transport == "http" and config.host not in (
        "127.0.0.1",
        "::1",
        "localhost",
    ):
        print(
            "Attenzione: il server HTTP non ha autenticazione; non esporlo "
            "in rete senza un reverse proxy con autenticazione e TLS.",
            file=sys.stderr,
        )

    if not config.ledger_path.is_file() and not config.allow_init:
        log_event(
            f"startup: ledger not found: {config.ledger_path}",
            verbose=config.verbose,
        )
        print(f"Ledger non trovato: {config.ledger_path}", file=sys.stderr)
        if args.ledger:
            print(
                "Controlla il percorso oppure crea un nuovo ledger con: "
                f"beancount-mcp init {config.ledger_path} --currency EUR",
                file=sys.stderr,
            )
        else:
            print(
                "Per creare un nuovo ledger: beancount-mcp init --currency EUR",
                file=sys.stderr,
            )
            print(
                "Oppure indica un ledger esistente: beancount-mcp /percorso/main.bean",
                file=sys.stderr,
            )
        return 2

    log_event("startup: launching MCP server", verbose=config.verbose)
    try:
        server.run(config)
    except RuntimeError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0
