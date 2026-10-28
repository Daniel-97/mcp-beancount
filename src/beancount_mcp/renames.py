"""Token-aware rewrites for account, tag, and link renames."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beancount.core import account as beancount_account
from beancount.core import getters

from beancount_mcp.ledger import LedgerSnapshot

TAG_RE = re.compile(r"[A-Za-z0-9\-_/.]+")
TAG_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_./")
ROOT_OPTIONS = (
    ("name_assets", "Assets"),
    ("name_liabilities", "Liabilities"),
    ("name_equity", "Equity"),
    ("name_income", "Income"),
    ("name_expenses", "Expenses"),
)
NON_TRANSACTION_DIRECTIVES = {
    "open",
    "close",
    "balance",
    "pad",
    "note",
    "document",
    "price",
    "event",
    "query",
    "custom",
    "commodity",
}


class RenameError(Exception):
    """Domain error for a rename operation."""

    def __init__(
        self,
        code: str,
        message: str,
        hint: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details or []


@dataclass(frozen=True, slots=True)
class RenameChange:
    """One rewritten line."""

    file: str
    line: int
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """All file modifications for one rename operation."""

    changes: tuple[RenameChange, ...]
    modifications: dict[Path, str]


def plan_account_rename(
    snapshot: LedgerSnapshot,
    old_account: str,
    new_account: str,
    include_subaccounts: bool = False,
) -> RenamePlan:
    """Plan an account rename across the current ledger snapshot."""
    old_account = old_account.strip()
    new_account = new_account.strip()

    if not beancount_account.is_valid(new_account):
        raise RenameError(
            "VALIDATION_FAILED",
            f"Nome account non valido: {new_account!r}.",
            "Usa il formato Root:Sottoconto, ad esempio Expenses:Restaurant.",
        )
    root = beancount_account.split(new_account)[0]
    allowed_roots = {snapshot.options.get(option, default) for option, default in ROOT_OPTIONS}
    if root not in allowed_roots:
        raise RenameError(
            "VALIDATION_FAILED",
            f"Radice account non ammessa: {root}.",
            f"Radici ammesse: {', '.join(sorted(allowed_roots))}.",
        )
    if include_subaccounts and new_account.startswith(f"{old_account}:"):
        raise RenameError(
            "VALIDATION_FAILED",
            "Il nuovo nome non può essere un sottoconto del vecchio durante un "
            "rename con sottoconti.",
            "Scegli un nuovo nome che non sia dentro il vecchio account.",
        )
    existing_accounts = getters.get_accounts(list(snapshot.entries))
    if old_account == new_account:
        if old_account in existing_accounts:
            return RenamePlan(changes=(), modifications={})
        raise RenameError(
            "ENTRY_NOT_FOUND",
            f"Nessuna occorrenza dell'account {old_account}.",
            "Controlla il nome dell'account e riprova.",
        )
    if new_account in existing_accounts:
        raise RenameError(
            "ACCOUNT_EXISTS",
            f"L'account {new_account} esiste già.",
            "Scegli un nome nuovo oppure fondi i due account con un'operazione dedicata.",
            details=[{"account": new_account}],
        )

    changes: list[RenameChange] = []
    modifications: dict[Path, str] = {}
    seen: set[Path] = set()
    for source in snapshot.files:
        file = Path(os.path.realpath(source))
        if file in seen:
            continue
        seen.add(file)
        text = _read_text(file)
        lines = text.splitlines(keepends=True)
        rewritten_lines: list[str] = []
        changed = False
        for line_number, (line, in_string) in enumerate(_source_lines(lines), start=1):
            if in_string:
                rewritten_lines.append(line)
                continue
            rewritten = _rewrite_account_line(
                line,
                old_account,
                new_account,
                include_subaccounts,
            )
            rewritten_lines.append(rewritten)
            if rewritten != line:
                changed = True
                changes.append(
                    RenameChange(
                        file=str(file),
                        line=line_number,
                        before=line.rstrip("\r\n"),
                        after=rewritten.rstrip("\r\n"),
                    )
                )
        if changed:
            modifications[file] = "".join(rewritten_lines)

    if not changes:
        raise RenameError(
            "ENTRY_NOT_FOUND",
            f"Nessuna occorrenza dell'account {old_account}.",
            "Controlla il nome dell'account e riprova.",
        )
    return RenamePlan(tuple(changes), modifications)


def plan_tag_rename(
    snapshot: LedgerSnapshot,
    old_tag: str,
    new_tag: str,
) -> RenamePlan:
    """Plan a tag rename across the current ledger snapshot."""
    return _plan_token_rename(snapshot, "#", old_tag, new_tag)


def plan_link_rename(
    snapshot: LedgerSnapshot,
    old_link: str,
    new_link: str,
) -> RenamePlan:
    """Plan a link rename across the current ledger snapshot."""
    return _plan_token_rename(snapshot, "^", old_link, new_link)


def _plan_token_rename(
    snapshot: LedgerSnapshot,
    marker: str,
    old_value: str,
    new_value: str,
) -> RenamePlan:
    old = _normalize_tag(old_value, marker)
    new = _normalize_tag(new_value, marker)
    if old == new:
        return RenamePlan(changes=(), modifications={})

    changes: list[RenameChange] = []
    modifications: dict[Path, str] = {}
    seen: set[Path] = set()
    for source in snapshot.files:
        file = Path(os.path.realpath(source))
        if file in seen:
            continue
        seen.add(file)
        text = _read_text(file)
        lines = text.splitlines(keepends=True)
        rewritten_lines: list[str] = []
        changed = False
        for line_number, (line, in_string) in enumerate(_source_lines(lines), start=1):
            if not in_string and not _line_can_contain_token(line, marker):
                rewritten_lines.append(line)
                continue
            rewritten = _rewrite_token_line(line, marker, old, new, in_string=in_string)
            rewritten_lines.append(rewritten)
            if rewritten != line:
                changed = True
                changes.append(
                    RenameChange(
                        file=str(file),
                        line=line_number,
                        before=line.rstrip("\r\n"),
                        after=rewritten.rstrip("\r\n"),
                    )
                )
        if changed:
            modifications[file] = "".join(rewritten_lines)

    if not changes:
        label = "tag" if marker == "#" else "link"
        raise RenameError(
            "ENTRY_NOT_FOUND",
            f"Nessuna occorrenza del {label} {marker}{old}.",
            f"Controlla il nome del {label} e riprova.",
        )
    return RenamePlan(tuple(changes), modifications)


def _normalize_tag(value: str, marker: str) -> str:
    normalized = value.strip()
    if normalized.startswith(marker):
        normalized = normalized[1:]
    if not TAG_RE.fullmatch(normalized):
        label = "tag" if marker == "#" else "link"
        raise RenameError(
            "VALIDATION_FAILED",
            f"{label.capitalize()} non valido: {value!r}.",
            "Usa solo lettere, numeri, '-', '_', '/' e '.'.",
        )
    return normalized


def _rewrite_account_line(
    line: str,
    old: str,
    new: str,
    include_subaccounts: bool,
) -> str:
    newline = ""
    body = line
    if line.endswith("\r\n"):
        newline = "\r\n"
        body = line[:-2]
    elif line.endswith("\n"):
        newline = "\n"
        body = line[:-1]

    pad = re.match(
        r"^(\d{4}-\d{2}-\d{2}\s+pad\s+)(\S+)(\s+)(\S+)(.*)$",
        body,
    )
    if pad:
        first = _replace_account_token(pad.group(2), old, new, include_subaccounts)
        second = _replace_account_token(pad.group(4), old, new, include_subaccounts)
        if first != pad.group(2) or second != pad.group(4):
            return f"{pad.group(1)}{first}{pad.group(3)}{second}{pad.group(5)}{newline}"
        return body + newline

    directive = re.match(
        r"^(\d{4}-\d{2}-\d{2}\s+(?:open|close|balance|note|document)\s+)"
        r"(\S+)(.*)$",
        body,
    )
    if directive:
        account = _replace_account_token(
            directive.group(2),
            old,
            new,
            include_subaccounts,
        )
        if account != directive.group(2):
            return f"{directive.group(1)}{account}{directive.group(3)}{newline}"
        return body + newline

    posting = re.match(r"^(\s+(?:\S\s+)?)(\S+)(.*)$", body)
    if posting:
        account = _replace_account_token(
            posting.group(2),
            old,
            new,
            include_subaccounts,
        )
        if account != posting.group(2):
            return f"{posting.group(1)}{account}{posting.group(3)}{newline}"
    return body + newline


def _replace_account_token(
    token: str,
    old: str,
    new: str,
    include_subaccounts: bool,
) -> str:
    if token == old:
        return new
    if include_subaccounts and token.startswith(f"{old}:"):
        return new + token[len(old) :]
    return token


def _line_can_contain_token(line: str, marker: str) -> bool:
    stripped = line.lstrip()
    if marker == "#" and stripped.startswith(("pushtag", "poptag")):
        return True
    match = re.match(r"^\d{4}-\d{2}-\d{2}\s+(\S+)", line)
    if match is None:
        return False
    return match.group(1) not in NON_TRANSACTION_DIRECTIVES


def _rewrite_token_line(
    line: str,
    marker: str,
    old: str,
    new: str,
    *,
    in_string: bool = False,
) -> str:
    output: list[str] = []
    index = 0
    escaped = False
    while index < len(line):
        char = line[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ";":
            output.append(line[index:])
            break
        if char == marker:
            end = index + 1
            while end < len(line) and line[end] in TAG_CHARS:
                end += 1
            token = line[index + 1 : end]
            if token == old:
                output.append(f"{marker}{new}")
            else:
                output.append(line[index:end])
            index = end
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenameError(
            "LEDGER_ERROR",
            f"File non UTF-8: {path}",
            "Converti il file del ledger in UTF-8 e riprova.",
        ) from exc
    except OSError as exc:
        raise RenameError(
            "LEDGER_ERROR",
            f"Impossibile leggere {path}: {exc}",
            "Verifica che il file esista e sia leggibile.",
        ) from exc


def _source_lines(lines: list[str]) -> Iterator[tuple[str, bool]]:
    """Track quoted strings across lines; comments cannot open strings."""
    in_string = False
    escaped = False
    for line in lines:
        starts_in_string = in_string
        for char in line:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == ";":
                break
            elif char == '"':
                in_string = True
        yield line, starts_in_string
