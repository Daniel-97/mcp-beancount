# beancount-mcp

An MCP server for querying and safely editing Beancount ledgers.

## Overview

`beancount-mcp` is a local [Model Context Protocol](https://modelcontextprotocol.io/)
(MCP) server that exposes a Beancount ledger to MCP-capable AI clients. It lets an
agent inspect accounts and transactions, run read-only BQL queries, validate the
ledger, and make controlled edits. The server does not run an LLM and does not
replace Beancount: the MCP client decides what to do, and the server enforces the
write rules.

It is intended for personal bookkeeping and ledger-maintenance workflows, for
example:

- asking an assistant what is in the ledger or how an account is doing;
- reconciling transactions or finding entries by payee, account, date, or tag;
- adding transactions and opening accounts through an LLM;
- renaming accounts, tags, or links across multiple included files;
- letting a model help with the ledger without giving it unrestricted access to
  the filesystem.

The server is local-first. It binds to `127.0.0.1` by default and has no built-in
authentication or TLS. Treat it as a local service and put it behind a reverse
proxy with authentication and TLS if you need to expose it.

## Safety model

Every write follows the same principles:

- **Validate before writing.** The proposed change is staged and loaded with
  Beancount; only new errors block the write. Preexisting errors are reported but
  do not prevent unrelated edits.
- **Write to the inbox by default.** Added entries and `open` directives go to the
  inbox file (`inbox.bean` next to the ledger by default). Other included files are
  read-only unless the server is started with `--allow-edit-outside-inbox`.
- **Atomic writes.** Files are written through a temporary file in the same
  directory, followed by `fsync` and `os.replace`.
- **One writer at a time.** A lock serializes writes, including across processes.
- **Version checks.** `add_transactions` can receive `expected_ledger_version` to
  refuse a write when the ledger changed after it was read.
- **Stable entry IDs.** Edits and deletes use an `entry_id` containing the file,
  starting line, and a content hash. If the entry changed in the meantime, the
  server returns `ENTRY_CHANGED` with the current text.
- **Journaled multi-file renames.** Account, tag, and link renames are applied as
  one journaled operation. If a write fails, files are restored; a pending journal
  is recovered on the next writable startup.
- **Read-only mode.** Starting with `--read-only` removes the write tools from the
  MCP server.
- **Structured errors.** Every response contains `ok`; failures include a stable
  error code, a message, details, and a concrete hint for the next attempt.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- The dependencies pinned in `pyproject.toml`: Beancount, Beanquery, and the
  official MCP Python SDK

## Installation

From a checkout of this repository:

```bash
uv sync
uv run beancount-mcp --version
```

This installs the project and its development dependencies in the local virtual
environment. The `beancount-mcp` executable is also available through
`uv run beancount-mcp`.

## Tools

The server exposes eleven tools. All responses are JSON objects with an `ok`
field; successful responses contain the data described below, and failures
contain a structured `error` object.

| Tool | Purpose |
| --- | --- |
| `ledger_info` | Inspect files, accounts, version, errors, and inbox status. |
| `query` | Run read-only BQL queries with pagination. |
| `validate` | Run full Beancount validation. |
| `find_transactions` | Find transactions and return their text and `entry_id`. |
| `add_transactions` | Append directives to the inbox. |
| `open_account` | Write an `open` directive to the inbox. |
| `edit_transaction` | Replace one directive by `entry_id`. |
| `delete_transaction` | Delete one transaction by `entry_id`. |
| `rename_account` | Rename an account across included files. |
| `rename_tag` | Rename a tag across included files. |
| `rename_link` | Rename a link across included files. |

### `ledger_info`

Takes no parameters. Returns a compact overview of the ledger:

- included files and the current ledger version;
- operating currencies;
- accounts with opening/closing dates, currencies, and open/closed status;
- first and last transaction dates and transaction count;
- preexisting error count and warnings;
- most frequent tags and links;
- inbox existence/inclusion status;
- whether the server is read-only and whether edits outside the inbox are enabled.

Call this at the start of a session. The returned `ledger_version` can be passed
to `add_transactions` as `expected_ledger_version`.

### `query`

Parameters:

- `bql` (string, required): a read-only BQL query;
- `limit` (integer, optional): maximum rows, from 1 to 1000; defaults to the
  server's `--query-limit` setting;
- `offset` (integer, optional): number of rows to skip.

Only read-only `SELECT`, `BALANCES`, and `JOURNAL` statements are accepted.
`PRINT`, `CREATE TABLE`, `INSERT`, and mutation statements are rejected.

The response contains `columns`, `rows`, `limit`, `offset`, `truncated`, and
`total_rows` when known. Amounts are returned as strings, never floating-point
numbers. Include `filename, lineno` in the query to get file and line
information.

```sql
SELECT account, SUM(position) GROUP BY account
SELECT date, payee, narration, position
WHERE account = 'Expenses:Food' ORDER BY date DESC
```

### `validate`

Takes no parameters. Runs a complete Beancount validation and returns:

- `valid`: whether the ledger has errors;
- `ledger_version`;
- `error_count`;
- the list of errors with file, line, type, and message.

Preexisting errors do not block writes; the write tools only reject changes that
introduce new errors.

### `find_transactions`

Finds transactions and returns their full Beancount text plus an `entry_id` that
can be passed to `edit_transaction` or `delete_transaction`.

All filters are optional and combined with AND:

- `payee`;
- `narration_contains` (case-insensitive substring);
- `account` (matches the account and its subaccounts);
- `date_from` and `date_to`;
- `min_amount` and `max_amount` (absolute posting amounts without currency, for
  example `"10.00"`);
- `tags` (all listed tags must match);
- `limit` (default 50).

Results are newest first. `entry_id` has the shape
`{"file": "...", "line": 42, "hash": "..."}`.

```text
find_transactions(payee="Shop")
find_transactions(narration_contains="coffee", date_from="2026-01-01")
find_transactions(account="Expenses:Food", min_amount="10.00", max_amount="50.00")
```

### `add_transactions`

Appends one or more Beancount directives to the inbox.

Parameters:

- `text` (string, required): one or more directives;
- `dry_run` (boolean, default `false`): validate and show the result without
  writing;
- `expected_ledger_version` (string, optional): refuse the write if the ledger
  version changed.

The write is atomic, serialized by a lock, and validated before and after. Only
new errors block the operation. With `dry_run=true`, the response includes the
text that would be written without modifying any file.

```text
2026-02-01 * "Bar" "Coffee"
  Expenses:Food    2.50 EUR
  Assets:Cash     -2.50 EUR
```

### `open_account`

Opens a new account by appending an `open` directive to the inbox.

Parameters:

- `account` (string, required): the full account name;
- `currencies` (array of strings, optional): allowed currencies;
- `date` (string, optional): opening date in `YYYY-MM-DD` format; defaults to
  today;
- `confirm_new` (boolean, default `false`): allow a new account whose name is
  similar to an existing open account;
- `dry_run` (boolean, default `false`).

The account name must be valid and use one of the roots configured by the ledger
(`Assets`, `Liabilities`, `Equity`, `Income`, `Expenses` by default). An existing
open account produces `ACCOUNT_EXISTS`; a similar name produces
`ACCOUNT_SIMILAR_EXISTS`.

```text
open_account("Expenses:Restaurant", ["EUR"])
open_account("Expenses:Resturant", confirm_new=true)
```

### `edit_transaction`

Replaces one ledger directive identified by an `entry_id` returned by
`find_transactions`.

Parameters:

- `entry_id` (object, required): `{file, line, hash}`;
- `new_text` (string, required): the replacement directive;
- `dry_run` (boolean, default `false`).

The operation is validated like any other write. If the entry changed after the
`entry_id` was produced, the server returns `ENTRY_CHANGED` with the current
text. By default only entries in the inbox are editable; other included files
require `--allow-edit-outside-inbox`.

### `delete_transaction`

Deletes one transaction identified by an `entry_id`.

Parameters:

- `entry_id` (object, required);
- `dry_run` (boolean, default `false`).

Only transaction directives can be deleted. `open`, `close`, `balance`, and
`pad` directives are rejected. The same inbox and path rules as
`edit_transaction` apply.

### `rename_account`

Renames an account across all included files.

Parameters:

- `account` (string, required): the old account name;
- `new_account` (string, required): the new account name;
- `include_subaccounts` (boolean, default `false`): also rename `Old:*` to
  `New:*`;
- `dry_run` (boolean, default `false`).

The tool rewrites account fields in `open`, `close`, `balance`, `pad`, `note`, and
`document` directives, as well as transaction postings. It does not modify
narrations, comments, or arbitrary text. If the target account already exists,
the operation fails with `ACCOUNT_EXISTS`.

```text
rename_account("Expenses:Food", "Expenses:Groceries")
rename_account("Assets:Broker", "Assets:ScalableCapital", include_subaccounts=true)
```

### `rename_tag`

Renames a tag in all included files.

Parameters:

- `tag` (string, required): the old tag, with or without `#`;
- `new_tag` (string, required): the new tag;
- `dry_run` (boolean, default `false`).

Tags in transaction headers and `pushtag`/`poptag` directives are updated. Tags
inside quoted narrations and comments are not modified. If the new tag already
exists, occurrences are merged.

```text
rename_tag("food", "meals")
rename_tag("#november", "#2026-11", dry_run=true)
```

### `rename_link`

Renames a link in all included files.

Parameters:

- `link` (string, required): the old link, with or without `^`;
- `new_link` (string, required): the new link;
- `dry_run` (boolean, default `false`).

Links in transaction headers are updated. Links inside quoted narrations and
comments are not modified. If the new link already exists, occurrences are
merged.

```text
rename_link("november", "2026-11")
rename_link("^old", "^new", dry_run=true)
```

### Shared write behavior

- All write and rename tools support `dry_run=true`.
- `--allow-edit-outside-inbox` is required to edit, delete, or rename entries in
  included files outside the inbox. Only files inside the ledger directory (after
  resolving symlinks) and included by the main ledger are allowed.
- Multi-file renames are journaled. If a write fails, already-written files are
  restored; a pending journal is recovered at the next writable startup.
- In read-only mode, write tools are not exposed at all.
- Successful responses contain the new `ledger_version` when the ledger changed.

### Response format

Successful response:

```json
{
  "ok": true,
  "ledger_version": "…"
}
```

Error response:

```json
{
  "ok": false,
  "error": {
    "code": "ENTRY_CHANGED",
    "message": "The entry changed after the entry_id was issued.",
    "details": [],
    "hint": "Read the transaction again and use the new entry_id."
  }
}
```

Common error codes include `SYNTAX_ERROR`, `VALIDATION_FAILED`,
`VERSION_CONFLICT`, `ENTRY_NOT_FOUND`, `ENTRY_CHANGED`,
`ENTRY_NOT_IN_INBOX`, `PATH_NOT_ALLOWED`, `ACCOUNT_EXISTS`,
`ACCOUNT_SIMILAR_EXISTS`, `QUERY_ERROR`, `READ_ONLY`, `LOCKED`, and
`INBOX_NOT_INCLUDED`.

## Running the server

### HTTP transport (default)

```bash
uv run beancount-mcp /path/to/main.bean
```

The server binds to `http://127.0.0.1:8000/mcp` and uses stateless Streamable
HTTP. It speaks the MCP `2026-07-28` revision and also serves older clients in
stateless mode. Responses use `application/json`; no SSE stream is used.

Host, port, and path are configurable:

```bash
uv run beancount-mcp \
  --host 127.0.0.1 \
  --port 8765 \
  --http-path /beancount/mcp \
  /path/to/main.bean
```

The resulting endpoint is `http://127.0.0.1:8765/beancount/mcp`.

If another local service uses port `8000`, choose another port with `--port`.
Some local model providers probe `/health` on port `8000`; those requests are
not part of MCP and may appear as harmless `404` responses. This server exposes
only the MCP endpoint, not a `/health` endpoint. Add liveness checks in your
reverse proxy or container runtime if needed.

There is no built-in authentication. Binding to a non-loopback host prints a
warning; do not expose the server directly to a network. Use a reverse proxy with
authentication and TLS instead.

### stdio transport

```bash
uv run beancount-mcp --transport stdio /path/to/main.bean
```

Use stdio when the MCP client launches the server as a child process. With
stdio, stdout is reserved for the MCP protocol and logs go to stderr.

For stdio, SIGINT and SIGTERM trigger a graceful shutdown. If a signal arrives
during a tool call, the server finishes the current operation before exiting; a
second signal forces exit. SIGSTOP cannot be intercepted, and SIGKILL is not
graceful. For HTTP, shutdown is handled by uvicorn.

### Connecting a client

The exact configuration format depends on the MCP client. A typical remote
server entry looks like this:

```json
{
  "mcpServers": {
    "beancount": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

A local stdio entry looks like this:

```json
{
  "mcpServers": {
    "beancount": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/mcp-beancount",
        "beancount-mcp",
        "--transport",
        "stdio",
        "/path/to/main.bean"
      ]
    }
  }
}
```

Adapt the shape to your client. Clients that support the modern MCP revision
should use `2026-07-28`; older clients are still served through the stateless
legacy path.

### Docker

The image is intended for local use. It runs the HTTP transport, binds to
`0.0.0.0` inside the container, and expects the ledger directory at `/ledger`
with a `main.bean` file. Docker Engine or Docker Desktop must be running before
using these commands.

Build the image:

```bash
docker build -t beancount-mcp:local .
```

Run it with a host ledger directory mounted read-write:

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -v "/absolute/path/to/ledger:/ledger" \
  -u "$(id -u):$(id -g)" \
  beancount-mcp:local
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. The `-u` mapping lets the
container write the inbox with the host user's permissions. The directory must
contain `main.bean`. The inbox is required only for write operations; for
read-only use it may be absent or not included.

Append CLI flags after the image name. For a read-only server:

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -v "/absolute/path/to/ledger:/ledger" \
  -u "$(id -u):$(id -g)" \
  beancount-mcp:local --read-only
```

