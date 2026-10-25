# Bootstrap e comando `init` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare lo scheletro del pacchetto `beancount-mcp` e implementare il comando `beancount-mcp init`, che genera un ledger nuovo senza mai sovrascrivere dati esistenti.

**Architecture:** Un pacchetto Python `src/beancount_mcp/` con CLI basata su `argparse`. Il comando `init` è isolato in `init.py` e usa solo `pathlib`/`os`, senza dipendere da Beancount. Un `server.py` minimo espone un `MCPServer` senza tool, pronto per le milestone successive. La configurazione del percorso del ledger sta in `config.py`.

**Tech Stack:** Python >= 3.11 (sviluppo su 3.13), uv, hatchling, beancount 3.2.3, beanquery 0.2.0, mcp 2.3.0, ruff, mypy strict, pytest (rimandato).

**Spec:** `spec.md`

## Global Constraints

- Il ledger non va mai corrotto: `init` crea solo file nuovi e rifiuta di sovrascrivere file non vuoti.
- Percorso predefinito: `~/.beancount-mcp/ledger/main.bean`.
- Variabile d'ambiente per il ledger: `BEANCOUNT_MCP_LEDGER`.
- Nome pacchetto: `beancount-mcp`; modulo: `beancount_mcp`; comando: `beancount-mcp`.
- Versione minima Python: 3.11.
- Versioni esatte: `beancount==3.2.3`, `beanquery==0.2.0`, `mcp==2.3.0`.
- MCP SDK v2 usa `MCPServer`, non `FastMCP`.
- Trasporto predefinito: `stdio`.
- Test automatici rimandati su richiesta esplicita dell'utente; la verifica di questo incremento è manuale e riproducibile. La deviazione va annotata in `docs/decisions.md`.

## Review Focus

- `init` su file principale o inbox non vuoti: deve rifiutare e lasciare entrambi i file byte per byte invariati.
- `init` su file esistenti ma vuoti: deve poter completare, senza seguire symlink.
- Percorso predefinito senza `init` precedente: il server deve terminare con un messaggio che spiega le due strade (`init` o ledger esplicito).
- Valuta non valida o con spazi: deve produrre un errore chiaro, non un ledger malformato.
- Scrittura parziale: un errore durante la creazione non deve lasciare un ledger principale non valido.

---

### Task 1: Scheletro del repository e dipendenze

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `src/beancount_mcp/__init__.py`
- Create: `src/beancount_mcp/__main__.py`
- Modify: `README.md`
- Commit: `spec.md`

**Interfaces:**
- Consumes: nulla.
- Produces: pacchetto importabile `beancount_mcp` con `__version__ = "0.1.0"`; comando `beancount-mcp` registrato (implementato nel Task 4).

- [ ] **Step 1: Committare specifica e piano**

```bash
git add spec.md docs/superpowers/plans/2026-10-25-bootstrap-and-init.md
git commit -m "docs: add project specification and bootstrap plan"
```

- [ ] **Step 2: Creare `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "beancount-mcp"
version = "0.1.0"
description = "MCP server for querying and safely editing Beancount ledgers"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "beancount==3.2.3",
  "beanquery==0.2.0",
  "mcp==2.3.0",
]

[project.scripts]
beancount-mcp = "beancount_mcp.cli:main"

[dependency-groups]
dev = [
  "pytest>=8",
  "ruff>=0.14",
  "mypy>=1.18",
]

[tool.hatch.build.targets.wheel]
packages = ["src/beancount_mcp"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
strict = true
python_version = "3.11"
mypy_path = "src"

[[tool.mypy.overrides]]
module = ["beancount.*", "beanquery.*"]
ignore_missing_imports = true
```

- [ ] **Step 3: Creare `.python-version` e `.gitignore`**

`.python-version`:

```text
3.13
```

`.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/
*.egg-info/
.coverage
```

- [ ] **Step 4: Creare il pacchetto minimo**

`src/beancount_mcp/__init__.py`:

```python
"""MCP server for Beancount ledgers."""

__version__ = "0.1.0"
```

`src/beancount_mcp/__main__.py`:

```python
"""Allow running the package with ``python -m beancount_mcp``."""

from beancount_mcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Sincronizzare l'ambiente e verificare l'import**

Run:

```bash
uv sync
uv run python -c "import beancount_mcp; print(beancount_mcp.__version__)"
```

Expected: `uv sync` completa e stampa `0.1.0`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore src/beancount_mcp/__init__.py src/beancount_mcp/__main__.py
git commit -m "chore(M0): bootstrap Python package and dependencies"
```

---

### Task 2: Risoluzione del percorso del ledger

**Files:**
- Create: `src/beancount_mcp/config.py`

**Interfaces:**
- Consumes: `Path`, `os.environ`.
- Produces:
  - `DEFAULT_LEDGER_PATH: Path`
  - `ENV_LEDGER: str` con valore `"BEANCOUNT_MCP_LEDGER"`
  - `default_ledger_path() -> Path`
  - `resolve_ledger_path(explicit: str | None, env: Mapping[str, str] | None = None) -> Path`

- [ ] **Step 1: Implementare `config.py`**

Comportamento richiesto:

1. `default_ledger_path()` restituisce `Path.home() / ".beancount-mcp" / "ledger" / "main.bean"`, calcolato a ogni chiamata (non a import time).
2. `resolve_ledger_path` usa, nell'ordine: argomento esplicito non vuoto, variabile `BEANCOUNT_MCP_LEDGER` non vuota, percorso predefinito.
3. Il risultato è assoluto, con `~` espanso e `..` normalizzato, **senza** risolvere symlink (`os.path.abspath`, non `Path.resolve`).

```python
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_LEDGER_PATH = Path("~/.beancount-mcp/ledger/main.bean")
ENV_LEDGER = "BEANCOUNT_MCP_LEDGER"


def default_ledger_path() -> Path:
    """Return the default ledger path."""
    return Path(os.path.abspath(os.path.expanduser(DEFAULT_LEDGER_PATH)))


def resolve_ledger_path(
    explicit: str | None, env: Mapping[str, str] | None = None
) -> Path:
    """Resolve the ledger path from CLI, environment, or default."""
    environ = os.environ if env is None else env
    value = explicit or environ.get(ENV_LEDGER) or str(default_ledger_path())
    return Path(os.path.abspath(os.path.expanduser(value)))
```

- [ ] **Step 2: Verificare i tre percorsi di risoluzione**

Run:

```bash
uv run python - <<'PY'
import os
from beancount_mcp.config import resolve_ledger_path

print(resolve_ledger_path("/tmp/esplicito.bean", {"BEANCOUNT_MCP_LEDGER": "/tmp/env.bean"}))
print(resolve_ledger_path(None, {"BEANCOUNT_MCP_LEDGER": "/tmp/env.bean"}))
print(resolve_ledger_path(None, {}))
PY
```

Expected: `/tmp/esplicito.bean`, `/tmp/env.bean`, `/home/<utente>/.beancount-mcp/ledger/main.bean`.

- [ ] **Step 3: Commit**

```bash
git add src/beancount_mcp/config.py
git commit -m "feat(M1): resolve ledger path from CLI, env, and default"
```

---

### Task 3: Creazione atomica del ledger (`init`)

**Files:**
- Create: `src/beancount_mcp/init.py`

**Interfaces:**
- Consumes: `Path`, `date`.
- Produces:
  - `class InitError(Exception)`
  - `@dataclass(frozen=True, slots=True) class InitResult` con campi `ledger_path: Path`, `inbox_path: Path`, `currency: str`, `opening_date: date`
  - `render_main_ledger(currency: str, opening_date: date) -> str`
  - `create_ledger(ledger_path: Path, currency: str, *, today: date | None = None) -> InitResult`

- [ ] **Step 1: Implementare `render_main_ledger`**

Contenuto esatto, con valuta e data interpolate e newline finale:

```beancount
option "title" "Beancount MCP Ledger"
option "operating_currency" "EUR"

include "inbox.bean"

2026-10-25 open Equity:Opening-Balances
```

