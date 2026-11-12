"""Token-aware rewrites for account, tag, and link renames."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from beancount.core import account as beancount_account
from beancount.core import getters
from beancount.core.data import Custom, Directive

from beancount_mcp.entries import NON_TRANSACTION_DIRECTIVES, source_lines, split_lines
from beancount_mcp.ledger import LedgerSnapshot

TAG_RE = re.compile(r"[A-Za-z0-9\-_/.]+")
ROOT_OPTIONS = (
    ("name_assets", "Assets"),
    ("name_liabilities", "Liabilities"),
    ("name_equity", "Equity"),
    ("name_income", "Income"),
    ("name_expenses", "Expenses"),
)
# Directives whose header accepts tags and links.
_TAGGED_DIRECTIVES = frozenset({"note", "document"})
_DATED_LINE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\s+(\S+)")

LineRewriter = Callable[[str, bool], str]


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
    # Text each modified file had when the plan was computed.
    originals: dict[Path, str] = field(default_factory=dict)


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

    def rewrite(line: str, in_string: bool) -> str:
        if not in_string and not _line_can_contain_account(line):
            return line
        return _rewrite_account_line(
            line, old_account, new_account, include_subaccounts, in_string=in_string
        )

    plan = _rewrite_files(snapshot, rewrite)
    if not plan.changes:
        raise RenameError(
            "ENTRY_NOT_FOUND",
            f"Nessuna occorrenza dell'account {old_account}.",
            "Controlla il nome dell'account e riprova.",
        )
    return plan


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

    def rewrite(line: str, in_string: bool) -> str:
        if not in_string and not _line_can_contain_token(line, marker):
            return line
        return _rewrite_token_line(line, marker, old, new, in_string=in_string)

    plan = _rewrite_files(snapshot, rewrite)
    if not plan.changes:
        label = "tag" if marker == "#" else "link"
        raise RenameError(
            "ENTRY_NOT_FOUND",
            f"Nessuna occorrenza del {label} {marker}{old}.",
            f"Controlla il nome del {label} e riprova.",
        )
    return plan


def _rewrite_files(snapshot: LedgerSnapshot, rewrite: LineRewriter) -> RenamePlan:
    """Rewrite every line of the snapshot's files and collect what changed."""
    changes: list[RenameChange] = []
    modifications: dict[Path, str] = {}
    originals: dict[Path, str] = {}
    seen: set[Path] = set()
    for source in snapshot.files:
        file = Path(os.path.realpath(source))
        if file in seen:
            continue
        seen.add(file)
        text = _snapshot_text(snapshot, source, file)
        rewritten_lines: list[str] = []
        for line_number, (line, in_string) in enumerate(source_lines(split_lines(text)), start=1):
            rewritten = rewrite(line, in_string)
            rewritten_lines.append(rewritten)
            if rewritten != line:
                changes.append(
                    RenameChange(
                        file=str(file),
                        line=line_number,
                        before=line.rstrip("\r\n"),
                        after=rewritten.rstrip("\r\n"),
                    )
                )
        rewritten_text = "".join(rewritten_lines)
        if rewritten_text != text:
            modifications[file] = rewritten_text
            originals[file] = text
    return RenamePlan(tuple(changes), modifications, originals)


def account_leftovers(
    entries: Iterable[Directive],
    old_account: str,
    include_subaccounts: bool,
) -> list[Directive]:
    """List loaded entries that still reference the renamed account."""
    old = old_account.strip()

    def is_old(name: object) -> bool:
        return (
            isinstance(name, str)
            and _replace_account_token(name, old, "", include_subaccounts) != name
        )

    leftovers: list[Directive] = []
    for entry in entries:
        names = set(getters.get_entry_accounts(entry))
        if isinstance(entry, Custom):
            names.update(
                value.value
                for value in entry.values or ()
                if getattr(value, "dtype", None) == beancount_account.TYPE
            )
        if any(is_old(name) for name in names):
            leftovers.append(entry)
    return leftovers


def token_leftovers(
    entries: Iterable[Directive],
    marker: str,
    old_value: str,
) -> list[Directive]:
    """List loaded entries that still carry the renamed tag or link."""
    old = _normalize_tag(old_value, marker)
    attribute = "tags" if marker == "#" else "links"
    return [entry for entry in entries if old in (getattr(entry, attribute, None) or ())]


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


def _line_can_contain_account(line: str) -> bool:
    """Dated directives, their indented lines, and pushmeta can name accounts."""
    return line[:1].isspace() or line.startswith("pushmeta") or bool(_DATED_LINE_RE.match(line))


def _rewrite_account_line(
    line: str,
    old: str,
    new: str,
    include_subaccounts: bool,
    *,
    in_string: bool = False,
) -> str:
    """Rename account tokens outside strings and comments.

    Account names contain a colon and no other token kind can equal one, so
    every whole-token match is an account: postings, directive arguments,
    custom values and metadata values alike.
    """

    def rewrite(code: str) -> str:
        return re.sub(
            r"\S+",
            lambda match: _replace_account_token(match[0], old, new, include_subaccounts),
            code,
        )

    return _rewrite_code(line, rewrite, in_string=in_string)


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
    if line[:1].isspace():
        # Tags and links may continue on indented lines below the header.
        return stripped.startswith(("#", "^"))
    match = _DATED_LINE_RE.match(line)
    if match is None:
        return False
    return match[1] in _TAGGED_DIRECTIVES or match[1] not in NON_TRANSACTION_DIRECTIVES


def _rewrite_token_line(
    line: str,
    marker: str,
    old: str,
    new: str,
    *,
    in_string: bool = False,
) -> str:
    pattern = re.compile(rf"{re.escape(marker)}([A-Za-z0-9\-_/.]*)")

    def rewrite(code: str) -> str:
        return pattern.sub(
            lambda match: f"{marker}{new}" if match[1] == old else match[0],
            code,
        )

    return _rewrite_code(line, rewrite, in_string=in_string)


def _rewrite_code(
    line: str,
    rewrite: Callable[[str], str],
    *,
    in_string: bool = False,
) -> str:
    """Apply ``rewrite`` to the parts of ``line`` outside strings and comments."""
    output: list[str] = []
    code: list[str] = []
    escaped = False
    for index, char in enumerate(line):
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            output.append(rewrite("".join(code)))
            code.clear()
            output.append(char)
            in_string = True
        elif char == ";":
            output.append(rewrite("".join(code)))
            code.clear()
            output.append(line[index:])
            break
        else:
            code.append(char)
    output.append(rewrite("".join(code)))
    return "".join(output)


def _snapshot_text(snapshot: LedgerSnapshot, source: Path, file: Path) -> str:
    """Return the bytes the snapshot was parsed from, so plan and version agree."""
    data = snapshot.contents.get(source)
    if data is None:
        return _read_text(file)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenameError(
            "LEDGER_ERROR",
            f"File non UTF-8: {file}",
            "Converti il file del ledger in UTF-8 e riprova.",
        ) from exc


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
