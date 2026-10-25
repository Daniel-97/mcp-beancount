# Decisioni tecniche

Data: 2026-10-25

## Versioni delle dipendenze

- Python minimo: `>=3.11`. Sviluppo e verifica locale con Python 3.13, fissato in
  `.python-version`.
- `beancount==3.2.3`
- `beanquery==0.2.0`
- `mcp==2.3.0`

Motivazione: Beancount 3.x è la major corrente; in v3 `beanquery` è un pacchetto
separato da Beancount. L'SDK MCP Python 2.x è la versione corrente.

## API MCP

La specifica cita `FastMCP`, ma nell'SDK MCP 2.x la classe è stata rinominata
`MCPServer` e si importa da `mcp.server`. Il codice usa quindi `MCPServer`.

## Tooling

- Build backend: `hatchling`, con layout `src/`.
- Gestione dipendenze e ambiente: `uv`.
- CLI: `argparse` della standard library, senza dipendenze aggiuntive.
- Lint e formattazione: `ruff`.
- Tipi: `mypy` in modalità `strict`. I pacchetti `beancount` e `beanquery` sono
  esclusi dal controllo dei type hint mancanti.

## Comando `init`

- `--currency` è obbligatorio: non viene applicata una valuta predefinita implicita.
- Il titolo del ledger creato è `"Beancount MCP Ledger"`.
- La direttiva `open Equity:Opening-Balances` usa la data odierna e non vincola
  valute.
- `init` rifiuta file esistenti non vuoti, symlink e path che non sono file
  regolari; un file esistente vuoto è accettato.
- Il file principale viene scritto in modo atomico (file temporaneo nella stessa
  directory, `fsync`, `os.replace`), così un errore non lascia un ledger parziale.
- Le directory padre del ledger vengono create se mancanti.

## Test e CI

Su richiesta esplicita dell'utente, i test automatici e la CI sono rimandati. La
specifica prevede TDD e CI in M0: questa deviazione va recuperata prima di
considerare chiusa la milestone. Per ora la verifica è manuale e documentata nel
piano `docs/superpowers/plans/2026-10-25-bootstrap-and-init.md`.
