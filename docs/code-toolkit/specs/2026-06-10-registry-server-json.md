# Brief — Publish redshift-comment-mcp to the official MCP Registry (server.json)

> **⚠️ SUPERSEDED (2026-06-10).** During brainstorming the user clarified two
> things that invalidate this brief's premise: (1) their only distribution
> channel is the Claude Code plugin marketplace (`add <repo URL>` → install),
> where `server.json` plays no role; (2) their actual goal is a **pure-GUI
> connection-config experience for Claude Desktop users** (cited Tableau MCP's
> Settings form as the target). `server.json` delivers neither. The live brief
> is **[2026-06-10-mcpb-desktop-extension.md](2026-06-10-mcpb-desktop-extension.md)**.
> This file is kept for the decision trail.

Date: 2026-06-10
Stage: brainstorming → (next) writing-plans
Decision locked in conversation: **do server.json now, defer the .mcpb Desktop Extension.**

## Problem
(Axis 1 — JTBD)

Today `redshift-comment-mcp` is only frictionlessly installable inside **Claude Code**
(via the `.claude-plugin` marketplace). A user on any other MCP-aware client —
especially **Claude Desktop** — cannot *discover* the server, and has no
declarative description of *what connection parameters it needs* to wire it up.

> When I run an MCP client that isn't Claude Code, I want to find this server and
> know exactly which connection fields it expects, so I can install and configure
> it without reading the source or hand-crafting a launch command.

The chosen instrument is the official **MCP Registry `server.json`**: a
vendor-neutral, declarative parameter spec that registry-aware hosts read to
discover the server and render/collect its inputs (args + env), then launch it.

## Users
(Axis 2)

- **Primary**: operators of registry-aware MCP clients (Claude Desktop manual
  config, VS Code, Cursor, registry browsers) who want to find + install the
  server and see its required connection fields up front.
- **Secondary**: the maintainer (kouko), who must keep one more distribution
  artifact version-synced with the existing two.
- Not in this round: non-technical Claude Desktop users who need a *Settings-panel
  form* — that's the deferred MCPB work.

## Smallest End State
(Axis 3)

A repo-root `server.json`, validated against the official schema and published to
the registry, that:
1. points at the existing **PyPI** package run via **uvx** (`uvx redshift-comment-mcp`),
2. declares the four connection args (`--host` / `--port` / `--user` / `--dbname`) and
   one secret env var (`REDSHIFT_PASSWORD`, `isSecret: true`),
3. stays version-consistent with the other two version fields via a repo-invariant test,
4. is published via a CI path (prefer GitHub OIDC — no stored secret) on release,
   mirroring the existing `publish.yml` trigger.

**Server code is NOT changed** — the existing inline mode
(`--host/--user/--dbname` + `REDSHIFT_PASSWORD`) is already the exact shape
`server.json` declares.

## Current State Evidence
(file:line citations from recon)

- **Forward** (entry → behavior): `[project.scripts] redshift-comment-mcp =
  redshift_comment_mcp.server:main` (pyproject.toml) → `main()` parses args →
  `resolve_connection_params` takes the **inline branch** when host+user+dbname
  are all present, password from `--password` or `REDSHIFT_PASSWORD` env
  (`src/redshift_comment_mcp/server.py:48-56`). This IS the launch contract
  server.json will declare.
- **Reverse** (SSOT / dependents): version is **already dual-sourced** —
  `.claude-plugin/plugin.json` `"version"` (0.7.1) and `pyproject.toml`
  `[tool.setuptools_scm] fallback_version` (0.7.1); `CLAUDE.md` mandates they
  move together. **server.json adds a THIRD version field** that must join the
  sync discipline. PyPI release is driven by `.github/workflows/publish.yml`
  on `release: [published, released]`.
- **Error** (failure modes): inline mode without a password raises
  `ConfigurationError` (`server.py:51-55`). New failure surface from publishing:
  schema-validation failure, namespace-auth failure, and **package-ownership
  verification** failure at `mcp-publisher publish` time.
