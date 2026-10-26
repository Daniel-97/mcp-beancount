"""Edit and delete directives by stable entry identifier."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beancount.core.data import Balance, Directive, Pad
from beancount.parser import parser

from beancount_mcp.config import Config
from beancount_mcp.entries import (
    DirectiveSpan,
    delete_span,
    entry_id_to_dict,
    extract_directive_spans,
    find_span,
    is_transaction_span,
    replace_span,
)
from beancount_mcp.errors import ErrorInfo, error_response
from beancount_mcp.ledger import (
    LEDGER_ERROR_HINT,
    LedgerError,
    LedgerService,
    LedgerSnapshot,
)
from beancount_mcp.staging import validate_staged_file
from beancount_mcp.validation import Issue, issue_to_dict, issues_from_errors
from beancount_mcp.write_service import (
    tool_error,
    validation_failed_response,
)
from beancount_mcp.writer import (
    LockError,
    atomic_write,
    lock_path_for,
    write_lock,
)

_FORBIDDEN_LINE_RE = re.compile(r"(?m)^\s*(include|plugin)\b")


@dataclass(frozen=True, slots=True)
class EntryIdData:
    """Validated entry identifier input."""

    file: str
    line: int
    hash: str


@dataclass(frozen=True, slots=True)
class ResolvedEntry:
    """A resolved directive with its current file text."""

    path: Path
    text: str
    span: DirectiveSpan


def edit_transaction(
    service: LedgerService,
    entry_id: dict[str, Any],
    new_text: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Replace one directive identified by ``entry_id``."""
    if service.config.read_only:
        return _read_only_error()
    parsed_id = parse_entry_id(entry_id)
    if isinstance(parsed_id, dict):
        return parsed_id
    return _run_write(
        service,
        dry_run,
        lambda: _edit_once(service, parsed_id, new_text, dry_run),
    )


