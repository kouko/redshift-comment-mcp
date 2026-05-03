---
description: "Generate a Mermaid erDiagram for a Redshift schema. FK source priority: pg_constraint (HIGH) → dbt manifest depends_on (MEDIUM) → naming heuristic (LOW). Heuristic edges clearly labeled."
---

Use the redshift-comment-mcp:redshift-erd skill. Argument forms:

- `/redshift-erd --schema <name>`                         (all tables in schema)
- `/redshift-erd --tables <schema>.<t1>,<schema>.<t2>`    (listed tables)
- `/redshift-erd --schema <name> --depth 2`               (expand 2 hops via FKs)
- `/redshift-erd --schema <name> --manifest target/manifest.json`  (use dbt manifest as MEDIUM source)
- `/redshift-erd --schema <name> --fk-source pg_constraint`        (declared FKs only)
- `/redshift-erd --schema <name> --columns all`           (every column, not just keys)
