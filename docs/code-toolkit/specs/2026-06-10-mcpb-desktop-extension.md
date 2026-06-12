# Brief — Ship a Claude Desktop Extension (.mcpb) with a connection-config form

> **⚠️ SUPERSEDED (2026-06-11).** Research correction: Claude Code plugins have a
> native `userConfig` mechanism (enable-time config dialog, keychain for sensitive
> fields) — so the user's actual audience (Claude Code via marketplace) needs no
> `.mcpb` at all. Live brief: **[2026-06-11-plugin-userconfig.md](2026-06-11-plugin-userconfig.md)**.
> This `.mcpb` plan stays relevant ONLY if serving non-Claude-Code Claude Desktop
> users later. Kept for the decision trail.

Date: 2026-06-10
Stage: brainstorming → (next) writing-plans
Supersedes: [2026-06-10-registry-server-json.md](2026-06-10-registry-server-json.md)
Decision locked in conversation: **pure-GUI Desktop install + Settings-panel
connection form, via an `.mcpb` using `server.type: "uv"`. Verification-spike first.**

## Problem
(Axis 1 — JTBD)

> When I'm a Claude Desktop user, I want to install this Redshift server and enter
> my connection details through a GUI form (like Tableau's MCP extension does),
> so I never hand-edit `claude_desktop_config.json` and my password never goes
> into chat or a plaintext file.

The user explicitly rejected both hand-editing JSON and a one-line terminal
installer; the bar is **pure GUI**, with Tableau's Claude Desktop extension as
the reference UX (verified: Tableau ships a DXT/MCPB extension with a `user_config`
form — but Tableau is Node, so its bundling is frictionless).

## Users
(Axis 2)

- **Primary**: Claude Desktop users (macOS/Windows) who are *not* on Claude Code,
  want one-click install + a Settings form, and won't touch a terminal or JSON.
- **Constraint discovered**: for a Python server with native deps, "pure GUI,
  zero prerequisite" is **not fully achievable today** — see Risks. Realistic
  user profile is "willing to install `uv` via Homebrew once," not "zero setup."
- Claude Code users are unaffected — they keep the existing plugin + profile +
  `setup_via_dialog` flow.

## Smallest End State
(Axis 3)

A distributable `.mcpb` that, on Claude Desktop:
1. installs from Settings → Extensions (double-click / file), no JSON, no terminal;
2. shows a `user_config` form: `host` (string, req), `port` (number, default 5439),
   `user` (string, req), `dbname` (string, req), `password` (string, **sensitive**, req);
3. launches the **existing PyPI package** via `server.type: "uv"` (deps from
   `pyproject.toml`, no bundled wheels), injecting form values as
   `--host/--port/--user/--dbname` + `REDSHIFT_PASSWORD` env;
4. connects with **zero server code change** (inline mode is already the adapter);
   sensitive password stored by Desktop's OS-keychain-backed secure storage.

**Gated by a verification spike** (task #1): prove a `uv`-type `.mcpb` actually
installs + runs + injects `user_config` on real Claude Desktop, given the open
install-detection bugs (Risks). If the spike fails, revisit before building out.

## Current State Evidence
(file:line)

- **Forward**: `resolve_connection_params` takes the inline branch when
  host+user+dbname are present, password from `REDSHIFT_PASSWORD`
  (`src/redshift_comment_mcp/server.py:48-56`). This IS the launch contract the
  `user_config` form feeds — no code change needed. Entry point
  `redshift-comment-mcp = redshift_comment_mcp.server:main` (pyproject.toml).
- **Reverse / SSOT**: version already dual-sourced — `.claude-plugin/plugin.json`
  `"version"` + `pyproject.toml` `fallback_version` (both 0.7.1); `CLAUDE.md`
  mandates lockstep. The `.mcpb` `manifest.json` adds a **third** version field to
  the sync discipline. Release flow: `.github/workflows/publish.yml` on release.
- **Error**: inline mode without password → `ConfigurationError` (`server.py:51-55`)
  — but required `user_config` fields mean Desktop won't launch with them empty.
  New failure surface: Desktop refusing to install a uv-type Python extension
  (mcpb#84 / #96).
- **Data**: MCPB manifest — `server.type: "uv"`, `mcp_config` (command/args/env),
  `user_config` 5 fields. Maps 1:1 to inline tuple `(host,port,user,password,dbname)`.
- **Boundary**: PyPI (package present, `uvx`-runnable); `uv`/Homebrew on the user's
  machine (Desktop detection caveat); Claude Desktop Extensions runtime; `mcpb pack`
  CLI for building; GitHub Releases for hosting the `.mcpb` asset.

Evidence paths: `pyproject.toml`, `.claude-plugin/plugin.json`,
`.github/workflows/publish.yml`, `src/redshift_comment_mcp/server.py`,
`src/redshift_comment_mcp/connection.py`, `tests/test_repo_invariants.py`.

## Decision

Build a Claude Desktop Extension (`.mcpb`) with `server.type: "uv"` and a
`user_config` connection form (5 fields, password `sensitive`), reusing the
server's inline mode unchanged. First task is a **verification spike** against
real Claude Desktop (does uv-type install + run + inject?). Distribute the built
`.mcpb` as a GitHub Release asset (optionally submit to Anthropic's extension
directory later). Document the `uv` (Homebrew) prerequisite honestly. Extend the
version-sync discipline + invariant test to the manifest's version field.

## Out of Scope

- `server.json` / official-registry publishing (abandoned for this goal — serves
  discoverability, not the Desktop form; see superseded brief).
- Multi-profile in the form (form = single connection; multi-profile stays a
  Claude Code + CLI feature).
- Any change to `setup_via_dialog` / profile system / keychain — they remain the
  Claude Code & CLI path; the `.mcpb` path bypasses them via inline mode.
- Rewriting the server in Node to get bundled-runtime parity with Tableau.
- A bundled-CPython `.mcpb` (`server.type: python`) — only revisited if the uv-type
  spike fails.

## Alternatives Considered
(Axis 4 — WebSearch EN + JA + primary sources)

1. **`server.type: python` (bundle CPython + wheels)** — zero user prereq in
   theory, but native wheels (`redshift_connector`/`awswrangler`/`pandas`) can't be
   portably bundled; per-OS builds; large. Rejected unless uv-type spike fails.
2. **`server.type: uv` (CHOSEN)** — no dependency bundling, deps from
   `pyproject.toml` ([MANIFEST.md](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md));
   lightest build. Cost: requires `uv` on the host + current Desktop install bugs.
3. **installer subcommand (`install-desktop` writes the JSON)** — cheapest, but the
   user explicitly rejected "one terminal command"; kept only as a fallback if the
   uv-type `.mcpb` proves unshippable.

My take: pursue #2 behind a verification spike; #3 is the documented fallback,
#1 the heavy fallback.

## What Becomes Obsolete
(Axis 5)

Nothing is removed. **Flag**: docs must now coherently present two install paths
(Claude Code plugin marketplace / Claude Desktop `.mcpb`) without implying one is
the only way — doc reconciliation is in-scope.

## Open Questions / Risks
(resolve in writing-plans; spike answers the first)

1. **[GATING] uv-type install on Claude Desktop**: mcpb#84 ("no system Python →
   install disabled even with uv") and mcpb#96 ("uv runtime → 'incompatible'") are
   open. Spike must confirm it installs + runs + injects `user_config` on a target
   machine, and document the exact prereq (Homebrew `uv`? system Python too?).
2. **Exact `mcp_config` shape for `server.type: uv`**: command/args/`entry_point`
   wiring + how `${user_config.X}` substitutes into args/env — confirm against
   mcpb examples before packaging.
3. **Distribution**: GitHub Release asset is the baseline; decide whether to also
   submit to Anthropic's reviewed extension directory (adds review latency).
4. **Version field count → 3**: extend `CLAUDE.md`'s version-bump rule and the
   repo-invariant test to cover `manifest.json` version alongside the existing two.
5. **Bump level**: new distribution capability → MINOR (per `CLAUDE.md` table).
