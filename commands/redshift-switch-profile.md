---
description: "Switch the active Redshift profile by flipping the active-profile pointer file. No connection field re-entry; verifies connection before declaring success. Single-profile users get a friendly bow-out."
---

Use the redshift-comment-mcp:redshift-switch-profile skill to switch which configured Redshift profile the MCP server connects to. Do NOT collect any connection fields — the skill assumes the target profile is already configured.
