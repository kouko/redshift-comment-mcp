# redshift_comment_mcp

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

The Python source for the `redshift-comment-mcp` MCP server. The
package exposes 11 read-only tools to a Claude (or any MCP-aware)
client: schema / table / column listing, hit-count keyword search,
comment retrieval, and SELECT-only SQL execution. Everything is
read-only by design — `execute_sql` rejects DDL / DML keywords at
the parse layer.

## Module map

| File | Role |
|---|---|
| [`server.py`](server.py) | Process entry point. Routes between the MCP server (default) and the setup CLI subcommands (`setup`, `set-password`, `test-connection`, etc.). |
| [`redshift_tools.py`](redshift_tools.py) | The 11 MCP tools (`list_schemas` / `list_tables` / `list_columns` / `search_*` / `get_*_comment` / `get_all_column_comments` / `execute_sql`). Every tool has explicit pagination, `WARNING` strings nudging the LLM to read comments, and tight identifier validation. |
| [`config.py`](config.py) | Profile storage. Non-secret fields live in `~/.config/redshift-comment-mcp/config.toml` (XDG Base Directory); passwords go to the OS keychain via the `keyring` library. Multiple profiles supported. |
| [`connection.py`](connection.py) | Per-use connection pattern (`@contextmanager`) — opens a fresh Redshift connection per tool call, closes immediately. No long-lived pool, deliberately. |
| [`setup_cli.py`](setup_cli.py) | Interactive Q&A CLI for the subcommands above. Passwords collected via `getpass` so they never enter shell history. |
| [`__init__.py`](__init__.py) | Empty — the package surface is whatever `server.py` registers. |

## Charter

Everything here serves **Guided Data Discovery**. Concretely:

- **Comments are first-class.** Every list / search tool eagerly
  returns comments when asked. Names lie; comments are the closest
  thing to semantic ground truth.
- **No mutations.** `execute_sql` only accepts statements starting
  with `SELECT` or `WITH`, and rejects `INSERT` / `UPDATE` / `DELETE`
  / `DROP` / `CREATE` / `ALTER` / `TRUNCATE` via word-boundary regex.
  This is enforced at the server boundary; skills in `skills/` rely
  on it.
- **Per-use connections.** The MCP server doesn't pool connections.
  Each tool call opens, runs, closes. Rationale: simpler error
  recovery, no stale-cursor surprises, and the tool overhead is
  small relative to actual query latency.
- **Pagination first.** Every list tool exposes `limit` / `offset`
  and auto-truncates to `DEFAULT_MAX_ITEMS` to keep responses
  bounded.

## Where things live at runtime

| Path | Contents | Permissions |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | non-secret profile fields (host / port / user / dbname) | `0600` |
| OS keychain (service `redshift-comment-mcp`, account `<profile-name>`) | passwords | OS-managed |
| `~/.cache/redshift-comment-mcp/<profile>/` | optional offline structure cache, written by the [`/redshift-cache-schema`](../../skills/redshift-cache-schema/) skill | `0700` |

## Running

```bash
# 1. Install (one-time)
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp setup

# 2. Verify
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp test-connection

# 3. Use as an MCP server (the plugin's plugin.json wires this up automatically)
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp --profile default
```

For end-user setup walk-through, see
[`skills/redshift-setup/SKILL.md`](../../skills/redshift-setup/SKILL.md).
For the design rationale (per-use connection pattern, comment-first
charter, semantic layer best practices), see
[`implementation_guide.md`](../../implementation_guide.md).

## Testing

Tests live in [`../../tests/`](../../tests/) and cover the tool
surface plus pagination math. Run via `pytest` from the repo root.
