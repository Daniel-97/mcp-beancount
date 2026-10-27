# Backlog

## History delle modifiche ai file Beancount

Tool MCP dedicato per rispondere a domande del tipo “quali sono state le ultime
10 modifiche ai miei file bean?”.

Possibili fonti, da valutare in un piano dedicato:

- audit log del server (`.<ledger>.history.jsonl`) per le scritture MCP;
- Git history quando il ledger è in un repository;
- granularità della voce: per operazione, per file, per commit o per entry;
- filtri per file, data, tool e `limit`.

## Altre idee

- `rename_commodity` (rinomina commodity: postings, prezzi, balance, commodity).
- `rename_payee` / sostituzione narrazioni (bulk edit, non rename).
