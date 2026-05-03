---
name: redshift-explore
description: >-
  Three-step interactive wizard for exploring a Redshift cluster from
  zero context: schema → table → column, each step listing candidates
  with comments so the user picks by reading, not by remembering names.
  Hands off to /redshift-profile on the chosen column. Makes the implementation_guide.md "Guided Data Discovery"
  charter explicit. Use when user invokes /redshift-explore, or says:
  "I don't know where to start", "explore the warehouse", "browse
  Redshift", "where do I look", "找一下這個 cluster", "我不知道要看
  哪個 table", "從哪開始", "guide me through", "走一遍 schema",
  "Redshift を探検", "どのテーブルか分からない", "探したい",
  "ガイド付き探索". Do NOT use when user already knows the table.column
  (use /redshift-profile directly), in
  non-interactive contexts (wizard requires human picks), for
  schema-wide reporting (use /redshift-cache-schema), or batch
  question answering (intentionally conversational).
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

### Step 1 — pick a schema

`list_schemas(include_comments=true)` → MCP returns
`{schemas: [{name, comment}]}`. Render numbered list, comment-first:
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

`list_tables(schema_name, include_comments=true)` → MCP returns
`{tables: [{name, type, comment}]}`. Same render shape. Keyword
fallback: `search_tables(keywords, schema_name)`. Page through
`--max-list` at a time if > 50 tables; show "1-10 of 47, reply 'more'".

### Step 3 — pick a column

`list_columns(schema_name, table_name, include_comments=true)` → MCP
returns `{columns: [{name, type, nullable, comment}]}`. Render with
PK-shaped columns first (heuristic: name = `id` or `<table>_id`), then
commented columns, then rest:
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

## Errors
| Condition | Behavior |
|---|---|
| list_schemas empty | `cluster_appears_empty: check connection profile` |
| Picked schema has no tables | "Pick another or run /redshift-cache-schema --scope <s>" |
| Picked table has no columns | `_error: no_columns` (likely permission) |
| Reply matches no candidate / keyword | re-render with hint |
| User says cancel / quit | exit cleanly, no error |
