# M1 — LedgerService, versione del ledger e `ledger_info` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Caricare il ledger a ogni richiesta, calcolarne la versione SHA-256 e esporre il tool `ledger_info` con account, date, errori, tag/link, inbox e modalità read-only.

**Architecture:** `ledger.py` incapsula caricamento Beancount, scoperta dei file inclusi, versione e stato dell'inbox dietro `LedgerService`. `tools/ledger_info.py` trasforma lo snapshot in una risposta compatta; `server.py` registra il tool e inietta il servizio senza stato globale. `config.py` costruisce un `Config` immutabile usato da CLI, servizio e tool.

**Tech Stack:** Python >= 3.11, Beancount 3.2.3, MCP Python SDK 2.3.0, pytest, ruff, mypy strict.

**Spec:** `spec.md` (in particolare §4.3, §5.2, §6.1, §8, §9, §10.2, §11 M1)

## Global Constraints

- Il ledger viene caricato da disco a **ogni** `load()`; nessuna cache in memoria.
- La versione è SHA-256 della concatenazione ordinata di `(percorso assoluto, SHA-256 del contenuto)` per tutti i file restituiti da `options_map["include"]` (file principale più include risolti, inclusi i glob).
- I file inclusi si leggono da `options_map["include"]`: Beancount 3.2.3 li restituisce già assoluti, normalizzati, ordinati e deduplicati.
- L'inbox predefinita è `inbox.bean` accanto al ledger; `--inbox` è relativo alla directory del ledger, ma un path assoluto è accettato.
- Se l'inbox manca o non è inclusa, `ledger_info` funziona e riporta un warning con la riga `include` da aggiungere.
- Un ledger vuoto o con soli commenti è valido: `is_empty` è `true` e `ledger_info` suggerisce `open_account`.
- Gli errori preesistenti non bloccano `ledger_info`; vengono solo contati.
- Tutte le risposte hanno `ok: bool`. Gli importi, quando arriveranno, saranno stringhe con valuta, mai float.
- La docstring del tool contiene esempi d'uso.
- I test si scrivono **alla fine dell'incremento** (Task 4), non in TDD, come da workflow richiesto dall'utente.
- Nomi dei test: `test<Subject>_should<Behavior>_when<Condition>()`; corpo con `# Given`, `# When`, `# Then`.
- Nessuna modifica ai file dell'utente; questo incremento è di sola lettura.

## Review Focus

- Un file incluso cambia tra due `load()`: la versione deve cambiare e il secondo load deve vedere il nuovo contenuto (nessuna cache).
- Inbox inesistente ma già inclusa nel main: nessun crash; warning che chiede di creare il file senza imporre un `include` duplicato.
- Inbox esistente ma non inclusa: `included` falso e warning con il percorso relativo corretto.
- Ledger con soli commenti o vuoto: nessuna eccezione, `is_empty` vero, date transazioni nulle.
- Ledger con errori preesistenti: `ok` resta vero, `error_count` corretto e warning presente.
- File inclusi via glob o include annidati: tutti compaiono in `files` e contribuiscono alla versione.
- Ledger passato tramite symlink: i file inclusi e l'inbox devono essere confrontati per path reale per l'appartenenza, ma la versione usa il path assoluto non risolto.

---

## Struttura dei file

```
src/beancount_mcp/
  config.py              # Config, build_config, resolve_inbox_path
  ledger.py              # LedgerService, LedgerSnapshot, InboxStatus, version
  tools/
    __init__.py
    ledger_info.py       # build_ledger_info
  server.py              # create_server(config), registrazione ledger_info
  cli.py                 # flag server completi, passa Config a server.run

tests/
  fixtures/
    minimal/{main.bean,inbox.bean}
    empty/{main.bean,inbox.bean}
    no_inbox/main.bean
    multifile/{main.bean,inbox.bean,accounts/accounts.bean,accounts/cash.bean}
  unit/
    test_config.py       # esteso
    test_ledger.py       # nuovo
    test_ledger_info.py  # nuovo
    test_cli.py          # esteso
    test_server.py       # esteso
  integration/
    test_ledger_service.py
    test_ledger_info.py
```

---

### Task 1: Configurazione completa e CLI

**Files:**
- Modify: `src/beancount_mcp/config.py`
- Modify: `src/beancount_mcp/cli.py`

