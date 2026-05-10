---
name: redshift-grep-tables
description: >-
  Cross-schema table search — finds every table whose name or comment
  matches a keyword across all schemas via one cluster-wide MCP call.
  Use when user is looking for a table by topic but unsure which schema
  (e.g. "where is the orders fact table"), or auditing table-naming
  consistency. Do NOT use when schema is already known (use
  search_tables directly), for column-level search (use
  /redshift-grep-columns), or for general schema browsing (use
  /redshift-explore). Triggers: /redshift-grep-tables / find table /
  search tables / which schema has / 哪個 schema 有 / 跨 schema 找表 /
  テーブル横断検索 / テーブル名検索.
---

# Redshift Cross-Schema Table Grep

Find every table whose name or comment matches a keyword across all
schemas in the cluster via one cluster-wide MCP call.

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
| `<kw1> <kw2>` | space-separated keywords (OR logic on MCP side) |
| `--max-list N` | results per page (default 50) |

## Flow

### Step 1 — cluster-wide search via MCP

The MCP server's `search_tables` accepts an optional `schema_name`;
omit it for **cluster-wide table search in one call**:

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

Latency: ~0.2s for cluster-wide searches (clusters with < 10K tables).

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

- NEVER iterate `search_tables` per schema as a substitute for the cluster-wide call. Use `search_tables(keywords, schema_name=None)` for one-shot search.
- NEVER call `list_tables` for every schema as a substitute for `search_tables`. The MCP `search_tables` already filters at the SQL layer; `list_tables` then client-side filter is wasteful round trips.
- NEVER omit the schema column in render — the whole point IS which schema has the table.

## Errors
| Condition | Behavior |
|---|---|
| Empty keyword | refuse with usage hint |
| 0 hits across all schemas | "No tables match; broaden keyword?" |
| `--schema` doesn't exist | fail with schema name + suggestion to check spelling |

## See also

| Need | Use |
|---|---|
| Cross-table column search | `/redshift-grep-columns` |
| Search columns within a known table | use MCP `search_columns(kw, schema, table)` directly |
| Browse interactively from zero context | `/redshift-explore` |
