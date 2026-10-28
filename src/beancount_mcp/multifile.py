"""Multi-file transaction with journal, backups, rollback, and recovery."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from beancount_mcp.writer import atomic_write, fsync_directory

_COMMITTED_MARKER = "committed"


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

    The caller must hold the ledger write lock. A pending journal is never
    recovered implicitly; the server must run recovery before planning writes.
    """
    if not modifications:
        return

    directory = transaction_dir(ledger_path)
    if directory.exists():
        if (directory / _COMMITTED_MARKER).exists() or not (directory / "journal.json").exists():
            _remove_transaction_directory(directory)
        else:
            raise TransactionError(
                "Transazione pendente: riavvia il server per eseguire il recovery "
                f"prima di nuove scritture ({directory})."
            )

    entries: list[dict[str, Any]] = []
    try:
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        backup_dir = directory / "backup"
        backup_dir.mkdir(mode=0o700)
        fsync_directory(ledger_path.parent)

        for index, (path, content) in enumerate(modifications.items()):
            if not path.is_file():
                raise TransactionError(f"File non trovato: {path}")
            original = _read_text(path)
            backup = backup_dir / str(index)
            _write_fsync(backup, original, mode=0o600)
            entries.append(
                {
                    "path": str(path),
                    "backup": str(backup),
                    "original_sha256": _sha256(original),
                    "new_sha256": _sha256(content),
                }
            )

        fsync_directory(backup_dir)
        journal = {"version": 2, "files": entries}
        _write_atomic_fsync(
            directory / "journal.json",
            json.dumps(journal, ensure_ascii=False, indent=2),
            mode=0o600,
        )
        fsync_directory(directory)

        new_hashes = {str(path): _sha256(content) for path, content in modifications.items()}
        for path, content in modifications.items():
            atomic_write(path, content)
            if _sha256(_read_text(path)) != new_hashes[str(path)]:
                raise TransactionError(f"Verifica della scrittura fallita per {path}.")

        _write_fsync(directory / _COMMITTED_MARKER, "committed\n", mode=0o600)
        fsync_directory(directory)
    except Exception as exc:
        marker = directory / _COMMITTED_MARKER
        if marker.exists():
            marker.unlink()
            fsync_directory(directory)
        restored = _restore_backups(entries)
        if restored:
            _remove_transaction_directory(directory)
            raise TransactionError(f"Transazione annullata e file ripristinati: {exc}") from exc
        raise TransactionError(
            f"Transazione fallita e ripristino incompleto; il journal resta per il recovery: {exc}"
        ) from exc

    _remove_transaction_directory(directory)


def recover_pending_transaction(ledger_path: Path) -> bool:
    """Recover a transaction left pending by a crash.

    Returns ``True`` when a transaction directory was present. A committed
    transaction is only cleaned up; an uncommitted one is rolled back.
    """
    directory = transaction_dir(ledger_path)
    if not directory.exists():
        return False

    if (directory / _COMMITTED_MARKER).exists():
        _remove_transaction_directory(directory)
        return True

    journal_path = directory / "journal.json"
    if not journal_path.exists():
        # The process died before the journal was written, so no target file
        # was modified yet.
        _remove_transaction_directory(directory)
        return True

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
            "Recovery incompleto: backup non valido o file modificato esternamente. "
            f"Journal: {journal_path}"
        )

    _remove_transaction_directory(directory)
    return True


def _restore_backups(entries: list[dict[str, Any]]) -> bool:
    # Preflight the whole journal before touching any file. A third version
    # belongs to an external writer and must never be overwritten by recovery.
    planned: list[tuple[Path, str]] = []
    try:
        for entry in entries:
            path = Path(str(entry["path"]))
            backup = Path(str(entry["backup"]))
            expected = str(entry["original_sha256"])
            original = _read_text(backup)
            if _sha256(original) != expected or not path.is_file():
                return False
            current_hash = _sha256(_read_text(path))
            if current_hash == expected:
                continue
            if current_hash != str(entry["new_sha256"]):
                return False
            planned.append((path, original))
    except Exception:
        return False

    try:
        for path, original in planned:
            atomic_write(path, original)
            if _sha256(_read_text(path)) != _sha256(original):
                return False
    except Exception:
        return False
    return True


def _write_fsync(path: Path, content: str, *, mode: int = 0o600) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode,
    )
    with os.fdopen(
        descriptor,
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_atomic_fsync(path: Path, content: str, *, mode: int = 0o600) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _remove_transaction_directory(directory: Path) -> None:
    # Once journal removal is durable, a crash during recursive cleanup cannot
    # turn a committed operation into a rollback with partially deleted backups.
    (directory / "journal.json").unlink(missing_ok=True)
    fsync_directory(directory)
    shutil.rmtree(directory)
    fsync_directory(directory.parent)