def delete_transaction(
    service: LedgerService,
    entry_id: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete one transaction identified by ``entry_id``."""
    if service.config.read_only:
        return _read_only_error()
    parsed_id = parse_entry_id(entry_id)
    if isinstance(parsed_id, dict):
        return parsed_id
    return _run_write(
        service,
        dry_run,
        lambda: _delete_once(service, parsed_id, dry_run),
    )


def parse_entry_id(data: dict[str, Any]) -> EntryIdData | dict[str, Any]:
    """Validate the JSON shape of an entry identifier."""
    file = data.get("file")
    line = data.get("line")
    hash_value = data.get("hash")
    if (
        not isinstance(file, str)
        or not isinstance(hash_value, str)
        or not isinstance(line, int)
        or isinstance(line, bool)
        or line < 1
        or len(hash_value) != 64
    ):
        return tool_error(
            "ENTRY_NOT_FOUND",
            "entry_id non valido.",
            "entry_id deve contenere file, line e hash, come restituito da find_transactions.",
        )
    return EntryIdData(file=file, line=line, hash=hash_value)


def resolve_entry(
    snapshot: LedgerSnapshot,
    config: Config,
    entry_id: EntryIdData,
    *,
    require_transaction: bool = False,
) -> ResolvedEntry | dict[str, Any]:
    """Resolve and authorize an entry identifier against the current ledger."""
    path = Path(entry_id.file).expanduser()
    if not path.is_absolute():
        return tool_error(
            "PATH_NOT_ALLOWED",
            "Il path dell'entry_id deve essere assoluto.",
            "Usa l'entry_id restituito dai tool di lettura.",
        )

    real_path = Path(os.path.realpath(path))
    inbox_real = Path(os.path.realpath(config.inbox_path))

    if not config.allow_edit_outside_inbox:
        if real_path != inbox_real:
            return tool_error(
                "ENTRY_NOT_IN_INBOX",
                "L'entry è fuori dall'inbox e il server non consente modifiche esterne.",
                "Riavvia il server con --allow-edit-outside-inbox per modificare "
                "entry in altri file inclusi.",
                details=[{"file": str(real_path), "inbox": str(inbox_real)}],
            )
    else:
        included = {Path(os.path.realpath(file)) for file in snapshot.files}
        if real_path not in included:
            return tool_error(
                "PATH_NOT_ALLOWED",
                "Il file dell'entry non è incluso dal ledger.",
                "Usa solo file inclusi dal ledger.",
                details=[{"file": str(real_path)}],
            )
        ledger_dir = Path(os.path.realpath(snapshot.ledger_path.parent))
        if not real_path.is_relative_to(ledger_dir):
            return tool_error(
                "PATH_NOT_ALLOWED",
                "Il file dell'entry è fuori dalla directory del ledger.",
                f"Modifica solo file dentro {ledger_dir}.",
                details=[{"file": str(real_path), "ledger_dir": str(ledger_dir)}],
            )

    if not real_path.is_file():
        return tool_error(
            "ENTRY_NOT_FOUND",
            f"File non trovato: {real_path}",
            "Rileggi il ledger e usa un entry_id aggiornato.",
        )
    try:
        text = real_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return tool_error(
            "ENTRY_NOT_FOUND",
            f"Impossibile leggere il file dell'entry: {exc}",
            "Verifica che il file esista e sia UTF-8.",
        )

    span = find_span(extract_directive_spans(real_path, text), entry_id.line)
    if span is None:
        return tool_error(
            "ENTRY_NOT_FOUND",
            f"Nessuna direttiva alla riga {entry_id.line} di {real_path}.",
            "Rileggi l'entry e usa un entry_id aggiornato.",
        )
    if span.entry_id.hash != entry_id.hash:
        return tool_error(
            "ENTRY_CHANGED",
            "Il contenuto dell'entry è cambiato.",
            "Rileggi l'entry e usa il nuovo entry_id.",
            details=[
                {
                    "file": str(real_path),
                    "line": entry_id.line,
                    "current_text": span.text,
                    "current_hash": span.entry_id.hash,
                }
            ],
        )
    if require_transaction and not is_transaction_span(span):
        return tool_error(
            "VALIDATION_FAILED",
            "L'entry non è una transazione.",
            "delete_transaction può eliminare solo transazioni.",
        )
    return ResolvedEntry(path=real_path, text=text, span=span)


def _edit_once(
    service: LedgerService,
    entry_id: EntryIdData,
    new_text: str,
    dry_run: bool,
) -> dict[str, Any]:
    snapshot = _load(service)
    if isinstance(snapshot, dict):
        return snapshot
    resolved = resolve_entry(snapshot, service.config, entry_id)
    if isinstance(resolved, dict):
        return resolved
    if not _span_has_directive(resolved.span):
        return tool_error(
            "ENTRY_NOT_FOUND",
            "L'entry non contiene una direttiva.",
            "Usa l'entry_id di una direttiva, non di un commento.",
        )

    parsed = _parse_new_text(new_text, resolved.path)
    if isinstance(parsed, dict):
        return parsed
    if len(parsed) != 1:
        return tool_error(
            "VALIDATION_FAILED",
            "new_text deve contenere esattamente una direttiva.",
            "Sostituisci l'entry con una sola direttiva Beancount.",
        )

    new_content = replace_span(resolved.text, resolved.span, new_text)
    return _validate_and_write(
        service,
        snapshot,
        resolved,
        new_content,
        dry_run=dry_run,
        new_text=new_text,
    )


def _delete_once(
    service: LedgerService,
    entry_id: EntryIdData,
    dry_run: bool,
) -> dict[str, Any]:
    snapshot = _load(service)
    if isinstance(snapshot, dict):
        return snapshot
    resolved = resolve_entry(
        snapshot,
        service.config,
        entry_id,
        require_transaction=True,
    )
    if isinstance(resolved, dict):
        return resolved

    new_content = delete_span(resolved.text, resolved.span)
    return _validate_and_write(
        service,
        snapshot,
        resolved,
        new_content,
        dry_run=dry_run,
        new_text=None,
    )


def _validate_and_write(
    service: LedgerService,
    snapshot: LedgerSnapshot,
    resolved: ResolvedEntry,
    new_content: str,
    *,
    dry_run: bool,
    new_text: str | None,
) -> dict[str, Any]:
    issues = _validate_staged(snapshot, resolved.path, new_content)
    if isinstance(issues, dict):
        return issues
    if issues:
        return validation_failed_response(issues, snapshot)

    new_span = (
        find_span(
            extract_directive_spans(resolved.path, new_content),
            resolved.span.entry_id.line,
        )
        if new_text is not None
        else None
    )
    if dry_run:
        return _success(
            snapshot,
            resolved,
            new_span,
            dry_run=True,
            new_text=new_text,
        )

    current = _load(service)
    if isinstance(current, dict):
        return current
    if current.version != snapshot.version:
        return tool_error(
            "VERSION_CONFLICT",
            "Il ledger è cambiato durante la validazione.",
            "Ricarica ledger_info e riprova.",
            details=[
                {
                    "expected": snapshot.version,
                    "actual": current.version,
                }
            ],
        )

    try:
        atomic_write(resolved.path, new_content)
    except OSError as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile scrivere il file: {exc}",
            "Verifica i permessi della directory e riprova.",
        )

    after = _load(service)
    if isinstance(after, dict):
        return after
    new_span = (
        find_span(
            extract_directive_spans(resolved.path, new_content),
            resolved.span.entry_id.line,
        )
        if new_text is not None
        else None
    )
    return _success(
        after,
        resolved,
        new_span,
        dry_run=False,
        new_text=new_text,
    )


def _validate_staged(
    snapshot: LedgerSnapshot,
    target: Path,
    new_content: str,
) -> list[Issue] | dict[str, Any]:
    try:
        return validate_staged_file(
            snapshot.ledger_path,
            snapshot.files,
            target,
            new_content,
            snapshot.errors,
        )
    except OSError as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile validare la modifica: {exc}",
            "Verifica che i file del ledger siano leggibili.",
        )


def _parse_new_text(
    new_text: str,
    path: Path,
) -> list[Directive] | dict[str, Any]:
    if not new_text.strip():
        return tool_error(
            "VALIDATION_FAILED",
            "new_text è vuoto.",
            "Fornisci una direttiva Beancount.",
        )
    if _FORBIDDEN_LINE_RE.search(new_text):
        return tool_error(
            "VALIDATION_FAILED",
            "new_text contiene include o plugin non ammessi.",
            "Rimuovi include e plugin dal testo.",
        )
    entries, errors, _ = parser.parse_string(
        new_text,
        report_filename=str(path),
    )
    if errors:
        return tool_error(
            "SYNTAX_ERROR",
            "new_text non è Beancount valido.",
            "Correggi la sintassi indicata nei details.",
            details=[issue_to_dict(issue) for issue in issues_from_errors(errors)],
        )
    forbidden = [entry for entry in entries if isinstance(entry, (Pad, Balance))]
    if forbidden:
        return tool_error(
            "VALIDATION_FAILED",
            "new_text contiene pad o balance.",
            "I tool di modifica non possono introdurre pad o balance.",
        )
    return entries


def _span_has_directive(span: DirectiveSpan) -> bool:
    entries, _, _ = parser.parse_string(span.text)
    return bool(entries)


def _run_write(
    service: LedgerService,
    dry_run: bool,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if dry_run:
        return operation()
    try:
        with write_lock(service.config.ledger_path):
            return operation()
    except LockError as exc:
        lock = lock_path_for(service.config.ledger_path)
        return tool_error(
            "LOCKED",
            str(exc),
            "Un'altra scrittura è in corso. Riprova tra poco; se il processo è "
            f"terminato, rimuovi il file di lock {lock}.",
        )


def _load(service: LedgerService) -> LedgerSnapshot | dict[str, Any]:
    try:
        return service.load()
    except (LedgerError, OSError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)


def _success(
    snapshot: LedgerSnapshot,
    resolved: ResolvedEntry,
    new_span: DirectiveSpan | None,
    *,
    dry_run: bool,
    new_text: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "file": str(resolved.path),
        "line": resolved.span.entry_id.line,
        "ledger_version": snapshot.version,
        "warning_count": len(snapshot.errors),
    }
    if new_span is not None:
        result["entry_id"] = entry_id_to_dict(new_span.entry_id)
    if new_text is None:
        result["deleted"] = True
        result["entry_text"] = resolved.span.text
        if dry_run:
            result["would_delete"] = True
    else:
        if dry_run:
            result["would_write_text"] = new_text.strip("\n") + "\n"
    return result


def _read_only_error() -> dict[str, Any]:
    return error_response(
        ErrorInfo(
            code="READ_ONLY",
            message="Il server è in modalità sola lettura.",
            hint="Riavvia il server senza --read-only per abilitare le scritture.",
        )
    )
