"""Read original directives and configuration without exposing arbitrary files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from beancount.core.data import Directive
from beancount.parser import parser

from beancount_mcp.entries import DirectiveSpan, entry_id_to_dict, extract_directive_spans
from beancount_mcp.entry_service import parse_entry_id
from beancount_mcp.errors import tool_error
from beancount_mcp.ledger import LEDGER_ERROR_HINT, LedgerError, LedgerService, LedgerSnapshot

CONFIG_LINE = re.compile(r'^\s*(option|plugin|include)\s+"((?:\\.|[^"\\])*)"')
SCOPE_LINE = re.compile(r"^\s*(pushtag|poptag|pushmeta|popmeta)\b")


@dataclass(frozen=True)
class SourceEntry:
    directive: Directive
    span: DirectiveSpan

    @property
    def kind(self) -> str:
        return type(self.directive).__name__.lower()


def source_entries(snapshot: LedgerSnapshot) -> dict[tuple[Path, int], SourceEntry]:
    """Index source directives, excluding entries synthesized by plugins/booking."""
    result: dict[tuple[Path, int], SourceEntry] = {}
    for file, content in sorted(snapshot.contents.items()):
        text = content.decode("utf-8")
        spans = {span.entry_id.line: span for span in extract_directive_spans(file, text)}
        entries, _, _ = parser.parse_string(text, report_filename=str(file))
        for entry in entries:
            line = int(entry.meta["lineno"])
            if line in spans:
                result[(file.resolve(), line)] = SourceEntry(entry, spans[line])
    return result


def payload(entry: SourceEntry) -> dict[str, Any]:
    return {
        "entry_id": entry_id_to_dict(entry.span.entry_id),
        "type": entry.kind,
        "date": entry.directive.date.isoformat(),
        "text": entry.span.text,
    }


def lookup_entry(
    index: dict[tuple[Path, int], SourceEntry], entry_id: dict[str, Any]
) -> SourceEntry | dict[str, Any]:
    parsed = parse_entry_id(entry_id)
    if isinstance(parsed, dict):
        return parsed
    path = Path(parsed.file)
    if not path.is_absolute():
        return tool_error(
            "PATH_NOT_ALLOWED",
            "entry_id.file deve essere assoluto.",
            "Usa gli identificatori restituiti da find_entries.",
        )
    entry = index.get((path.resolve(), parsed.line))
    if entry is None:
        return tool_error(
            "ENTRY_NOT_FOUND",
            "Direttiva non trovata nei file sorgente.",
            "Rileggi find_entries; le entry generate dai plugin non sono modificabili.",
        )
    if entry.span.entry_id.hash != parsed.hash:
        return tool_error(
            "ENTRY_CHANGED",
            "La direttiva è cambiata.",
            "Usa l'identificatore aggiornato.",
            details=[payload(entry)],
        )
    return entry


def find_entries(
    service: LedgerService,
    *,
    types: list[str] | None = None,
    account: str | None = None,
    file: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    text_contains: str | None = None,
    limit: int = 100,
    offset: int = 0,
    expected_ledger_version: str | None = None,
) -> dict[str, Any]:
    """Page over every source directive in deterministic file/line order."""
    if not 1 <= limit <= 500 or offset < 0:
        return tool_error(
            "LIMIT_EXCEEDED",
            "limit deve essere 1–500 e offset >= 0.",
            "Riduci la pagina o correggi offset.",
        )
    try:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
        if start and end and start > end:
            raise ValueError("Intervallo date invertito.")
        snapshot = service.load()
        if expected_ledger_version is not None and expected_ledger_version != snapshot.version:
            return version_conflict(snapshot)
        rows = []
        for (path, _), entry in sorted(source_entries(snapshot).items()):
            if types is not None and entry.kind not in types:
                continue
            if (
                file is not None
                and path != Path(os.path.abspath(snapshot.ledger_path.parent / file)).resolve()
            ):
                continue
            if start and entry.directive.date < start or end and entry.directive.date > end:
                continue
            if (
                text_contains is not None
                and text_contains.casefold() not in entry.span.text.casefold()
            ):
                continue
            if account is not None:
                accounts = [getattr(entry.directive, "account", "")]
                accounts += [getattr(entry.directive, "source_account", "")]
                accounts += [p.account for p in getattr(entry.directive, "postings", [])]
                if not any(a == account or a.startswith(account + ":") for a in accounts):
                    continue
            rows.append(payload(entry))
        selected = rows[offset : offset + limit]
        return {
            "ok": True,
            "entries": selected,
            "count": len(selected),
            "total_matches": len(rows),
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "ledger_version": snapshot.version,
        }
    except ValueError as exc:
        return tool_error("VALIDATION_FAILED", str(exc), "Usa date ISO YYYY-MM-DD.")
    except (LedgerError, OSError, UnicodeDecodeError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)


def get_entry(service: LedgerService, entry_id: dict[str, Any]) -> dict[str, Any]:
    """Read and verify a source entry by ID."""
    try:
        snapshot = service.load()
        entry = lookup_entry(source_entries(snapshot), entry_id)
        if isinstance(entry, dict):
            return entry
        return {"ok": True, "entry": payload(entry), "ledger_version": snapshot.version}
    except (LedgerError, OSError, UnicodeDecodeError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)


def ledger_config(service: LedgerService) -> dict[str, Any]:
    """Return source option/include/plugin statements and capability flags."""
    try:
        snapshot = service.load()
        statements = []
        for file, data in sorted(snapshot.contents.items()):
            for span in extract_directive_spans(file, data.decode("utf-8")):
                match = CONFIG_LINE.match(span.text)
                if match:
                    statements.append(
                        {
                            "file": str(file),
                            "line": span.entry_id.line,
                            "type": match[1],
                            "name": match[2],
                            "text": span.text,
                        }
                    )
        config = service.config
        return {
            "ok": True,
            "statements": statements,
            "ledger_version": snapshot.version,
            "capabilities": {
                "read_only": config.read_only,
                "edit_outside_inbox": config.allow_edit_outside_inbox,
                "config_changes": config.allow_config_changes,
                "plugin_changes": config.allow_plugin_changes,
                "init": config.allow_init,
            },
        }
    except (LedgerError, OSError, UnicodeDecodeError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)


def version_conflict(snapshot: LedgerSnapshot) -> dict[str, Any]:
    return tool_error(
        "VERSION_CONFLICT",
        "La versione del ledger è cambiata.",
        "Rileggi i dati e usa la nuova ledger_version.",
        details=[{"actual": snapshot.version}],
    )
