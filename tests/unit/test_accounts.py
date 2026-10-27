"""Unit tests for account metadata extraction."""

from __future__ import annotations

from datetime import date
from typing import cast

from beancount.core.data import Close, Directive, Open

from beancount_mcp.accounts import account_infos


def testAccountInfos_shouldRecordOpenDateAndCurrencies_whenOpenExists() -> None:
    # Given
    entries = [
        Open(
            meta={},
            date=date(2026, 1, 1),
            account="Assets:Cash",
            currencies=["EUR", "USD"],
            booking=None,
        )
    ]

    # When
    result = account_infos(entries)

    # Then
    assert result["Assets:Cash"].open_date == date(2026, 1, 1)
    assert result["Assets:Cash"].close_date is None
    assert result["Assets:Cash"].currencies == ("EUR", "USD")
    assert result["Assets:Cash"].is_open is True


def testAccountInfos_shouldRecordCloseDateAndMarkClosed_whenCloseExists() -> None:
    # Given
    entries: list[Directive] = [
        Open(
            meta={},
            date=date(2026, 1, 1),
            account="Expenses:Food",
            currencies=cast(list[str], None),
            booking=None,
        ),
        Close(meta={}, date=date(2026, 2, 1), account="Expenses:Food"),
    ]

    # When
    result = account_infos(entries)

    # Then
    assert result["Expenses:Food"].open_date == date(2026, 1, 1)
    assert result["Expenses:Food"].close_date == date(2026, 2, 1)
    assert result["Expenses:Food"].currencies is None
    assert result["Expenses:Food"].is_open is False


def testAccountInfos_shouldIncludeCloseOnlyAccount_whenNoOpenExists() -> None:
    # Given
    entries = [Close(meta={}, date=date(2026, 2, 1), account="Expenses:Food")]

    # When
    result = account_infos(entries)

    # Then
    assert result["Expenses:Food"].open_date is None
    assert result["Expenses:Food"].close_date == date(2026, 2, 1)
    assert result["Expenses:Food"].is_open is False
