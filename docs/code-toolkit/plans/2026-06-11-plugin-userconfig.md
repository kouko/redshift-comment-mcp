# Plan: plugin.json userConfig (reverse D2)

Source brief: docs/code-toolkit/specs/2026-06-11-plugin-userconfig.md
Total tasks: 4
Critical-path depth: 2 (≤5) — longest chain: Task 2 → Task 3 (and Task 2 → Task 4)
Execution order: parallel-where-possible (T1 ∥ T2 at level 0; then T3 ∥ T4)
Plan-document-reviewer verdict: PASS (2026-06-11, 14/14; 1 advisory note — T3∥T4 parallel-eligible after T2)

## Task 1 — Harden inline-arg ingestion (empty / placeholder → profile fallback)
- Description: In `server.py`, make connection-arg ingestion tolerant of the
  empty strings (and any unsubstituted `${user_config.*}` literal) that an
  optional userConfig produces. Add a port parser used as argparse `type=` that
  maps "" / non-numeric to the 5439 default instead of crashing; normalize
  host/user/dbname/port so empty-or-placeholder values count as "unset" in the
  inline-completeness check, falling back to profile mode. Valid inline args and
  a valid `--port` must still work unchanged.
- Module: server (resolve_connection_params + port-parse helper)
- Files touched: src/redshift_comment_mcp/server.py, tests/test_server_resolution.py
- Context paths:
  - src/redshift_comment_mcp/server.py (resolve_connection_params L48-56; --port arg L156)
  - tests/test_server_resolution.py (existing _ns() helper + inline-mode tests)
- Acceptance:
  - RED: new parametrized test (e.g. `test_inline_args_empty_or_placeholder_fall_back_to_profile`)
    in tests/test_server_resolution.py — cases: empty `--port ""` does not raise;
    empty host/user/dbname → profile mode; literal `${user_config.host}` → treated
    as unset → profile mode. Plus a case asserting a real `--port "5439"` and full
    real inline args still resolve to inline.
  - GREEN: all new cases pass AND existing test_server_resolution.py tests stay green.
- External surfaces: none (internal arg-resolution logic; stdlib argparse only).
- Dependencies: none
- Independent: true
- Brief item covered: "(b) server guard … empty inline args — especially `--port ""`
  (int parse) — must fall back to profile mode cleanly, never crash."

## Task 2 — Rewrite D2 guard tests + add userConfig to plugin.json
- Description: Rewrite the two D2 guard tests in tests/test_repo_invariants.py into
  the reversed contract, THEN edit .claude-plugin/plugin.json to satisfy them: add a
  top-level `userConfig` with 5 optional fields — host (string), port (number,
  default 5439), user (string), dbname (string), password (string, `sensitive: true`),
  each with title + description; inject `--host ${user_config.host} --port
  ${user_config.port} --user ${user_config.user} --dbname ${user_config.dbname}` into
  `mcpServers."redshift-comment".args` and add `env: { "REDSHIFT_PASSWORD":
  "${user_config.password}" }`. Update the D2-contract comment block to describe the
  reversal.
- Module: plugin-manifest contract
- Files touched: tests/test_repo_invariants.py, .claude-plugin/plugin.json
- Context paths:
  - tests/test_repo_invariants.py (D2 guards L181-222; version-sync L161-178)
  - .claude-plugin/plugin.json (mcpServers L20-30)
  - memory project_d2_userconfig_reversal (why this is intentional)
- Acceptance:
  - RED: rewritten `test_plugin_manifest_has_connection_userconfig` asserts
    `userConfig` present with the 5 keys and `password.sensitive is True`
    (fails against current no-userConfig plugin.json); rewritten mcp-args test
    asserts args contain `${user_config.host/port/user/dbname}` + env
    `REDSHIFT_PASSWORD` == `${user_config.password}` AND still no `--profile`.
  - GREEN: plugin.json edited to satisfy both; full tests/ suite green.
- External surfaces: Claude Code plugin manifest schema — `userConfig` field
  (type/title/description/sensitive) + `${user_config.*}` substitution into
  mcpServers args/env. Verify key casing against
  https://code.claude.com/docs/en/plugins-reference §User configuration.
