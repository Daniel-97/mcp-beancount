"""Unit tests for ledger path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp.config import default_ledger_path, resolve_ledger_path


def testResolveLedgerPath_shouldPreferExplicitPath_whenEnvironmentIsSet(
    tmp_path: Path,
) -> None:
    # Given
    explicit = tmp_path / "explicit.bean"
    environment = {"BEANCOUNT_MCP_LEDGER": str(tmp_path / "env.bean")}

    # When
    result = resolve_ledger_path(str(explicit), environment)

    # Then
    assert result == explicit


def testResolveLedgerPath_shouldUseEnvironment_whenExplicitPathIsMissing(
    tmp_path: Path,
) -> None:
    # Given
    expected = tmp_path / "env.bean"
    environment = {"BEANCOUNT_MCP_LEDGER": str(expected)}

    # When
    result = resolve_ledger_path(None, environment)

    # Then
    assert result == expected


def testResolveLedgerPath_shouldUseEnvironment_whenExplicitPathIsEmpty(
    tmp_path: Path,
) -> None:
    # Given
    expected = tmp_path / "env.bean"
    environment = {"BEANCOUNT_MCP_LEDGER": str(expected)}

    # When
    result = resolve_ledger_path("", environment)

    # Then
    assert result == expected


def testResolveLedgerPath_shouldUseDefaultLedgerPath_whenNoExplicitPathOrEnvironmentIsSet() -> None:
    # Given
    expected = Path.home() / ".beancount-mcp" / "ledger" / "main.bean"

    # When
    result = resolve_ledger_path(None, {})

    # Then
    assert result == expected


def testDefaultLedgerPath_shouldPointToMainBean_whenCalled() -> None:
    # Given
    # no explicit path and no environment override

    # When
    result = default_ledger_path()

    # Then
    assert result == Path.home() / ".beancount-mcp" / "ledger" / "main.bean"


def testResolveLedgerPath_shouldExpandTilde_whenPathStartsWithHomeShorthand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    # When
    result = resolve_ledger_path("~/ledger.bean", {})

    # Then
    assert result == tmp_path / "ledger.bean"


def testResolveLedgerPath_shouldReturnAbsolutePath_whenPathIsRelative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    monkeypatch.chdir(tmp_path)

    # When
    result = resolve_ledger_path("main.bean", {})

    # Then
    assert result.is_absolute()
    assert result == Path.cwd() / "main.bean"


def testResolveLedgerPath_shouldKeepSymlinkPath_whenTargetIsSymlink(
    tmp_path: Path,
) -> None:
    # Given
    target = tmp_path / "target.bean"
    target.write_text("existing\n")
    link = tmp_path / "link.bean"
    link.symlink_to(target)

    # When
    result = resolve_ledger_path(str(link), {})

    # Then
    assert result == link
