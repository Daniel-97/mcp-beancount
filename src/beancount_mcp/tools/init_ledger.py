"""Bootstrap only the server's configured ledger through MCP."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from beancount.core.amount import CURRENCY_RE

from beancount_mcp.config import Config
from beancount_mcp.errors import tool_error
from beancount_mcp.init import render_main_ledger
from beancount_mcp.ledger import LedgerError, LedgerService
from beancount_mcp.multifile import TransactionError, commit_files, transaction_dir
from beancount_mcp.staging import StagingError, validate_staged_tree
from beancount_mcp.writer import LockError, fsync_directory, write_lock


def init_ledger(config: Config, currency: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Create a main ledger and inbox together, refusing every existing target."""
    if config.read_only or not config.allow_init:
        return tool_error(
            "INIT_NOT_ALLOWED",
            "Serve --allow-init in modalità scrittura.",
            "Abilita l'inizializzazione all'avvio del server.",
        )
    main = config.ledger_path
    inbox = config.inbox_path
    currency = currency.strip().upper()
    if re.fullmatch(CURRENCY_RE, currency) is None:
        return tool_error("VALIDATION_FAILED", "Valuta non valida.", "Usa EUR o USD, ad esempio.")
    if inbox.resolve() == main.resolve() or not inbox.resolve().is_relative_to(
        main.parent.resolve()
    ):
        return tool_error(
            "PATH_NOT_ALLOWED",
            "L'inbox deve essere un file distinto dentro il ledger.",
            "Correggi --inbox prima di inizializzare.",
        )
    if inbox.resolve().is_relative_to(transaction_dir(main).resolve()):
        return tool_error(
            "PATH_NOT_ALLOWED", "Percorso inbox riservato al journal.", "Correggi --inbox."
        )
    if main.exists() or inbox.exists() or main.is_symlink() or inbox.is_symlink():
        return tool_error(
            "ALREADY_INITIALIZED",
            "Il ledger o l'inbox esistono già.",
            "init_ledger non sovrascrive file esistenti, nemmeno vuoti.",
        )
    relative = Path(os.path.relpath(inbox, main.parent)).as_posix()
    if '"' in relative or "\n" in relative or "\r" in relative:
        return tool_error(
            "PATH_NOT_ALLOWED", "Percorso inbox non valido.", "Scegli un nome semplice."
        )
    content = render_main_ledger(currency, date.today()).replace(
        'include "inbox.bean"', f'include "{relative}"'
    )
    modifications = {main: content, inbox: ""}
    try:
        issues = validate_staged_tree(
            main, [], modifications, [], allow_new_files=True, required_files=modifications
        )
        if issues:
            return tool_error(
                "VALIDATION_FAILED",
                "Il ledger iniziale non è valido.",
                "Controlla la valuta e i percorsi.",
            )
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "files": {str(p): t for p, t in modifications.items()},
            }
        missing = []
        parent = main.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for parent in reversed(missing):
            parent.mkdir()
            fsync_directory(parent.parent)
        with write_lock(main):
            commit_files(main, modifications, expected_contents={main: None, inbox: None})
        snapshot = LedgerService(config).load()
        return {
            "ok": True,
            "dry_run": False,
            "ledger_version": snapshot.version,
            "ledger_path": str(main),
            "inbox_path": str(inbox),
        }
    except LockError as exc:
        return tool_error("LOCKED", str(exc), "Riprova dopo l'altra inizializzazione.")
    except (LedgerError, OSError, StagingError, TransactionError) as exc:
        return tool_error(
            "LEDGER_ERROR", str(exc), "Controlla permessi, file e journal prima del retry."
        )
