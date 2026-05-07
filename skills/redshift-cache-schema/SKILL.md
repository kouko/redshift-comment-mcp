---
name: redshift-cache-schema
description: >-
  LLM-side metadata cache. Dumps schema / table / column structure
  with comments to local files for use by /redshift-explore,
  /redshift-profile, and MCP CACHE PROTOCOL — read on cache hit, live
  MCP on miss. Read-only, idempotent. Use when user wants to prime /
  refresh the cache before a heavy analysis session on a stable
  schema. Do NOT use for: human-readable docs, row-data export,
  fast-mutating schemas (use --ttl 24h or skip). Triggers:
  /redshift-cache-schema / prime cache / refresh schema cache /
  快取結構 / メタデータキャッシュ.
---

# Redshift Schema Cache

Walks the Redshift catalog and writes structure as files under
`~/.cache/redshift-comment-mcp/<profile>/` for **LLM consumption** —
read back by `/redshift-explore`, `/redshift-profile`, and the MCP
server's CACHE PROTOCOL when fresh; fall back to MCP otherwise.

**Internal cache, not docs.** Files are 100% rebuildable; no human
audience; no synthesis. Format optimized for LLM grep + Read.

## When to use / NOT
- Use to prime / refresh before a heavy analysis session.
- NOT for hand-edited docs; NOT for row-data export; NOT for fast-mutating schemas (use `--ttl 24h` or skip).

## Inputs
| Form | Behavior |
|---|---|
| (none) | full cache (refused if > 50 schemas) |
| `--scope <s>[,<s>...]` | subset of schemas |
| `--tables <s>.<t>[,...]` | only listed tables |
| `--ttl <hours>` | override TTL written to `_meta.json` (default 168h = 1 week) |
| `--dry-run` | enumerate, no writes |

## Layout
```
~/.cache/redshift-comment-mcp/<profile>/
├── _meta.json                # freshness gate; consumers Read this first
├── _tables_index.tsv         # schema\ttable\tsummary  (1 line per table, lossy)
├── _columns_index.tsv        # schema\ttable\tcol\ttype\tsummary  (1 line per col)
└── tables/
    └── <schema>__<table>.md  # full markdown spec; multi-line markdown comments preserved verbatim
```

Filenames lowercased; `__` separator handles `_` in identifiers.
Identifiers in *file content* preserve original case.

## File formats

### `_meta.json` (freshness gate)
```json
{
  "profile": "ichef-prod",
  "refreshed_at": "2026-05-07T10:00:00Z",
  "ttl_hours": 168,
  "complete": true,
  "schema_count": 8,
  "table_count": 142,
  "column_count": 3041,
  "scope": ["dbt_marts", "dbt_staging"]
}
```
Consumers must check **all three**: file exists, `complete: true`, and `(now - refreshed_at) < ttl_hours`. Any miss → fall back to MCP. `complete: false` is set at run start and only flipped to `true` at the end of a successful run.

### `_tables_index.tsv` (cross-cluster table search)
```
schema	table	summary
dbt_marts	fct_orders	Central order facts table for the e-commerce funnel.
dbt_marts	dim_users	User dimension.
dbt_staging	stg_orders	Staging layer for orders, one row per raw event.
```
Header row IS present (line 1: `schema\ttable\tsummary`). `summary` rule applied to the table comment:
1. Take first line (split on `\n`)
2. Replace embedded `\t` with single space
3. Truncate to 100 chars
4. Empty / null comment → `(no comment)`

Lossy by design — agent grep this for candidates, then Read `tables/<schema>__<table>.md` for full content.

### `_columns_index.tsv` (cross-cluster column search)
```
schema	table	column	type	summary
dbt_marts	fct_orders	order_id	bigint	Unique order identifier.
dbt_marts	fct_orders	status	varchar(32)	Order lifecycle state. Possible values:
dbt_marts	fct_orders	revenue_twd	numeric(18,2)	Order revenue in TWD.
```
Same `summary` rule. Multi-line comments end with the first line truncated — the trailing `:` (as in `Possible values:`) is the natural cue for the agent to Read the per-table file for full detail.

`type` preserves Redshift native form including precision (`numeric(18,2)`, `varchar(32)`); no conversion.

### `tables/<schema>__<table>.md` (full per-table spec)
```markdown
# dbt_marts.fct_orders
refreshed: 2026-05-07T10:00:00Z

## Table comment

Central order facts table for the e-commerce funnel.

### Granularity

One row per `order_id`.

### Key relationships

- `user_id` → `dim_users.user_id`
- `product_id` → `dim_products.product_id`

## Columns (12)

### `order_id` (bigint, NOT NULL)

Unique order identifier.

### `status` (varchar(32), NOT NULL)

Order lifecycle state. Possible values:

- `active`: payment confirmed, fulfillment pending
- `cancelled`: cancelled by user or system
- `pending`: payment in progress
- `refunded`: cancelled after payment

### `revenue_twd` (numeric(18,2))

Order revenue in TWD.

**Important**: NULL when:
- order cancelled before payment
- payment in escrow

For total revenue, use `coalesce(revenue_twd, 0)`.
```

