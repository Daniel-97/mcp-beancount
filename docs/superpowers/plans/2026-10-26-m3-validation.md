# M3 — Validazione e tool `validate` — Implementation Plan

**Goal:** Confrontare gli errori Beancount prima/dopo una modifica (multiset di tipo+messaggio, ignorando le righe) ed esporre `validate` con file, riga e messaggio.

**Architecture:** `validation.py` definisce `Issue`, i protocolli `ErrorTree`/`Validator`, l'estrazione degli errori e il confronto. `tools/validate.py` formatta la risposta; `server.py` registra il tool. Il confronto sarà riusato da M4.

**Spec:** `spec.md` §5.3, §6.7, §7, §11 M3

## Global Constraints

- Il confronto ignora i numeri di riga: la firma è `(tipo errore, messaggio)`.
- Sono bloccanti solo gli errori **nuovi**; gli errori preesistenti vengono sottratti come multiset.
- `validate` restituisce tutti gli errori correnti con file, riga, tipo e messaggio.
- Errori di I/O → `LEDGER_ERROR` strutturato.
- I test automatici sono stati aggiunti nella fase finale (suite completa: 276 test).

## Task

- [x] Creare `src/beancount_mcp/validation.py` con `Issue`, `ErrorTree`, `Validator`, `issues_from_errors`, `compare_issues`, `ErrorMultisetValidator`, `issue_to_dict`.
- [x] Creare `src/beancount_mcp/tools/validate.py` con `build_validation(service)`.
- [x] Registrare il tool `validate` in `server.py`.
- [x] Aggiornare il test esistente dei tool registrati a `["ledger_info", "query", "validate"]`.
- [x] Aggiungere il fixture `tests/fixtures/with_errors/` con transazione sbilanciata e account non aperto.
- [x] Aggiornare README e `docs/decisions.md`.
- [x] Commit: `feat(M3): add error comparison and validate tool`.

## Verifica manuale

- [x] `validate` su `minimal` → 0 errori.
- [x] `validate` su `with_errors` → 2 errori con file/riga.
- [x] `compare_issues` sottrae correttamente errori identici e segnala solo i nuovi.
