"""Unit tests for ledger path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from beancount_mcp.config import default_ledger_path, resolve_ledger_path


def test_explicit_path_wins_over_environment(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.bean"

    result = resolve_ledger_path(
        str(explicit),
        {"BEANCOUNT_MCP_LEDGER": str(tmp_path / "env.bean")},
    )

    assert result == explicit


def test_environment_is_used_without_explicit_path(tmp_path: Path) -> None:
    expected = tmp_path / "env.bean"

    result = resolve_ledger_path(None, {"BEANCOUNT_MCP_LEDGER": str(expected)})

    assert result == expected


def test_empty_explicit_path_falls_back_to_environment(tmp_path: Path) -> None:
    expected = tmp_path / "env.bean"

    result = resolve_ledger_path("", {"BEANCOUNT_MCP_LEDGER": str(expected)})

    assert result == expected


def test_default_is_used_without_explicit_path_or_environment() -> None:
    expected = Path.home() / ".beancount-mcp" / "ledger" / "main.bean"

    result = resolve_ledger_path(None, {})

    assert result == expected


def test_default_ledger_path_points_to_main_bean() -> None:
    result = default_ledger_path()

    assert result == Path.home() / ".beancount-mcp" / "ledger" / "main.bean"


def test_tilde_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    result = resolve_ledger_path("~/ledger.bean", {})

    assert result == tmp_path / "ledger.bean"


def test_relative_path_becomes_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = resolve_ledger_path("main.bean", {})

    assert result.is_absolute()
    assert result == Path.cwd() / "main.bean"


def test_symlink_is_not_resolved(tmp_path: Path) -> None:
    target = tmp_path / "target.bean"
    target.write_text("existing\n")
    link = tmp_path / "link.bean"
    link.symlink_to(target)

    result = resolve_ledger_path(str(link), {})

    assert result == link
