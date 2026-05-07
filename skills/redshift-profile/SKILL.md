---
name: redshift-profile
description: >-
  Profile a Redshift column — cardinality, top-N values, null rate,
  min/max, plus comment. Read-only. Use when about to write CREATE
  TABLE or dbt schema.yml based on column assumptions, or to check
  whether a column is an enum. Do NOT use for full row counts (use
  execute_sql), schema/table search (use search_columns), or
  free-text columns where top-100 is noise. Triggers:
  /redshift-profile / profile column / distinct values / enum /
  欄位分布 / カラムプロファイル / 値の分布.
---

# Redshift Column Profile

Discovers what a column actually contains. Read-only, MCP-composed.

## When to use / NOT
- Use when user wants enum check, null rate, value distribution.
- NOT for free-text columns (top-100 is noise) or huge tables without
  user-confirmed full-scan.

## Inputs
| Form | Parsed |
|---|---|
| `<schema>.<table> <col>` | direct |
| `<schema> <table> <col>` | direct |
| `<table> <col>` | schema missing → ask user |
| (no args) | ask "which table.column?" |

Quote identifiers in SQL as `"<schema>"."<table>"."<col>"`.

## Flow
1. **Resolve column metadata** (`type`, `nullable`, `comment`) — try cache first:

   - **Cache path** (preferred): if `~/.cache/redshift-comment-mcp/<profile>/_meta.json` is `complete: true` and `(now - refreshed_at) < ttl_hours`, Read `tables/<schema>__<table>.md` and find the `` ### `<col>` (type[, NOT NULL]) `` heading + the comment block under it. Capture `type`, `nullable` (presence of `, NOT NULL`), `comment` (text from heading to next `### \`` or `## `).
   - **Live path**: `list_columns(schema_name, table_name, include_comments=true)`. Find the row whose `name == <col>` (MCP returns `{name, type, nullable, comment}` — NOT `column_name` / `data_type`; `nullable` is the string `"YES"` / `"NO"`).

   Stale / missing cache → fall back to live path; emit one chat line:
   ```
   [cache] miss for `<schema>.<table>` — fetching live; rebuild with /redshift-cache-schema --refresh.
   ```

   If column missing in either source → error `column_not_found`.

2. **Type branch** (lowercase prefix match on `type`):

   | branch | Redshift types | top-N | min/max |
   |---|---|---|---|
   | `string` | varchar, char, text, bpchar, nvarchar | ✓ | — |
   | `numeric` | int, integer, bigint, smallint, numeric, decimal, real, double, float | ✓ | ✓ |
   | `date` | date, timestamp, timestamptz, timetz, time | ✓ | ✓ |
   | `boolean` | bool, boolean | ✓ | — |
   | `unsupported` | super, geometry, geography, hllsketch, varbyte | — | — |

   `unsupported` → emit error JSON, stop.

3. **Cardinality + null + total** (one `execute_sql`):
   ```sql
   SELECT COUNT(*) AS total_rows,
          SUM(CASE WHEN "<col>" IS NULL THEN 1 ELSE 0 END) AS null_count,
          COUNT(DISTINCT "<col>") AS distinct_count
   FROM "<schema>"."<table>";
   ```
   `COUNT(DISTINCT)` excludes NULL — the null bucket lives in Step 4.
   If `total_rows == 0` → emit empty profile, skip Steps 4-5.

4. **Top-100** (one `execute_sql`, all branches):
   ```sql
   WITH base AS (
       SELECT "<col>"::text AS v, COUNT(*) OVER () AS total_rows
       FROM "<schema>"."<table>"
   )
   SELECT v AS value, COUNT(*) AS count,
          ROUND(COUNT(*)*100.0 / MAX(total_rows), 2) AS pct
   FROM base GROUP BY v ORDER BY count DESC NULLS LAST LIMIT 100;
   ```
   `::text` normalizes booleans/numerics/dates so JSON shape is uniform.
   The NULL bucket appears as `{"value": null, ...}` — intentional;
   downstream skills handle it. `distinct_count_truncated` = `distinct_count > 100`.

5. **Min/Max** (only `numeric` / `date`, one `execute_sql`):
   ```sql
   SELECT MIN("<col>") AS min_val, MAX("<col>") AS max_val
   FROM "<schema>"."<table>" WHERE "<col>" IS NOT NULL;
   ```
   Skip for `string` / `boolean` — lexical min/max is misleading.

## Output

JSON block (chainable):
```json
{
  "schema": "dbt_marts", "table": "fct_orders", "column": "status",
  "type": "varchar(32)", "type_branch": "string",
  "comment": "Order lifecycle state",
  "total_rows": 13030, "null_count": 39, "null_pct": 0.30,
  "distinct_count": 4, "distinct_count_truncated": false,
  "cardinality_class": "low",
  "top_values": [{"value": "active", "count": 12340, "pct": 94.70}],
  "min": null, "max": null,
  "sampled_at": "2026-05-03T12:34:56Z", "sample_method": "full"
}
```
Field rules: `null_pct = round(null/total, 2)` (0.0 if empty);
`cardinality_class` = `low<50` / `mid 50-1000` / `high>1000`;
`min`/`max` always `null` for string/boolean.

Plus a chat summary (user's language) showing header + top-10 + range,
ending with a one-line interpretation hint:
- low + top>90% → "skewed enum, `<top>` dominates"
- low + ≤10 distinct → "clean enum, accepted_values candidate"
- high → "probably ID / free text"
- null_pct>50% → "mostly null — verify upstream"

## Anti-patterns

- NEVER use MCP keys `column_name` / `data_type` — MCP returns `{name, type, nullable, comment}`. Wrong shape costs a debugging cycle.
- NEVER profile free-text or huge-cardinality columns without warning the user — top-100 of `varchar(2000)` is noise. Warn and confirm before scanning.
- NEVER skip the `::text` cast in the top-N CTE — Redshift coerces booleans/dates inconsistently across drivers; uniform JSON shape requires explicit cast.
- NEVER report `min` / `max` for `string` / `boolean` types — lexical extrema mislead, and `/redshift-suggest-schema-yml` would turn them into range bounds.
- NEVER swallow `execute_sql` errors — Redshift error text is diagnostic. Surface verbatim under `_error: execute_sql_failed`.

## Errors
| Condition | `_error` |
|---|---|
| list_columns empty | `table_not_found_or_no_permission` |
| Column not in response | `column_not_found` (+ `did_you_mean[]` from list_columns) |
| Type unsupported | `type_not_supported` |
| execute_sql failed | `execute_sql_failed: <verbatim>` |

Surface execute_sql errors verbatim — Redshift errors are diagnostic.

## See also

| Need | Use |
|---|---|
| Chain a profile into a dbt yml draft | `/redshift-suggest-schema-yml` |
| Find which column to profile | `/redshift-explore` |
| Structure (vs values) | `/redshift-cache-schema` |
