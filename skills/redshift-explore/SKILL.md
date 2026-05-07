---
name: redshift-explore
description: >-
  Interactive walkthrough for an unfamiliar Redshift cluster — schema
  → table → column, picked by reading comments. Hands off to
  /redshift-profile. Use when user doesn't know where to start in a
  cluster. Do NOT use when user already knows the table.column (use
  /redshift-profile directly), in non-interactive contexts, or for
  schema-wide reporting (use /redshift-cache-schema). Triggers:
  /redshift-explore / browse Redshift / where do I look / 找 cluster
  / 從哪開始 / 探検 / ガイド付き探索.
---

# Redshift Guided Explore

Three-step wizard from zero context to a concrete column. Each step
lists candidates comment-first so users read and pick.

## When to use / NOT
- Use when user is new to a cluster / schema and needs orientation.
- NOT when the answer is already known (jump direct); NOT
  non-interactive; NOT for schema-wide report.

## Inputs
| Form | Behavior |
|---|---|
| (none) | start at Step 1 |
| `<schema>` | skip to Step 2 |
| `<schema>.<table>` | skip to Step 3 |
| `--keyword <kw>` | pre-filter Step 1 via search_schemas |
| `--max-list N` | candidates per page (default 10) |

## Flow

### Step 0 — cache lookup (decide source for Steps 1-3)

Read `~/.cache/redshift-comment-mcp/<profile>/_meta.json`. If it
exists with `complete: true` and `(now - refreshed_at) < ttl_hours`,
set `cache=fresh` and source metadata in the steps below from cache:

- **Step 1** schemas → unique `schema` column of `_tables_index.tsv` (Bash `cut -f1 | sort -u`); comments from the per-table `.md` headers if needed
- **Step 2** tables in `<schema>` → `grep "^<schema>\t" _tables_index.tsv`
- **Step 3** columns in `<schema>.<table>` → Read `tables/<schema>__<table>.md` and parse `### \`colname\` (type[, NOT NULL])` blocks

Otherwise (`cache=miss`), use the live MCP calls described in each
step. On `cache=miss` from a missing / stale `_meta.json`, emit one
chat line:

```
[cache] miss / stale — fetching live; rebuild with /redshift-cache-schema --refresh.
```

For `--keyword` fallback (`search_schemas` / `search_tables` /
`search_columns`), always use live MCP — TSV indices are lossy
(first-line summary) and will under-match keyword search.

### Step 1 — pick a schema

`list_schemas(include_comments=true)` (or cache; see Step 0) →
returns `{schemas: [{name, comment}]}`. Render numbered list,
comment-first:
```
Pick a schema:
  1. dbt_marts     — Final marts layer
  2. dbt_staging   — Staging models
  3. raw_orders    — Raw event stream
  ...
Reply: number / name / keyword.
```
Ranking: pin schemas with non-empty comments to top, alphabetical;
empty-comment schemas labeled `(no comment)` below. If `--keyword`
passed, prefer `search_schemas(keywords)`. If user replies a keyword,
re-render via search_schemas. Auto-pick if cluster has only one schema.

### Step 2 — pick a table

`list_tables(schema_name, include_comments=true)` (or cache via
`grep "^<schema>\t" _tables_index.tsv`) → `{tables: [{name, type,
comment}]}`. Same render shape. Keyword fallback always uses live
`search_tables(keywords, schema_name)` (TSV summary is lossy). Page
through `--max-list` at a time if > 50 tables; show "1-10 of 47,
reply 'more'".

### Step 3 — pick a column

`list_columns(schema_name, table_name, include_comments=true)` (or
cache via Read `tables/<schema>__<table>.md` and parse the
`### \`colname\` (type[, NOT NULL])` blocks) → `{columns: [{name,
type, nullable, comment}]}`. Render with PK-shaped columns first
(heuristic: name = `id` or `<table>_id`), then commented columns,
then rest:
```
You picked dbt_marts.fct_orders. Now pick a column:
  1. order_id      bigint       — Unique order identifier (PK?)
  2. status        varchar(32)  — Order lifecycle state
  ...
```
Recognized replies: number/name → Step 4; keyword →
`search_columns(keywords, schema_name, table_name)` (both schema_name
AND table_name required — no wildcards); `back` → Step 2.

### Step 4 — handoff

```
What do you want about <S>.<T>.<col>?
  a) values / cardinality / null rate / top-N    → /redshift-profile <S>.<T> <col>
  b) just the comment (already shown above)
```
On `a`: invoke `/redshift-profile`'s flow with resolved args
(`<schema>.<table> <column>`). On `b`: emit comment + type, exit.
Custom question: answer directly using the MCP tools that fit.

## Escape hatches (every step)
- Direct identifier → skip render, jump forward.
- Keyword → re-render filtered.
- `back` → previous step.
- `cancel` / `quit` → exit cleanly.

## Output

Wizard prose IS the output. No JSON block — interactive by design.
Step 4 produces the downstream skill's output.

## Anti-patterns

- NEVER skip the comment-first render even when the user named a table — the rendering IS the value. If the answer is already known, hand off to the right sister skill instead of running the wizard.
- NEVER show > 50 candidates per step — paginate. Comment-first reading scales worse than alphabetical.
- NEVER call `search_columns` without both `schema_name` AND `table_name` — MCP rejects wildcard scope; user gets a cryptic error.
- NEVER auto-execute Step 4 option (a) without an explicit pick — handoff to `/redshift-profile` changes the workflow contract.
- NEVER strip empty-comment items — render as `(no comment)` so the user sees what to ask the data owner about.

## Errors
| Condition | Behavior |
|---|---|
| list_schemas empty | `cluster_appears_empty: check connection profile` |
| Picked schema has no tables | "Pick another or run /redshift-cache-schema --scope <s>" |
| Picked table has no columns | `_error: no_columns` (likely permission) |
| Reply matches no candidate / keyword | re-render with hint |
| User says cancel / quit | exit cleanly, no error |

## See also

| Need | Use |
|---|---|
| Profile a column once you have it | `/redshift-profile` |
| Prime / refresh the cache for faster metadata reads | `/redshift-cache-schema` |
