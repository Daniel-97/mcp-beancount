# M6 — Tool `find_transactions` — Implementation Plan

**Goal:** Cercare transazioni con filtri e restituirne il testo Beancount completo con `entry_id`.

**Architecture:** `tools/find_transactions.py` carica lo snapshot, costruisce la mappa `(file, riga) → span` con `entries.py`, filtra le `Transaction` e serializza i risultati. Nessuna scrittura.

**Spec:** `spec.md` §6.3, §6.4, §7, §11 M6

## Global Constraints

- Filtri combinati in AND: `payee` esatto, `narration_contains` case-insensitive, `account` include i sottoconti, date inclusive.
- `min_amount`/`max_amount` sono importi assoluti delle posting, senza valuta.
- `tags` richiede tutti i tag indicati.
- Risultati dal più recente; default `limit=50`, massimo 500.
- Ogni risultato contiene `entry_id` compatibile con `edit_transaction`/`delete_transaction`.
- Test automatici rimandati alla fase finale.

## Task

- [x] Implementare `find_transactions` con filtri e validazione parametri.
- [x] Costruire gli `entry_id` dagli span estratti dai file inclusi.
- [x] Registrare il tool in `server.py`.
- [x] Aggiornare il test esistente dei tool registrati.
- [x] Aggiornare README e `docs/decisions.md`.
- [x] Commit: `feat(M6): add find_transactions tool`.

## Verifica manuale

- [x] Senza filtri restituisce le transazioni dal più recente.
- [x] Filtri payee, narration, account, date, importi e tag.
- [x] `limit` e `truncated` corretti.
- [x] Date o importi invalidi → `VALIDATION_FAILED`.
- [x] `entry_id` restituito funziona con `edit_transaction` (con flag path appropriato).
