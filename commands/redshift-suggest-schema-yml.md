---
description: "Draft a dbt schema.yml v2 block for a Redshift table — descriptions from existing comments, data_type from Redshift, suggested tests (not_null / unique / accepted_values) from a profile run. Read-only; outputs to chat (no file writes)."
---

Use the redshift-comment-mcp:redshift-suggest-schema-yml skill to draft a dbt schema.yml block. Argument forms accepted:

- `/redshift-suggest-schema-yml <schema>.<table>`  (whole-table draft)
- `/redshift-suggest-schema-yml <schema> <table>`
- `/redshift-suggest-schema-yml <schema>.<table> <column>`  (single-column draft)
- `/redshift-suggest-schema-yml`  (then paste profile JSON, or be asked for table)
