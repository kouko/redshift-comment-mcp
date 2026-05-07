# redshift-cache-schema

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-cache-schema` walks the Redshift catalog through the read-only
`redshift-comment-mcp` server and writes the cluster structure — schemas,
tables, columns, and their comments — as files under
`~/.cache/redshift-comment-mcp/<profile>/`. It's idempotent: rerun it and
the same inputs produce the same files.

**LLM-internal cache, not user-facing docs.** The files are designed to
be read by other skills (`/redshift-explore`, `/redshift-profile`) and
the MCP server's CACHE PROTOCOL — not by humans browsing in an editor.
Comments are preserved verbatim (including multi-line markdown), but
the layout is optimized for LLM grep + Read, not for visual reading.

## When to use

Run this once before a heavy analysis session on a stable schema. With
the cache populated, subsequent skill invocations resolve metadata via
a local Read instead of round-tripping to MCP — saves tokens and shaves
~100-1000 ms off each metadata lookup.

When the cache goes stale (default TTL is 168 hours = 1 week), consumers
fall back to live MCP automatically and emit a `[cache]` chat hint
suggesting `/redshift-cache-schema --refresh`. For fast-mutating
schemas, use `--ttl 24` to shorten the trust window.

## Example invocation

```
/redshift-cache-schema --scope dbt_marts,dbt_staging --dry-run
```

`--scope` limits the walk to the listed schemas; `--dry-run` enumerates
files that *would* be written without writing anything. Other flags:
`--tables <s>.<t>[,...]` for specific tables, `--ttl <hours>` to
override the freshness window.

## Cache layout

```
~/.cache/redshift-comment-mcp/<profile>/
├── _meta.json                # freshness gate (refreshed_at, ttl_hours, complete)
├── _tables_index.tsv         # schema\ttable\tsummary (1 row per table; for grep)
├── _columns_index.tsv        # schema\ttable\tcolumn\ttype\tsummary (for grep)
└── tables/
    └── <schema>__<table>.md  # full per-table spec (multi-line markdown comments preserved)
```

See [SKILL.md](./SKILL.md) for the file format spec, freshness contract,
error table, and orphan handling rules.
