"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest


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