- **Data** (shapes): server.json schema `2025-12-11`; `packageArguments` (named
  `--host`/`--port`/`--user`/`--dbname`, `--port` `format:number` default 5439)
  + `environmentVariables` (`REDSHIFT_PASSWORD`, `isRequired:true`,
  `isSecret:true`). Maps 1:1 to the inline-mode tuple
  `(host, port, user, password, dbname)`.
- **Boundary** (external systems): **PyPI** — package present (`GET
  pypi.org/pypi/redshift-comment-mcp/json` → 200), `uvx` entry point exists;
  **MCP Registry API** + `mcp-publisher` CLI; **GitHub OIDC** for secret-free CI
  publish; namespace `io.github.kouko/...` (matches the GitHub-auth requirement).

Evidence paths: `pyproject.toml`, `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, `.github/workflows/publish.yml`,
`src/redshift_comment_mcp/server.py`, `src/redshift_comment_mcp/connection.py`,
`tests/test_repo_invariants.py` (existing version-sync invariant precedent).

## Decision

Author a repo-root `server.json` (schema 2025-12-11) declaring the pypi/uvx
package with the four named connection args + the `REDSHIFT_PASSWORD` secret env;
add a repo-invariant test asserting server.json's version matches the other two
version fields AND its declared args match the server's argparse surface; wire
registry publishing into CI via GitHub OIDC on release; update the three READMEs
with the registry-discoverability note + a `claude_desktop_config.json`
uvx-launch snippet (so Desktop users have a working manual path today). We do
**not** build the MCPB Desktop Extension / `user_config` form this round.

## Out of Scope

- `.mcpb` Desktop Extension + `user_config` Settings-panel form (deferred; revisit
  after the uvx path is validated in the wild).
- Multi-profile support in any GUI/form surface — stays a Claude Code + CLI feature.
- Any change to password handling or `setup_via_dialog` (osascript/zenity → keychain).
- Rewriting the server in Node to get the bundled-runtime story.

## Alternatives Considered
(Axis 4 — WebSearch EN + JA)

1. **MCPB `.mcpb` with user_config form, Python-bundled** — true Desktop form, but
   Claude Desktop bundles Node not Python; native wheels (`redshift_connector`,
   `awswrangler`, `pandas`) can't be portably bundled; official Python-DXT guidance
   still undefined ([mcpb#89](https://github.com/modelcontextprotocol/mcpb/issues/89)).
   Rejected for now — highest friction, lowest certainty.
2. **MCPB shelling to uvx** — lighter, but requires `uv` on the user's machine,
   which undercuts the "non-technical, no-prereq" goal. Deferred with #1.
3. **server.json → official Registry (CHOSEN)** — cheapest, server code unchanged,
   matches the dominant Python-MCP distribution pattern (uvx); JA consensus
   "[Python MCP は uv/uvx 一択](https://zenn.dev/acntechjp/articles/1bc192050848fc)".
   EN/Anthropic guidance and JA guidance agree uvx is the pragmatic Python path.

My take: ship #3 now; #1/#2 become a separate, de-risked follow-up.

## What Becomes Obsolete
(Axis 5)

- Nothing is removed — this is additive distribution metadata. **Flag**: the
  READMEs currently imply "Claude Code plugin" is the only install path; after
  this, docs must present **three** paths (Claude Code plugin / uvx manual config /
  registry) coherently, or the docs fragment. Doc reconciliation is in-scope.

## Open Questions
(resolve in writing-plans)

1. **Package-ownership verification**: how does `mcp-publisher publish` prove we
   own the PyPI `redshift-comment-mcp` package? (Likely an `mcpName`/registry
   metadata field that must ship in a *new* PyPI release before the registry
   accepts it — may add a release dependency.)
2. **Publish mechanism**: one-time local `mcp-publisher login github` + `publish`,
   vs a GitHub OIDC Action wired into the release flow. Recommend CI/OIDC to match
   `publish.yml`, but confirm ordering (PyPI publish must land before registry
   publish so version exists).
3. **Version bump level**: additive packaging metadata — PATCH or MINOR per
   `CLAUDE.md` table? (Leaning MINOR: new distribution capability.)
4. **uvx runtime declaration**: confirm exact `server.json` `runtimeHint`/package
   field values against the live `2025-12-11` schema before publishing.
