"""Plan source edits and file/configuration changes as one validated transaction."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from beancount.core.data import Balance, Document, Pad
from beancount.parser import parser

from beancount_mcp.entries import DirectiveSpan, extract_directive_spans
from beancount_mcp.errors import tool_error
from beancount_mcp.ledger import LEDGER_ERROR_HINT, LedgerError, LedgerService, LedgerSnapshot
from beancount_mcp.multifile import TransactionError, commit_files, transaction_dir
from beancount_mcp.source_service import (
    CONFIG_LINE,
    SCOPE_LINE,
    SourceEntry,
    lookup_entry,
    source_entries,
    version_conflict,
)
from beancount_mcp.staging import StagingError, validate_staged_tree
from beancount_mcp.write_service import validation_failed_response
from beancount_mcp.writer import LockError, append_text, write_lock


class ChangeError(Exception):
    """A structured, user-correctable planning failure."""

    def __init__(self, code: str, message: str, hint: str = "Correggi il batch e riprova.") -> None:
        self.response = tool_error(code, message, hint)
        super().__init__(message)


def _quote(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ChangeError("VALIDATION_FAILED", "La stringa contiene caratteri di controllo.")
    return json.dumps(value, ensure_ascii=False)


class ChangePlan:
    """Resolve all entry IDs against one immutable source version."""

    def __init__(
        self, service: LedgerService, snapshot: LedgerSnapshot, allow_balance_changes: bool
    ) -> None:
        self.config = service.config
        self.snapshot = snapshot
        self.allow_balances = allow_balance_changes
        self.originals: dict[Path, str | None] = {
            path.resolve(): data.decode("utf-8") for path, data in snapshot.contents.items()
        }
        self.index = source_entries(snapshot)
        self.edits: dict[Path, list[tuple[int, int, str]]] = defaultdict(list)
        self.appends: dict[Path, list[str]] = defaultdict(list)
        self.config_targets: set[tuple[Path, str, str | None]] = set()
        self.required_files: set[Path] = set()
        if snapshot.inbox.included:
            self.required_files.add(self.config.inbox_path.resolve())

    def target(self, value: str, *, config: bool = False, new: bool = False) -> Path:
        root = self.config.ledger_path.parent.resolve()
        path = (root / Path(value).expanduser()).resolve()
        inbox = self.config.inbox_path.resolve()
        journal = transaction_dir(self.config.ledger_path).resolve()
        if path.is_relative_to(journal) or path == Path(str(self.config.ledger_path) + ".lock"):
            raise ChangeError("PATH_NOT_ALLOWED", "Il percorso è riservato al server.")
        if not path.is_relative_to(root) and path != inbox:
            raise ChangeError("PATH_NOT_ALLOWED", f"File fuori dalla directory del ledger: {path}")
        if path != inbox and not config and not self.config.allow_edit_outside_inbox:
            raise ChangeError("ENTRY_NOT_IN_INBOX", "Il batch richiede --allow-edit-outside-inbox.")
        if not new and path not in self.originals:
            raise ChangeError("PATH_NOT_ALLOWED", f"File non incluso nel ledger: {path}")
        return path

    def parse_text(self, text: str, *, empty: bool = False) -> int:
        if re.search(r"(?m)^\s*(include|plugin|option)\b", text):
            raise ChangeError(
                "VALIDATION_FAILED", "Usa le operazioni dedicate per include e configurazione."
            )
        if any(line.startswith("; beancount-mcp-idempotency:") for line in text.splitlines()):
            raise ChangeError("VALIDATION_FAILED", "I commenti di idempotenza sono riservati.")
        entries, errors, _ = parser.parse_string(text)
        if errors:
            raise ChangeError("SYNTAX_ERROR", "; ".join(str(error.message) for error in errors))
        if not entries and not empty:
            raise ChangeError("VALIDATION_FAILED", "Il testo non contiene direttive contabili.")
        for entry in entries:
            self.protect(entry)
        return len(entries)

    def protect(self, entry: Any) -> None:
        if isinstance(entry, Pad):
            raise ChangeError("PAD_PROTECTED", "Il padding automatico non è consentito.")
        if isinstance(entry, Balance) and not self.allow_balances:
            raise ChangeError(
                "BALANCE_PROTECTED",
                "La modifica tocca una balance assertion.",
                "Controlla il saldo osservato e passa allow_balance_changes=true.",
            )

    def edit(self, file: Path, span: DirectiveSpan, replacement: str) -> None:
        for start, end, _ in self.edits[file]:
            if start < span.end_offset and span.start_offset < end:
                raise ChangeError("CHANGE_CONFLICT", "La stessa direttiva è modificata più volte.")
        self.edits[file].append((span.start_offset, span.end_offset, replacement))

    def resolve(self, value: Any) -> SourceEntry:
        if not isinstance(value, dict):
            raise ChangeError("VALIDATION_FAILED", "entry_id deve essere un oggetto.")
        result = lookup_entry(self.index, value)
        if isinstance(result, dict):
            error = ChangeError("ENTRY_NOT_FOUND", "Direttiva non trovata.")
            error.response = result
            raise error
        self.target(result.span.entry_id.file)
        return result

    def config_edit(
        self, file: Path, kind: str, name: str | None, *, require_match: bool = False
    ) -> None:
        target = (file, kind, name)
        if target in self.config_targets:
            raise ChangeError("CHANGE_CONFLICT", "La stessa configurazione è modificata più volte.")
        self.config_targets.add(target)
        found = False
        text = self.originals[file] or ""
        for span in extract_directive_spans(file, text):
            match = CONFIG_LINE.match(span.text)
            if match and match[1] == kind and (name is None or match[2] == name):
                self.edit(file, span, "")
                found = True
        if require_match and not found:
            raise ChangeError(
                "ENTRY_NOT_FOUND", "Include non trovato: usa il pattern da ledger_config."
            )

    def apply(self, change: dict[str, Any]) -> None:
        schemas = {
            "append": ({"op", "text"}, {"file"}),
            "replace": ({"op", "entry_id", "text"}, set()),
            "delete": ({"op", "entry_id"}, set()),
            "move": ({"op", "entry_id", "file"}, set()),
            "create_file": ({"op", "file"}, {"text"}),
            "add_include": ({"op", "file"}, {"source_file"}),
            "remove_include": ({"op", "pattern"}, {"source_file"}),
            "set_option": ({"op", "name", "values"}, {"file"}),
            "set_plugins": ({"op", "plugins"}, {"file"}),
        }
        op = change.get("op")
        if not isinstance(op, str) or op not in schemas:
            raise ChangeError("VALIDATION_FAILED", f"Operazione sconosciuta: {op!r}")
        required, optional = schemas[op]
        if not required <= change.keys() or change.keys() - required - optional:
            raise ChangeError("VALIDATION_FAILED", f"Campi non validi per {op}.")
        for key in {"file", "source_file", "text", "name", "pattern"} & change.keys():
            if not isinstance(change[key], str):
                raise ChangeError("VALIDATION_FAILED", f"{key} deve essere una stringa.")
        if op in {"replace", "delete", "move"}:
            entry = self.resolve(change["entry_id"])
            file = Path(entry.span.entry_id.file).resolve()
            if op == "move":
                target = self.target(change["file"])
                if target == file:
                    raise ChangeError("CHANGE_CONFLICT", "Origine e destinazione coincidono.")
                for scoped in [file, target]:
                    if any(
                        SCOPE_LINE.match(span.text)
                        for span in extract_directive_spans(scoped, self.originals[scoped] or "")
                    ):
                        raise ChangeError(
                            "MOVE_CONTEXT_DEPENDENT",
                            "Il file usa pushtag/pushmeta.",
                            "Rendi espliciti tag e metadati prima di spostare le entry.",
                        )
                moved_text = entry.span.text
                if isinstance(entry.directive, Document):
                    # The parser resolves relative document names against their
                    # source file. Preserve that reference when changing files.
                    match = re.match(
                        r'(\d{4}-\d{2}-\d{2}\s+document\s+\S+\s+)("(?:\\.|[^"\\])*")',
                        moved_text,
                        flags=re.DOTALL,
                    )
                    if match is None:
                        raise ChangeError(
                            "MOVE_CONTEXT_DEPENDENT", "Percorso documento non leggibile."
                        )
                    moved_text = (
                        match[1] + _quote(entry.directive.filename) + moved_text[match.end() :]
                    )
                self.appends[target].append(moved_text)
                self.edit(file, entry.span, "")
            else:
                self.protect(entry.directive)
                replacement = ""
                if op == "replace":
                    if self.parse_text(change["text"]) != 1:
                        raise ChangeError(
                            "VALIDATION_FAILED", "replace richiede una sola direttiva."
                        )
                    replacement = change["text"].strip("\n") + "\n"
                self.edit(file, entry.span, replacement)
        elif op == "append":
            self.parse_text(change["text"])
            self.appends[self.target(change.get("file", str(self.config.inbox_path)))].append(
                change["text"]
            )
        elif op == "create_file":
            file = self.target(change["file"], new=True)
            if (
                file.exists()
                or file in self.originals
                or file.suffix not in {".bean", ".beancount"}
            ):
                raise ChangeError(
                    "PATH_NOT_ALLOWED", "create_file richiede un nuovo file .bean/.beancount."
                )
            text = change.get("text", "")
            self.parse_text(text, empty=True)
            self.originals[file] = None
            self.appends[file].append(text)
            self.required_files.add(file)
        elif op in {"add_include", "remove_include"}:
            source = self.target(change.get("source_file", str(self.config.ledger_path)))
            if op == "add_include":
                file = self.target(change["file"], new=True)
                if file not in self.originals:
                    if not file.is_file():
                        raise ChangeError("PATH_NOT_ALLOWED", "Il file da includere non esiste.")
                    text = file.read_bytes().decode("utf-8")
                    self.parse_text(text, empty=True)
                    self.originals[file] = text
                self.required_files.add(file)
                relative = Path(os.path.relpath(file, source.parent)).as_posix()
                self.appends[source].append(f"include {_quote(relative)}\n")
            else:
                self.config_edit(source, "include", change["pattern"], require_match=True)
        elif op == "set_option":
            if not self.config.allow_config_changes:
                raise ChangeError("CONFIG_NOT_ALLOWED", "Serve --allow-config-changes.")
            file = self.target(change.get("file", str(self.config.ledger_path)), config=True)
            name = change["name"]
            if not re.fullmatch(r"[a-z][a-z_]*", name):
                raise ChangeError("VALIDATION_FAILED", "Nome opzione non valido.")
            values = change["values"]
            if values is not None and (
                not isinstance(values, list) or not all(isinstance(v, str) for v in values)
            ):
                raise ChangeError(
                    "VALIDATION_FAILED", "values deve essere una lista di stringhe o null."
                )
            self.config_edit(file, "option", name)
            for value in values or []:
                self.appends[file].append(f"option {_quote(name)} {_quote(value)}\n")
        elif op == "set_plugins":
            if not self.config.allow_plugin_changes:
                raise ChangeError("PLUGIN_NOT_ALLOWED", "Serve --allow-plugin-changes.")
            file = self.target(change.get("file", str(self.config.ledger_path)), config=True)
            plugins = change["plugins"]
            if not isinstance(plugins, list):
                raise ChangeError("VALIDATION_FAILED", "plugins deve essere una lista.")
            self.config_edit(file, "plugin", None)
            for plugin in plugins:
                if (
                    not isinstance(plugin, dict)
                    or not isinstance(plugin.get("name"), str)
                    or plugin.keys() - {"name", "config"}
                ):
                    raise ChangeError(
                        "VALIDATION_FAILED", "Ogni plugin richiede name e config opzionale."
                    )
                if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", plugin["name"]):
                    raise ChangeError("VALIDATION_FAILED", "Modulo plugin non valido.")
                config = plugin.get("config")
                if config is not None and not isinstance(config, str):
                    raise ChangeError(
                        "VALIDATION_FAILED", "La configurazione plugin deve essere una stringa."
                    )
                suffix = " " + _quote(config) if config is not None else ""
                self.appends[file].append(f"plugin {_quote(plugin['name'])}{suffix}\n")

    def contents(self) -> dict[Path, str]:
        result = {}
        for file, original in self.originals.items():
            text = original or ""
            for start, end, replacement in sorted(self.edits[file], reverse=True):
                text = text[:start] + replacement + text[end:]
            for block in self.appends[file]:
                if block:
                    text = append_text(text, block)
            result[file] = text
        return result


def apply_changes(
    service: LedgerService,
    changes: list[dict[str, Any]],
    expected_ledger_version: str,
    *,
    dry_run: bool = False,
    allow_balance_changes: bool = False,
) -> dict[str, Any]:
    """Validate the final tree once, then commit all changes under one journal."""
    if service.config.read_only:
        return tool_error(
            "READ_ONLY", "Il server è in sola lettura.", "Riavvialo in modalità scrittura."
        )
    if (
        not isinstance(changes, list)
        or not 1 <= len(changes) <= 500
        or not all(isinstance(c, dict) for c in changes)
    ):
        return tool_error(
            "VALIDATION_FAILED", "Invia da 1 a 500 operazioni.", "Dividi i batch più grandi."
        )
    try:
        if dry_run:
            return _apply_once(
                service, changes, expected_ledger_version, True, allow_balance_changes
            )
        with write_lock(service.config.ledger_path):
            return _apply_once(
                service, changes, expected_ledger_version, False, allow_balance_changes
            )
    except ChangeError as exc:
        return exc.response
    except LockError as exc:
        return tool_error("LOCKED", str(exc), "Riprova dopo la scrittura in corso.")
    except StagingError as exc:
        return tool_error(
            "VALIDATION_FAILED", str(exc), "Controlla gli include e mantieni inclusa l’inbox."
        )
    except (LedgerError, OSError, UnicodeDecodeError, TransactionError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)


def _apply_once(
    service: LedgerService,
    changes: list[dict[str, Any]],
    expected: str,
    dry_run: bool,
    allow_balances: bool,
) -> dict[str, Any]:
    snapshot = service.load()
    if snapshot.version != expected:
        return version_conflict(snapshot)
    plan = ChangePlan(service, snapshot, allow_balances)
    for change in changes:
        plan.apply(change)
    contents = plan.contents()
    issues = validate_staged_tree(
        snapshot.ledger_path,
        snapshot.files,
        contents,
        snapshot.errors,
        allow_new_files=True,
        required_files=plan.required_files,
    )
    if issues:
        return validation_failed_response(issues, snapshot)
    # Install new destinations before changing include statements/source files.
    modifications = {
        file: contents[file]
        for file in sorted(contents, key=lambda path: (plan.originals[path] is not None, path))
        if contents[file] != plan.originals[file]
    }
    previews = [
        {"file": str(file), "before": plan.originals[file], "after": text}
        for file, text in sorted(modifications.items())
    ]
    if dry_run:
        return {"ok": True, "dry_run": True, "files": previews, "ledger_version": snapshot.version}
    current = service.load()
    if current.version != expected:
        return version_conflict(current)
    for file, original in plan.originals.items():
        actual = file.read_bytes().decode("utf-8") if file.exists() else None
        if actual != original:
            raise ChangeError("VERSION_CONFLICT", f"Il file è cambiato: {file}")
    commit_files(
        snapshot.ledger_path,
        modifications,
        expected_contents={file: plan.originals[file] for file in modifications},
    )
    after = service.load()
    return {
        "ok": True,
        "dry_run": False,
        "files_changed": len(modifications),
        "files": [str(file) for file in modifications],
        "ledger_version": after.version,
        "warning_count": len(after.errors),
    }
