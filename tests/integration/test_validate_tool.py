"""Integration tests for the validate tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService
from beancount_mcp.tools.validate import build_validation


def testBuildValidation_shouldReturnValid_whenLedgerHasNoErrors(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = LedgerService(build_config(str(ledger.main)))

    # When
    result = build_validation(service)

    # Then
    assert result["ok"] is True
    assert result["valid"] is True
    assert result["error_count"] == 0
    assert result["errors"] == []


def testBuildValidation_shouldListErrorsWithLocation_whenLedgerHasErrors(
    copy_fixture: Any,
) -> None:
    # Given
    ledger = copy_fixture("with_errors")
    service = LedgerService(build_config(str(ledger.main)))

    # When
    result = build_validation(service)

    # Then
    assert result["ok"] is True
    assert result["valid"] is False
    assert result["error_count"] == 2
    assert len(result["errors"]) == 2
    for issue in result["errors"]:
        assert issue["file"] == str(ledger.main)
        assert isinstance(issue["line"], int)
        assert issue["type"]
        assert issue["message"]


def testBuildValidation_shouldReturnLedgerError_whenLedgerIsMissing(
    tmp_path: Path,
) -> None:
    # Given
    service = LedgerService(build_config(str(tmp_path / "missing.bean")))

    # When
    result = build_validation(service)

    # Then
    assert result["ok"] is False
    assert result["error"]["code"] == "LEDGER_ERROR"


def testBuildValidation_shouldReturnVersion_whenLoaded(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("minimal")
    service = LedgerService(build_config(str(ledger.main)))

    # When
    result = build_validation(service)

    # Then
    assert result["ledger_version"] == service.load().version


def testBuildValidation_shouldSucceed_whenInboxIsMissing(copy_fixture: Any) -> None:
    # Given
    ledger = copy_fixture("no_inbox")
    service = LedgerService(build_config(str(ledger.main)))

    # When
    result = build_validation(service)

    # Then
    assert result["ok"] is True
    assert result["valid"] is True
