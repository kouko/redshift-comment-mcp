---
name: redshift-erd
description: >-
  Generate a Mermaid erDiagram for a Redshift schema with tables, key
  columns, and confidence-labeled FK relationships. Read-only. Use
  when user wants to map an unfamiliar schema visually, before
  drilling into individual tables. Do NOT use for column-level lineage
  (use /redshift-lineage-from-stl), single-table inspection (use
  /redshift-explore), or validating production FKs (Redshift declares
  but does not enforce them). Triggers: /redshift-erd / ERD / table
  relationships / foreign keys / 畫個 ERD / 關係圖 / ER 図 /
  リレーション図.
---

# Redshift ERD

Renders a Mermaid `erDiagram` for a schema with FK inference. Read-only.

**Important Redshift caveat**: Redshift declares but does NOT enforce
FK constraints, and `pg_constraint` SQL using `unnest WITH ORDINALITY`
may not run on all Redshift cluster types. If Step 2 errors, drop to
MEDIUM/LOW silently — the skill stays useful.

## When to use / NOT
- Use to map an unfamiliar schema visually before drilling in.
- NOT for runtime data flow (use lineage-from-stl); NOT for > 30
  tables without --tables filter; NOT to claim FKs are enforced.

## Inputs
| Form | Behavior |
|---|---|
| `--schema <name>` | all tables in schema (refused if > 30) |
| `--tables <s>.<t>,<s>.<t>` | listed tables |
| `--depth N` | expand N hops via inferred FKs from seed tables |
| `--manifest <path>` | also use dbt manifest depends_on (MEDIUM source) |
| `--fk-source pg_constraint` | declared only |
| `--columns key|all` | key columns (default) or all |

## Flow

1. **Scope**: `list_tables(schema_name, include_comments=true)` per
   scoped schema → returns `{tables: [{name, type, comment}]}`. Filter
   by `--tables`. Refuse if > 30 without filter.

2. **HIGH — pg_constraint** (run `execute_sql`; tolerate failure):
   ```sql
   SELECT n.nspname AS schema_name, c.relname AS table_name,
          a.attname AS column_name, rn.nspname AS ref_schema,
          rc.relname AS ref_table, ra.attname AS ref_column
   FROM pg_constraint con
   JOIN pg_class       c  ON c.oid  = con.conrelid
   JOIN pg_namespace   n  ON n.oid  = c.relnamespace
   JOIN pg_class       rc ON rc.oid = con.confrelid
   JOIN pg_namespace   rn ON rn.oid = rc.relnamespace
   JOIN pg_attribute   a  ON a.attrelid  = c.oid  AND a.attnum  = con.conkey[0]
   JOIN pg_attribute   ra ON ra.attrelid = rc.oid AND ra.attnum = con.confkey[0]
   WHERE con.contype = 'f'
     AND array_length(con.conkey, 1) = 1
     AND n.nspname IN (<scoped>);
   ```
   Single-column FKs only (Redshift array indexing on `int2[]` is
   limited). If query errors → footer "pg_constraint unavailable on
   this cluster"; continue with MEDIUM/LOW.

3. **MEDIUM — dbt manifest** (only if `--manifest <path>`):
   `Read` the JSON; walk `nodes[*].depends_on.nodes`; for `model.*`
   refs, record (downstream → upstream). Render with dotted line,
   labeled `via dbt ref`.

4. **LOW — naming heuristic**: `list_columns` per scoped table →
   `{columns: [{name, type, nullable, comment}]}`. For each column
   ending in `_id`: strip suffix, look for in-scope table named
   exactly `<base>` or `<base>s`. If found, infer FK. Render dashed,
   labeled `(heuristic)`.

5. **Dedupe**: same edge from multiple sources → keep highest confidence.

6. **Compose Mermaid**:
   ```mermaid
   erDiagram
       DBT_MARTS_FCT_ORDERS {
           bigint   order_id   PK
           bigint   user_id    FK
       }
       DBT_MARTS_DIM_USERS {
           bigint   user_id    PK
       }
       DBT_MARTS_FCT_ORDERS }o--|| DBT_MARTS_DIM_USERS : "user_id (HIGH)"
   ```
   Conventions: UPPER_SNAKE entity names, schema prefix, default
   cardinality `}o--||` (note in rationale that cardinality isn't
   reliably knowable from catalog), edge label `<col> (HIGH|MEDIUM|LOW)`.

## Output

Mermaid block (paste into [mermaid.live](https://mermaid.live/) or
markdown) + edge rationale table:
```
| from | column | to | confidence | source |
| dbt_marts.fct_orders | user_id | dbt_marts.dim_users | HIGH | pg_constraint |
| dbt_marts.fct_orders | product_id | dbt_marts.dim_products | LOW | naming |
```
Footer: "Drew N tables, M edges (X HIGH / Y MEDIUM / Z LOW). Heuristic
edges are guesses — verify before trusting."

## Anti-patterns

- NEVER claim FK constraints are enforced — Redshift declares but does not validate. Always render confidence tier in the edge label.
- NEVER assume `pg_constraint` works on every cluster — `unnest WITH ORDINALITY` fails on some Redshift versions. On error, drop to MEDIUM/LOW silently and add a footer note.
- NEVER infer multi-column FKs from naming — single-column `<other>_id` heuristic only. Multi-column tells need `pg_constraint`.
- NEVER set non-default cardinality (e.g. `}|--||`) without reading actual constraint metadata — catalog cardinality is unreliable; default `}o--||`.
- NEVER hide LOW-confidence edges silently, but DO truncate to top-N when count > 100 — visual noise crowds out HIGH edges.

## Errors
| Condition | Behavior |
|---|---|
| Scope empty | `_error: no_tables_in_scope` |
| pg_constraint query failed | continue, footer note (don't abort) |
| `--manifest` path missing | `_error: manifest_not_found: <path>` |
| Heuristic > 100 edges | warn, render top-N by confidence + frequency |
| Scope > 30 without filter | `_error: scope_too_large` |

## See also

| Need | Use |
|---|---|
| Find tables before drawing | `/redshift-explore` |
| Offline structure browse | `/redshift-cache-schema` |
| Actual runtime data flow (vs declared FKs) | `/redshift-lineage-from-stl` |
