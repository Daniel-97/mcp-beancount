"""Unit tests for before/after error comparison."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from beancount.core.data import BeancountError

from beancount_mcp.validation import (
    ErrorMultisetValidator,
    Issue,
    compare_issues,
    issue_to_dict,
    issues_from_errors,
)


@dataclass(frozen=True)
class FakeError:
    message: str
    source: dict[str, Any] | None


class FakeTree:
    def __init__(self, errors: list[BeancountError]) -> None:
        self.errors: Sequence[BeancountError] = errors


def testCompareIssues_shouldReturnOnlyNewIssues_whenSameSignatureAppearsBefore() -> None:
    # Given
    before = [Issue(type="ValidationError", message="same")]
    after = [
        Issue(type="ValidationError", message="same"),
        Issue(type="ValidationError", message="new"),
    ]

    # When
    result = compare_issues(before, after)

    # Then
    assert result == [Issue(type="ValidationError", message="new")]


def testCompareIssues_shouldPreserveDuplicateCounts_whenBeforeHasFewerCopies() -> None:
    # Given
    before = [Issue(type="ValidationError", message="same")]
    after = [
        Issue(type="ValidationError", message="same"),
        Issue(type="ValidationError", message="same"),
    ]

    # When
    result = compare_issues(before, after)

    # Then
    assert result == [Issue(type="ValidationError", message="same")]


def testCompareIssues_shouldIgnoreFileAndLine_whenSignatureMatches() -> None:
    # Given
    before = [Issue(type="E", message="m", file="a.bean", line=1)]
    after = [Issue(type="E", message="m", file="b.bean", line=99)]

    # When
    result = compare_issues(before, after)

    # Then
    assert result == []


def testIssuesFromErrors_shouldExtractSourceAndMessage_whenErrorHasSource() -> None:
    # Given
    error = cast(
        BeancountError,
        FakeError(
            message="boom",
            source={"filename": "main.bean", "lineno": 3},
        ),
    )

    # When
    result = issues_from_errors([error])

    # Then
    assert result == [
        Issue(
            type="FakeError",
            message="boom",
            file="main.bean",
            line=3,
        )
    ]


def testIssuesFromErrors_shouldHandleMissingSource_whenSourceIsNone() -> None:
    # Given
    error = cast(
        BeancountError,
        FakeError(message="boom", source=None),
    )

    # When
    result = issues_from_errors([error])

    # Then
    assert result == [Issue(type="FakeError", message="boom", file=None, line=None)]


def testIssueToDict_shouldRenderAllFields_whenIssueHasValues() -> None:
    # Given
    issue = Issue(type="E", message="boom", file="main.bean", line=3)

    # When
    result = issue_to_dict(issue)

    # Then
    assert result == {
        "type": "E",
        "message": "boom",
        "file": "main.bean",
        "line": 3,
    }


def testErrorMultisetValidator_shouldSubtractBeforeErrors_whenValidatingTrees() -> None:
    # Given
    old = cast(
        BeancountError,
        FakeError(message="old", source={"filename": "a.bean", "lineno": 1}),
    )
    new = cast(
        BeancountError,
        FakeError(message="new", source={"filename": "b.bean", "lineno": 2}),
    )
    before = FakeTree([old])
    after = FakeTree([old, new])

    # When
    result = ErrorMultisetValidator().validate(before, after)

    # Then
    assert result == [Issue(type="FakeError", message="new", file="b.bean", line=2)]
