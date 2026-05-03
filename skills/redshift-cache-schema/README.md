# redshift-cache-schema

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-cache-schema` walks the Redshift catalog through the read-only
`redshift-comment-mcp` server and writes the cluster structure — schemas,
tables, columns, and their comments — as markdown files under
`~/.cache/redshift-comment-mcp/<profile>/`. The skill is idempotent: rerun
it and the same inputs produce the same files.

**Cache, not wiki.** Every file is 100% rebuildable from the live database.
Do not hand-edit them; do not add a `# Notes` section; do not treat them as
a knowledge base. Edits will be silently overwritten on the next run.
Synthesis, stale tracking, and curated prose belong in a separate plugin.
If you reach for this skill expecting a wiki, you will misuse it — pick a
docs tool instead.

## When to use

- **Offline browsing** — read schema and column comments on a plane, in a
  meeting room, or anywhere the cluster is unreachable.
- **Flaky VPN** — avoid re-issuing MCP queries every time the tunnel drops.
- **Onboarding handoff** — point a new analyst at a checked-in directory
  instead of asking them to learn MCP first.

## Example invocation

```
/redshift-cache-schema --scope dbt_marts,dbt_staging --dry-run
```

`--scope` limits the walk to listed schemas. `--dry-run` enumerates files
that *would* be written and writes nothing — preview before committing
disk.

## Cache layout

```
~/.cache/redshift-comment-mcp/<profile>/
├── index.md
├── schemas/<schema>.md
├── tables/<schema>__<table>.md
└── _orphans/<date>/...
```

See [SKILL.md](./SKILL.md) for the full contract, error table, and orphan
handling rules.
