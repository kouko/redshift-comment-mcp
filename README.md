# redshift-comment-mcp

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

A read-only **Model Context Protocol** server for Amazon Redshift,
plus a Claude Code plugin with 5 slash-command skills built on top.
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
  markdown, no stale tracking. (Cache is rebuildable; that's
  different.) Persistence belongs in a separate plugin.

See [`implementation_guide.md`](implementation_guide.md) §1.2 for the
full charter.

## What you get

### MCP tools (11, defined in [`src/redshift_comment_mcp/`](src/redshift_comment_mcp/))

| Group | Tools |
|---|---|
| List | `list_schemas` · `list_tables` · `list_columns` |
| Search (hit-count ranked) | `search_schemas` · `search_tables` · `search_columns` |
| Comment retrieval | `get_schema_comment` · `get_table_comment` · `get_column_comment` · `get_all_column_comments` |
| Query | `execute_sql` (SELECT / WITH only) |

Pagination on every list / search; explicit `WARNING` strings nudging
the LLM to read comments before trusting names.

### Slash-command skills (5, defined in [`skills/`](skills/))

| Skill | One-liner | Since |
|---|---|---|
| [/redshift-setup](skills/redshift-setup/) | Conversational walk-through to configure a connection profile. | v0.2.0 |
| [/redshift-profile](skills/redshift-profile/) | Profile a column: cardinality / top-N / null rate / min-max / existing comment, one round. | v0.3.0 |
| [/redshift-cache-schema](skills/redshift-cache-schema/) | LLM-internal cache: dumps cluster structure to local files for faster metadata lookups in subsequent skill invocations. | v0.3.0 |
| [/redshift-explore](skills/redshift-explore/) | Three-step interactive wizard (schema → table → column) — pick by reading comments. | v0.3.0 |
| [/redshift-lineage-from-stl](skills/redshift-lineage-from-stl/) | Mine `STL_QUERY` + sqlglot to reconstruct **actual** table-to-table lineage from query history. | v0.3.0 |

Each skill has its own tri-lingual README inside its folder.

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
Run `/redshift-setup` again with a different profile name.

For Claude Desktop / other MCP clients / local development, see
[`docs/install.md`](docs/install.md) (or scroll down to **Other install
paths**).

## Other install paths

| Scenario | How |
|---|---|
| Claude Code (recommended) | `claude plugin install redshift-comment-mcp` (above) |
| Claude Desktop / generic MCP client | `pip install redshift-comment-mcp` then point your client at `uvx redshift-comment-mcp --profile default` |
| Local development | `git clone … && pip install -e ".[dev]"` then `python -m redshift_comment_mcp.server --profile default` |
| Multi-cluster | One profile per cluster: `redshift-comment-mcp setup --profile prod` |

The plugin runs from the cloned repo source via
`uv run --project ${CLAUDE_PLUGIN_ROOT}` — PyPI release is NOT a
prerequisite for plugin updates.

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
| OS keychain (`redshift-comment-mcp` / `<profile>`) | Passwords | OS-managed |
| `~/.cache/redshift-comment-mcp/<profile>/` | Optional offline structure cache (written by `/redshift-cache-schema`) | `0700` |

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
- `/redshift-cache-schema` writes per-table `.md` files that consumers
  Read directly via the Read tool, bypassing the MCP response path
  entirely. Once primed, metadata lookups are not size-bound.

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
pytest tests/                    # run tests
python -m build                  # build sdist + wheel
```

CI / release flow lives in [`.github/`](.github/).

## License

[MIT](LICENSE)

## Contributing

Issues and pull requests welcome. New skills should follow the
patterns documented in [`skills/README.md`](skills/README.md):
read-only, MCP-composed, no direct DB connections, no synthesis
layer. SKILL.md ≤ 130 lines, tri-lingual README, audited via
`dev-workflow:skill-judge` before commit.