**Interfaces:**
- Consumes: `resolve_ledger_path`, `Path`, `os.environ`.
- Produces:
  - `DEFAULT_INBOX = "inbox.bean"`
  - `DEFAULT_QUERY_LIMIT = 100`
  - `@dataclass(frozen=True, slots=True) class Config` con campi `ledger_path: Path`, `inbox_path: Path`, `read_only: bool`, `allow_edit_outside_inbox: bool`, `query_limit: int`, `transport: str`
  - `resolve_inbox_path(ledger_path: Path, inbox: str = DEFAULT_INBOX) -> Path`
  - `build_config(ledger: str | None, *, inbox: str = DEFAULT_INBOX, read_only: bool = False, allow_edit_outside_inbox: bool = False, query_limit: int = DEFAULT_QUERY_LIMIT, transport: str = "stdio", env: Mapping[str, str] | None = None) -> Config`

- [ ] **Step 1: Aggiungere `Config`, costanti e `resolve_inbox_path`**

Comportamento:

1. `resolve_inbox_path` espande `~`, rende assoluto con `os.path.abspath` (senza risolvere symlink) e, se `inbox` è relativo, lo unisce alla directory del ledger.
2. `build_config` chiama `resolve_ledger_path(ledger, env)` e `resolve_inbox_path`.
3. `query_limit` deve essere tra `1` e `1000`; fuori intervallo solleva `ValueError` con messaggio `"--query-limit deve essere tra 1 e 1000"`.
4. `transport` accettato solo `"stdio"`; altrimenti `ValueError`.

- [ ] **Step 2: Estendere il parser server in `cli.py`**

Aggiungere a `_run_server`:

```python
parser.add_argument("--inbox", default=DEFAULT_INBOX)
parser.add_argument("--read-only", action="store_true")
parser.add_argument("--allow-edit-outside-inbox", action="store_true")
parser.add_argument("--query-limit", type=int, default=DEFAULT_QUERY_LIMIT)
parser.add_argument("--transport", choices=["stdio"], default="stdio")
```

Costruire `config = build_config(...)`, usare `config.ledger_path` per il controllo di esistenza e chiamare `server.run(config)`. Gli errori di `ValueError` da `build_config` vanno convertiti in `parser.error(str(exc))` (exit code 2).

- [ ] **Step 3: Verifica manuale**

```bash
uv run python - <<'PY'
from beancount_mcp.config import build_config

config = build_config("/tmp/main.bean", inbox="sub/inbox.bean", read_only=True)
print(config.ledger_path)
print(config.inbox_path)
print(config.read_only, config.query_limit, config.transport)
PY
```

Expected: ledger assoluto, inbox `/tmp/sub/inbox.bean`, `True 100 stdio`.

- [ ] **Step 4: Commit**

```bash
git add src/beancount_mcp/config.py src/beancount_mcp/cli.py
git commit -m "feat(M1): add server config and CLI flags"
```

---

### Task 2: `ledger.py` — caricamento, versione e inbox

**Files:**
- Create: `src/beancount_mcp/ledger.py`

**Interfaces:**
- Consumes: `Config` dal Task 1; `beancount.loader.load_file`; `beancount.core.data.BeancountError`, `Directive`.
- Produces:
  - `class LedgerError(Exception)`
  - `@dataclass(frozen=True, slots=True) class InboxStatus` con `path: Path`, `exists: bool`, `included: bool`, `warning: str | None`
  - `@dataclass(frozen=True, slots=True) class LedgerSnapshot` con `ledger_path: Path`, `files: tuple[Path, ...]`, `entries: tuple[Directive, ...]`, `errors: tuple[BeancountError, ...]`, `options: dict[str, Any]`, `version: str`, `inbox: InboxStatus`, proprietà `is_empty: bool`
  - `compute_ledger_version(files: Iterable[Path]) -> str`
  - `inspect_inbox(inbox_path: Path, ledger_path: Path, included_files: Iterable[Path]) -> InboxStatus`
  - `class LedgerService`: `__init__(config: Config)`, proprietà `config: Config`, `load() -> LedgerSnapshot`

- [ ] **Step 1: Implementare `compute_ledger_version`**

Algoritmo esatto:

```python
normalized = sorted({Path(os.path.abspath(os.path.expanduser(p))) for p in files})
digest = hashlib.sha256()
for path in normalized:
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    digest.update(str(path).encode("utf-8"))
    digest.update(b"\0")
    digest.update(content_hash.encode("ascii"))
    digest.update(b"\n")
return digest.hexdigest()
```

