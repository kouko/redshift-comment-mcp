---
description: "Cross-table column search — find every column whose name or comment matches a keyword across all tables in one (or all) schemas via schema-wide MCP call. Composes the redshift-comment-mcp tools."
---

Use the redshift-comment-mcp:redshift-grep-columns skill to find columns by keyword across many tables. Argument forms accepted:

- `/redshift-grep-columns <keyword>`                          (all schemas)
- `/redshift-grep-columns <keyword> --schema <s>`             (scope to one schema)
- `/redshift-grep-columns <keyword> --schema <s1>,<s2>`       (scope to listed schemas)
- `/redshift-grep-columns <kw1> <kw2>`                        (AND across keywords)
- `/redshift-grep-columns <keyword> --max-list 30`            (results per page)
