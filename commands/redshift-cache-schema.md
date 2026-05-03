---
description: "Dump Redshift cluster structure (schemas/tables/columns/comments) to markdown under ~/.cache/redshift-comment-mcp/<profile>/ for offline browsing. Cache (rebuildable), not wiki. Idempotent."
---

Use the redshift-comment-mcp:redshift-cache-schema skill. Argument forms:

- `/redshift-cache-schema`                                       (full cluster)
- `/redshift-cache-schema --scope <schema>[,<schema>...]`        (subset)
- `/redshift-cache-schema --tables <schema>.<table>[,...]`       (specific tables)
- `/redshift-cache-schema --dry-run`                             (no writes)
