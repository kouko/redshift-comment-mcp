---
name: redshift-grep-columns
description: >-
  Cross-table column search — finds every column whose name or comment
  matches a keyword across all tables in one (or all) schemas.
  Cache-first (~50ms via local TSV grep); falls back to live MCP when
  cache is stale or absent. Use when user wants to find FK / shared-key
  columns across many tables (e.g. before composing a JOIN), or to
  audit column-naming consistency. Do NOT use for a single known table
  (use search_columns directly), single-column lookup (use
  get_column_comment), or table-name search (use /redshift-grep-tables).
  Triggers: /redshift-grep-columns / find column / search columns
  across tables / where is foo column / 跨表找欄位 / 哪些表有 foo /
  カラム横断検索 / カラム名検索.
---

# Redshift Cross-Table Column Grep

Find every column whose name or comment matches a keyword across all
tables in one or all schemas. Cache-first; live MCP fallback.

## When to use / NOT
- Use to find FK / shared-key columns across many tables (typical
  pre-JOIN reconnaissance).
- Use to audit naming consistency ("are we calling this `customer_id`
  or `cust_no`?").
- NOT for a single known table — use MCP `search_columns(kw, schema, table)` directly.
- NOT for single-column lookup — use MCP `get_column_comment`.
- NOT for table-name search — use `/redshift-grep-tables`.

## Inputs
| Form | Behavior |
|---|---|
| `<keyword>` | grep across all schemas in the cluster |
| `<keyword> --schema <name>` | scope to one schema |
| `<keyword> --schema <s1>,<s2>` | scope to listed schemas |
| `<kw1> <kw2>` | AND across keywords (both must match) |
| `--max-list N` | results per page (default 50) |

## Flow

### Step 0 — cache lookup

Read `~/.cache/redshift-comment-mcp/<profile>/_meta.json`. If the file
exists, `complete: true`, and `(now - refreshed_at) < ttl_hours`, set
`cache=fresh` and use the cache path below. Otherwise emit one chat line:

```
[cache] miss / stale — falling back to live search; rebuild with /redshift-cache-schema --refresh.
```

`<profile>` resolves from `~/.config/redshift-comment-mcp/active-profile`
(default `default`).

### Step 1a — cache path (preferred)

`_columns_index.tsv` columns: `schema\ttable\tcolumn\ttype\tsummary`,
header on line 1.

```bash
PROFILE=$(cat ~/.config/redshift-comment-mcp/active-profile 2>/dev/null || echo default)
INDEX=~/.cache/redshift-comment-mcp/$PROFILE/_columns_index.tsv

# single keyword, all schemas
grep -i -- 'KEYWORD' "$INDEX" | head -50

# multi-keyword AND
grep -i -- 'KW1' "$INDEX" | grep -i -- 'KW2' | head -50

# scoped to one schema
awk -F'\t' '$1 == "SCHEMA"' "$INDEX" | grep -i -- 'KEYWORD' | head -50

# scoped to multiple schemas
awk -F'\t' '$1 == "S1" || $1 == "S2"' "$INDEX" | grep -i -- 'KEYWORD' | head -50
```

Always pass `--` to `grep` and single-quote the keyword to neutralize
shell metacharacters (`-`, `*`, `$`, etc. in user input).

### Step 1b — live MCP path (fallback)

Used when `cache=miss/stale`. The MCP server's `search_columns` accepts an
optional `table_name`; omit it for **schema-wide column search in one call**:

```
search_columns(keywords, schema_name=<schema>, table_name=None)
```

This returns one row per matching column with `table_name` included, ranked
by `hit_count` across name + comment. Paginate via `has_more` if total > 50.

Procedure:
- If `--schema` given: one call per listed schema.
- Else: `list_schemas(include_comments=true)` → enumerate user schemas;
  one `search_columns` per schema (schema-wide each).
- Aggregate.

Latency on the live path is ~0.7s per schema-wide call (12K-column schemas).
Compare to the cache path (~50ms via local TSV grep) — the live fallback is
~14x slower than cache-hit but ~27x faster than the legacy approach of
orchestrating `search_tables` + per-table `search_columns` (which costs N
round trips on N matching tables, easily 19s+ on big schemas).

Still emit the cache hint so user knows to prime for next time.

### Step 2 — render

Group by `<schema>.<table>`, comment-first. One blank line between groups:

```
Matches for "customer_id" (12 hits in 3 schemas, 8 tables):

dbt_marts.fct_orders
  customer_id   bigint   Customer reference (FK to dim_users.id)

dbt_marts.fct_returns
  customer_id   bigint   Customer who initiated the return

dbt_staging.stg_users
  id            bigint   Customer's primary key
  cust_no       bigint   Legacy customer no, alias for id
```

Cap at 50 results per page; show `1-50 of 87, reply 'more'` when truncated.

## Output

Rendered list IS the output. No JSON. Hand off to user to pick a target.
If the user wants to profile one of the columns, suggest
`/redshift-profile <schema>.<table> <column>`.

## Anti-patterns

- NEVER orchestrate `search_tables` + per-table `search_columns` as the live fallback — use `search_columns(keywords, schema_name, table_name=None)` for one-shot schema-wide search. The orchestration approach is ~27x slower and the legacy code path it replaced.
- NEVER strip the `<schema>.<table>` prefix when rendering — same column name across tables IS the value of cross-table grep.
- NEVER omit the cache freshness hint — a stale cache silently lying about FK relationships is the known risk for JOIN-discovery work.
- NEVER use `grep` without `--` and single-quoted keyword — user keywords with leading `-` or shell metacharacters will misbehave.

## Errors
| Condition | Behavior |
|---|---|
| Empty keyword | refuse with usage hint |
| Cache miss + cluster has > 5 schemas | emit hint, ask user to confirm before proceeding live |
| `--schema` doesn't exist | fail with the schema name + suggestion to run `/redshift-cache-schema` or check spelling |
| Live MCP returns 0 hits everywhere | "No matches; broaden keyword?" |
| Cache file unreadable | fall through to live path with a one-line warning |

## See also

| Need | Use |
|---|---|
| Search tables by name/comment across schemas | `/redshift-grep-tables` |
| Browse interactively from zero context | `/redshift-explore` |
| Prime the cache for fast grep | `/redshift-cache-schema` |
| Profile a column's values once located | `/redshift-profile` |
