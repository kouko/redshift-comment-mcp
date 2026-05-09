# Skills

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

This directory contains the skills shipped with the `redshift-comment-mcp`
plugin. All skills are **read-only**, **MCP-composed** (they call the
plugin's MCP tools rather than connecting to Redshift directly), and
aligned with the plugin's **Guided Data Discovery** charter.

Each skill has its own `SKILL.md` (the authoritative execution
contract) and a tri-lingual README (orientation for new readers).

## Charter

The plugin exists to help analysts and engineers find their way
through an unfamiliar Redshift cluster, comment-first. Names lie;
comments are usually the closest thing to ground truth. Every skill
here either composes the existing `list_*` / `search_*` /
`execute_sql` MCP tools or — in one case — adds a sqlglot helper
script for a parsing problem the LLM can't do reliably on its own.

What you will NOT find here:

- Direct database connections (the MCP server is the only path).
- Anything that writes to Redshift (`execute_sql` is SELECT-only).
- Persistent synthesis layers (no `.redshift-wiki/` markdown,
  no stale-tracking, no hand-curated docs). That belongs in a
  separate plugin.

## Skills

| Skill | One-line | Stable |
|---|---|---|
| [redshift-setup](redshift-setup/) | Conversational walk-through to configure a connection profile (host / port / user / dbname / password). | v0.2.0 |
| [redshift-switch-profile](redshift-switch-profile/) | Switch the active profile by flipping the active-profile pointer file (no host / user / password re-entry). Single-profile users get a friendly bow-out. | v0.4.0 |
| [redshift-profile](redshift-profile/) | Profile a column: cardinality / top-N / null rate / min-max / existing comment, all in one chat round. | v0.3.0 |
| [redshift-cache-schema](redshift-cache-schema/) | LLM-internal cache: dumps cluster structure to local files so other skills resolve metadata via Read instead of MCP round-trips. Read by `/redshift-explore`, `/redshift-profile`, and the server-level CACHE PROTOCOL. | v0.3.0 |
| [redshift-explore](redshift-explore/) | Three-step interactive wizard (schema → table → column) that lets users pick by reading comments instead of remembering names. | v0.3.0 |
| [redshift-lineage-from-stl](redshift-lineage-from-stl/) | Mine `STL_QUERY` / `SYS_QUERY_HISTORY` + parse SQL with sqlglot to reconstruct *actual* table-to-table data flow from query history. | v0.3.0 |
| [redshift-grep-columns](redshift-grep-columns/) | Cross-table column search by keyword (name + comment) across one or all schemas. Cache-first via local TSV grep; live MCP fallback. | v0.4.0 |
| [redshift-grep-tables](redshift-grep-tables/) | Cross-schema table search by keyword (name + comment) across all schemas. Cache-first via local TSV grep; live MCP fallback. | v0.4.0 |

## How to use

Each skill has a slash command counterpart in `commands/` at the
plugin root. Type the command in chat, e.g. `/redshift-profile
dbt_marts.fct_orders status`, and the skill orchestrates the
necessary MCP calls.

For execution details (input parsing, exact SQL templates, error
codes, output shape), open the skill's `SKILL.md`. For orientation
(what / when / one example), open the skill's `README.md` —
available in three languages.

## Authoritative reference

- Plugin charter: [implementation_guide.md](../implementation_guide.md) §1.2
- MCP tool surface: [src/redshift_comment_mcp/redshift_tools.py](../src/redshift_comment_mcp/redshift_tools.py)
- Plugin manifest: [.claude-plugin/plugin.json](../.claude-plugin/plugin.json)
