# Decisioni tecniche

Ultimo aggiornamento: 2026-10-26

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

## Caricamento del ledger e versione

- Il ledger viene caricato da disco a ogni `LedgerService.load()`, senza cache.
- Il server risolve i symlink del file principale prima del caricamento, così gli
  `include` relativi usano la directory reale. `init` continua a rifiutare i
  symlink e a non risolverli.
- I file coinvolti sono quelli restituiti da `options_map["include"]` di
  Beancount 3.2.3: path assoluti, normalizzati, ordinati e deduplicati (file
  principale più include risolti, inclusi i glob).
- La versione è SHA-256 della concatenazione, in ordine alfabetico di path, di
  `path assoluto + NUL + SHA-256 del contenuto + newline`. I path non vengono
  risolti tramite symlink.
- Lo stato dell'inbox confronta i path reali. `--inbox` è relativo alla directory
  del ledger; è accettato anche un path assoluto.
- `is_empty` è vero quando il loader non restituisce direttive, quindi anche per
  un file con soli commenti.

## Tool `ledger_info`

- Risposta con `ok: true`, percorso del ledger, file, versione, operating
  currencies (sempre lista), account, date delle transazioni, conteggio errori,
  top tag/link, stato inbox, modalità read-only, `allow_edit_outside_inbox` e
  warnings.
- Se il ledger sparisce o diventa illeggibile dopo l'avvio, il tool restituisce
  `ok: false` con `error.code = "LEDGER_ERROR"`, messaggio, `details` e `hint`.
  Questo codice estende la tabella di §7 per gli errori di I/O non altrimenti
  rappresentati.
- Gli account derivano da `Open`/`Close`; `currencies` è `null` quando l'account
  non ha restrizioni; `is_open` dipende dall'assenza di `Close`.
- Gli errori preesistenti non bloccano il tool: vengono contati e segnalati nei
  warnings.
- I tag e i link sono ordinati per frequenza decrescente e nome, massimo 10.

## Configurazione del server

- `Config` è immutabile e contiene ledger, inbox, read-only,
  allow-edit-outside-inbox, query limit e transport.
- Flag CLI: `--inbox`, `--read-only`, `--allow-edit-outside-inbox`,
  `--query-limit` (1–1000), `--transport stdio`.
- Un ledger mancante termina il server con exit code 2 e un messaggio che rimanda
  a `init` o al percorso corretto.

## Tool `query`

- Statement ammessi: `SELECT`, `BALANCES`, `JOURNAL`. `PRINT`, `CREATE TABLE`,
  `INSERT` e qualsiasi altro statement sono rifiutati con `QUERY_ERROR`.
- `total_rows` viene letto da `cursor.rowcount` prima di consumare il cursore;
  `truncated` è vero quando esiste almeno una riga oltre `limit`.
- `limit` è 1–1000; se omesso usa `Config.query_limit`. `offset` deve essere
  `>= 0`. Violazioni → `LIMIT_EXCEEDED`.
- Serializzazione: `Decimal` come stringa, `Amount`/`Position`/`Inventory` come
  stringa, date/datetime ISO, set come lista ordinata, float come stringa.
- Le colonne riportano nome e tipo (`string`, `integer`, `decimal`, `date`,
  `datetime`, `boolean`, `amount`, `position`, `inventory`).

## Validazione prima/dopo

- La firma di un errore è `(tipo, messaggio)`; i numeri di riga e i path non
  entrano nel confronto.
- Il confronto è un multiset: gli errori preesistenti vengono sottratti e solo
  quelli nuovi sono bloccanti.
- `ErrorMultisetValidator` implementa il protocollo `Validator` su viste con
  `errors`.
- Il tool `validate` restituisce `ok`, `valid`, `ledger_version`, `error_count`
  ed `errors` con `type`, `message`, `file`, `line`.
- Il fixture `with_errors` contiene una transazione sbilanciata e un account non
  aperto, per verificare il confronto e la reportistica.

## Scritture sull'inbox

- Le scritture sono serializzate da un lock non bloccante accanto al ledger
  (`<main>.lock`). Se il lock esiste, il tool risponde `LOCKED` e indica il file.
- La scrittura usa un file temporaneo nella directory di destinazione, `fsync` e
  `os.replace`; il mode del file esistente viene preservato.
- `dry_run` esegue parsing, staging e validazione senza creare lock né scrivere.
- Lo staging copia i file inclusi in un albero temporaneo, applica la modifica a
  un solo file e ricarica la copia con Beancount. I path assoluti negli `include`
  vengono riscritti nell'albero temporaneo; i path relativi restano invariati.
- Il confronto usa `ErrorMultisetValidator`: solo gli errori nuovi bloccano.
- `pad` e `balance` sono rifiutati; `include` e `plugin` sono rifiutati per
  impedire accessi a file o esecuzione di codice tramite l'inbox.
- `expected_ledger_version` viene controllata prima e dopo lo staging; un cambio
  concorrente produce `VERSION_CONFLICT`.
- `add_transactions` restituisce entry formattate, `entry_count`, versione,
  `warning_count` e, in dry-run, `would_write_text`.
- `open_account` valida formato e radice dell'account, rifiuta duplicati e nomi
  simili (`confirm_new` per procedere), valida le valute e usa oggi come data
  predefinita.

## Identità e modifica delle entry

- `entry_id` è un oggetto `{"file": path assoluto, "line": int, "hash": sha256}`.
- Lo span di una direttiva parte da una riga non vuota e non indentata e arriva
  alla riga precedente la successiva riga con le stesse caratteristiche.
- L'hash è SHA-256 del testo UTF-8 dello span, righe vuote finali incluse.
- Se il file o la riga non esistono → `ENTRY_NOT_FOUND`; se l'hash non coincide →
  `ENTRY_CHANGED` con `current_text` e `current_hash`.
- Senza `--allow-edit-outside-inbox` sono modificabili solo entry dell'inbox.
- Con il flag, il file deve essere incluso e dentro la directory del ledger dopo
  `realpath`; altrimenti `PATH_NOT_ALLOWED`.
- `delete_transaction` accetta solo transazioni; open/close/balance/pad sono
  rifiutati.
- Edit e delete usano lock, staging, validazione prima/dopo e scrittura atomica.

## Ricerca transazioni

- Filtri combinati in AND.
- `payee` è un confronto esatto; `narration_contains` è case-insensitive.
- `account` corrisponde all'account esatto e ai suoi sottoconti.
- `date_from`/`date_to` sono inclusive, in formato ISO.
- `min_amount`/`max_amount` sono numeri decimali senza valuta e si applicano al
  valore assoluto delle posting.
- `tags` richiede la presenza di tutti i tag indicati.
- I risultati sono ordinati dal più recente; default `limit=50`, massimo 500.
- La risposta include `transactions` (testo Beancount e `entry_id`), `count`,
  `total_matches`, `truncated` e `limit`.

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

Stato attuale: 99 test, tutti relativi a M0/M1. I test di M2–M6 sono la fase
successiva e precedono il merge del branch di implementazione.

Pubblicazione su PyPI e CI restano da fare: richiedono rispettivamente
credenziali del maintainer e la configurazione CI rimossa su richiesta.

La CI resta rimandata; va aggiunta prima di considerare chiusa la milestone M0,
insieme ai passi `ruff`, `mypy` e `pytest`.
