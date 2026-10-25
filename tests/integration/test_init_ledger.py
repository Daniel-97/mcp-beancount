"""Integration tests for ledgers produced by ``init``."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from beancount import loader
from beancount.core.data import Open

from beancount_mcp.init import create_ledger


def test_initialized_ledger_loads_without_errors(tmp_path: Path) -> None:
    result = create_ledger(tmp_path / "main.bean", "EUR", today=date(2026, 10, 25))

    entries, errors, options = loader.load_file(str(result.ledger_path))

    assert errors == []
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, Open)
    assert entry.account == "Equity:Opening-Balances"
    assert entry.date == date(2026, 10, 25)
    assert options["operating_currency"] == ["EUR"]
    assert options["title"] == "Beancount MCP Ledger"
