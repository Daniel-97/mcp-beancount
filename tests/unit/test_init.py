"""Unit tests for safe ledger initialization."""

from __future__ import annotations

import os
import stat
from datetime import date
from pathlib import Path

import pytest

from beancount_mcp.init import InitError, create_ledger, render_main_ledger


def test_render_interpolates_currency_and_date() -> None:
    result = render_main_ledger("USD", date(2025, 1, 2))

    assert result == (
        'option "title" "Beancount MCP Ledger"\n'
        'option "operating_currency" "USD"\n'
        "\n"
        'include "inbox.bean"\n'
        "\n"
        "2025-01-02 open Equity:Opening-Balances\n"
    )


def test_create_writes_main_ledger_and_empty_inbox(
    tmp_path: Path, expected_main_ledger: str
) -> None:
    ledger = tmp_path / "main.bean"

    result = create_ledger(ledger, "EUR", today=date(2026, 10, 25))

    assert result.ledger_path == ledger
    assert result.inbox_path == tmp_path / "inbox.bean"
    assert result.currency == "EUR"
    assert result.opening_date == date(2026, 10, 25)
    assert ledger.read_text(encoding="utf-8") == expected_main_ledger
    assert (tmp_path / "inbox.bean").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(("raw", "expected"), [("eur", "EUR"), (" usd ", "USD")])
def test_currency_is_normalized(tmp_path: Path, raw: str, expected: str) -> None:
    result = create_ledger(tmp_path / "main.bean", raw)

    assert result.currency == expected
    assert f'option "operating_currency" "{expected}"' in result.ledger_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("currency", ["", "EU R", "EUR\nX", "E", "1EUR", "EUR\tX"])
def test_invalid_currency_is_refused_without_creating_files(tmp_path: Path, currency: str) -> None:
    with pytest.raises(InitError, match="Valuta non valida"):
        create_ledger(tmp_path / "main.bean", currency)

    assert list(tmp_path.iterdir()) == []


def test_existing_non_empty_main_is_refused(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    ledger.write_text("existing\n", encoding="utf-8")

    with pytest.raises(InitError, match="esiste già e non è vuoto"):
        create_ledger(ledger, "EUR")

    assert ledger.read_text(encoding="utf-8") == "existing\n"
    assert not (tmp_path / "inbox.bean").exists()


def test_existing_non_empty_inbox_is_refused(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox.bean"
    inbox.write_text("existing\n", encoding="utf-8")

    with pytest.raises(InitError, match="esiste già e non è vuoto"):
        create_ledger(tmp_path / "main.bean", "EUR")

    assert not (tmp_path / "main.bean").exists()
    assert inbox.read_text(encoding="utf-8") == "existing\n"


def test_refusal_leaves_both_existing_files_unchanged(tmp_path: Path) -> None:
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.write_text("main\n", encoding="utf-8")
    inbox.write_text("inbox\n", encoding="utf-8")
    before = (ledger.read_bytes(), inbox.read_bytes())

    with pytest.raises(InitError):
        create_ledger(ledger, "EUR")

    assert (ledger.read_bytes(), inbox.read_bytes()) == before


def test_symlink_main_is_refused_and_target_is_untouched(tmp_path: Path) -> None:
    target = tmp_path / "target.bean"
    target.write_text("target\n", encoding="utf-8")
    link = tmp_path / "main.bean"
    link.symlink_to(target)

    with pytest.raises(InitError, match="symlink"):
        create_ledger(link, "EUR")

    assert target.read_text(encoding="utf-8") == "target\n"


def test_symlink_inbox_is_refused_and_main_is_not_created(tmp_path: Path) -> None:
    target = tmp_path / "target.bean"
    target.write_text("target\n", encoding="utf-8")
    (tmp_path / "inbox.bean").symlink_to(target)

    with pytest.raises(InitError, match="symlink"):
        create_ledger(tmp_path / "main.bean", "EUR")

    assert not (tmp_path / "main.bean").exists()
    assert target.read_text(encoding="utf-8") == "target\n"


def test_non_regular_main_is_refused(tmp_path: Path) -> None:
    (tmp_path / "main.bean").mkdir()

    with pytest.raises(InitError, match="non è un file regolare"):
        create_ledger(tmp_path / "main.bean", "EUR")


def test_non_regular_inbox_is_refused(tmp_path: Path) -> None:
    (tmp_path / "inbox.bean").mkdir()

    with pytest.raises(InitError, match="non è un file regolare"):
        create_ledger(tmp_path / "main.bean", "EUR")

    assert not (tmp_path / "main.bean").exists()


def test_inbox_bean_as_main_path_is_refused(tmp_path: Path) -> None:
    ledger = tmp_path / "inbox.bean"

    with pytest.raises(InitError, match="inbox stessa"):
        create_ledger(ledger, "EUR")

    assert list(tmp_path.iterdir()) == []


def test_existing_empty_files_are_accepted_and_modes_are_preserved(
    tmp_path: Path, expected_main_ledger: str
) -> None:
    ledger = tmp_path / "main.bean"
    inbox = tmp_path / "inbox.bean"
    ledger.touch()
    inbox.touch()
    ledger.chmod(0o640)
    inbox.chmod(0o640)

    result = create_ledger(ledger, "EUR", today=date(2026, 10, 25))

    assert result.ledger_path.read_text(encoding="utf-8") == expected_main_ledger
    assert result.inbox_path.read_text(encoding="utf-8") == ""
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o640
    assert stat.S_IMODE(inbox.stat().st_mode) == 0o640


def test_new_files_respect_umask(tmp_path: Path) -> None:
    previous_umask = os.umask(0o077)
    try:
        result = create_ledger(tmp_path / "main.bean", "EUR")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(result.ledger_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.inbox_path.stat().st_mode) == 0o600


def test_parent_directories_are_created(tmp_path: Path) -> None:
    ledger = tmp_path / "nested" / "directory" / "main.bean"

    result = create_ledger(ledger, "EUR")

    assert result.ledger_path.is_file()
    assert result.inbox_path.is_file()


def test_failed_replace_leaves_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "main.bean"

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(InitError, match="replace failed"):
        create_ledger(ledger, "EUR")

    assert not ledger.exists()
    assert list(tmp_path.iterdir()) == []


def test_failed_replace_preserves_existing_empty_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "main.bean"
    ledger.touch()

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(InitError, match="replace failed"):
        create_ledger(ledger, "EUR")

    assert ledger.exists()
    assert ledger.read_text(encoding="utf-8") == ""
    assert list(tmp_path.iterdir()) == [ledger]


def test_failed_replace_preserves_existing_empty_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inbox = tmp_path / "inbox.bean"
    inbox.touch()

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(InitError, match="replace failed"):
        create_ledger(tmp_path / "main.bean", "EUR")

    assert not (tmp_path / "main.bean").exists()
    assert inbox.exists()
    assert list(tmp_path.iterdir()) == [inbox]
