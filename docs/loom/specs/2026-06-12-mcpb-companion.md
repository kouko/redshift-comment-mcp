# Brief — Companion `.mcpb` Desktop Extension (Claude Desktop config form)

Date: 2026-06-12
Stage: brainstorming → (next) writing-plans
Related: [2026-06-11-plugin-userconfig.md](2026-06-11-plugin-userconfig.md) (the plugin side; this is the companion)
Decision locked in conversation: **ship a companion `.mcpb` (server.type `uv`) alongside the
existing Claude Code plugin, so Claude Desktop/Cowork users get a Tableau-like connection
form. Verification-spike FIRST (uv-type install is the gating unknown).**

## Problem
(Axis 1 — JTBD)

> When I'm a Claude **Desktop / Cowork** user (not on Claude Code CLI/VS Code), I want to
> install this Redshift integration and enter my connection (host/user/db/password) through
> a graphical form in the Connectors panel — exactly like the Tableau MCP Server extension —
> so I never edit raw config and the password is stored securely.

Empirically grounded: at plugin v0.9.0, the Cowork desktop Connectors panel shows the plugin's
MCP server as **raw config** (`command`/`args` with literal `${user_config.*}` + masked
`REDSHIFT_PASSWORD`) — NO form. Tableau gets a form because it's a `.mcpb` Desktop Extension.

## Users
(Axis 2)

- **Primary**: Claude Desktop / Cowork users who want the GUI Connectors form (Tableau-parity).
- **Constraint**: a `.mcpb` is **form + 11 MCP tools only** — it does NOT carry the 6 skills.
  Skills remain plugin-only. So a Desktop user installing only the `.mcpb` gets tools+form, not
  the guided skills.
- Claude Code (CLI/VS Code) users keep the plugin (skills + userConfig dialog) — unaffected.

## Smallest End State
(Axis 3)

A distributable `.mcpb` that, on Claude Desktop/Cowork:
1. installs (double-click / drag-drop) and appears in the Connectors panel;
2. renders a `user_config` **form**: host (string, req), port (number, default 5439),
   user (string, req), dbname (string, req), password (string, **sensitive**, req);
3. launches the existing PyPI package via `server.type: "uv"` (deps from `pyproject.toml`),
   injecting `${user_config.*}` into args + `REDSHIFT_PASSWORD` env;
4. connects with **zero server code change** (inline mode is the adapter), sensitive password
   in OS keychain.

