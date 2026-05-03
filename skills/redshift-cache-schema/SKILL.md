---
name: redshift-cache-schema
description: >-
  Dump Redshift cluster structure (schemas / tables / columns / comments)
  as markdown under ~/.cache/redshift-comment-mcp/<profile>/ for offline
  browsing — give analysts a directory of files to read instead of
  re-issuing MCP queries every conversation. Cache (rebuildable from
  live DB), NOT wiki (no synthesis, no hand-edits). Idempotent.
  Use when user invokes /redshift-cache-schema, or says: "cache the
  schema", "dump redshift structure", "offline schema browse", "save
  metadata", "把 schema dump 下來", "離線瀏覽", "結構快取", "把 table
  抓下來放本地", "快取 metadata", "schema を キャッシュ", "メタデータを
  ローカルに", "スキーマ ダンプ", "オフライン参照". Do NOT use for:
  persistent hand-edited docs (that's a wiki — separate plugin),
  synthesis / stale-tracking (out of charter), exporting row data
  (only structure is cached), one-off questions (use list_* directly),
  clusters with hundreds of tables without --scope.
---

# Redshift Schema Cache

Walks the Redshift catalog and writes structure to
`~/.cache/redshift-comment-mcp/<profile>/` as markdown. Read-only DB
access; output is on disk for offline browsing by humans / external
tools.

**Cache, not wiki.** Files are 100% rebuildable; no hand edits assumed;
synthesis / stale tracking belongs in a separate plugin. If you're
tempted to add `# Notes` sections people will edit, stop — that's a
different product.

## When to use / NOT
- Use for offline browsing on flaky network / VPN, or onboarding handoff.
- NOT for one-off questions (just call list_*); NOT for hand-curated
  docs; NOT for clusters with > 50 schemas without `--scope`.

## Inputs
| Form | Behavior |
|---|---|
| (none) | full cache (refused if > 50 schemas) |
| `--scope <s>[,<s>...]` | subset of schemas |
| `--tables <s>.<t>[,...]` | only listed tables |
| `--dry-run` | enumerate, no writes |

## Flow

1. **Resolve profile name**: from session config, default `default`.
2. **Enumerate**: `list_schemas(include_comments=true)` → MCP returns
   `{schemas: [{name, comment}]}`. Filter by `--scope`/`--tables`.
   Validate; warn on misses, don't abort. Refuse full-cache if > 50.
3. **Walk**: for each in-scope schema:
   - `list_tables(schema_name, include_comments=true)` → returns
     `{tables: [{name, type, comment}]}`. Page through if `has_more`.
   - Write `schemas/<schema>.md`.
   - For each in-scope table: `list_columns(...,include_comments=true)`
     → `{columns: [{name, type, nullable, comment}]}`. Write
     `tables/<schema>__<table>.md`.
4. **Index + meta**: regenerate `index.md` (TOC) + `_meta.json`
   (`{schema_count, table_count, refreshed_at, profile, scope,
   files_written: [<rel_path>...]}`). `files_written` is the
   idempotency anchor — Step 5 reads the prior `_meta.json` to
   compute the orphan set.
5. **Orphan handling**: only orphan files **falling within the current
   `--scope` / `--tables` filter that were NOT regenerated this run**
   (i.e. the table got dropped from the DB or moved out of scope).
   Files outside the current scope MUST be left untouched — a partial
   `--scope dbt_marts` re-cache must NEVER move `dbt_staging/*` files
   to `_orphans/`. Tracking: read previous-run filenames from
   `_meta.json.files_written` (regenerated each run); diff against
   this-run set, intersected with current scope. Move orphans to
   `_orphans/<refreshed_at>/`. Never auto-prune `_orphans/`.

## Layout
```
~/.cache/redshift-comment-mcp/<profile>/
├── index.md                       # TOC
├── _meta.json                     # { refreshed_at, counts, profile }
├── schemas/<schema>.md            # schema card + table list
├── tables/<schema>__<table>.md    # column list
└── _orphans/<date>/...            # files no longer in scope
```

Filenames lowercased; `__` separator handles `_` in identifiers.
Identifiers in *file content* preserve original case.

## File templates

`tables/<schema>__<table>.md`:
```markdown
# `<schema>.<table>`

> <table comment, or "(no comment)">

Refreshed: 2026-05-03T12:34:56Z

## Columns (12)
| # | name | type | nullable | comment |
|---|---|---|---|---|
| 1 | order_id | bigint | NO | Unique order identifier |
```

`nullable` is the raw `"YES"`/`"NO"` string from MCP — do not convert.
No row counts / samples in cache files — structure only by design.

## Output (chat)
```
✓ Cached at ~/.cache/redshift-comment-mcp/<profile>/
  Schemas: 8 (1 new, 0 removed)   Tables: 142 (3 new, 1 → _orphans/)
  Refreshed: 2026-05-03T12:34:56Z
```
`--dry-run` lists filenames that would be written; no disk writes.

## Errors
| Condition | Behavior |
|---|---|
| list_schemas empty | `_error: no_schemas_returned` — abort |
| Per-schema list_tables fails | record skip, continue, footer note |
| Per-table list_columns fails | record skip, continue, footer note |
| Filesystem write fails | `_error: write_failed: <path>: <reason>` — abort |
| Full cache without --scope, > 50 schemas | `_error: scope_too_large` |

Cache dir created with `mkdir -p`, mode 700.
