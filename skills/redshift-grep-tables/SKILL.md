---
name: redshift-grep-tables
description: >-
  Cross-schema table search — finds every table whose name or comment
  matches a keyword, across all schemas in the cluster. Cache-first
  (~50ms via local TSV grep); live MCP fallback (one search_tables
  call per schema, slower for many-schema clusters). Use when user is
  looking for a table by topic but unsure which schema (e.g. "where
  is the orders fact table"), or auditing table-naming consistency.
  Do NOT use when schema is already known (use search_tables directly),
  for column-level search (use /redshift-grep-columns), or for general
  schema browsing (use /redshift-explore). Triggers:
  /redshift-grep-tables / find table / search tables / which schema
  has / 哪個 schema 有 / 跨 schema 找表 / テーブル横断検索 /
  テーブル名検索.
---

# Redshift Cross-Schema Table Grep

Find every table whose name or comment matches a keyword across all
schemas in the cluster. Cache-first; live MCP fallback.

## When to use / NOT
- Use to find a table by topic when schema is unknown ("where is the
  orders fact?").
- Use to audit table-naming consistency across schemas.
- NOT when schema is already known — use MCP `search_tables(kw, schema)` directly.
- NOT for column-level search — use `/redshift-grep-columns`.
- NOT for general schema browsing — use `/redshift-explore`.

## Inputs
| Form | Behavior |
|---|---|
| `<keyword>` | grep across all schemas |
| `<keyword> --schema <s1>,<s2>` | scope to listed schemas |
| `<kw1> <kw2>` | AND across keywords (both must match) |
| `--max-list N` | results per page (default 50) |

## Flow

### Step 0 — cache lookup

Read `~/.cache/redshift-comment-mcp/<profile>/_meta.json`. If the file
exists, `complete: true`, and `(now - refreshed_at) < ttl_hours`, set
`cache=fresh` and use the cache path. Otherwise emit:

```
[cache] miss / stale — falling back to live search; rebuild with /redshift-cache-schema --refresh.
```

`<profile>` resolves from `~/.config/redshift-comment-mcp/active-profile`
(default `default`).

### Step 1a — cache path (preferred)

`_tables_index.tsv` columns: `schema\ttable\tsummary`, header on line 1.

```bash
PROFILE=$(cat ~/.config/redshift-comment-mcp/active-profile 2>/dev/null || echo default)
INDEX=~/.cache/redshift-comment-mcp/$PROFILE/_tables_index.tsv

# single keyword, all schemas
grep -i -- 'KEYWORD' "$INDEX" | head -50

# multi-keyword AND
grep -i -- 'KW1' "$INDEX" | grep -i -- 'KW2' | head -50

# scoped to listed schemas
awk -F'\t' '$1 == "S1" || $1 == "S2"' "$INDEX" | grep -i -- 'KEYWORD' | head -50
```

Always pass `--` to `grep` and single-quote the keyword to neutralize
shell metacharacters in user input.

### Step 1b — live MCP path (fallback)

Used when `cache=miss/stale`. The MCP server's `search_tables` accepts an
optional `schema_name`; omit it for **cluster-wide table search in one call**:

```
search_tables(keywords, schema_name=None)
```

This returns one row per matching table with `schema_name` included,
ordered by `(schema_name, table_name)`. Paginate via `has_more` if
total > 50.

Procedure:
- If `--schema <s1>,<s2>` given: one `search_tables` per listed schema
  (cheap — typically a handful).
- Else: one `search_tables(keywords, schema_name=None)` covers the
  whole cluster.
- Aggregate.

Latency on the live path is ~0.2s for cluster-wide searches (cluster has
<10K tables). Compare to cache path (~50ms via local TSV grep) — the live
fallback is ~4x slower than cache-hit but vastly faster than the legacy
N-call-per-schema approach.

Still emit the cache hint so user knows to prime for next time.

### Step 2 — render

Group by schema, count per schema in header line, comment-first body.
One blank line between groups:

```
Tables matching "fct" (8 hits in 4 schemas):

dbt_marts (3)
  fct_orders          BASE TABLE   Central order facts.
  fct_returns         BASE TABLE   Return events.
  fct_payments        BASE TABLE   Payment events.

dbt_staging (2)
  stg_fct_orders      BASE TABLE   Staging for fct_orders.
  stg_fct_returns     BASE TABLE   Staging for fct_returns.

raw_events (2)
  fct_event_log       BASE TABLE   Raw event ingest.
  fct_session_log     BASE TABLE   Session tracking.

reporting (1)
  v_fct_orders_daily  VIEW         Daily aggregation of fct_orders.
```

Cap at 50 results per page; show `1-50 of 87, reply 'more'` when truncated.

## Output

Rendered list IS the output. No JSON. Hand off to user to pick a target.
If the user wants to drill into a chosen table, suggest
`/redshift-explore <schema>.<table>`.

## Anti-patterns

- NEVER iterate `search_tables` per schema as the live fallback — use `search_tables(keywords, schema_name=None)` for one-shot cluster-wide search. The legacy iteration approach was N-calls-per-schema.
- NEVER call `list_tables` for every schema as a substitute for `search_tables`. The MCP `search_tables` already filters at the SQL layer; `list_tables` then client-side filter is wasteful round trips.
- NEVER omit the schema column in render — the whole point IS which schema has the table.
- NEVER skip cache check — cache path is ~4x faster than even the optimized live path, and has zero leader-node load.
- NEVER use `grep` without `--` and single-quoted keyword — user keywords with leading `-` or shell metacharacters will misbehave.

## Errors
| Condition | Behavior |
|---|---|
| Empty keyword | refuse with usage hint |
| Cache miss + > 10 schemas | emit hint, ask user to confirm before proceeding live |
| 0 hits across all schemas | "No tables match; broaden keyword?" |
| `--schema` doesn't exist | fail with schema name + suggestion to check spelling |
| Cache file unreadable | fall through to live path with a one-line warning |

## See also

| Need | Use |
|---|---|
| Cross-table column search | `/redshift-grep-columns` |
| Search columns within a known table | use MCP `search_columns(kw, schema, table)` directly |
| Browse interactively from zero context | `/redshift-explore` |
| Prime the cache | `/redshift-cache-schema` |
