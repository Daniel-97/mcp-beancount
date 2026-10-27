"""Stage ledger files in a temporary tree for before/after validation."""

from __future__ import annotations

import glob
import os
import re
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from beancount import loader
from beancount.core.data import BeancountError

from beancount_mcp.validation import (
    Issue,
    compare_issues,
    issues_from_errors,
)

_INCLUDE_RE = re.compile(r'(?m)^(\s*include\s+")([^"]+)(")')
_DOCUMENT_RE = re.compile(r'(?m)^(\s*\d{4}-\d{2}-\d{2}\s+document\s+\S+\s+")([^"]+)(")')
_DOCUMENTS_OPTION_RE = re.compile(r'(?m)^(\s*option\s+"documents"\s+")([^"]+)(")')
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")


class StagingError(Exception):
    """Raised when the staged tree cannot be built faithfully."""


def validate_staged_file(
    ledger_path: Path,
    files: Iterable[Path],
    modified_path: Path,
    modified_content: str,
    before_errors: Iterable[BeancountError],
) -> list[Issue]:
    """Load a staged copy with one modified file and return only new issues."""
    with _staged_tree(
        files,
        ledger_path,
        modified_path,
        modified_content,
    ) as (staged_main, path_map):
        _, errors, _ = loader.load_file(str(staged_main))

    before = issues_from_errors(before_errors)
    after = issues_from_errors(errors)
    return [_translate_issue(issue, path_map) for issue in compare_issues(before, after)]


@contextmanager
def _staged_tree(
    files: Iterable[Path],
    ledger_path: Path,
    modified_path: Path,
    modified_content: str,
) -> Iterator[tuple[Path, dict[str, Path]]]:
    with tempfile.TemporaryDirectory(prefix="beancount-mcp-stage-") as temporary:
        root = Path(temporary)
        path_map: dict[str, Path] = {}
        modified_real = Path(os.path.realpath(modified_path))
        applied = False
        for source in files:
            source_real = Path(os.path.realpath(source))
            staged = _staged_path(root, source)
            staged.parent.mkdir(parents=True, exist_ok=True)
            path_map[str(staged)] = source
            content = None
            if source_real == modified_real:
                content = modified_content
                applied = True
            _stage_file(source, staged, root, ledger_path, content)
        if not applied:
            raise StagingError(f"Il file modificato non è incluso nel ledger: {modified_path}")
        yield _staged_path(root, ledger_path), path_map


def _stage_file(
    source: Path,
    target: Path,
    root: Path,
    ledger_path: Path,
    content: str | None,
) -> None:
    if content is None:
        data = source.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            target.write_bytes(data)
            return
    else:
        text = content
    text = _rewrite_absolute_includes(text, root)
    text = _rewrite_document_paths(text, source, ledger_path)
    target.write_text(text, encoding="utf-8", newline="")


def _rewrite_absolute_includes(text: str, root: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        pattern = os.path.expanduser(match.group(2))
        if not os.path.isabs(pattern):
            return match.group(0)
        expanded = os.path.abspath(pattern)
        if not glob.glob(expanded, recursive=True):
            return match.group(0)
        staged = _staged_path(root, expanded)
        return f"{match.group(1)}{staged}{match.group(3)}"

    return _INCLUDE_RE.sub(replace, text)


def _rewrite_document_paths(
    text: str,
    source: Path,
    ledger_path: Path,
) -> str:
    def replace_document(match: re.Match[str]) -> str:
        value = os.path.expanduser(match.group(2))
        if os.path.isabs(value):
            return match.group(0)
        absolute = os.path.abspath(os.path.join(source.parent, value))
        return f"{match.group(1)}{absolute}{match.group(3)}"

    def replace_documents_option(match: re.Match[str]) -> str:
        value = os.path.expanduser(match.group(2))
        if os.path.isabs(value):
            return match.group(0)
        absolute = os.path.abspath(os.path.join(ledger_path.parent, value))
        return f"{match.group(1)}{absolute}{match.group(3)}"

    text = _DOCUMENT_RE.sub(replace_document, text)
    return _DOCUMENTS_OPTION_RE.sub(replace_documents_option, text)


def _staged_path(root: Path, path: str | Path) -> Path:
    raw = str(path).replace("\\", "/")
    drive = ""
    if _WINDOWS_DRIVE_RE.match(raw):
        drive = raw[0]
        raw = raw[2:]
    components = [component for component in raw.split("/") if component]
    if drive:
        components.insert(0, drive)
    return root.joinpath(*components)


def _translate_issue(issue: Issue, path_map: dict[str, Path]) -> Issue:
    if issue.file is None:
        return issue
    original = path_map.get(issue.file)
    if original is None:
        return issue
    return Issue(
        type=issue.type,
        message=issue.message,
        file=str(original),
        line=issue.line,
    )
