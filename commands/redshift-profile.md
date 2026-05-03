---
description: "Profile a Redshift column — surface cardinality, top-N values, null rate, min/max, and the existing comment in one round. Read-only; composes the redshift-comment-mcp tools."
---

Use the redshift-comment-mcp:redshift-profile skill to profile a Redshift column. Argument forms accepted:

- `/redshift-profile <schema>.<table> <column>`
- `/redshift-profile <schema> <table> <column>`
- `/redshift-profile <table> <column>`  (will disambiguate schema if needed)
- `/redshift-profile`  (will ask for table.column)
