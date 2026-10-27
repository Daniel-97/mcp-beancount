"""Unit tests for token-aware account, tag, and link rewrites."""

from __future__ import annotations

import pytest

from beancount_mcp.renames import (
    RenameError,
    _line_can_contain_token,
    _normalize_tag,
    _rewrite_account_line,
    _rewrite_token_line,
)


def testRewriteAccountLine_shouldReplaceDirectiveAccount_whenExactMatch() -> None:
    # Given
    line = "2026-01-01 open Expenses:Food EUR\n"

    # When
    result = _rewrite_account_line(line, "Expenses:Food", "Expenses:Groceries", False)

    # Then
    assert result == "2026-01-01 open Expenses:Groceries EUR\n"


def testRewriteAccountLine_shouldReplacePostingAccount_whenIndented() -> None:
    # Given
    line = "  Expenses:Food   10.00 EUR\n"

    # When
    result = _rewrite_account_line(line, "Expenses:Food", "Expenses:Groceries", False)

    # Then
    assert result == "  Expenses:Groceries   10.00 EUR\n"


def testRewriteAccountLine_shouldReplaceBothPadAccounts_whenMatched() -> None:
    # Given
    line = "2026-01-01 pad Assets:Cash Equity:Opening-Balances\n"

    # When
    first = _rewrite_account_line(line, "Assets:Cash", "Assets:Bank:Cash", False)
    second = _rewrite_account_line(
        first,
        "Equity:Opening-Balances",
        "Equity:Opening",
        False,
    )

    # Then
    assert second == "2026-01-01 pad Assets:Bank:Cash Equity:Opening\n"


def testRewriteAccountLine_shouldNotReplaceNarrationText_whenAccountAppearsInString() -> None:
    # Given
    line = '2026-01-01 * "Expenses:Food" "Narration Expenses:Food"\n'

    # When
    result = _rewrite_account_line(line, "Expenses:Food", "Expenses:Groceries", False)

    # Then
    assert result == line


def testRewriteAccountLine_shouldRenameSubaccounts_whenIncludeSubaccounts() -> None:
    # Given
    line = "  Expenses:Food:Dining   10.00 EUR\n"

    # When
    result = _rewrite_account_line(line, "Expenses:Food", "Expenses:Groceries", True)

    # Then
    assert result == "  Expenses:Groceries:Dining   10.00 EUR\n"


def testRewriteAccountLine_shouldNotRenamePrefix_whenExactOnly() -> None:
    # Given
    line = "  Expenses:Foodie   10.00 EUR\n"

    # When
    result = _rewrite_account_line(line, "Expenses:Food", "Expenses:Groceries", False)

    # Then
    assert result == line


def testRewriteTokenLine_shouldReplaceTagOutsideQuotes_whenPresent() -> None:
    # Given
    line = '2026-01-01 * "P" "N" #food ^l\n'

    # When
    result = _rewrite_token_line(line, "#", "food", "meals")

    # Then
    assert result == '2026-01-01 * "P" "N" #meals ^l\n'


def testRewriteTokenLine_shouldNotReplaceTagInsideNarration_whenQuoted() -> None:
    # Given
    line = '2026-01-01 * "P" "I like #food" #food\n'

    # When
    result = _rewrite_token_line(line, "#", "food", "meals")

    # Then
    assert result == '2026-01-01 * "P" "I like #food" #meals\n'


def testRewriteTokenLine_shouldNotReplaceTagInComment_whenAfterSemicolon() -> None:
    # Given
    line = '2026-01-01 * "P" "N" #food ; old #food\n'

    # When
    result = _rewrite_token_line(line, "#", "food", "meals")

    # Then
    assert result == '2026-01-01 * "P" "N" #meals ; old #food\n'


def testRewriteTokenLine_shouldSkipEscapedQuotes_whenScanning() -> None:
    # Given
    line = '2026-01-01 * "P" "a \\" #food" #food\n'

    # When
    result = _rewrite_token_line(line, "#", "food", "meals")

    # Then
    assert result == '2026-01-01 * "P" "a \\" #food" #meals\n'


def testLineCanContainToken_shouldAllowTransaction_whenTag() -> None:
    # Given
    line = '2026-01-01 * "P" "N" #food\n'

    # When
    result = _line_can_contain_token(line, "#")

    # Then
    assert result is True


def testLineCanContainToken_shouldAllowPushtag_whenTag() -> None:
    # Given
    line = "pushtag #food\n"

    # When
    result = _line_can_contain_token(line, "#")

    # Then
    assert result is True


def testLineCanContainToken_shouldRejectPushtag_whenLink() -> None:
    # Given
    line = "pushtag #food\n"

    # When
    result = _line_can_contain_token(line, "^")

    # Then
    assert result is False


def testLineCanContainToken_shouldRejectOpenDirective_whenTag() -> None:
    # Given
    line = "2026-01-01 open Expenses:Food EUR\n"

    # When
    result = _line_can_contain_token(line, "#")

    # Then
    assert result is False


def testNormalizeTag_shouldStripMarker_whenPresent() -> None:
    # Given
    value = "#food"

    # When
    result = _normalize_tag(value, "#")

    # Then
    assert result == "food"


def testNormalizeTag_shouldRaise_whenInvalid() -> None:
    # Given
    value = "not a tag"

    # When
    with pytest.raises(RenameError, match="non valido") as raised:
        _normalize_tag(value, "#")

    # Then
    assert "non valido" in str(raised.value)
