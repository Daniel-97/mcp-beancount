"""Unit tests for pure ``ledger_info`` helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from beancount.core.data import BeancountError, Directive

from beancount_mcp.ledger import InboxStatus, LedgerSnapshot
from beancount_mcp.tools.ledger_info import _top_values, _warnings


def _snapshot(
    *,
    entries: tuple[Directive, ...] = (),
    errors: tuple[BeancountError, ...] = (),
    inbox_warning: str | None = None,
) -> LedgerSnapshot:
    return LedgerSnapshot(
        ledger_path=Path("/tmp/main.bean"),
        files=(),
        entries=entries,
        errors=errors,
        options={},
        version="version",
        inbox=InboxStatus(
            path=Path("/tmp/inbox.bean"),
            exists=inbox_warning is None,
            included=inbox_warning is None,
            warning=inbox_warning,
        ),
    )


def testTopValues_shouldSortByFrequencyThenName_whenCountsDiffer() -> None:
    # Given
    values = ["b", "a", "b", "c", "a", "b"]

    # When
    result = _top_values(values)

    # Then
    assert result == [
        {"name": "b", "count": 3},
        {"name": "a", "count": 2},
        {"name": "c", "count": 1},
    ]


def testTopValues_shouldLimitResults_whenMoreThanTenValuesExist() -> None:
    # Given
    values = [f"value-{index}" for index in range(12)]

    # When
    result = _top_values(values)

    # Then
    assert len(result) == 10


def testWarnings_shouldIncludeEmptyAndInboxWarnings_whenBothConditionsHold() -> None:
    # Given
    snapshot = _snapshot(inbox_warning="Inbox non trovata.")

    # When
    result = _warnings(snapshot)

    # Then
    assert result == [
        "Il ledger è vuoto. Apri gli account necessari con open_account.",
        "Inbox non trovata.",
    ]


def testWarnings_shouldUseSingular_whenLedgerHasOneError() -> None:
    # Given
    snapshot = _snapshot(errors=(cast(BeancountError, object()),))

    # When
    result = _warnings(snapshot)

    # Then
    assert result[-1] == "Il ledger contiene 1 errore preesistente."


def testWarnings_shouldUsePlural_whenLedgerHasMultipleErrors() -> None:
    # Given
    snapshot = _snapshot(
        errors=(
            cast(BeancountError, object()),
            cast(BeancountError, object()),
        )
    )

    # When
    result = _warnings(snapshot)

    # Then
    assert result[-1] == "Il ledger contiene 2 errori preesistenti."
