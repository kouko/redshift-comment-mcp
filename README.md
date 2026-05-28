# redshift-comment-mcp

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

A read-only **Model Context Protocol** server for Amazon Redshift,
plus a Claude Code plugin with 6 slash-command skills built on top.
Designed around one assertion: **column names lie, comments don't**
— so the server exposes comments aggressively and the skills compose
those tools into the discovery workflows you actually do every day.

```
"What values does dbt_marts.fct_orders.status really hold?"
   → /redshift-profile dbt_marts.fct_orders status
   → cardinality, top-N, null rate, min/max, existing comment — one round.
```

## Why this exists

If you've ever opened an unfamiliar Redshift table and squinted at
column names like `f3`, `legacy_id_v2`, or `status` (which `status`?),
you already know the pain. dbt manifests are too narrow. Web GUIs
are too slow. Hand-written SQL is too repetitive.

This plugin's charter is **Guided Data Discovery**:

- **Comments first.** Every list / search tool returns the column,
  table, or schema comment when asked — names are advisory, comments
  are authoritative.
- **Read-only by construction.** `execute_sql` rejects DDL / DML at
  the parse layer; no skill in this repo can mutate Redshift.
- **MCP-composed skills.** New workflows are built by stringing
  together existing tools, not by adding new database connections.
- **No persistence.** No synthesis layer, no `.redshift-wiki/`
  markdown, no stale tracking. Persistence belongs in a separate plugin.

See [`implementation_guide.md`](implementation_guide.md) §1.2 for the
full charter.

## What you get

### MCP tools (12, defined in [`src/redshift_comment_mcp/`](src/redshift_comment_mcp/))

| Group | Tools |
|---|---|
| List | `list_schemas` · `list_tables` · `list_columns` |
| Search (hit-count ranked) | `search_schemas` · `search_tables` · `search_columns` |
| Comment retrieval | `get_schema_comment` · `get_table_comment` · `get_column_comment` · `get_all_column_comments` |
| Query | `execute_sql` (SELECT / WITH only) |
| Setup (since v0.7.0) | `setup_via_dialog` — in-band profile bootstrap; OS-native password dialog, never crosses MCP wire |

Pagination on every list / search; explicit `WARNING` strings nudging
the LLM to read comments before trusting names.

### Slash-command skills (6, defined in [`skills/`](skills/))

| Skill | One-liner | Since |
|---|---|---|
| [/redshift-setup](skills/redshift-setup/) | Conversational walk-through to configure a connection profile. | v0.2.0 |
| [/redshift-switch-profile](skills/redshift-switch-profile/) | Switch the active profile (no host / user / password re-entry); single-profile users get a friendly bow-out. | v0.4.0 |
| [/redshift-profile](skills/redshift-profile/) | Profile a column: cardinality / top-N / null rate / min-max / existing comment, one round. | v0.3.0 |
| [/redshift-explore](skills/redshift-explore/) | Three-step interactive wizard (schema → table → column) — pick by reading comments. | v0.3.0 |
| [/redshift-lineage-from-stl](skills/redshift-lineage-from-stl/) | Mine `STL_QUERY` + sqlglot to reconstruct **actual** table-to-table lineage from query history. | v0.3.0 |
| [/redshift-grep-columns](skills/redshift-grep-columns/) | Cross-table column search by keyword across one or all schemas via schema-wide MCP call. | v0.4.0 |
| [/redshift-grep-tables](skills/redshift-grep-tables/) | Cross-schema table search by keyword across all schemas via cluster-wide MCP call. | v0.4.0 |

Each skill has its own tri-lingual README inside its folder (except
`/redshift-setup` and `/redshift-switch-profile`, which are setup-style
internals — see SKILL.md directly).

## Quick start

The fastest path is the Claude Code plugin.

```bash
# 1. Register the marketplace (one-time)
claude plugin marketplace add kouko/redshift-comment-mcp

# 2. Install the plugin
claude plugin install redshift-comment-mcp

# 3. Configure a connection profile (in a Claude Code chat)
/redshift-setup
```

`/redshift-setup` walks you through host / port / user / dbname /
password. **The password is collected in a system dialog (macOS) or a
zenity prompt (Linux desktop) or your own terminal (headless) — never
in chat.** It lands directly in your OS keychain.

After setup, just type any of the slash commands above. Multi-cluster?
Add a second profile with `/redshift-setup <name>`, then switch between
them with `/redshift-switch-profile`.

For Claude Desktop / other MCP clients / local development, scroll
down to **Other install paths**.

## Other install paths

| Scenario | How |
|---|---|
| Claude Code (recommended) | `claude plugin install redshift-comment-mcp` (above). Zero config — manifest no longer asks for a profile name; the MCP server reads the active-profile pointer file written by `/redshift-setup`. |
| Claude Desktop / generic MCP client | `pip install redshift-comment-mcp` then point your client at `uvx redshift-comment-mcp` (or `--profile <name>` to override the pointer file) |
| Local development | `git clone … && pip install -e ".[dev]"` then `python -m redshift_comment_mcp.server` |
| Multi-cluster | `/redshift-setup <name>` per cluster + `/redshift-switch-profile` to switch |

