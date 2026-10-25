# beancount-mcp

Server MCP per interrogare e modificare in sicurezza un ledger Beancount.
Il progetto è in sviluppo: per ora è disponibile il comando `init` e lo scheletro
del server MCP.

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

## Documentazione

- Specifica: [`spec.md`](spec.md)
- Decisioni tecniche: [`docs/decisions.md`](docs/decisions.md)
