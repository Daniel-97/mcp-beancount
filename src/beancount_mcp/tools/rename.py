"""Implementation of rename_account, rename_tag, and rename_link."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from beancount_mcp.errors import tool_error
from beancount_mcp.ledger import LEDGER_ERROR_HINT, LedgerError, LedgerService, LedgerSnapshot
from beancount_mcp.multifile import TransactionError, commit_files
from beancount_mcp.renames import (
    RenameError,
    RenamePlan,
    plan_account_rename,
    plan_link_rename,
    plan_tag_rename,
)
from beancount_mcp.staging import StagingError, validate_staged_tree
from beancount_mcp.validation import Issue
from beancount_mcp.write_service import validation_failed_response
from beancount_mcp.writer import LockError, lock_path_for, write_lock

Planner = Callable[[LedgerSnapshot], RenamePlan]


def rename_account(
    service: LedgerService,
    account: str,
    new_account: str,
    include_subaccounts: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rename an account across all files included in the ledger."""
    return _perform_rename(
        service,
        lambda snapshot: plan_account_rename(
            snapshot,
            account,
            new_account,
            include_subaccounts=include_subaccounts,
        ),
        dry_run=dry_run,
        normalize_before=lambda issue: _normalize_account_issue(
            issue,
            account,
            new_account,
            include_subaccounts,
        ),
    )


def rename_tag(
    service: LedgerService,
    tag: str,
    new_tag: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rename a tag in transactions and pushtag/poptag directives."""
    return _perform_rename(
        service,
        lambda snapshot: plan_tag_rename(snapshot, tag, new_tag),
        dry_run=dry_run,
        normalize_before=lambda issue: _normalize_token_issue(
            issue,
            "#",
            tag,
            new_tag,
        ),
    )


def rename_link(
    service: LedgerService,
    link: str,
    new_link: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rename a link in transaction headers."""
    return _perform_rename(
        service,
        lambda snapshot: plan_link_rename(snapshot, link, new_link),
        dry_run=dry_run,
        normalize_before=lambda issue: _normalize_token_issue(
            issue,
            "^",
            link,
            new_link,
        ),
    )


def _perform_rename(
    service: LedgerService,
    planner: Planner,
    *,
    dry_run: bool,
    normalize_before: Callable[[Issue], Issue] | None = None,
) -> dict[str, Any]:
    if service.config.read_only:
        return tool_error(
            "READ_ONLY",
            "Il server è in modalità sola lettura.",
            "Riavvia il server senza --read-only per abilitare i rename.",
        )

    if dry_run:
        snapshot = _load(service)
        if isinstance(snapshot, dict):
            return snapshot
        try:
            plan = planner(snapshot)
        except RenameError as exc:
            return _rename_error(exc)
        authorized = _authorize_files(snapshot, service, plan.modifications)
        if authorized is not None:
            return authorized
        issues = _validate(snapshot, plan, normalize_before)
        if isinstance(issues, dict):
            return issues
        if issues:
            return validation_failed_response(issues, snapshot)
        return _success(snapshot, plan, dry_run=True)

    try:
        with write_lock(service.config.ledger_path):
            snapshot = _load(service)
            if isinstance(snapshot, dict):
                return snapshot
            try:
                plan = planner(snapshot)
            except RenameError as exc:
                return _rename_error(exc)
            authorized = _authorize_files(snapshot, service, plan.modifications)
            if authorized is not None:
                return authorized
            issues = _validate(snapshot, plan, normalize_before)
            if isinstance(issues, dict):
                return issues
            if issues:
                return validation_failed_response(issues, snapshot)

            current = _load(service)
            if isinstance(current, dict):
                return current
            if current.version != snapshot.version:
                return tool_error(
                    "VERSION_CONFLICT",
                    "Il ledger è cambiato durante la validazione.",
                    "Ricarica ledger_info e riprova.",
                    details=[
                        {
                            "expected": snapshot.version,
                            "actual": current.version,
                        }
                    ],
                )

            try:
                commit_files(snapshot.ledger_path, plan.modifications)
            except TransactionError as exc:
                return tool_error(
                    "LEDGER_ERROR",
                    str(exc),
                    "La transazione multi-file è stata annullata o richiede "
                    "recovery. Controlla il ledger e riprova.",
                )
            after = _load(service)
            if isinstance(after, dict):
                after["error"]["message"] = (
                    f"Rename applicato ma il ledger non è ricaricabile: {after['error']['message']}"
                )
                return after
            return _success(after, plan, dry_run=False)
    except LockError as exc:
        lock = lock_path_for(service.config.ledger_path)
        return tool_error(
            "LOCKED",
            str(exc),
            "Un'altra scrittura è in corso. Riprova tra poco; se il processo è "
            f"terminato, riprova: il lock viene rilasciato dal sistema operativo ({lock}).",
        )
    except (OSError, StagingError) as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile completare il rename: {exc}",
            "Verifica che i file del ledger siano leggibili e riprova.",
        )


