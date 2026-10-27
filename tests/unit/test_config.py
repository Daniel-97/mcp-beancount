"""Unit tests for ledger path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp.config import (
    build_config,
    default_ledger_path,
    resolve_inbox_path,
    resolve_ledger_path,
)


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


def testResolveInboxPath_shouldBeRelativeToLedgerDirectory_whenInboxIsRelative(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "ledger" / "main.bean"

    # When
    result = resolve_inbox_path(ledger, "sub/inbox.bean")

    # Then
    assert result == tmp_path / "ledger" / "sub" / "inbox.bean"


def testResolveInboxPath_shouldKeepAbsolutePath_whenInboxIsAbsolute(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "ledger" / "main.bean"
    inbox = tmp_path / "absolute" / "inbox.bean"

    # When
    result = resolve_inbox_path(ledger, str(inbox))

    # Then
    assert result == inbox


@pytest.mark.parametrize("limit", [0, 1001])
def testBuildConfig_shouldValidateQueryLimit_whenLimitIsOutsideRange(
    tmp_path: Path, limit: int
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    with pytest.raises(ValueError, match="--query-limit") as raised:
        build_config(str(ledger), query_limit=limit)

    # Then
    assert "--query-limit" in str(raised.value)


def testBuildConfig_shouldRejectUnsupportedTransport_whenTransportIsNotStdio(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    with pytest.raises(ValueError, match="Trasporto non supportato") as raised:
        build_config(str(ledger), transport="http")

    # Then
    assert "http" in str(raised.value)


def testBuildConfig_shouldResolveLedgerSymlink_whenLedgerIsSymlink(
    tmp_path: Path,
) -> None:
    # Given
    real = tmp_path / "real" / "main.bean"
    real.parent.mkdir()
    real.touch()
    link = tmp_path / "link.bean"
    link.symlink_to(real)

    # When
    config = build_config(str(link))

    # Then
    assert config.ledger_path == real
    assert config.inbox_path == real.parent / "inbox.bean"


def testBuildConfig_shouldCombineLedgerInboxAndFlags_whenAllOptionsAreProvided(
    tmp_path: Path,
) -> None:
    # Given
    ledger = tmp_path / "ledger" / "main.bean"

    # When
    config = build_config(
        str(ledger),
        inbox="sub/inbox.bean",
        read_only=True,
        allow_edit_outside_inbox=True,
        query_limit=250,
        transport="stdio",
    )

    # Then
    assert config.ledger_path == ledger
    assert config.inbox_path == tmp_path / "ledger" / "sub" / "inbox.bean"
    assert config.read_only is True
    assert config.allow_edit_outside_inbox is True
    assert config.query_limit == 250
    assert config.transport == "stdio"


def testBuildConfig_shouldStoreVerbose_whenEnabled(tmp_path: Path) -> None:
    # Given
    ledger = tmp_path / "main.bean"

    # When
    config = build_config(str(ledger), verbose=True)

    # Then
    assert config.verbose is True