To allow edits outside the inbox, append `--allow-edit-outside-inbox`. This is
an explicit opt-in and is not enabled by default.

With Docker Compose:

```bash
BEANCOUNT_LEDGER_DIR="/absolute/path/to/ledger" \
HOST_UID="$(id -u)" HOST_GID="$(id -g)" \
docker compose up --build
```

`BEANCOUNT_LEDGER_DIR` is required and must point to the directory containing
`main.bean`. `HOST_UID` and `HOST_GID` should match the host user so the
container can write the inbox.

Stop it with:

```bash
docker compose down
```

Compose publishes the port only on `127.0.0.1`; do not change it to a public
interface unless you put an authenticating reverse proxy in front of the
server. The image has no built-in authentication, TLS, or `/health` endpoint.
The image is local-only and is not published to a registry.

## CLI reference

### Server options

| Option | Default | Description |
| --- | --- | --- |
| `ledger` | `BEANCOUNT_MCP_LEDGER`, then `~/.beancount-mcp/ledger/main.bean` | Path to the main ledger file. |
| `--inbox` | `inbox.bean` | Inbox path, relative to the ledger directory unless absolute. |
| `--read-only` | `false` | Do not expose write tools. |
| `--allow-edit-outside-inbox` | `false` | Allow edit, delete, and rename in included files outside the inbox. |
| `--query-limit` | `100` | Default row limit for `query`; must be between 1 and 1000. |
| `--transport` | `http` | `http` or `stdio`. |
| `--host` | `127.0.0.1` | HTTP bind host. |
| `--port` | `8000` | HTTP bind port. |
| `--http-path` | `/mcp` | HTTP endpoint path. |
| `--version` | — | Print the version and exit. |
| `--verbose` | `false` | Log configuration, startup, tool calls, and shutdown to stderr. |

