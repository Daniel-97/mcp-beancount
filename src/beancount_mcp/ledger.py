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
    """Load the ledger from disk on every request, without caching."""

    def __init__(self, config: Config) -> None:
        self._config = config

    @property
    def config(self) -> Config:
        """Return the immutable configuration used by this service."""
        return self._config

    def load(self) -> LedgerSnapshot:
        """Load the current state of the ledger from disk."""
        ledger_path = self._config.ledger_path
        if not ledger_path.is_file():
            raise LedgerError(f"Ledger non trovato: {ledger_path}")

        # Discover includes, then bracket the actual parse with captured bytes
        # and stat checks. Retry if files or the include graph changed.
        _, _, discovery = loader.load_file(str(ledger_path))
        files = tuple(Path(path) for path in discovery.get("include", [str(ledger_path)]))
        for _ in range(3):
            before = {path: _file_state(path) for path in files}
            contents = {path: path.read_bytes() for path in files}
            entries, errors, options = loader.load_file(str(ledger_path))
            loaded_files = tuple(Path(path) for path in options.get("include", [str(ledger_path)]))
            stable = set(loaded_files) == set(files) and all(
                _file_state(path) == before[path] and path.read_bytes() == contents[path]
                for path in files
            )
            if stable:
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


def _file_state(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