- Dependencies: none
- Independent: true
- Brief item covered: Smallest End State #1 (userConfig block + injection) and #5
  (rewrite the two D2 guard tests into the new contract).

## Task 3 — Bump version 0.7.1 → 0.8.0 (both fields)
- Description: Bump `.claude-plugin/plugin.json` `"version"` and `pyproject.toml`
  `[tool.setuptools_scm] fallback_version` from 0.7.1 to 0.8.0 (MINOR — new
  user-visible capability), per CLAUDE.md's two-fields-move-together rule.
- Module: release metadata
- Files touched: .claude-plugin/plugin.json, pyproject.toml
- Context paths:
  - .claude-plugin/plugin.json (version field)
  - pyproject.toml ([tool.setuptools_scm] fallback_version = "0.7.1")
  - tests/test_repo_invariants.py (test_pyproject_plugin_version_sync L161-178)
- Acceptance:
  - RED: `test_pyproject_plugin_version_sync` fails if only one field is bumped.
  - GREEN: both fields read "0.8.0"; version-sync test green; `grep -R 0.8.0`
    confirms both.
- External surfaces: none (version string literals).
- Dependencies: Task 2 completes first (shares .claude-plugin/plugin.json — edit
  after the userConfig block lands to avoid a write conflict).
- Independent: false
- Brief item covered: Smallest End State #3 (bump 0.7.1 → 0.8.0, both fields).

## Task 4 — Update root READMEs (×3) for the enable-time connection prompt
- Description: Update README.md / README.ja.md / README.zh-TW.md so the install
  flow documents that enabling the plugin now prompts for the Redshift connection
  (host/port/user/dbname + password); reconcile with the existing `/redshift-setup`
  chat flow and the "Other install paths" section so the three setup stories stay
  coherent (the prior text claims a deliberate zero-userConfig design — update it,
  don't leave it contradicting the new behavior). Do not hardcode the version number.
- Module: docs (root READMEs)
- Files touched: README.md, README.ja.md, README.zh-TW.md
- Context paths:
  - README.md (install / "Other install paths" section)
  - README.ja.md, README.zh-TW.md (trilingual mirrors)
- Acceptance:
  - RED: a reviewer/grep diagnostic — each README still describes the pre-D2
    "no form" install and lacks an enable-time-prompt description.
  - GREEN: all three READMEs describe the enable-time connection prompt coherently;
    `test_no_dead_skill_references` and the README trilingual-parity invariants in
    tests/test_repo_invariants.py stay green.
- External surfaces: none (prose docs).
- Dependencies: Task 2 completes first (doc-mirrors-code — describes the userConfig
  added in Task 2; disjoint files from Task 3, so Task 3 ∥ Task 4).
- Independent: false
- Brief item covered: Smallest End State #4 (READMEs document the enable-time
  prompt) + What Becomes Obsolete (keep the three setup stories coherent).

## Notes

- **Manual verification gate (NOT SDD-dispatched; no RED test).** After Task 2,
  install the working-tree plugin into Claude Code (VS Code) and confirm: (a) the
  enable-time dialog renders and collects the 5 fields; (b) the `sensitive`
  password lands in the OS keychain / `~/.claude/.credentials.json` — NOT plaintext
  in settings.json (this is the premise that reverses D2); (c) an UNSET optional
  field substitutes to empty string, not the literal `${user_config.host}`. Task 1
  hardens for BOTH the empty and literal cases, so a "literal" outcome here is
  tolerated, not a blocker.
- **Test tiers** (CLAUDE.md): Tasks 1–3 are pure logic / repo-invariants → run
  `uv run pytest tests/ --ignore=tests/integration --ignore=tests/e2e`. No live
  Redshift needed; e2e/registration shape is unaffected by this work.
- **Parallelism**: level 0 = Task 1 ∥ Task 2 (disjoint files, no semantic dep);
  level 1 = Task 3 ∥ Task 4 (both depend on Task 2; disjoint files; docs don't
  reference the version number).