Conventions:
- Column heading is `` ### `colname` (type, nullable) `` — backticks around `colname`, parenthetical `(type[, NOT NULL])`. Pattern `^### \`` is unique to column boundaries; agents can grep on it.
- `nullable` shown only when `NO` (rendered as `, NOT NULL`); nullable columns omit it entirely.
- Empty column comment → `*(no comment)*` placeholder under the column heading. Empty table comment → `*(no table comment)*` under `## Table comment`.
- Comment markdown is **preserved verbatim** from the DB — including its own headings, lists, code spans, emphasis, links. The LLM reads raw text and disambiguates by context; no escape / safe-render needed.

## Flow

1. **Resolve profile + TTL**: profile from session config (default `default`); TTL from `--ttl` arg → fall back to existing `_meta.json.ttl_hours` → default `168`.

2. **Enumerate**: `list_schemas(include_comments=true)` → MCP returns `{schemas: [{name, comment}]}`. Filter by `--scope` / `--tables`. Validate; warn on misses, don't abort. Refuse full-cache without `--scope` if `> 50` schemas.

3. **Mark in-progress**: write `_meta.json` with `complete: false` and the new `refreshed_at`. Any consumer reading mid-run will treat the cache as stale.

4. **Walk** (read-only DB access):
   - Per scoped schema: `list_tables(schema_name, include_comments=true)` → `{tables: [{name, type, comment}]}`. Page through `has_more`.
     - **Dedupe rows by `(schema_name, name)` before iterating** — when MCP joins on `pg_description`, a single relation can appear multiple times (with vs without comment). Keep the row whose `comment` is non-null. `total_count` reflects raw join rows, not unique tables; do not use it for progress.
   - Per scoped table: `list_columns(schema_name, table_name, include_comments=true)` → `{columns: [{name, type, nullable, comment}]}`. Page through.
     - Same dedupe risk: dedupe by `(schema_name, table_name, name)`, keeping the row whose `comment` is non-null.
   - Build `tables/<schema>__<table>.md` (full spec) and append rows to `_tables_index.tsv` / `_columns_index.tsv` (lossy summary).
     - If `list_columns` returns an empty array, mark the per-table `.md` with `_error: no_columns: likely VIEW or permission` in place of the columns block (still emit the table heading + comment) and skip writing to `_columns_index.tsv`.

5. **Finalize**: rewrite `_meta.json` with `complete: true`, the refreshed timestamp, scope, and counts. Compute orphan set (filenames recorded by the prior run minus this run's filenames, intersected with current scope) and **delete** orphan files — there is no human audience for forensic logs; orphans risk misleading the agent.

   To compute orphans: read the prior `_meta.json` (if any) to get the prior run's scope. If a prior cache file falls under the **current** `--scope` / `--tables` filter and was not written this run, it's an orphan. Files outside current scope MUST be left untouched — a partial `--scope dbt_marts` re-cache must NEVER delete `dbt_staging/*`.

6. **Output to chat**:
   ```
   ✓ Cached at ~/.cache/redshift-comment-mcp/<profile>/
     8 schemas, 142 tables, 3041 columns.   TTL 168h.
     Refreshed: 2026-05-07T10:00:00Z
   ```

`--dry-run` lists filenames that would be written; no disk writes; no `_meta.json` mutation.

## Anti-patterns

- NEVER skip the `complete: false` → `complete: true` transition — partial caches must not be trusted by consumers; the flag is the only signal.
- NEVER preserve orphan files for forensics — there is no human audience; orphans are stale data that risks misleading the agent. Delete them outright.
- NEVER convert `nullable` from raw `"YES"` / `"NO"` strings to bool — keep the source-of-truth string consistent with MCP shape that downstream skills already rely on.
- NEVER cache row data — charter is structure only; a billion-row table would exhaust local disk before the user notices.
- NEVER inline the full multi-line comment into TSV indices — newlines + tabs break the format. TSV summary is lossy by design (first line, 100 chars); per-table `.md` is the source of truth for full content.
- NEVER alter the column heading pattern `` ### `colname` (type[, NOT NULL]) `` — consumers grep `^### \`` to enumerate columns; deviating breaks them.

## Errors
| Condition | Behavior |
|---|---|
| `list_schemas` empty | `_error: no_schemas_returned` — abort, do not touch `_meta.json` |
| Per-schema `list_tables` fails | record skip in chat output, continue with other schemas |
| Per-table `list_columns` fails | record skip, continue |
| Per-table `list_columns` returns 0 columns (e.g. VIEW, or insufficient privilege on a base table) | Write per-table `.md` with `_error: no_columns: likely VIEW or permission` marker in place of the columns block; still emit the table heading + comment. Do not write to `_columns_index.tsv`. |
| Filesystem write fails | `_error: write_failed: <path>: <reason>` — abort, leave `_meta.json.complete: false` so consumers know cache is broken |
| Full cache without `--scope`, > 50 schemas | `_error: scope_too_large` |

Cache dir created with `mkdir -p`, mode 700.

## See also

| Need | Use |
|---|---|
| Interactive schema walk (uses this cache when fresh, falls back to MCP) | `/redshift-explore` |
| Profile a column's values (uses this cache for column metadata) | `/redshift-profile` |
| Mine actual usage from query history | `/redshift-lineage-from-stl` |