The plugin runs from the cloned repo source via
`uv run --project ${CLAUDE_PLUGIN_ROOT}` — PyPI release is NOT a
prerequisite for plugin updates.

### Setting up with `uvx` — Claude Desktop / generic MCP client

The Claude Code plugin's `uv run --project ${CLAUDE_PLUGIN_ROOT}` form
is specific to Claude Code. For any other MCP client (Claude Desktop,
generic stdio MCP clients), the equivalent launch is
`uvx redshift-comment-mcp` against the PyPI release.

**Step 1 — set up a profile via the CLI.** `redshift-comment-mcp`
ships the same Q&A flow that the Claude Code plugin's `/redshift-setup`
uses, exposed as subcommands:

```bash
# interactive Q&A — writes config.toml + stores password in OS keychain
uvx redshift-comment-mcp setup

# or a named profile (for multi-cluster setups)
uvx redshift-comment-mcp setup --profile prod

# verify
uvx redshift-comment-mcp test-connection --profile prod
uvx redshift-comment-mcp list-profiles
```

The files it writes — `~/.config/redshift-comment-mcp/config.toml` +
OS keychain entry under service `redshift-comment-mcp` — are per-user,
not per-client. Run setup once and every MCP client that launches
`uvx redshift-comment-mcp` afterwards reads the same profile data. If
you already have Claude Code with the plugin, `/redshift-setup` writes
the exact same files; no duplicate setup needed.

Other useful subcommands: `set-password`, `delete-profile`. See
`uvx redshift-comment-mcp --help`.

**For code-agent bootstrap** (any MCP client, since v0.7.0): the
preferred path is the in-band MCP tool `setup_via_dialog` — no Bash
tool, no MCP client restart, password stays out of chat:

```
agent calls any DB tool          → {"error": "not_configured", "next_step": "Call setup_via_dialog..."}
agent asks user for host/user/dbname  (these are NOT secrets)
agent calls MCP tool setup_via_dialog(host=..., user=..., dbname=...)
                                 → server-side spawns OS dialog (macOS osascript / Linux zenity)
                                 → user types password directly into dialog
                                 → server writes config.toml + keychain
                                 → {"status": "configured", ...}
agent retries the DB tool        → works (lazy resolve; no restart needed)
```

The server boots in **degraded mode** even when no profile exists —
DB tools return a structured `not_configured` error pointing at
`setup_via_dialog`, so the agent sees the recovery path in its own
tool-call result (no need to read MCP client log files). After setup,
lazy resolution picks up the new profile on the next tool call.

**Fallback for headless / non-GUI hosts** (no `osascript` / no
`zenity`): drop to the Bash + CLI path which uses `--stdin` instead of
the dialog:

```bash
uvx redshift-comment-mcp set-fields --profile default \
    --host H --port P --user U --dbname D
echo "$PASSWORD" | uvx redshift-comment-mcp set-password \
    --profile default --stdin
```

