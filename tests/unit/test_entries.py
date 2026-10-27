"""Unit tests for directive spans and entry identities."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp.entries import (
    DirectiveSpan,
    delete_span,
    entry_id_to_dict,
    extract_directive_spans,
    find_span,
    is_transaction_span,
    replace_span,
)


def _spans() -> list[DirectiveSpan]:
    text = (
        "; comment\n"
        "2026-01-01 open Assets:Cash EUR\n"
        "\n"
        '2026-01-02 * "Shop" "Lunch"\n'
        "  Expenses:Food   10.00 EUR\n"
        "  Assets:Cash    -10.00 EUR\n"
    )
    return extract_directive_spans(Path("/tmp/main.bean"), text)


def testExtractDirectiveSpans_shouldSplitOnNonIndentedLines_whenFileHasMultipleDirectives() -> None:
    # Given
    # a file with a comment, an open directive, and a transaction

    # When
    spans = _spans()

    # Then
    assert [span.entry_id.line for span in spans] == [1, 2, 4]
    assert spans[0].text == "; comment\n"
    assert spans[1].text == "2026-01-01 open Assets:Cash EUR\n\n"
    assert spans[2].text.startswith('2026-01-02 * "Shop" "Lunch"')


def testExtractDirectiveSpans_shouldComputeStableHash_whenTextIsUnchanged() -> None:
    # Given
    # the same file text extracted twice

    # When
    first = _spans()
    second = _spans()

    # Then
    assert [span.entry_id.hash for span in first] == [span.entry_id.hash for span in second]


def testFindSpan_shouldReturnSpan_whenLineMatches() -> None:
    # Given
    spans = _spans()

    # When
    result = find_span(spans, 2)

    # Then
    assert result is not None
    assert result.entry_id.line == 2


def testFindSpan_shouldReturnNone_whenLineDoesNotExist() -> None:
    # Given
    spans = _spans()

    # When
    result = find_span(spans, 99)

    # Then
    assert result is None


def testIsTransactionSpan_shouldReturnTrue_whenSpanIsTransaction() -> None:
    # Given
    span = _spans()[2]

    # When
    result = is_transaction_span(span)

    # Then
    assert result is True


def testIsTransactionSpan_shouldReturnFalse_whenSpanIsOpen() -> None:
    # Given
    span = _spans()[1]

    # When
    result = is_transaction_span(span)

    # Then
    assert result is False


def testReplaceSpan_shouldPreserveTrailingBlankLines_whenReplacing() -> None:
    # Given
    text = "d1\n\nd2\n"
    spans = extract_directive_spans(Path("/tmp/main.bean"), text)

    # When
    result = replace_span(text, spans[0], "new\n")

    # Then
    assert result == "new\n\nd2\n"


def testReplaceSpan_shouldRaiseValueError_whenNewTextIsEmpty() -> None:
    # Given
    text = "d1\n"
    span = extract_directive_spans(Path("/tmp/main.bean"), text)[0]

    # When
    with pytest.raises(ValueError, match="vuota") as raised:
        replace_span(text, span, "\n")

    # Then
    assert "vuota" in str(raised.value)


def testDeleteSpan_shouldRemoveDirectiveAndTrailingBlankLines_whenDeleting() -> None:
    # Given
    text = "d1\n\nd2\n"
    spans = extract_directive_spans(Path("/tmp/main.bean"), text)

    # When
    result = delete_span(text, spans[0])

    # Then
    assert result == "d2\n"


def testEntryIdToDict_shouldReturnFileLineHash_whenCalled() -> None:
    # Given
    span = _spans()[1]

    # When
    result = entry_id_to_dict(span.entry_id)

    # Then
    assert result == {
        "file": "/tmp/main.bean",
        "line": 2,
        "hash": span.entry_id.hash,
    }