- [ ] **Step 2: Implementare `inspect_inbox`**

1. `exists = inbox_path.is_file()`.
2. `included = exists and any(os.path.realpath(inbox_path) == os.path.realpath(f) for f in included_files)`.
3. `include_line = Path(os.path.relpath(inbox_path, ledger_path.parent)).as_posix()`.
4. Warning esatti:
   - mancante: `Inbox non trovata: {inbox_path}. Creala; se non è già inclusa nel ledger, aggiungi: include "{include_line}"`
   - presente ma non inclusa: `Inbox non inclusa. Aggiungi al ledger: include "{include_line}"`
   - inclusa: `None`.

- [ ] **Step 3: Implementare `LedgerService.load`**

1. Se `config.ledger_path` non è un file, sollevare `LedgerError(f"Ledger non trovato: {config.ledger_path}")`.
2. `entries, errors, options = loader.load_file(str(config.ledger_path))`.
3. `files = tuple(Path(p) for p in options.get("include", [str(config.ledger_path)]))`.
4. `version = compute_ledger_version(files)`.
5. `inbox = inspect_inbox(config.inbox_path, config.ledger_path, files)`.
6. Restituire `LedgerSnapshot` con `tuple(entries)`, `tuple(errors)`, `dict(options)`.
7. `is_empty` è `not self.entries`.

Nessuna cache: ogni chiamata rilegge da disco.

- [ ] **Step 4: Verifica manuale sui fixture esistenti o temporanei**

```bash
uv run python - <<'PY'
import tempfile
from pathlib import Path
from beancount_mcp.config import build_config
from beancount_mcp.ledger import LedgerService

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "inbox.bean").write_text("")
    (root / "main.bean").write_text(
        'option "operating_currency" "EUR"\ninclude "inbox.bean"\n'
        '2026-01-01 open Assets:Cash EUR\n'
    )
    snapshot = LedgerService(build_config(str(root / "main.bean"))).load()
    print(len(snapshot.entries), len(snapshot.errors), snapshot.version)
    print(snapshot.files)
    print(snapshot.inbox)
PY
```

Expected: 1 entry, 0 errori, versione esadecimale a 64 caratteri, entrambi i file elencati, inbox inclusa.

- [ ] **Step 5: Commit**

```bash
git add src/beancount_mcp/ledger.py
git commit -m "feat(M1): load ledger, compute version, inspect inbox"
```

---

### Task 3: Tool `ledger_info` e registrazione MCP

**Files:**
- Create: `src/beancount_mcp/tools/__init__.py`
- Create: `src/beancount_mcp/tools/ledger_info.py`
- Modify: `src/beancount_mcp/server.py`

**Interfaces:**
- Consumes: `LedgerService`, `LedgerSnapshot`, `InboxStatus`; `Open`, `Close`, `Transaction`.
- Produces:
  - `build_ledger_info(service: LedgerService) -> dict[str, Any]`
  - `create_server(config: Config) -> MCPServer`
  - `run(config: Config) -> None`

- [ ] **Step 1: Implementare `build_ledger_info`**

Risposta esatta:

```python
{
    "ok": True,
    "ledger_path": str,
    "files": [str, ...],
    "ledger_version": str,
    "operating_currency": [str, ...],
    "accounts": [
        {
            "account": str,
            "open_date": str | None,      # ISO
            "close_date": str | None,     # ISO
            "currencies": list[str] | None,
            "is_open": bool,
        }
    ],
    "first_transaction_date": str | None,
    "last_transaction_date": str | None,
    "transaction_count": int,
    "error_count": int,
    "top_tags": [{"name": str, "count": int}],
    "top_links": [{"name": str, "count": int}],
    "inbox": {
        "path": str,
        "exists": bool,
        "included": bool,
        "warning": str | None,
    },
    "read_only": bool,
    "is_empty": bool,
    "warnings": [str, ...],
}
```

Regole:

1. Account da `Open` e `Close`; un account con solo `Close` compare comunque. `currencies` è `list(entry.currencies)` se presente, altrimenti `None`. `is_open` è `close_date is None`. Ordinamento alfabetico.
2. Transazioni solo `Transaction`; `first_transaction_date`/`last_transaction_date` da min/max; `transaction_count` è il numero.
3. `top_tags` e `top_links`: `Counter`, ordinamento per `(-count, name)`, massimo **10** elementi.
4. `warnings` nell'ordine: ledger vuoto, warning inbox, errori preesistenti.
   - vuoto: `Il ledger è vuoto. Apri gli account necessari con open_account.`
   - errori: `Il ledger contiene {n} errori preesistenti.`
