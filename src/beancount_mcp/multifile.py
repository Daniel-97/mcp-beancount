"""Multi-file transaction with journal, backups, rollback, and recovery."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from beancount_mcp.writer import atomic_write


class TransactionError(Exception):
    """Raised when a multi-file transaction cannot be completed safely."""


def transaction_dir(ledger_path: Path) -> Path:
    """Return the hidden journal directory for the ledger."""
    return ledger_path.parent / f".{ledger_path.name}.txn"


def commit_files(
    ledger_path: Path,
    modifications: Mapping[Path, str],
) -> None:
    """Apply several file modifications as one application-level transaction.

    The caller must hold the ledger write lock.
    """
    if not modifications:
        return

    directory = transaction_dir(ledger_path)
    if directory.exists():
        recover_pending_transaction(ledger_path)

    try:
        directory.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise TransactionError(f"Transazione pendente non recuperabile: {directory}") from exc

    backup_dir = directory / "backup"
    backup_dir.mkdir()
    entries: list[dict[str, Any]] = []

    try:
        for index, (path, content) in enumerate(modifications.items()):
            if not path.is_file():
                raise TransactionError(f"File non trovato: {path}")
            try:
                original = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise TransactionError(f"Impossibile leggere {path} per il backup: {exc}") from exc
            backup = backup_dir / str(index)
            _write_fsync(backup, original)
            entries.append(
                {
                    "path": str(path),
                    "backup": str(backup),
                    "original_sha256": _sha256(original),
                    "new_sha256": _sha256(content),
                }
            )

        journal = {
            "version": 1,
            "files": entries,
        }
        _write_fsync(
            directory / "journal.json",
            json.dumps(journal, ensure_ascii=False, indent=2),
        )

        for path, content in modifications.items():
            atomic_write(path, content)
    except Exception as exc:
        restored = _restore_backups(entries)
        if restored:
            shutil.rmtree(directory, ignore_errors=True)
            raise TransactionError(f"Transazione annullata e file ripristinati: {exc}") from exc
        raise TransactionError(
            f"Transazione fallita e ripristino incompleto; il journal resta per il recovery: {exc}"
        ) from exc

    shutil.rmtree(directory, ignore_errors=True)


def recover_pending_transaction(ledger_path: Path) -> bool:
    """Roll back a transaction left pending by a crash, if present."""
    directory = transaction_dir(ledger_path)
    if not directory.exists():
        return False

    journal_path = directory / "journal.json"
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TransactionError(
            f"Journal di transazione illeggibile: {journal_path}: {exc}"
        ) from exc

    entries = journal.get("files")
    if not isinstance(entries, list):
        raise TransactionError(f"Journal di transazione non valido: {journal_path}")

    if not _restore_backups(entries):
        raise TransactionError(
            "Recovery incompleto: alcuni backup non sono stati ripristinati. "
            f"Journal: {journal_path}"
        )

    shutil.rmtree(directory, ignore_errors=True)
    return True


def _restore_backups(entries: list[dict[str, Any]]) -> bool:
    restored = True
    for entry in entries:
        try:
            path = Path(str(entry["path"]))
            backup = Path(str(entry["backup"]))
            original = backup.read_bytes().decode("utf-8")
            atomic_write(path, original)
        except Exception:
            restored = False
    return restored


def _write_fsync(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
