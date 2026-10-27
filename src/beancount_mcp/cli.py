"""Command-line interface for beancount-mcp."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from beancount_mcp import server
from beancount_mcp.config import (
    DEFAULT_INBOX,
    DEFAULT_QUERY_LIMIT,
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
        help="Allow edit/delete on included files outside the inbox.",
    )
    parser.add_argument(
        "--query-limit",
        type=int,
        default=DEFAULT_QUERY_LIMIT,
        help=f"Default row limit for queries (default: {DEFAULT_QUERY_LIMIT}).",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio). streamable-http listens on "
        "127.0.0.1:8000/mcp in stateless mode.",
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
            verbose=args.verbose,
        )
    except ValueError as exc:
        parser.error(str(exc))

    log_event(
        "config: "
        f"ledger={config.ledger_path} inbox={config.inbox_path} "
        f"read_only={config.read_only} "
        f"allow_edit_outside_inbox={config.allow_edit_outside_inbox} "
        f"query_limit={config.query_limit} transport={config.transport} "
        f"verbose={config.verbose}",
        verbose=config.verbose,
    )

    if not config.ledger_path.is_file():
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
