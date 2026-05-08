---
description: "Cross-schema table search — find every table whose name or comment matches a keyword across all schemas in the cluster. Cache-first, live MCP fallback. Composes the redshift-comment-mcp tools."
---

Use the redshift-comment-mcp:redshift-grep-tables skill to find tables by keyword across all schemas. Argument forms accepted:

- `/redshift-grep-tables <keyword>`                       (all schemas)
- `/redshift-grep-tables <keyword> --schema <s1>,<s2>`    (scope to listed schemas)
- `/redshift-grep-tables <kw1> <kw2>`                     (AND across keywords)
- `/redshift-grep-tables <keyword> --max-list 30`         (results per page)