5. `operating_currency` è sempre una lista (Beancount ammette più valute).

- [ ] **Step 2: Registrare il tool in `server.py`**

```python
def create_server(config: Config) -> MCPServer:
    mcp = MCPServer("beancount-mcp", version=__version__)
    service = LedgerService(config)

    @mcp.tool()
    def ledger_info() -> dict[str, Any]:
        """Return a compact overview of the Beancount ledger.

        Call this at the start of a session, before querying or writing.
        Returns included files, ledger version, operating currencies, accounts,
        transaction date range, preexisting error count, top tags/links, inbox
        status, and read-only mode.

        Examples:
        - Call with no arguments to discover the accounts available.
        - Use ledger_version when calling a write tool with expected_ledger_version.
        - Check inbox.included before attempting any write.
        """
        return build_ledger_info(service)

    return mcp


def run(config: Config) -> None:
    create_server(config).run()
```

- [ ] **Step 3: Verifica manuale del tool registrato**

```bash
uv run python - <<'PY'
import asyncio
from pathlib import Path
import tempfile

from beancount_mcp.config import build_config
from beancount_mcp.server import create_server

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "inbox.bean").write_text("")
    (root / "main.bean").write_text('include "inbox.bean"\n')
    mcp = create_server(build_config(str(root / "main.bean")))
    print([tool.name for tool in asyncio.run(mcp.list_tools())])
    result = asyncio.run(mcp.call_tool("ledger_info", {}))
    print(result.structured_content["ok"])
PY
```

Expected: `['ledger_info']` e `True`.

- [ ] **Step 4: Commit**

```bash
git add src/beancount_mcp/tools src/beancount_mcp/server.py
git commit -m "feat(M1): expose ledger_info MCP tool"
```

---

### Task 4: Fixture e test (Given-When-Then)

**Files:**
- Create: `tests/fixtures/minimal/main.bean`
- Create: `tests/fixtures/minimal/inbox.bean`
- Create: `tests/fixtures/empty/main.bean`
- Create: `tests/fixtures/empty/inbox.bean`
- Create: `tests/fixtures/no_inbox/main.bean`
- Create: `tests/fixtures/multifile/main.bean`
- Create: `tests/fixtures/multifile/inbox.bean`
- Create: `tests/fixtures/multifile/accounts/accounts.bean`
- Create: `tests/fixtures/multifile/accounts/cash.bean`
- Create: `tests/unit/test_ledger.py`
- Create: `tests/unit/test_ledger_info.py`
- Create: `tests/integration/test_ledger_service.py`
- Create: `tests/integration/test_ledger_info.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_cli.py`
- Modify: `tests/unit/test_server.py`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: suite pytest completa dell'incremento.

- [ ] **Step 1: Creare i fixture**

`minimal/main.bean`:

```beancount
option "title" "Minimal"
option "operating_currency" "EUR"
include "inbox.bean"

2026-01-01 open Assets:Cash EUR
2026-01-01 open Expenses:Food

2026-01-02 * "Shop" "Lunch" #food ^lunch
  Expenses:Food   10.00 EUR
  Assets:Cash    -10.00 EUR

2026-01-03 * "Shop" "Dinner" #food #travel ^lunch
  Expenses:Food   20.00 EUR
  Assets:Cash    -20.00 EUR
```

`minimal/inbox.bean`: vuoto.

`empty/main.bean`:

```beancount
; Ledger intentionally empty for tests.
include "inbox.bean"
```

`empty/inbox.bean`: vuoto.

`no_inbox/main.bean`:

```beancount
option "title" "No Inbox"
option "operating_currency" "EUR"

2026-01-01 open Assets:Cash EUR
2026-01-01 open Expenses:Food

2026-01-02 * "Shop" "Lunch"
  Expenses:Food   10.00 EUR
  Assets:Cash    -10.00 EUR
```

`multifile/main.bean`:

```beancount
option "title" "Multifile"
option "operating_currency" "EUR"
include "accounts/accounts.bean"
include "inbox.bean"
```

`multifile/accounts/accounts.bean`:

```beancount
include "cash.bean"

2026-01-01 open Expenses:Food
```

`multifile/accounts/cash.bean`:

```beancount
2026-01-01 open Assets:Cash EUR
```