**Step 2 — single profile.** In `claude_desktop_config.json` (or your
client's equivalent):

```json
{
  "mcpServers": {
    "redshift-comment": {
      "command": "uvx",
      "args": ["redshift-comment-mcp"]
    }
  }
}
```

The server resolves which profile to use via this chain (most explicit
wins): `--profile` CLI flag > `REDSHIFT_COMMENT_PROFILE` env var >
`active-profile` pointer file > implicit fallback (lone profile rescue
/ `default`).

**Step 3 — multi-cluster.** One MCP server entry per profile, override
the pointer file via `--profile`:

```json
{
  "mcpServers": {
    "redshift-prod": {
      "command": "uvx",
      "args": ["redshift-comment-mcp", "--profile", "prod"]
    },
    "redshift-stg": {
      "command": "uvx",
      "args": ["redshift-comment-mcp", "--profile", "stg"]
    }
  }
}
```

Each entry runs as a separate MCP server; tools appear in the client
under their respective server names.

**Tip — `uv tool install` for faster startup.** `uvx` fetches and
spawns on every invocation (~2s after the first cache warmup). If
you'd rather pay the install cost once:

```bash
uv tool install redshift-comment-mcp
```

then point `"command"` at `redshift-comment-mcp` directly with no
`uvx` wrapper.

## Where things live

```
.
├── README.md / README.ja.md / README.zh-TW.md     (this file, tri-lingual)
├── implementation_guide.md                         design rationale + charter
├── src/redshift_comment_mcp/                       MCP server source — see its own README
├── skills/                                         5 slash-command skills — see its own README
├── commands/                                       plugin slash command stubs
├── tests/                                          pytest suite
├── pyproject.toml                                  packaging metadata
└── .claude-plugin/                                 plugin manifest + marketplace
```

The two READMEs to read next:

- [`skills/README.md`](skills/README.md) — overview of all 5 skills
- [`src/redshift_comment_mcp/README.md`](src/redshift_comment_mcp/README.md) — server internals, module map, charter constraints

## Data layout at runtime

| Path | Contents | Permissions |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | Non-secret profile fields | `0600` |
| `~/.config/redshift-comment-mcp/active-profile` | One-line pointer to the active profile name. **Absent ↔ server uses `default`** (canonical single-profile state — most users never see this file). | `0600` |
| OS keychain (`redshift-comment-mcp` / `<profile>`) | Passwords | OS-managed |

## Recommended DB GRANTs (defense-in-depth)

`execute_sql` blocks DDL / DML / admin keywords at the parser layer
(`DROP` / `DELETE` / `UPDATE` / `INSERT` / `ALTER` / `CREATE` /
`TRUNCATE` / `MERGE` / `GRANT` / `REVOKE` / `COPY` / `UNLOAD`), but
that's a layer-1 defense. The defense-in-depth move is to give the
plugin's connecting Redshift user **read-only privileges only**, so
even if a parser bypass is found, the database itself rejects writes:

```sql
-- Create a dedicated read-only user for the plugin
CREATE USER redshift_mcp_reader WITH PASSWORD '...';

-- Grant only what the plugin actually needs
GRANT USAGE ON SCHEMA public, dbt_marts, dbt_staging TO redshift_mcp_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, dbt_marts, dbt_staging TO redshift_mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, dbt_marts, dbt_staging
  GRANT SELECT ON TABLES TO redshift_mcp_reader;

-- Do NOT grant: INSERT / UPDATE / DELETE / TRUNCATE / DROP / CREATE / GRANT / superuser
```

For `/redshift-lineage-from-stl`, the user additionally needs
`SYSLOG ACCESS UNRESTRICTED` (or admin) to read `STL_QUERY` /
`SYS_QUERY_HISTORY`. If you're not running that skill, skip this grant.

## Known limits

**MCP response token cap (~25K tokens default)** — Claude Code silently
truncates MCP tool results above ~25,000 tokens (no error, no marker;
see [anthropics/claude-code#2638](https://github.com/anthropics/claude-code/issues/2638)).
For dbt-rich schemas where column comments are long markdown blocks, a
single `list_columns(include_comments=True)` page (50 rows) on a wide
table can approach this. Two mitigations the plugin already applies:

- `include_comments` defaults to **False** on `list_tables` /
  `list_columns` (only `list_schemas` defaults True since schema count
  is small) — agent must opt in to comment-loaded responses.
- `MAX_COMMENT_LEN=1000` caps each comment in multi-item responses
  (with `comment_truncated_count` + ellipsis marker). Single-item
  getters (`get_table_comment` / `get_column_comment`) never truncate.

If you still need to bump the cap (e.g. to fetch a heavily-documented
column set in one shot), set `MAX_MCP_OUTPUT_TOKENS=50000` in the
environment where Claude Code runs. This affects all MCP servers in
that session, not just this one.

## Comment-writing tips for your DB

The plugin shines brightest on tables whose owners invest in comments.
Concrete tips (Chinese examples — adapt to your team's language):

```sql
COMMENT ON SCHEMA   sales        IS '[用途] 線上零售銷售數據 [主要實體] 訂單, 客戶, 產品';
COMMENT ON TABLE    sales.orders IS '[實體] 訂單 [PK] order_id [FK] customer_id → customers.customer_id';
COMMENT ON COLUMN   sales.orders.revenue IS '[定義] 訂單總銷售額 [語意類型] Metric [單位] 新台幣 [計算] 未稅商品總價 + 稅 − 折扣';
```

A more thorough Semantic Layer guide is in
[`implementation_guide.md`](implementation_guide.md) Appendix A.

## Development

```bash
pytest tests/                    # run unit + invariant tests (fast, no live cluster)
REDSHIFT_INTEGRATION=1 \
  pytest tests/integration/      # opt-in: smoke-test against the active Redshift profile
python -m build                  # build sdist + wheel
```

The `tests/integration/` smoke gate exercises every MCP tool against a real
Redshift cluster — connection, list / search / get tools, pagination, the
SQL-safety guard. It skips cleanly when `REDSHIFT_INTEGRATION` is unset, when
no active profile is configured, or when the keychain entry is missing, so
default `pytest tests/` is safe in CI.

CI / release flow lives in [`.github/`](.github/).

## License

[MIT](LICENSE)

## Contributing

Issues and pull requests welcome. New skills should follow the
patterns documented in [`skills/README.md`](skills/README.md):
read-only, MCP-composed, no direct DB connections, no synthesis
layer. SKILL.md ≤ 130 lines, tri-lingual README, audited via
`dev-workflow:skill-judge` before commit.
