---
name: redshift-lineage-from-stl
description: >-
  Mine Redshift's STL_QUERY (provisioned) or SYS_QUERY_HISTORY
  (serverless) + sqlglot SQL parsing to reconstruct ACTUAL table-to-table
  data flow from query history — catching ad-hoc, BI-tool (Tableau /
  Looker), and manual-fix usage that dbt manifest cannot see. Outputs
  adjacency table + optional Mermaid graph with usage frequency, top
  users, time range. Ships a sqlglot helper script (SQL parsing is
  LLM-unreliable). Read-only. Use when user invokes
  /redshift-lineage-from-stl, or says: "actual lineage", "who reads
  this table", "real query history", "STL lineage", "ad-hoc usage of",
  "Tableau usage of", "find consumers of", "實際 lineage", "誰在讀這
  table", "看 query 歷史", "從 STL 查使用情況", "STL_QUERY から",
  "実際の利用状況", "クエリ履歴から系譜", "誰が読んでいる". Do NOT
  use for: dbt-internal lineage (use dbt-wiki / dbt docs), declared
  FKs (use /redshift-erd), questions older than STL retention (~2-5
  days on provisioned), permission-restricted accounts (STL needs
  admin or specific GRANTs), real-time monitoring (this is batch).
---

# Redshift Lineage from STL_QUERY

Reconstructs **actual** lineage by mining query history + sqlglot
parsing. Ships a helper script — the only one in this plugin that
does, justified because LLM-driven SQL parsing is unreliable.

**STL retention warning** (mention upfront in chat):
- Provisioned: ~2-5 days; older queries gone.
- Serverless: longer; uses `SYS_QUERY_HISTORY`.
- Permissions: STL needs `SYSLOG ACCESS UNRESTRICTED` or admin.

## When to use / NOT
- Use to find ad-hoc / BI-tool consumers, audit deprecation candidates,
  diagnose freshness gaps.
- NOT for dbt-internal lineage (manifest is authoritative); NOT for
  declared FKs (use erd); NOT real-time.

## Inputs
| Form | Behavior |
|---|---|
| `--since <date>` or `--since 7d` | window (clamped to STL retention) |
| `--table <s>.<t>` | scope to queries touching this table |
| `--user <name>` | scope to one user |
| `--limit N` | cap pulled queries (default 5000) |
| `--include-system` | keep pg_catalog/STL/etc (default: filter out) |
| `--output mermaid` | also emit Mermaid graph |

## Flow

1. **Detect cluster type**: `execute_sql("SELECT version()")`. Look
   for "Redshift Serverless" → use SYS_QUERY_HISTORY; else STL.

2. **Pull queries** — provisioned (STL_QUERY + STL_QUERYTEXT):
   ```sql
   WITH recent AS (
       SELECT q.query, q.userid, q.starttime,
              u.usename AS user_name
       FROM STL_QUERY q LEFT JOIN PG_USER u ON u.usesysid = q.userid
       WHERE q.starttime >= '<since>'::timestamp AND q.aborted = 0
         /* if --user */ AND u.usename = '<user>'
       ORDER BY q.starttime DESC LIMIT <limit>
   )
   SELECT r.query, r.user_name, r.starttime,
          LISTAGG(qt.text, '') WITHIN GROUP (ORDER BY qt.sequence) AS sql_text
   FROM recent r JOIN STL_QUERYTEXT qt ON qt.query = r.query
   GROUP BY r.query, r.user_name, r.starttime;
   ```
   Caveat: `LISTAGG` result is `VARCHAR(65535)` — long queries truncate.
   Mention to user; truncated SQL parses worse.

   Serverless (SYS_QUERY_HISTORY — full SQL is one column already):
   ```sql
   SELECT query_id AS query, user_id AS user_name,
          start_time AS starttime, query_text AS sql_text
   FROM SYS_QUERY_HISTORY
   WHERE start_time >= '<since>'::timestamp
     AND status NOT IN ('failed', 'aborted')
     /* if --user */ AND user_id = '<user>'
   ORDER BY start_time DESC LIMIT <limit>;
   ```

3. **Save NDJSON + run helper**: write each query as a JSON line
   `{query, user, starttime, sql}` to `$TMPDIR/queries.ndjson`, then:
   ```bash
   cp "<SKILL_DIR>/assets/parse_stl_lineage.py" "$TMPDIR/"
   "$TMPDIR/parse_stl_lineage.py" --input "$TMPDIR/queries.ndjson" \
       --output "$TMPDIR/lineage.json" \
       [--filter-table <s>.<t>] [--include-system]
   ```
   Script handles multi-statement SQL (`sqlglot.parse`), CTE-name
   filtering, system-table filtering, per-edge aggregation. PEP 723 +
   `uv run --script` resolves `sqlglot` automatically.

4. **Read `lineage.json`** and render. Surface `parse_errors` verbatim.

## Output

Adjacency table (chat, primary):
```
| from | → | to | queries | distinct users | last seen |
| dbt_marts.fct_orders | → | (read by ad-hoc) | 243 | 12 | 2026-05-03 11:42:08 |
| dbt_staging.stg_orders | → | dbt_marts.fct_orders | 31 | 1 (dbt) | 2026-05-03 04:00:12 |
```
`(read by ad-hoc)` for SELECTs that don't write to a target.

Mermaid (only with `--output mermaid`):
```mermaid
flowchart LR
    raw_orders.events --> dbt_staging.stg_orders
    dbt_staging.stg_orders --> dbt_marts.fct_orders
    dbt_marts.fct_orders -. ad-hoc 243× .-> ((readers))
```

Footer: "Mined N queries from <since> to <now>. Found M edges across
K tables. P parse errors. Earliest STL row: <ts> (warn if `--since`
exceeds retention)."

## Errors
| Condition | Behavior |
|---|---|
| STL access denied | `_error: stl_access_denied: <verbatim>` |
| `--since` > earliest STL row | warn, proceed |
| Helper script missing | `_error: helper_script_missing` |
| Helper script crashed | `_error: parser_failed: <stderr>` |
| `uv` not available | `_error: uv_unavailable` |
| Zero queries in window | not error — render empty + hint widen window |
| > 50% queries failed parse | warn loudly, proceed with what parsed |