`multifile/inbox.bean`: vuoto.

- [ ] **Step 2: Test unitari versione e inbox (`tests/unit/test_ledger.py`)**

Nomi e asserzioni minime:

1. `testComputeLedgerVersion_shouldBeDeterministic_whenFilesAreUnchanged` — due chiamate con gli stessi file restituiscono la stessa stringa di 64 caratteri esadecimali.
2. `testComputeLedgerVersion_shouldChange_whenFileContentChanges` — modifica un file, la versione cambia.
3. `testComputeLedgerVersion_shouldIgnoreInputOrder_whenFilesAreSame` — ordine inverso, stessa versione.
4. `testComputeLedgerVersion_shouldDependOnFilePath_whenContentsAreIdentical` — due file con lo stesso contenuto in path diversi producono versioni diverse.
5. `testInspectInbox_shouldMarkIncluded_whenPathIsAmongFiles` — `exists`, `included`, `warning is None`.
6. `testInspectInbox_shouldWarnMissing_whenFileDoesNotExist` — `exists is False`, warning contiene `Inbox non trovata` e `include "inbox.bean"`.
7. `testInspectInbox_shouldWarnNotIncluded_whenFileExistsOutsideFiles` — `exists True`, `included False`, warning contiene `Inbox non inclusa`.
8. `testLedgerService_shouldRaise_whenLedgerFileIsMissing` — `pytest.raises(LedgerError)`.

- [ ] **Step 3: Test unitari config/CLI/server**

`tests/unit/test_config.py` aggiungere:

1. `testResolveInboxPath_shouldBeRelativeToLedgerDirectory_whenInboxIsRelative`
2. `testResolveInboxPath_shouldKeepAbsolutePath_whenInboxIsAbsolute`
3. `testBuildConfig_shouldValidateQueryLimit_whenLimitIsOutsideRange` (parametri `0`, `1001`)
4. `testBuildConfig_shouldRejectUnsupportedTransport_whenTransportIsNotStdio`
5. `testBuildConfig_shouldCombineLedgerInboxAndFlags_whenAllOptionsAreProvided`

`tests/unit/test_cli.py` aggiungere:

1. `testMainServer_shouldPassReadOnlyConfig_whenReadOnlyFlagIsPresent`
2. `testMainServer_shouldPassResolvedInbox_whenInboxOptionIsPresent`
3. `testMainServer_shouldRejectInvalidQueryLimit_whenLimitIsOutsideRange` (SystemExit 2)
4. `testMainServer_shouldPassStdioTransport_whenTransportIsSpecified`

`tests/unit/test_server.py` modificare/aggiungere:

1. `testCreateServer_shouldExposeLedgerInfoTool_whenCreated` — `asyncio.run(mcp.list_tools())` restituisce esattamente `["ledger_info"]`.
2. `testCreateServer_shouldUseProjectNameAndVersion_whenCreated` — invariato ma con `Config`.
3. `testCreateServer_shouldReturnOkFromLedgerInfo_whenToolIsCalled` — `asyncio.run(mcp.call_tool("ledger_info", {}))`, `structured_content["ok"] is True`.

- [ ] **Step 4: Test di integrazione sul servizio**

`tests/integration/test_ledger_service.py`:

1. `testLedgerService_shouldLoadMinimalLedger_whenFilesAreValid` — 3 entry, 0 errori, `files` contiene main e inbox.
2. `testLedgerService_shouldReportNestedIncludes_whenLedgerIsMultifile` — `files` contiene main, accounts, cash, inbox.
3. `testLedgerService_shouldReloadFromDisk_whenFileChanges` — carica, modifica, ricarica: versione e numero entry cambiano.
4. `testLedgerService_shouldKeepVersionStable_whenIncludedFileIsUnchanged` — due load, stessa versione.
5. `testLedgerService_shouldReportEmptyLedger_whenMainHasOnlyComments` — `is_empty is True`, 0 entry, 0 errori.
6. `testLedgerService_shouldReportInboxIncluded_whenInboxIsIncluded` — `exists` e `included` veri, warning nullo.
7. `testLedgerService_shouldReportInboxMissing_whenInboxDoesNotExist` — fixture `no_inbox`.
8. `testLedgerService_shouldReportInboxNotIncluded_whenInboxExistsButIsNotIncluded` — ledger temporaneo con inbox presente e nessun `include`.

- [ ] **Step 5: Test di integrazione su `ledger_info`**

