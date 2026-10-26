"""Before/after validation based on Beancount error multisets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from beancount.core.data import BeancountError


@dataclass(frozen=True, slots=True)
class Issue:
    """A validation issue with source location."""

    type: str
    message: str
    file: str | None = None
    line: int | None = None


class ErrorTree(Protocol):
    """Minimal view of a loaded ledger used by validators."""

    errors: Sequence[BeancountError]


class Validator(Protocol):
    """Compare two ledger views and return only new issues."""

    def validate(self, before: ErrorTree, after: ErrorTree) -> list[Issue]: ...


def issues_from_errors(errors: Iterable[BeancountError]) -> list[Issue]:
    """Convert Beancount errors into structured issues."""
    return [_issue_from_error(error) for error in errors]


def _issue_from_error(error: BeancountError) -> Issue:
    source = getattr(error, "source", None) or {}
    filename = source.get("filename") if isinstance(source, dict) else None
    lineno = source.get("lineno") if isinstance(source, dict) else None
    return Issue(
        type=type(error).__name__,
        message=str(getattr(error, "message", str(error))),
        file=str(filename) if filename else None,
        line=int(lineno) if lineno is not None else None,
    )


def compare_issues(
    before: Sequence[Issue],
    after: Sequence[Issue],
) -> list[Issue]:
    """Subtract ``before`` from ``after`` as a multiset of (type, message)."""
    remaining = Counter((issue.type, issue.message) for issue in before)
    new_issues: list[Issue] = []
    for issue in after:
        signature = (issue.type, issue.message)
        if remaining[signature] > 0:
            remaining[signature] -= 1
        else:
            new_issues.append(issue)
    return new_issues


class ErrorMultisetValidator:
    """Validator that ignores line moves and blocks only new errors."""

    def validate(self, before: ErrorTree, after: ErrorTree) -> list[Issue]:
        return compare_issues(
            issues_from_errors(before.errors),
            issues_from_errors(after.errors),
        )


def issue_to_dict(issue: Issue) -> dict[str, Any]:
    """Render an issue as a JSON-compatible dictionary."""
    return {
        "type": issue.type,
        "message": issue.message,
        "file": issue.file,
        "line": issue.line,
    }
