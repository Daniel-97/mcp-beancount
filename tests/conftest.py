"""Shared fixtures for the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the directory containing the ledger fixtures."""
    return Path(__file__).parent / "fixtures"


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
