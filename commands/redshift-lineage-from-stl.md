---
description: "Mine Redshift's STL_QUERY (or SYS_QUERY_HISTORY for serverless) + sqlglot to reconstruct ACTUAL table-to-table lineage from query history. Catches ad-hoc, BI-tool, manual-fix usage that dbt manifest can't see. Read-only; sqlglot helper script ships in assets."
---

Use the redshift-comment-mcp:redshift-lineage-from-stl skill. Argument forms:

- `/redshift-lineage-from-stl --since 2026-04-01`               (mine queries since date)
- `/redshift-lineage-from-stl --since 7d`                       (last 7 days)
- `/redshift-lineage-from-stl --since 7d --table dbt_marts.fct_orders`  (scope to one table)
- `/redshift-lineage-from-stl --since 7d --user analyst@example.com`    (scope to one user)
- `/redshift-lineage-from-stl --since 7d --output mermaid`      (also emit Mermaid graph)
- `/redshift-lineage-from-stl --since 7d --include-system`      (include pg_catalog/STL/etc)

Caveat: STL retention is roughly 2-5 days on provisioned clusters, longer on serverless. The skill detects cluster type and warns if `--since` exceeds retention.
