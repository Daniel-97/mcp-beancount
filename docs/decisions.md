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
- Il file principale non può chiamarsi `inbox.bean`: verrebbe incluso da sé.
- Il file principale viene scritto in modo atomico (file temporaneo nella stessa
  directory, `fsync`, `os.replace`), così un errore non lascia un ledger parziale.
- I permessi dei file rispettano l'umask dell'utente; se il file principale esiste
  già vuoto, viene preservato il suo modo.
- Le directory padre del ledger vengono create se mancanti.
- La valuta è normalizzata in maiuscolo e validata con una grammatica simile a
  quella ISO (`[A-Z][A-Z0-9'._-]{0,22}[A-Z0-9]`). Questa regola è più restrittiva di
  Beancount, che accetta anche commodity di un carattere e prefissi `/`: scelta
  conservativa, da rivalutare quando `init` potrà usare `CURRENCY_RE`.

## Test e CI

Su richiesta esplicita dell'utente, i test automatici vengono scritti **alla fine
di ogni incremento**, non prima dell'implementazione come prevede la specifica.
La suite vive in `tests/unit/` e `tests/integration/` e si esegue con:

```bash
uv run pytest
```

Convenzioni obbligatorie per i test:

- nome nella forma `test<Subject>_should<Behavior>_when<Condition>()`, ad esempio
  `testCreateLedger_shouldRefuseInitialization_whenMainLedgerIsNotEmpty()`;
- corpo strutturato con i commenti `# Given`, `# When`, `# Then`;
- asserzioni su comportamento e side effect reali, non sull'esistenza di mock.

La CI resta rimandata; va aggiunta prima di considerare chiusa la milestone M0,
insieme ai passi `ruff`, `mypy` e `pytest`.
