# Brief — Collect connection config via plugin.json `userConfig` (no .mcpb)

Date: 2026-06-11
Stage: brainstorming → (next) writing-plans
Supersedes: [2026-06-10-mcpb-desktop-extension.md](2026-06-10-mcpb-desktop-extension.md),
[2026-06-10-registry-server-json.md](2026-06-10-registry-server-json.md)
Decision locked in conversation: **add a `userConfig` block to the existing
`plugin.json`; ship in the current marketplace channel; NO `.mcpb`, NO registry.**

## Why this supersedes the .mcpb plan

Research correction (claude-code-guide agent + official docs): Claude Code plugins
DO have a native config-collection mechanism — **`userConfig` in `plugin.json`**,
prompted at **enable time** via a configuration dialog, `sensitive` fields stored
in the OS keychain, values substituted as `${user_config.KEY}` into `mcpServers`.
Source: [Plugins reference §User configuration](https://code.claude.com/docs/en/plugins-reference).
Since the user's only distribution channel is the Claude Code plugin marketplace
(`add <repo URL>` → install), this is in-channel, near-zero-cost, and skips the
.mcpb Python-packaging pain entirely. (.mcpb remains the only option for true
non-Claude-Code Claude Desktop users — out of scope here.)

## Problem
(Axis 1 — JTBD)

> When I install this plugin via the marketplace on Claude Code, I want to be
> prompted for my Redshift connection (host/user/db/password) through Claude
> Code's own config dialog, so I never hand-edit settings.json, never type the
> password into chat, and it "just connects."

## Users
(Axis 2)

- **Primary**: Claude Code users (CLI + VS Code/JetBrains extension) installing via
  the marketplace. Confirmed this is the user's sole distribution channel.
- Out: non-Claude-Code Claude Desktop users (they can't install Claude Code
  plugins; would need .mcpb — deferred).

## Smallest End State
(Axis 3)

1. A `userConfig` block in `.claude-plugin/plugin.json` declaring `host` (string),
   `port` (number, default 5439), `user` (string), `dbname` (string),
   `password` (string, **sensitive**), each with `title` + `description`.
2. `mcpServers."redshift-comment"` injects them: `--host ${user_config.host}` …
   plus `env: { "REDSHIFT_PASSWORD": "${user_config.password}" }` → reuses the
   server's existing inline mode.
3. Version bump 0.7.1 → **0.8.0** (MINOR — new user-visible capability), moving
   BOTH `plugin.json` `version` and `pyproject.toml` `fallback_version` per CLAUDE.md.
4. READMEs (×3 langs) updated: "install → you'll be prompted for connection."
5. **Rewrite the two D2 guard tests** in `tests/test_repo_invariants.py` into the
   new contract: assert `userConfig` EXISTS with the 5 keys + `password` is
   `sensitive`; assert `mcpServers` args reference `${user_config.*}` for the 4
   non-secret fields + env injects `REDSHIFT_PASSWORD`; keep asserting NO
   `--profile` pin. Version-sync test (`test_pyproject_plugin_version_sync`) stays.

## Current State Evidence
(file:line)

- **Forward**: inline branch fires when host+user+dbname present, password from
  `REDSHIFT_PASSWORD` (`src/redshift_comment_mcp/server.py:48-56`). `${user_config.*}`
  feeds exactly this — likely **zero server change** (see Risk #1 for the one caveat).
- **Reverse / SSOT**: version dual-sourced — `.claude-plugin/plugin.json` `"version"`
  + `pyproject.toml` `fallback_version` (both 0.7.1); CLAUDE.md mandates lockstep.
  Current `mcpServers` (`plugin.json:20-30`) launches `uv run --project
  ${CLAUDE_PLUGIN_ROOT} redshift-comment-mcp` with no connection args.
- **Error**: empty/blank optional fields → see Risk #1 (`--port ""` int-parse;
  literal-vs-empty substitution). Profile mode + `setup_via_dialog` remain the
  fallback when inline args are absent.
- **Data**: userConfig schema (type/title/description/sensitive/required/default/
  min/max); `${user_config.KEY}` → args/env; values also exported as
  `CLAUDE_PLUGIN_OPTION_<KEY>`. Sensitive → keychain (~2KB).
- **Boundary**: Claude Code plugin runtime (enable-time dialog); OS keychain; the
  existing `uv run` launch; `setup_via_dialog`/profile system (coexists, untouched).

Evidence paths: `.claude-plugin/plugin.json`, `src/redshift_comment_mcp/server.py`,
`pyproject.toml`, `tests/test_repo_invariants.py`.

## Decision

Pivot from `.mcpb` to a `userConfig` block in the existing `plugin.json`, injecting
values into the existing `mcpServers` to drive the server's inline mode. Bump to
0.8.0. Update docs. Fields are **optional** (resolved) — blank falls back to the
existing profile/`setup_via_dialog` path.

**⚠️ This consciously REVERSES the D2 refactor (commit `3884f98`, v0.4.0)**, which
removed `userConfig` because Claude Code had no secret type (password → plaintext
`settings.json`). That blocker is gone: `sensitive: true` now routes to the OS
keychain. D2 also removed only a *profile-name* userConfig (indirection); this
re-adds *connection-field* userConfig (value-bearing), optional + backward-compatible.
The two D2 guard tests in `tests/test_repo_invariants.py`
(`test_plugin_manifest_has_no_user_config`, `test_plugin_manifest_mcp_args_have_no_profile_flag`)
must be **rewritten** into the new contract (userConfig allowed; password MUST be
`sensitive`; still no `--profile` pin), not deleted. See memory
`project_d2_userconfig_reversal`.

## Out of Scope

- `.mcpb` Desktop Extension / `user_config` form (only for non-Claude-Code Desktop).
- `server.json` / official registry.
- Multi-profile via the dialog (form = one connection; multi-profile stays CLI).
- Removing/altering `setup_via_dialog`, profile system, keychain CLI — they remain.

## Alternatives Considered
(Axis 4)

1. `.mcpb` user_config form — true GUI panel, but Python packaging + uv-on-Desktop
   bugs + only serves non-Claude-Code Desktop users. Deferred.
2. `server.json` registry — discoverability only, no form, not in their channel. Dropped.
3. **plugin.json `userConfig` (CHOSEN)** — in-channel, ~zero packaging, keychain-backed,
   reuses inline mode.

## What Becomes Obsolete
(Axis 5)

Nothing removed. Docs should note the enable-time prompt is now the default
setup path, with `/redshift-setup` (chat) and the CLI as the alternates — keep
them coherent, don't let three setup stories fragment the README.

## Open Questions / Risks
(resolve in writing-plans; the fork below needs a user decision)

1. **[RESOLVED → Optional + server hardening]** Fields are **optional**: filled →
   inline mode; blank → existing profile/`setup_via_dialog` path (backward
   compatible, multi-profile preserved). In scope as a result:
   - (a) verify Claude Code substitutes an unset optional field to empty string
     (not the literal `${user_config.host}`);
   - (b) **server guard** (TDD-able): empty inline args — especially `--port ""`
     (int parse) — must fall back to profile mode cleanly, never crash. This is
     the one small, test-first server change in this work.
2. **Verify substitution + rendering**: does the enable-time dialog render as input
   fields in the VS Code extension (not just CLI text)? What does an unset optional
   value substitute to? Resolve before finalizing field requiredness.
3. **Bump level**: MINOR (0.8.0) — new user-visible capability.
