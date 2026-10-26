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
errori preesistenti, tag/link più usati, stato dell'inbox e modalità read-only.
Va chiamato a inizio sessione; la versione restituita può essere usata come
`expected_ledger_version` dai tool di scrittura.

## Documentazione

- Specifica: [`spec.md`](spec.md)
- Decisioni tecniche: [`docs/decisions.md`](docs/decisions.md)
