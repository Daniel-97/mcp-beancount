"""Ledger loading, versioning, and inbox inspection."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from beancount import loader
from beancount.core.data import BeancountError, Directive

from beancount_mcp.config import Config
from beancount_mcp.errors import tool_error
from beancount_mcp.multifile import transaction_dir


class LedgerError(Exception):
    """Raised when the ledger cannot be loaded."""


LEDGER_ERROR_HINT = (
    "Verifica che il ledger esista e sia leggibile. "
    "Se è stato spostato, riavvia il server con il nuovo percorso."
)


@dataclass(frozen=True, slots=True)
class InboxStatus:
    """Whether the inbox exists and is included by the ledger."""

    path: Path
    exists: bool
    included: bool
    warning: str | None


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    """A load of the ledger at one point in time."""

    ledger_path: Path
    files: tuple[Path, ...]
    entries: tuple[Directive, ...]
    errors: tuple[BeancountError, ...]
    options: dict[str, Any]
    version: str
    inbox: InboxStatus
    contents: Mapping[Path, bytes] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Return whether the ledger has no directives."""
        return not self.entries


def compute_ledger_version(files: Iterable[Path]) -> str:
    """Compute a deterministic SHA-256 over file paths and contents."""
    return _version_from_contents({path: path.read_bytes() for path in files})


def _version_from_contents(contents: Mapping[Path, bytes]) -> str:
    normalized = {Path(os.path.abspath(os.path.expanduser(p))): b for p, b in contents.items()}
    digest = hashlib.sha256()
    for path in sorted(normalized):
        content_hash = hashlib.sha256(normalized[path]).hexdigest()
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def inspect_inbox(
    inbox_path: Path,
    ledger_path: Path,
    included_files: Iterable[Path],
) -> InboxStatus:
    """Check whether the inbox exists and is part of the loaded ledger."""
    exists = inbox_path.is_file()
    real_inbox = os.path.realpath(inbox_path)
    included = exists and any(os.path.realpath(path) == real_inbox for path in included_files)

    include_line = Path(os.path.relpath(inbox_path, ledger_path.parent)).as_posix()
    if included:
        warning = None
    elif exists:
        warning = f'Inbox non inclusa. Aggiungi al ledger: include "{include_line}"'
    else:
        warning = (
            f"Inbox non trovata: {inbox_path}. Creala; se non è già inclusa nel "
            f'ledger, aggiungi: include "{include_line}"'
        )

    return InboxStatus(
        path=inbox_path,
        exists=exists,
        included=included,
        warning=warning,
    )


class LedgerService:
    """Load the ledger from disk on every request, without caching its data."""

    def __init__(self, config: Config) -> None:
        self._config = config
        # Only the file list of the last load is remembered: it lets a ledger
        # whose include graph did not change be verified with a single parse.
        self._known_files: tuple[Path, ...] = (config.ledger_path,)

    @property
    def config(self) -> Config:
        """Return the immutable configuration used by this service."""
        return self._config

    def load(self) -> LedgerSnapshot:
        """Load the current state of the ledger from disk."""
        ledger_path = self._config.ledger_path
        _check_pending_transaction(ledger_path)
        if not ledger_path.is_file():
            raise LedgerError(f"Ledger non trovato: {ledger_path}")

        # Bracket the parse with captured bytes and stat checks of the files
        # expected to be included. Retry if they or the include graph changed;
        # the first load needs one such retry to discover the includes.
        files = tuple(path for path in self._known_files if path.is_file()) or (ledger_path,)
        for _ in range(4):
            before = {path: _file_state(path) for path in files}
            contents = {path: path.read_bytes() for path in files}
            entries, errors, options = loader.load_file(str(ledger_path))
            loaded_files = tuple(Path(path) for path in options.get("include", [str(ledger_path)]))
            stable = set(loaded_files) == set(files) and all(
                _file_state(path) == before[path] and path.read_bytes() == contents[path]
                for path in files
            )
            if stable:
                self._known_files = loaded_files
                _check_pending_transaction(ledger_path)
                return LedgerSnapshot(
                    ledger_path=ledger_path,
                    files=loaded_files,
                    entries=tuple(entries),
                    errors=tuple(errors),
                    options=dict(options),
                    version=_version_from_contents(contents),
                    inbox=inspect_inbox(self._config.inbox_path, ledger_path, loaded_files),
                    contents=MappingProxyType(contents),
                )
            files = loaded_files
        raise LedgerError(
            "Il ledger cambia durante la lettura. Riprova quando i file sono stabili."
        )


def ledger_error(error: Exception) -> dict[str, Any]:
    """Build the response for a ledger that cannot be loaded."""
    return tool_error("LEDGER_ERROR", str(error), LEDGER_ERROR_HINT)


def load_snapshot(service: LedgerService) -> LedgerSnapshot | dict[str, Any]:
    """Load the ledger, or return the error response to hand to the client."""
    try:
        return service.load()
    except (LedgerError, OSError) as exc:
        return ledger_error(exc)


def _file_state(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _check_pending_transaction(ledger_path: Path) -> None:
    directory = transaction_dir(ledger_path)
    if (directory / "journal.json").exists() and not (directory / "committed").exists():
        raise LedgerError(
            "Transazione multi-file in corso o da recuperare. Riprova o riavvia il server."
        )