La data usa il formato ISO (`YYYY-MM-DD`).

- [ ] **Step 2: Implementare `create_ledger`**

Comportamento richiesto:

1. Normalizzare la valuta con `strip().upper()` e validarla con
   `re.fullmatch(r"[A-Z][A-Z0-9'._-]{0,22}[A-Z0-9]", currency)`. Se non valida,
   sollevare `InitError` con messaggio che mostra il valore ricevuto.
2. Calcolare `inbox_path = ledger_path.parent / "inbox.bean"`.
3. Rifiutare con `InitError` se `ledger_path` o `inbox_path` sono symlink, non sono
   file regolari, o esistono con dimensione maggiore di zero. Il messaggio deve
   indicare il percorso colpevole e che nessun file è stato modificato.
4. Creare la directory padre con `mkdir(parents=True, exist_ok=True)`.
5. Scrivere prima l'inbox vuota, poi il file principale, entrambi in UTF-8 e con
   `newline="\n"`. Se la scrittura del file principale fallisce e l'inbox era stata
   creata da questa chiamata, rimuoverla prima di propagare l'errore.
6. Se `today` è `None`, usare `date.today()`.
7. Restituire `InitResult`.

- [ ] **Step 3: Verificare creazione e rifiuto in directory temporanee**

Run:

```bash
uv run python - <<'PY'
import tempfile
from datetime import date
from pathlib import Path
from beancount_mcp.init import InitError, create_ledger

with tempfile.TemporaryDirectory() as tmp:
    ledger = Path(tmp) / "main.bean"
    result = create_ledger(ledger, "eur", today=date(2026, 10, 25))
    print(result)
    print(ledger.read_text())
    print(repr((Path(tmp) / "inbox.bean").read_text()))
    try:
        create_ledger(ledger, "EUR")
    except InitError as exc:
        print("RIFIUTATO:", exc)
PY
```

Expected: il ledger contiene titolo, `operating_currency "EUR"`, `include "inbox.bean"` e `2026-10-25 open Equity:Opening-Balances`; l'inbox è vuota; il secondo tentativo è rifiutato e i file restano invariati.

- [ ] **Step 4: Commit**

```bash
git add src/beancount_mcp/init.py
git commit -m "feat(M1): create new Beancount ledger without overwriting files"
```

---

### Task 4: CLI `init` e server minimo

**Files:**
- Create: `src/beancount_mcp/cli.py`
- Create: `src/beancount_mcp/server.py`

**Interfaces:**
- Consumes: `resolve_ledger_path`, `create_ledger`, `InitError`, `InitResult`, `mcp.server.MCPServer`.
- Produces:
  - `main(argv: Sequence[str] | None = None) -> int`
  - `server.create_server() -> MCPServer`
  - `server.run() -> None`

- [ ] **Step 1: Implementare `server.py` minimo**

```python
from __future__ import annotations

from mcp.server import MCPServer


def create_server() -> MCPServer:
    """Create the MCP server. Tools are registered in later milestones."""
    return MCPServer("beancount-mcp")


def run() -> None:
    """Run the MCP server over stdio."""
    create_server().run()
```

- [ ] **Step 2: Implementare `cli.py`**

Comportamento richiesto:

1. `main` ispeziona `argv` (default `sys.argv[1:]`). Se il primo elemento è `init`,
   usa il parser di `init`; altrimenti usa il parser del server.
2. Parser `init`: argomento posizionale opzionale `path`; opzione obbligatoria
   `--currency`.
3. `init` risolve il percorso con `resolve_ledger_path(path)`. Se `path` è `None`,
   usa la variabile d'ambiente o il percorso predefinito.
4. Successo: stampa i due percorsi creati e la valuta, poi restituisce `0`.
5. `InitError`: stampa `Errore: <messaggio>` su `stderr` e restituisce `1`.
6. Parser server: argomento posizionale opzionale `ledger`. Risolve il percorso con
   `resolve_ledger_path(ledger)`. Se il file non esiste, stampa su `stderr` le due
   strade (creare con `beancount-mcp init --currency EUR` oppure indicare un ledger
   esistente) e restituisce `2`. Altrimenti chiama `server.run()` e restituisce `0`.

