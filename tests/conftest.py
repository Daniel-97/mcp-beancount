"""Shared fixtures for the test suite."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True, slots=True)
class LedgerPaths:
    """Paths of a copied or generated ledger tree."""

    root: Path
    main: Path
    inbox: Path


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the directory containing the ledger fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def ledger_factory(tmp_path: Path) -> Callable[[str, str | None], LedgerPaths]:
    """Build a temporary ledger from inline file contents."""
    counter = 0

    def create(main_text: str, inbox_text: str | None = "") -> LedgerPaths:
        nonlocal counter
        counter += 1
        root = tmp_path / f"ledger-{counter}"
        root.mkdir()
        main = root / "main.bean"
        main.write_text(main_text, encoding="utf-8")
        inbox = root / "inbox.bean"
        if inbox_text is not None:
            inbox.write_text(inbox_text, encoding="utf-8")
        return LedgerPaths(root=root, main=main, inbox=inbox)

    return create


@pytest.fixture
def copy_fixture(tmp_path: Path, fixtures_dir: Path) -> Callable[[str], LedgerPaths]:
    """Copy a named fixture into an isolated temporary directory."""
    counter = 0

    def copy(name: str) -> LedgerPaths:
        nonlocal counter
        counter += 1
        root = tmp_path / f"{name}-{counter}"
        shutil.copytree(fixtures_dir / name, root)
        return LedgerPaths(
            root=root,
            main=root / "main.bean",
            inbox=root / "inbox.bean",
        )

    return copy


@pytest.fixture
def snapshot_bytes() -> Callable[[Path], dict[str, bytes]]:
    """Snapshot user data and journals, excluding the persistent lock inode."""

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.name.endswith(".bean.lock")
        }

    return snapshot


@pytest.fixture
def expected_main_ledger() -> str:
    """Exact content written by ``init`` for EUR on 2026-10-25."""
    return (
        'option "title" "Beancount MCP Ledger"\n'
        'option "operating_currency" "EUR"\n'
        "\n"
        'include "inbox.bean"\n'
        "\n"
        "2026-10-25 open Equity:Opening-Balances\n"
    )
