# M5 — Identità entry, `edit_transaction` e `delete_transaction` — Implementation Plan

**Goal:** Identificare una direttiva con `(file, riga, hash)` e modificarla o eliminarla in sicurezza, solo inbox di default.

**Architecture:** `entries.py` estrae gli span e calcola gli hash; `entry_service.py` risolve e autorizza l'entry, applica la modifica e riusa staging/validazione/lock di M4; `server.py` registra i tool.

**Spec:** `spec.md` §5.4, §6.5, §6.6, §7, §11 M5

## Global Constraints

- `entry_id` è `{"file": str, "line": int, "hash": sha256}`.
- Lo span parte da una riga non vuota e non indentata e finisce prima della successiva.
- Hash diverso → `ENTRY_CHANGED` con testo corrente.
- Senza flag, solo inbox → altrimenti `ENTRY_NOT_IN_INBOX`.
- Con `--allow-edit-outside-inbox`: file incluso e dentro la directory del ledger (dopo realpath) → altrimenti `PATH_NOT_ALLOWED`.
- `delete_transaction` elimina solo transazioni; open/close/balance/pad sono rifiutati.
- Stessa validazione prima/dopo, lock e scrittura atomica di M4.
- Test automatici aggiunti nella fase finale (suite completa: 243 test).

## Task

- [x] Creare `entries.py` con `EntryId`, `DirectiveSpan`, estrazione span, hash, replace/delete.
- [x] Creare `entry_service.py` con risoluzione, autorizzazione path, edit/delete e dry-run.
- [x] Registrare `edit_transaction` e `delete_transaction`.
- [x] Aggiornare il test esistente dei tool registrati.
- [x] Aggiornare README e `docs/decisions.md`.
- [x] Commit: `feat(M5): add entry edit and delete`.

## Verifica manuale

- [x] Edit inbox con hash valido.
- [x] Dry-run non modifica il file.
- [x] Hash obsoleto → `ENTRY_CHANGED` con testo corrente.
- [x] Delete transazione inbox.
- [x] Delete open → `VALIDATION_FAILED`.
- [x] Edit fuori inbox senza flag → `ENTRY_NOT_IN_INBOX`.
- [x] Edit fuori inbox con flag → successo.
- [x] File incluso ma fuori dalla directory → `PATH_NOT_ALLOWED`.
- [x] Lock presente → `LOCKED`.
