"""Integration tests for read-only BQL queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.queries import run_bql


def _service(ledger: Path, **options: Any) -> LedgerService:
    return LedgerService(build_config(str(ledger), **options))


def testRunBql_shouldReturnSelectResult_whenQueryIsValid(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT account, SUM(position) GROUP BY account")

    # Then
    assert result["ok"] is True
    assert [column["name"] for column in result["columns"]] == [
        "account",
        "SUM(position)",
    ]
    assert result["rows"] == [
        ["Expenses:Food", "(30.00 EUR)"],
        ["Assets:Cash", "(-30.00 EUR)"],
    ]
    assert result["total_rows"] == 2
    assert result["truncated"] is False


def testRunBql_shouldSerializeInventoryAsString_whenAggregatingPositions(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT SUM(position)")

    # Then
    assert result["columns"][0]["type"] == "inventory"
    assert isinstance(result["rows"][0][0], str)


def testRunBql_shouldPaginateRows_whenLimitAndOffsetProvided(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(
        service,
        "SELECT date, narration ORDER BY date",
        limit=2,
        offset=2,
    )

    # Then
    assert result["rows"] == [
        ["2026-01-03", "Dinner"],
        ["2026-01-03", "Dinner"],
    ]
    assert result["total_rows"] == 4
    assert result["truncated"] is False


def testRunBql_shouldMarkTruncated_whenMoreRowsExist(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT date, narration", limit=1)

    # Then
    assert len(result["rows"]) == 1
    assert result["truncated"] is True
    assert result["total_rows"] == 4


def testRunBql_shouldReturnFilenameAndLine_whenSelected(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT filename, lineno, date, payee")

    # Then
    filename, lineno, day, payee = result["rows"][0]
    assert filename == str(ledger.main)
    assert isinstance(lineno, int)
    assert day == "2026-01-02"
    assert payee == "Shop"


@pytest.mark.parametrize("bql", ["BALANCES", "JOURNAL"])
def testRunBql_shouldAllowReadOnlyTabularStatements_whenStatementIsSupported(
    copy_fixture: Any, bql: str
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, bql)

    # Then
    assert result["ok"] is True
    assert result["columns"]
    assert result["rows"]


def testRunBql_shouldRejectPrint_whenStatementIsNotTabular(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "PRINT")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "QUERY_ERROR"
    assert "SELECT" in result["error"]["hint"]


def testRunBql_shouldRejectInvalidBql_whenSyntaxIsWrong(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT broken")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "QUERY_ERROR"


def testRunBql_shouldReturnLimitExceeded_whenLimitIsOutOfRange(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT account", limit=1001)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LIMIT_EXCEEDED"


def testRunBql_shouldReturnLimitExceeded_whenOffsetIsNegative(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT account", offset=-1)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LIMIT_EXCEEDED"


def testRunBql_shouldReturnLedgerError_whenLedgerIsMissing(tmp_path: Path) -> None:
    # Given
    service = _service(tmp_path / "missing.bean")

    # When
    result = run_bql(service, "SELECT account")

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"


def testRunBql_shouldUseConfiguredLimit_whenLimitIsOmitted(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main, query_limit=1)

    # When
    result = run_bql(service, "SELECT account")

    # Then
    assert result["limit"] == 1
    assert len(result["rows"]) == 1
    assert result["truncated"] is True


def testRunBql_shouldQueryMulticurrencyLedger_whenCostsArePresent(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("multicurrency")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT account, SUM(position) GROUP BY account")

    # Then
    assert result["ok"] is True
    assert result["rows"]
    assert all(isinstance(row[1], str) for row in result["rows"])


def testRunBql_shouldReturnEmptyRows_whenNoRowsMatch(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, "SELECT account WHERE account = 'Nope'")

    # Then
    assert result["ok"] is True
    assert result["rows"] == []
    assert result["total_rows"] == 0
    assert result["truncated"] is False


@pytest.mark.parametrize("bql", ["CREATE TABLE foo", "INSERT INTO foo VALUES (1)"])
def testRunBql_shouldRejectWriteStatements_whenStatementIsDdl(copy_fixture: Any, bql: str) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = _service(ledger.main)

    # When
    result = run_bql(service, bql)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "QUERY_ERROR"
