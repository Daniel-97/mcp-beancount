"""Safe inbox writes with locking, staging, and before/after validation."""

from __future__ import annotations

import hashlib
import os
import re
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from beancount.core.data import Balance, Directive, Pad
from beancount.parser import parser, printer

from beancount_mcp.accounts import account_infos
from beancount_mcp.errors import tool_error
from beancount_mcp.ledger import (
    LEDGER_ERROR_HINT,
    LedgerError,
    LedgerService,
    LedgerSnapshot,
)
from beancount_mcp.staging import StagingError, validate_staged_file
from beancount_mcp.validation import Issue, issue_to_dict, issues_from_errors
from beancount_mcp.writer import (
    LockError,
    append_text,
    atomic_write,
    fsync_directory,
    lock_path_for,
    write_lock,
)

_RECEIPT_PREFIX = "; beancount-mcp-idempotency: "

_FORBIDDEN_LINE_RE = re.compile(r"(?m)^\s*(include|plugin|option)\b")


def write_inbox_text(
    service: LedgerService,
    text: str,
    *,
    expected_ledger_version: str | None = None,
    idempotency_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append directives to the inbox after full validation."""
    if service.config.read_only:
        return tool_error(
            "READ_ONLY",
            "Il server è in modalità sola lettura.",
            "Riavvia il server senza --read-only per abilitare le scritture.",
        )

    if dry_run:
        return _write_inbox_text(
            service,
            text,
            expected_ledger_version=expected_ledger_version,
            idempotency_key=idempotency_key,
            dry_run=True,
        )

    try:
        with write_lock(service.config.ledger_path):
            return _write_inbox_text(
                service,
                text,
                expected_ledger_version=expected_ledger_version,
                idempotency_key=idempotency_key,
                dry_run=False,
            )
    except LockError as exc:
        lock = lock_path_for(service.config.ledger_path)
        return tool_error(
            "LOCKED",
            str(exc),
            "Un'altra scrittura è in corso. Riprova tra poco; se il processo è "
            f"terminato, riprova: il lock viene rilasciato dal sistema operativo ({lock}).",
        )


def _write_inbox_text(
    service: LedgerService,
    text: str,
    *,
    expected_ledger_version: str | None,
    idempotency_key: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        snapshot = service.load()
    except (LedgerError, OSError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)

    if not snapshot.inbox.included:
        return tool_error(
            "INBOX_NOT_INCLUDED",
            "L'inbox non esiste o non è inclusa dal ledger.",
            snapshot.inbox.warning
            or "Crea l'inbox e aggiungi il relativo include al file principale.",
            details=[{"inbox": str(snapshot.inbox.path)}],
        )

    inbox_path = Path(os.path.realpath(snapshot.inbox.path))

    parsed = _parse_proposed_text(text, inbox_path)
    if isinstance(parsed, dict):
        return parsed
    entries = parsed

    try:
        existing = inbox_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile leggere l'inbox: {exc}",
            "Verifica che l'inbox esista, sia leggibile e codificata in UTF-8.",
        )

    receipt = ""
    if idempotency_key is not None:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            return tool_error(
                "VALIDATION_FAILED",
                "idempotency_key deve contenere da 1 a 200 caratteri e non essere vuota.",
                "Usa una chiave univoca per ogni operazione e riusala solo per i retry.",
            )
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        payload_hash = hashlib.sha256(text.strip("\n").encode("utf-8")).hexdigest()
        prefix = f"{_RECEIPT_PREFIX}{key_hash} "
        receipts = [line for line in existing.splitlines() if line.startswith(prefix)]
        receipt = f"{prefix}{payload_hash}"
        if receipts:
            if any(line != receipt for line in receipts):
                return tool_error(
                    "IDEMPOTENCY_CONFLICT",
                    "La chiave è già stata usata con un testo diverso.",
                    "Riusa il testo originale per il retry o scegli una nuova chiave.",
                )
            if not dry_run:
                try:
                    # A previous response may have failed after replace but
                    # before syncing the directory. Acknowledge durability now.
                    with inbox_path.open("rb") as handle:
                        os.fsync(handle.fileno())
                    fsync_directory(inbox_path.parent)
                except OSError as exc:
                    return tool_error(
                        "LEDGER_ERROR",
                        f"Scrittura già presente ma sincronizzazione fallita: {exc}",
                        "Riprova con la stessa idempotency_key e lo stesso testo.",
                    )
            return {**_success(snapshot, entries, inbox_path, dry_run=dry_run), "replayed": True}

    if expected_ledger_version is not None and expected_ledger_version != snapshot.version:
        return tool_error(
            "VERSION_CONFLICT",
            "La versione del ledger non coincide con expected_ledger_version.",
            "Ricarica ledger_info e riprova con la versione corrente.",
            details=[
                {
                    "expected": expected_ledger_version,
                    "actual": snapshot.version,
                }
            ],
        )

    block = f"{receipt}\n{text}" if receipt else text
    proposed_content = append_text(existing, block)
    try:
        new_issues = validate_staged_file(
            snapshot.ledger_path,
            snapshot.files,
            inbox_path,
            proposed_content,
            snapshot.errors,
        )
    except (OSError, StagingError) as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile validare la modifica: {exc}",
            "Verifica che tutti i file del ledger siano leggibili.",
        )

    if new_issues:
        return validation_failed_response(new_issues, snapshot)

    if dry_run:
        return _success(
            snapshot,
            entries,
            inbox_path,
            dry_run=True,
            would_write_text=text.strip("\n") + "\n",
        )

    try:
        current = service.load()
    except (LedgerError, OSError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)

    if current.version != snapshot.version:
        return tool_error(
            "VERSION_CONFLICT",
            "Il ledger è cambiato durante la validazione.",
            "Ricarica ledger_info e riprova con la versione corrente.",
            details=[
                {
                    "expected": snapshot.version,
                    "actual": current.version,
                }
            ],
        )

    try:
        atomic_write(inbox_path, proposed_content)
    except OSError as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile scrivere l'inbox: {exc}",
            "Verifica i permessi della directory dell'inbox e riprova.",
        )

    try:
        after = service.load()
    except (LedgerError, OSError) as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Scrittura completata ma il ledger non è ricaricabile: {exc}",
            "Controlla il ledger con validate e verifica i file su disco.",
        )

    result = _success(after, entries, inbox_path, dry_run=False)
    if idempotency_key is not None:
        result["replayed"] = False
    return result


def _parse_proposed_text(
    text: str,
    inbox_path: Path,
) -> list[Directive] | dict[str, Any]:
    if not text.strip():
        return tool_error(
            "VALIDATION_FAILED",
            "Il testo non contiene direttive.",
            "Invia una o più direttive Beancount, ad esempio una transazione.",
        )
    if any(line.startswith(_RECEIPT_PREFIX) for line in text.splitlines()):
        return tool_error(
            "VALIDATION_FAILED",
            "Il testo contiene un commento riservato per idempotency_key.",
            "Rimuovi i commenti beancount-mcp-idempotency dal testo proposto.",
        )
    if _FORBIDDEN_LINE_RE.search(text):
        return tool_error(
            "VALIDATION_FAILED",
            "Il testo contiene una direttiva include, plugin o option non ammessa.",
            "Rimuovi include, plugin e option: le scritture possono solo aggiungere "
            "direttive contabili all'inbox.",
        )

    entries, errors, _ = parser.parse_string(
        text,
        report_filename=str(inbox_path),
    )
    if errors:
        return tool_error(
            "SYNTAX_ERROR",
            "Il testo non è Beancount valido.",
            "Correggi la sintassi indicata nei details e riprova.",
            details=[issue_to_dict(issue) for issue in issues_from_errors(errors)],
        )

    if not entries:
        return tool_error(
            "VALIDATION_FAILED",
            "Il testo non contiene direttive.",
            "Invia una o più direttive Beancount, ad esempio una transazione.",
        )

    forbidden = [entry for entry in entries if isinstance(entry, (Pad, Balance))]
    if forbidden:
        return tool_error(
            "VALIDATION_FAILED",
            "Il testo contiene direttive pad o balance.",
            "I tool di scrittura non possono aggiungere pad o balance.",
            details=[
                {"type": type(entry).__name__, "message": "Direttiva non ammessa."}
                for entry in forbidden
            ],
        )
    return entries


def validation_failed_response(
    issues: list[Issue],
    snapshot: LedgerSnapshot,
) -> dict[str, Any]:
    count = len(issues)
    noun = "errore nuovo" if count == 1 else "errori nuovi"
    return tool_error(
        "VALIDATION_FAILED",
        f"La scrittura introdurrebbe {count} {noun}.",
        _validation_hint(issues, snapshot),
        details=[issue_to_dict(issue) for issue in issues],
    )


def _validation_hint(issues: list[Issue], snapshot: LedgerSnapshot) -> str:
    infos = account_infos(snapshot.entries)
    open_accounts = [name for name, info in infos.items() if info.is_open]
    for issue in issues:
        message = issue.message
        if "inactive account" in message or "unknown account" in message:
            match = re.search(r"'([^']+)'", message)
            if match:
                missing = match.group(1)
                info = infos.get(missing)
                if info is not None:
                    if info.open_date is not None and info.close_date is not None:
                        opened = info.open_date.isoformat()
                        closed = info.close_date.isoformat()
                        return (
                            f"L'account '{missing}' è attivo dal {opened} al "
                            f"{closed}. Usa una data in questo intervallo o un "
                            "altro account."
                        )
                    if info.close_date is not None:
                        return (
                            f"L'account '{missing}' è stato chiuso il "
                            f"{info.close_date.isoformat()}. Usa un altro "
                            "account o una data precedente alla chiusura."
                        )
                    if info.open_date is not None:
                        opened = info.open_date.isoformat()
                        return (
                            f"L'account '{missing}' esiste ma la transazione è "
                            f"precedente alla sua apertura ({opened}). Usa una "
                            f"data >= {opened} o un altro account."
                        )
                similar = get_close_matches(missing, open_accounts, n=3, cutoff=0.8)
                if similar:
                    return (
                        f"L'account '{missing}' non è aperto. Account simili "
                        f"disponibili: {', '.join(similar)}. Usa open_account "
                        "per aprire l'account corretto."
                    )
                return (
                    f"L'account '{missing}' non è aperto. Usa open_account per "
                    "aprirlo prima di aggiungere la transazione."
                )
        if "does not balance" in message:
            return (
                "La transazione non è bilanciata. Correggi gli importi in modo "
                "che la somma delle postings sia zero."
            )
        if "Invalid currency" in message:
            return (
                "La valuta non è ammessa per l'account. Controlla le valute "
                "dell'account o apri un account con la valuta corretta."
            )
    return (
        "La modifica introdurrebbe nuovi errori. Correggi i details e usa "
        "validate per ricontrollare."
    )


def _success(
    snapshot: LedgerSnapshot,
    entries: list[Directive],
    inbox_path: Path,
    *,
    dry_run: bool,
    would_write_text: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "inbox_path": str(inbox_path),
        "entries": [printer.format_entry(entry) for entry in entries],
        "entry_count": len(entries),
        "ledger_version": snapshot.version,
        "warning_count": len(snapshot.errors),
    }
    if dry_run and would_write_text is not None:
        result["would_write_text"] = would_write_text
    return result