`--host`, `--port`, and `--http-path` apply only to the HTTP transport. Passing
non-default values for them with `--transport stdio` is an error.

Examples:

```bash
# Local HTTP server on a custom port
uv run beancount-mcp --port 8765 /path/to/main.bean

# Read-only HTTP server
uv run beancount-mcp --read-only /path/to/main.bean

# Allow edits outside the inbox
uv run beancount-mcp --allow-edit-outside-inbox /path/to/main.bean

# stdio for a client that launches the process
uv run beancount-mcp --transport stdio /path/to/main.bean
```

### `init` command

Create a new ledger and an empty inbox next to it:

```bash
uv run beancount-mcp init /path/to/main.bean --currency EUR
```

The main file contains the title, `operating_currency`, the `include` line for
the inbox, and an `open` directive for `Equity:Opening-Balances`. If the path is
omitted, `BEANCOUNT_MCP_LEDGER` or the default path is used:

```bash
uv run beancount-mcp init --currency EUR
```

`init` never overwrites a non-empty main file or inbox.

### Using an existing ledger

The server can only write to an inbox that is included by the main ledger. For an
existing ledger:

1. Create a file named `inbox.bean` next to the main ledger, or choose another
   path with `--inbox`.
2. Add this line to the main ledger:

```beancount
include "inbox.bean"
```

Until the inbox exists and is included, `ledger_info` reports a warning and
write tools return `INBOX_NOT_INCLUDED`.

## Testing

Install the development dependencies and run the suite:

```bash
uv sync
uv run pytest
```

Run only unit or integration tests:

```bash
uv run pytest tests/unit
uv run pytest tests/integration
```

Run with coverage:

```bash
uv run pytest --cov=beancount_mcp --cov-report=term-missing
```

Run the static checks used by the project:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

The test suite uses temporary ledger copies for write tests, so it does not
modify your own ledger.

## Current scope

Implemented:

- the eleven tools listed above;
- HTTP and stdio transports;
- `init` for creating a new ledger;
- read-only mode and inbox-scoped writes;
- atomic writes, locking, validation before/after, entry IDs, and multi-file
  rename journaling/recovery.

Not implemented yet:

- a history tool for recent file changes;
- `rename_commodity`;
- `rename_payee` / bulk narration replacement;
- `check_duplicates` and `suggest_account`;
- an MCP prompt with ledger conventions;
- CI and PyPI publication.

The server does not provide a web UI, remote storage backends, or automatic bank
statement import.

## Documentation

- Product specification: [`spec.md`](spec.md)