- [ ] **Step 3: Verificare `init` esplicito**

Run:

```bash
TMPDIR_TEST="$(mktemp -d)"
uv run beancount-mcp init "$TMPDIR_TEST/main.bean" --currency EUR
cat "$TMPDIR_TEST/main.bean"
uv run beancount-mcp init "$TMPDIR_TEST/main.bean" --currency EUR
echo "exit=$?"
```

Expected: il primo comando crea i file e stampa i percorsi; il secondo stampa un errore e termina con `exit=1` senza modificare i file.

- [ ] **Step 4: Verificare `init` sul percorso predefinito e il messaggio di ledger mancante**

Run:

```bash
uv run beancount-mcp init --currency EUR
ls -l ~/.beancount-mcp/ledger/
BEANCOUNT_MCP_LEDGER=/tmp/ledger-che-non-esiste.bean uv run beancount-mcp
echo "exit=$?"
```

Expected: `init` crea `main.bean` e `inbox.bean` nel percorso predefinito; il server termina con `exit=2` e un messaggio che rimanda a `init`.

- [ ] **Step 5: Commit**

```bash
git add src/beancount_mcp/cli.py src/beancount_mcp/server.py
git commit -m "feat(M1): add init command and minimal stdio server"
```

---

### Task 5: Documentazione e decisioni

**Files:**
- Create: `docs/decisions.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: documentazione utilizzabile da un nuovo contributore. CI esplicitamente rimandata.

- [ ] **Step 1: Scrivere `docs/decisions.md`**

Deve contenere, con data 2026-10-25:

1. Versioni scelte: Beancount 3.2.3, beanquery 0.2.0, MCP Python SDK 2.3.0.
2. Motivazione: Beancount v3 è la major corrente; beanquery è pacchetto separato; MCP SDK v2 è la versione corrente.
3. Nota API: in MCP SDK v2 `FastMCP` è rinominato `MCPServer`; la specifica cita `FastMCP`.
4. Python minimo 3.11, sviluppo su 3.13.
5. Build backend hatchling; CLI con `argparse`.
6. `init` richiede `--currency`; il titolo predefinito è `"Beancount MCP Ledger"`; la direttiva `open` usa la data odierna e non vincola valute.
7. `init` rifiuta symlink e file non vuoti; un file esistente vuoto è accettato.
8. Test automatici rimandati su richiesta esplicita dell'utente; la specifica prevede TDD e questa deviazione va recuperata prima della chiusura di M1.
9. CI rimandata su richiesta esplicita dell'utente; la specifica la prevede in M0 e va aggiunta prima della chiusura della milestone.

- [ ] **Step 2: Aggiornare `README.md`**

Includere: descrizione breve, prerequisito `uv`, `uv sync`, esempio `uv run beancount-mcp init /percorso/main.bean --currency EUR`, avvio con `uv run beancount-mcp /percorso/main.bean`, nota su `BEANCOUNT_MCP_LEDGER` e sul percorso predefinito, rimando a `spec.md` e `docs/decisions.md`.

- [ ] **Step 3: Verificare lint, formattazione e tipi**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Expected: tutti i comandi terminano con exit code `0`.

- [ ] **Step 4: Commit**

```bash
git add docs/decisions.md README.md
git commit -m "docs(M0): record technical decisions and usage"
```

---

## Verifica finale dell'incremento

- [ ] `uv run beancount-mcp init /tmp/prova/main.bean --currency EUR` crea entrambi i file.
- [ ] Un secondo `init` sullo stesso percorso fallisce senza modificare nulla.
- [ ] `uv run beancount-mcp /tmp/prova/main.bean` avvia il server MCP su stdio (senza tool).
- [ ] `uv run beancount-mcp` senza ledger predefinito termina con un messaggio che rimanda a `init`.
- [ ] `uv run ruff check .`, `uv run ruff format --check .` e `uv run mypy src` passano.
- [ ] `docs/decisions.md` contiene versioni, scelte e deviazione sui test.
