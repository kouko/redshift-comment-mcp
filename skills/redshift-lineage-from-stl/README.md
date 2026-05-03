# redshift-lineage-from-stl

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

This skill answers "**who is actually reading and writing this table?**"
by reading Redshift's query-history system tables, parsing the captured
SQL with `sqlglot`, and aggregating one row per `(source → target,
operation)` edge with query count, distinct users, top 5 users, first /
last seen, and sample query IDs.

It is the empirical complement to a dbt manifest. The dbt manifest tells
you the **declared** lineage — what `ref()` says should connect. This
skill tells you the **actual** lineage — what real queries did last
week, including ad-hoc analyst SQL, Tableau and Looker extracts, manual
backfills, and one-off fixes that no manifest captures.

## STL retention warning (read first)

Query history is short-lived. On **provisioned** clusters,
`STL_QUERY` retains roughly **2-5 days** before rows roll off — older
activity is simply gone, and no skill can recover it. **Serverless**
keeps `SYS_QUERY_HISTORY` longer (typically weeks), but quotas still
apply. The skill detects cluster type from `SELECT version()`, clamps
your `--since` window to what's actually available, and warns you in
the footer if `--since` predates the earliest row. If you need a
12-month audit, you need an archival pipeline; this tool cannot fabricate
history that Redshift has already discarded.

## When to use

- Auditing a model as a deprecation candidate — confirm no Tableau
  dashboard, scheduled extract, or analyst notebook still hits it.
- Finding the actual consumers of a mart (manifest only sees other
  dbt models, not BI tools or ad-hoc users).
- Diagnosing freshness complaints — see which user ran what against
  the table just before the report broke.

## Permissions

The querying user needs `SYSLOG ACCESS UNRESTRICTED` (or admin /
superuser equivalent) to see other users' rows in `STL_QUERY`. Without
it, you only see your own queries, which makes lineage results
misleading. The skill returns `_error: stl_access_denied` with the raw
Redshift message if access is refused.

## Example

```bash
/redshift-lineage-from-stl --since 7d --table dbt_marts.fct_orders
```

Mines the last 7 days of activity touching `dbt_marts.fct_orders`,
parses each statement, and emits an adjacency table:

```
| from                   | →  | to                   | queries | distinct users | last seen           |
| dbt_staging.stg_orders | →  | dbt_marts.fct_orders | 31      | 1 (dbt)        | 2026-05-03 04:00:12 |
| dbt_marts.fct_orders   | →  | (read by ad-hoc)     | 243     | 12             | 2026-05-03 11:42:08 |
```

Add `--output mermaid` for a Mermaid graph alongside the table.

For full input syntax, output schema, edge-aggregation logic, and error
handling, see [SKILL.md](SKILL.md).