`tests/integration/test_ledger_info.py`:

1. `testBuildLedgerInfo_shouldListAccountsWithDatesAndCurrencies_whenLedgerHasOpenAndClose` — ledger temporaneo con `open`/`close`, verifica date ISO, valute e `is_open`.
2. `testBuildLedgerInfo_shouldReturnOperatingCurrencies_whenOptionsAreSet` — fixture `minimal` → `["EUR"]`.
3. `testBuildLedgerInfo_shouldReturnTransactionRange_whenTransactionsExist` — fixture `minimal` → `2026-01-02` e `2026-01-03`, count 2.
4. `testBuildLedgerInfo_shouldReturnNullTransactionDates_whenLedgerIsEmpty` — fixture `empty`.
5. `testBuildLedgerInfo_shouldCountPreexistingErrors_whenLedgerHasErrors` — ledger temporaneo con errore (es. transazione sbilanciata) → `ok True`, `error_count > 0`, warning.
6. `testBuildLedgerInfo_shouldSortTopTagsAndLinks_whenValuesRepeat` — fixture `minimal` → `food` count 2, `lunch` count 2.
7. `testBuildLedgerInfo_shouldReportInboxStatus_whenInboxIsIncluded` — fixture `minimal`.
8. `testBuildLedgerInfo_shouldWarnAboutMissingInbox_whenInboxIsAbsent` — fixture `no_inbox`.
9. `testBuildLedgerInfo_shouldReportReadOnly_whenConfigIsReadOnly` — `read_only True`.
10. `testBuildLedgerInfo_shouldReportEmpty_whenLedgerHasNoEntries` — fixture `empty`, warning con `open_account`.
11. `testBuildLedgerInfo_shouldReturnServiceVersion_whenLedgerIsLoaded` — confronto con `LedgerService(config).load().version`.

- [ ] **Step 6: Eseguire la suite**

```bash
uv run pytest -q
```

Expected: tutti i test passano (numero atteso aggiornato a fine implementazione).

- [ ] **Step 7: Mutation check**

Verificare che almeno due mutazioni facciano fallire la suite:

1. rimuovere il ricalcolo della versione (usare una costante) → test versione/reload falliscono;
2. marcare `included` sempre `True` → test inbox falliscono.

Ripristinare il codice e rieseguire la suite.

- [ ] **Step 8: Commit**

```bash
git add tests src
git commit -m "test(M1): cover ledger service and ledger_info"
```

---

### Task 5: Documentazione e verifica finale

**Files:**
- Modify: `docs/decisions.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-10-26-m1-ledger-service-ledger-info.md`

- [ ] **Step 1: Aggiornare `docs/decisions.md`**

Registrare:

1. Algoritmo della versione (path assoluto, hash contenuto, separatori, ordinamento).
2. Fonte dei file inclusi: `options_map["include"]`.
3. Nessuna cache del ledger.
4. Schema di `ledger_info`: `operating_currency` lista, `currencies` null per account senza restrizioni, tag/link massimo 10 ordinati per frequenza.
5. Warning per inbox mancante/non inclusa ed empty ledger.
6. Flag CLI aggiunti e validazione `--query-limit`.
7. Numero finale dei test e comando di verifica.

- [ ] **Step 2: Aggiornare `README.md`**

Aggiungere che `ledger_info` è disponibile, con un esempio di chiamata MCP e i flag server principali (`--read-only`, `--inbox`, `--query-limit`, `--transport stdio`).

- [ ] **Step 3: Verificare qualità**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Expected: tutti exit code `0`.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions.md README.md docs/superpowers/plans/2026-10-26-m1-ledger-service-ledger-info.md
git commit -m "docs(M1): document ledger version and ledger_info"
```

---

## Verifica finale dell'incremento

- [ ] `uv run pytest -q` passa.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests` passano.
- [ ] `ledger_info` su `minimal` restituisce 2 transazioni, 2 account, tag/link ordinati e inbox inclusa.
- [ ] `ledger_info` su `empty` restituisce `is_empty: true` e warning con `open_account`.
- [ ] `ledger_info` su `no_inbox` restituisce warning con `include "inbox.bean"`.
- [ ] Modificare un file incluso cambia `ledger_version` al load successivo.
- [ ] Il server espone il tool `ledger_info` e `tools/list` restituisce `["ledger_info"]`.
- [ ] `docs/decisions.md` e README sono aggiornati.
