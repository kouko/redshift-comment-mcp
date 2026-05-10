---
name: redshift-grep-columns
description: >-
  Cross-table column search — finds every column whose name or comment
  matches a keyword across all tables in one (or all) schemas via one
  schema-wide MCP call per schema. Use when user wants to find FK /
  shared-key columns across many tables (e.g. before composing a JOIN),
  or to audit column-naming consistency. Do NOT use for a single known
  table (use search_columns directly), single-column lookup (use
  get_column_comment), or table-name search (use /redshift-grep-tables).
  Triggers: /redshift-grep-columns / find column / search columns
  across tables / where is foo column / 跨表找欄位 / 哪些表有 foo /
  カラム横断検索 / カラム名検索.
---

# Redshift Cross-Table Column Grep

Find every column whose name or comment matches a keyword across all
tables in one or all schemas. Single MCP call per schema via
`search_columns(table_name=None)`.

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
| `<kw1> <kw2>` | space-separated keywords (OR logic on MCP side) |
| `--max-list N` | results per page (default 50) |

## Flow

### Step 1 — schema-wide search via MCP

The MCP server's `search_columns` accepts an optional `table_name`;
omit it for **schema-wide column search in one call**:

```
search_columns(keywords, schema_name=<schema>, table_name=None)
```

This returns one row per matching column with `table_name` included,
ranked by `hit_count` across name + comment. Paginate via `has_more`
if total > 50.

Procedure:
- If `--schema` given: one call per listed schema.
- Else: `list_schemas(include_comments=true)` → enumerate user schemas;
  one `search_columns` per schema (schema-wide each).
- Aggregate.

Latency: ~0.7s per schema-wide call (12K-column schemas). For clusters
with many schemas, prompt user to scope via `--schema` before running.

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

- NEVER orchestrate `search_tables` + per-table `search_columns` — use `search_columns(keywords, schema_name, table_name=None)` for one-shot schema-wide search. The orchestration approach is ~27x slower.
- NEVER strip the `<schema>.<table>` prefix when rendering — same column name across tables IS the value of cross-table grep.
- NEVER iterate every schema without a keyword scope — for clusters with > 5 schemas this multiplies leader-node load. Prompt user to scope first.

## Errors
| Condition | Behavior |
|---|---|
| Empty keyword | refuse with usage hint |
| `--schema` doesn't exist | fail with the schema name + suggestion to check spelling |
| MCP returns 0 hits everywhere | "No matches; broaden keyword?" |

## See also

| Need | Use |
|---|---|
| Search tables by name/comment across schemas | `/redshift-grep-tables` |
| Browse interactively from zero context | `/redshift-explore` |
| Profile a column's values once located | `/redshift-profile` |
