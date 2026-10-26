# beancount-mcp

Server MCP per interrogare e modificare in sicurezza un ledger Beancount.
Il progetto è in sviluppo: sono disponibili il comando `init` e il tool
`ledger_info`.

## Requisiti

- [uv](https://docs.astral.sh/uv/)

## Sviluppo

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

## Creare un ledger nuovo

```bash
uv run beancount-mcp init /percorso/main.bean --currency EUR
```

Il comando crea il file principale e un `inbox.bean` vuoto accanto ad esso.
Il file principale contiene titolo, `operating_currency`, l'`include` dell'inbox
e l'account `Equity:Opening-Balances`.

Se il percorso è omesso, viene usato `BEANCOUNT_MCP_LEDGER` oppure il percorso
predefinito `~/.beancount-mcp/ledger/main.bean`:

```bash
uv run beancount-mcp init --currency EUR
```

`init` non sovrascrive mai file non vuoti.

## Avviare il server

```bash
uv run beancount-mcp /percorso/main.bean
```

Il trasporto predefinito è `stdio`. Il server termina con un messaggio esplicativo
se il ledger non esiste.

Flag principali:

- `--inbox` — percorso dell'inbox relativo al ledger (default `inbox.bean`);
- `--read-only` — disabilita i tool di scrittura;
- `--allow-edit-outside-inbox` — consente modifiche fuori dall'inbox;
- `--query-limit` — limite predefinito per `query` (1–1000);
- `--transport stdio` — trasporto MCP.

Esempio:

```bash
uv run beancount-mcp /percorso/main.bean --read-only --inbox inbox.bean
```

## Tool disponibili

### `ledger_info`

Nessun parametro. Restituisce file inclusi, versione del ledger, valute
operative, account con date e valute, intervallo delle transazioni, numero di
errori preesistenti, tag/link più usati, stato dell'inbox, modalità read-only e
se le modifiche fuori dall'inbox sono abilitate. Va chiamato a inizio sessione;
la versione restituita può essere usata come `expected_ledger_version` dai tool
di scrittura.

### `query`

Esegue query BQL di sola lettura (`SELECT`, `BALANCES`, `JOURNAL`) con
paginazione. Parametri: `bql`, `limit` (1–1000, default dalla configurazione),
`offset`.

Esempi:

```sql
SELECT account, SUM(position) WHERE date >= 2026-01-01 GROUP BY account
SELECT date, payee, narration, position WHERE account = 'Expenses:Food' ORDER BY date DESC
```

La risposta contiene `columns`, `rows`, `limit`, `offset`, `truncated` e
`total_rows`. Gli importi sono stringhe.

### `validate`

Nessun parametro. Esegue la validazione completa del ledger e restituisce tutti
gli errori correnti con file, riga, tipo e messaggio, oltre a `valid` e
`ledger_version`. Gli errori preesistenti non bloccano le scritture; solo quelli
nuovi verranno rifiutati dai tool di modifica.

### `add_transactions`

Aggiunge una o più direttive Beancount all'inbox, con validazione prima/dopo.
Parametri: `text`, `dry_run` (default `false`),
`expected_ledger_version` (opzionale).

```text
2026-02-01 * "Bar" "Caffè"
  Expenses:Food    2.50 EUR
  Assets:Cash     -2.50 EUR
```

La scrittura è atomica, serializzata da un lock e rifiutata se introdurrebbe
nuovi errori. Con `dry_run=true` restituisce `would_write_text` senza modificare
file.

### `open_account`

Apre un account scrivendo una direttiva `open` nell'inbox. Parametri:
`account`, `currencies`, `date` (default oggi), `confirm_new`, `dry_run`.

```text
open_account("Expenses:Restaurant", ["EUR"])
```

Rifiuta account già aperti, nomi simili (`ACCOUNT_SIMILAR_EXISTS`) e radici non
ammesse. `confirm_new=true` consente di aprire comunque un nome simile.

### `edit_transaction`

Sostituisce una direttiva identificata da `entry_id`
(`{"file", "line", "hash"}`), restituito da `find_transactions`. Parametri:
`entry_id`, `new_text`, `dry_run`.

Di default funziona solo sull'inbox; con `--allow-edit-outside-inbox` anche su
file inclusi dentro la directory del ledger. Se il contenuto è cambiato
dall'emissione dell'id, risponde `ENTRY_CHANGED` con il testo corrente.

### `delete_transaction`

Elimina una transazione identificata da `entry_id`. Parametri: `entry_id`,
`dry_run`. Non elimina `open`, `close`, `balance` o `pad`. Valgono le stesse
regole di path e validazione di `edit_transaction`.

### `find_transactions`

Cerca transazioni e restituisce testo Beancount completo e `entry_id`. Filtri
opzionali combinati in AND: `payee`, `narration_contains`, `account`,
`date_from`, `date_to`, `min_amount`, `max_amount`, `tags`, `limit`.

```text
find_transactions(payee="Shop")
find_transactions(narration_contains="coffee", date_from="2026-01-01")
find_transactions(account="Expenses:Food", min_amount="10.00", max_amount="50.00")
```

`account` include i sottoconti. Gli importi sono valori assoluti delle posting,
senza valuta. I risultati sono dal più recente e `entry_id` può essere passato a
`edit_transaction` o `delete_transaction`.

## Configurazione di un client MCP

Esempio per un client che supporta la configurazione JSON (adatta i percorsi):

```json
{
  "mcpServers": {
    "beancount": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/percorso/del/repo/mcp-beancount",
        "beancount-mcp",
        "/percorso/main.bean"
      ]
    }
  }
}
```

Per una sessione in sola lettura aggiungi `"--read-only"` agli `args`.

## Documentazione

- Specifica: [`spec.md`](spec.md)
- Decisioni tecniche: [`docs/decisions.md`](docs/decisions.md)