def _authorize_files(
    snapshot: LedgerSnapshot,
    service: LedgerService,
    files: dict[Path, str],
) -> dict[str, Any] | None:
    inbox_real = Path(os.path.realpath(service.config.inbox_path))
    included = {Path(os.path.realpath(path)) for path in snapshot.files}
    ledger_dir = Path(os.path.realpath(snapshot.ledger_path.parent))
    blocked: list[dict[str, str]] = []
    for file in files:
        real = Path(os.path.realpath(file))
        if real == inbox_real:
            continue
        if not service.config.allow_edit_outside_inbox:
            blocked.append({"file": str(real), "reason": "outside inbox"})
            continue
        if real not in included:
            return tool_error(
                "PATH_NOT_ALLOWED",
                "Il rename toccherebbe un file non incluso dal ledger.",
                "Usa solo file inclusi dal ledger.",
                details=[{"file": str(real)}],
            )
        if not real.is_relative_to(ledger_dir):
            return tool_error(
                "PATH_NOT_ALLOWED",
                "Il rename toccherebbe un file fuori dalla directory del ledger.",
                f"Modifica solo file dentro {ledger_dir}.",
                details=[{"file": str(real), "ledger_dir": str(ledger_dir)}],
            )
    if blocked:
        return tool_error(
            "ENTRY_NOT_IN_INBOX",
            "Il rename toccherebbe file fuori dall'inbox e il server non "
            "consente modifiche esterne.",
            "Riavvia il server con --allow-edit-outside-inbox per rinominare "
            "anche gli altri file inclusi.",
            details=blocked,
        )
    return None


def _validate(
    snapshot: LedgerSnapshot,
    plan: RenamePlan,
    normalize_before: Callable[[Issue], Issue] | None,
) -> list[Issue] | dict[str, Any]:
    try:
        return validate_staged_tree(
            snapshot.ledger_path,
            snapshot.files,
            plan.modifications,
            snapshot.errors,
            normalize_before=normalize_before,
        )
    except (OSError, StagingError) as exc:
        return tool_error(
            "LEDGER_ERROR",
            f"Impossibile validare il rename: {exc}",
            "Verifica che i file del ledger siano leggibili.",
        )


def _success(
    snapshot: LedgerSnapshot,
    plan: RenamePlan,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": dry_run,
        "changes": [
            {
                "file": change.file,
                "line": change.line,
                "before": change.before,
                "after": change.after,
            }
            for change in plan.changes
        ],
        "change_count": len(plan.changes),
        "files_changed": len(plan.modifications),
        "ledger_version": snapshot.version,
        "warning_count": len(snapshot.errors),
    }


def _load(service: LedgerService) -> LedgerSnapshot | dict[str, Any]:
    try:
        return service.load()
    except (LedgerError, OSError) as exc:
        return tool_error("LEDGER_ERROR", str(exc), LEDGER_ERROR_HINT)


def _rename_error(error: RenameError) -> dict[str, Any]:
    return tool_error(
        error.code,
        error.message,
        error.hint,
        details=error.details,
    )


def _normalize_account_issue(
    issue: Issue,
    old_account: str,
    new_account: str,
    include_subaccounts: bool,
) -> Issue:
    old = old_account.strip()
    new = new_account.strip()
    suffix = r"(?::[A-Za-z0-9-]+)*" if include_subaccounts else ""
    lookahead = r"(?![A-Za-z0-9-])" if include_subaccounts else r"(?![A-Za-z0-9:-])"
    pattern = re.compile(rf"(?<![A-Za-z0-9:-]){re.escape(old)}{suffix}{lookahead}")
    message = pattern.sub(
        lambda match: new + match.group(0)[len(old) :],
        issue.message,
    )
    return Issue(
        type=issue.type,
        message=message,
        file=issue.file,
        line=issue.line,
    )


def _normalize_token_issue(
    issue: Issue,
    marker: str,
    old_value: str,
    new_value: str,
) -> Issue:
    old = old_value.strip().lstrip(marker)
    new = new_value.strip().lstrip(marker)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9\-_/.]){re.escape(marker)}{re.escape(old)}"
        r"(?![A-Za-z0-9\-_/.])"
    )
    message = pattern.sub(f"{marker}{new}", issue.message)
    return Issue(
        type=issue.type,
        message=message,
        file=issue.file,
        line=issue.line,
    )
