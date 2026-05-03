---
description: "3-step guided wizard: schema → table → column. Each step lists candidates with comments so the user picks by reading, not remembering names. Hands off to /redshift-profile. Formalizes the Guided Data Discovery charter."
---

Use the redshift-comment-mcp:redshift-explore skill. Argument forms:

- `/redshift-explore`                                (start at schema picker)
- `/redshift-explore <schema>`                       (skip to table picker)
- `/redshift-explore <schema>.<table>`               (skip to column picker)
- `/redshift-explore --keyword <kw>`                 (pre-filter via search)
- `/redshift-explore --max-list 15`                  (candidates per page)
