"""Command-line interface for beancount-mcp."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from beancount_mcp import server
from beancount_mcp.config import resolve_ledger_path
from beancount_mcp.init import InitError, create_ledger

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
    args = parser.parse_args(argv)

    ledger_path = resolve_ledger_path(args.ledger)
    if not ledger_path.is_file():
        print(f"Ledger non trovato: {ledger_path}", file=sys.stderr)
        print(
            "Per creare un nuovo ledger: beancount-mcp init --currency EUR",
            file=sys.stderr,
        )
        print(
            "Oppure indica un ledger esistente: beancount-mcp /percorso/main.bean",
            file=sys.stderr,
        )
        return 2

    server.run()
    return 0
