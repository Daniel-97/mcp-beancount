"""Stage ledger files in a temporary tree for before/after validation."""

from __future__ import annotations

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
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[/\\]")


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
        for source in files:
            staged = _staged_path(root, source)
            staged.parent.mkdir(parents=True, exist_ok=True)
            path_map[str(staged)] = source
            content = modified_content if source == modified_path else None
            _stage_file(source, staged, root, content)
        yield _staged_path(root, ledger_path), path_map


def _stage_file(
    source: Path,
    target: Path,
    root: Path,
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
    target.write_text(
        _rewrite_absolute_includes(text, root),
        encoding="utf-8",
        newline="",
    )


def _rewrite_absolute_includes(text: str, root: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        pattern = match.group(2)
        expanded = os.path.abspath(os.path.expanduser(pattern))
        if not os.path.isabs(os.path.expanduser(pattern)):
            return match.group(0)
        staged = _staged_path(root, expanded)
        return f"{match.group(1)}{staged}{match.group(3)}"

    return _INCLUDE_RE.sub(replace, text)


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