**GATED by a verification spike (plan task #1)**: hand-write a minimal manifest → `mcpb pack`
→ install on real Claude Desktop → confirm it (a) installs as a uv-type Python extension,
(b) renders the form, (c) injects values, (d) connects. If the spike fails (mcpb#84/#96),
STOP and revisit before building the full artifact + docs.

## Current State Evidence
(file:line — read this session)

- **Forward**: inline mode is the launch adapter — `resolve_connection_params` inline branch
  (`src/redshift_comment_mcp/server.py:48-56`) + `_coerce_port`/`_normalize_inline` hardening
  (added v0.8.0) already tolerate empty/`${...}`-literal args. `${user_config.*}` → args/env
  feeds exactly this. **Zero server change expected.**
- **Reverse / SSOT**: version is currently dual-sourced — `.claude-plugin/plugin.json` `"version"`
  + `pyproject.toml` `fallback_version` (both 0.9.0; `tests/test_repo_invariants.py::test_pyproject_plugin_version_sync`).
  A `.mcpb` `manifest.json` adds a **THIRD** version field → extend the sync discipline + invariant.
- **Error**: uv-type desktop install bugs ([mcpb#84](https://github.com/modelcontextprotocol/mcpb/issues/84)
  no-system-python, [#96](https://github.com/modelcontextprotocol/mcpb/issues/96) incompatible);
  empty/literal injected args → server falls back to profile mode (already hardened, won't crash).
- **Data**: manifest.json — `manifest_version "0.4"`, `server.type "uv"` + `entry_point` (Python file)
  + optional `mcp_config`; `user_config` is an **object keyed by name** (type/title/description/
  required/sensitive/default); injection via `${user_config.KEY}` template substitution. Maps to
  inline tuple `(host,port,user,password,dbname)`. (Schema verified vs live
  [MANIFEST.md](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md).)
- **Boundary**: PyPI package `redshift-comment-mcp` (entry point `redshift-comment-mcp`); the `uv`
  runtime (host-managed, needs `uv` present); Claude Desktop Extensions framework; `mcpb` CLI
  (`npm i -g @anthropic-ai/mcpb` → `mcpb init`/`pack`); GitHub Releases for the `.mcpb` asset.

Evidence paths: `.claude-plugin/plugin.json`, `pyproject.toml`,
`src/redshift_comment_mcp/server.py`, `tests/test_repo_invariants.py`,
`.github/workflows/publish.yml`.

## Decision

Add a companion `.mcpb` Desktop Extension (likely under `mcpb/` in the repo) with `server.type:
"uv"` and a `user_config` form (5 fields, password `sensitive`), reusing the server's inline mode
unchanged. **Verification spike first** (does uv-type install + render + inject on real Desktop?).
Distribute the built `.mcpb` as a GitHub Release asset. Extend version-sync + invariant test to the
manifest version. Document a "two install paths" story (plugin for skills / `.mcpb` for the Desktop
form). Keep the Claude Code plugin and its userConfig exactly as-is.

## Out of Scope

- Removing or changing the Claude Code plugin / its `userConfig` / skills.
- Trying to make ONE artifact serve both (researched — impossible; plugin and `.mcpb` are
  separate schemas/installers; `.mcpb` can't carry skills).
- `server.type: "python"` with bundled CPython/wheels (heavy; only if the uv-type spike fails).
- Submitting to Anthropic's reviewed extension directory (optional later; adds review latency).
- Multi-profile in the form (form = one connection; multi-profile stays CLI/plugin).

## Alternatives Considered
(Axis 4 — researched across the conversation, named-case verified)

1. **Claude Code plugin `userConfig`** — empirically does NOT render a form in the Cowork desktop
   Connectors panel (shows raw config). Works only on the VS Code/CLI surface. Rejected for the
   desktop-form goal.
2. **MCP Elicitation form-mode** — [spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)
   forbids form-mode for passwords/keys/tokens. Disqualified for credentials.
3. **MCP Apps / MCP-UI (iframe)** — production-adopted (Shopify/Postman/etc.) but for in-chat app
   UX, not connection config; no named case uses it as a config form. Rejected.
4. **`.mcpb` Desktop Extension (CHOSEN)** — the only mechanism that renders the desktop Connectors
   form (Tableau, Azure MCP Server ship this). `server.type: uv` avoids bundling deps.

My take: `.mcpb` is the only path to the desktop form; gate on the install spike.

## What Becomes Obsolete
(Axis 5)

Nothing removed. Additive second artifact. Docs must present two install paths coherently (don't
let plugin / `.mcpb` / `/redshift-setup` fragment into competing stories).

## Spike Result (2026-06-12) — PASSED ✅

Built a minimal `server.type: "uv"` `.mcpb` (manifest + thin `server/main.py` adapter +
bundle `pyproject.toml` pinning the PyPI package), packed with `mcpb pack`
(`manifest_version "0.4"` — schema validation passed), installed on the user's real
Claude Cowork desktop app. Findings (some via an env-dump diagnostic bundle):

- **Form renders** ✅ — the `user_config` (host/port/user/dbname/password-sensitive)
  shows as a Tableau-style config form in the Connectors panel.
- **Injection works** ✅ — for `server.type: uv`, the host **ignores** `mcp_config.command/args`
  (runs the entry_point itself) but **HONORS `mcp_config.env`**. So `${user_config.X}` →
  `REDSHIFT_*` env reaches the process. The adapter translates env → argv → `main()` (inline mode).
- **Connection works** ✅ — `list_schemas` returned real schemas end-to-end.
- **Red herring**: `get_setup_status` reports `not_configured` even when inline mode is
  live — it only checks config.toml profiles, NOT inline mode. Judge by a real DB tool.
- **Decision locked**: `server.type: "uv"`, **assume `uv` is present** (the user accepted
  the prereq). NO bundling, NO PyInstaller, NO codesigning. (Clean Macs lack python3 — only
  an Xcode-CLT stub — so a no-prereq path would require PyInstaller; out of scope now.)

Resolves Open Questions 1 (gating spike → PASS), 2 (entry_point → thin env→argv adapter),
3 (manifest_version → "0.4").

## Open Questions
(resolve in writing-plans)

1. **[GATING] uv-type install on real Desktop** — does it install + render + inject given mcpb#84/#96?
   What exact prereq (Homebrew `uv`? system Python)? The spike decides go/no-go.
2. **entry_point mechanics** — bundle a thin `server.py` (`from redshift_comment_mcp.server import
   main; main()`) + a bundle `pyproject.toml` depending on `redshift-comment-mcp` (uv installs from
   PyPI), VS. use `mcp_config` to run the package directly. Confirm against MANIFEST.md + spike.
3. **manifest_version** — live MANIFEST.md header says `0.3` but the uv example uses `0.4`; confirm
   the correct value for uv runtime at pack time.
4. **Version correspondence** — does the `.mcpb` manifest version track plugin/pyproject (now a 3rd
   field), or version independently? Extend the invariant accordingly.
5. **Distribution** — GitHub Release asset (baseline); whether/when to submit to the extension directory.
