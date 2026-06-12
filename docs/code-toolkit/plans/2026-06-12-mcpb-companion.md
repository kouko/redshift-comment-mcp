# Plan: companion .mcpb Desktop Extension (uv-type)

Source brief: docs/code-toolkit/specs/2026-06-12-mcpb-companion.md
Total tasks: 5 (SDD code) + 1 post-merge release action (Notes, human)
Critical-path depth: 2 (≤5) — longest chain: Task 3 (generator) → Task 4/Task 5
Execution order: parallel-where-possible (T1, T3, T5 at level 0; T2, T4 depend on T3)
Plan-document-reviewer verdict: PASS (2026-06-12, 14/14). Amendment after PASS: flipped T4/T5
`Independent: true → false` (they depend on T3) per reviewer note — additive/schema-correctness
only, DAG and Files-touched unchanged, re-review skipped.

## Task 1 — mcpb adapter (env → argv)
- Description: Add `mcpb/server/main.py` — the `.mcpb` entry point. Define a pure
  `build_argv(environ) -> list[str]` that maps `REDSHIFT_HOST/PORT/USER/DBNAME` env vars
  into `["redshift-comment-mcp","--host",H,"--port",P,"--user",U,"--dbname",D]` (omit a
  flag when its env var is absent/empty). Under `if __name__ == "__main__":` lazily import
  `redshift_comment_mcp.server.main`, set `sys.argv = build_argv(os.environ)`, call `main()`.
  Password stays in `REDSHIFT_PASSWORD` env (inline mode reads it; not in argv). Keep
  `main` import inside `__main__` so `build_argv` is importable without the heavy server.
- Module: mcpb/server/main.py
- Files touched: mcpb/server/main.py, tests/test_mcpb_adapter.py
- Context paths:
  - src/redshift_comment_mcp/server.py (inline mode L48-56 — the contract build_argv targets)
  - /tmp/redshift-mcpb-spike/server/main.py (the proven spike adapter to adapt from)
- Acceptance:
  - RED: tests/test_mcpb_adapter.py::test_build_argv_maps_env_to_inline_flags — loads
    build_argv (via importlib by path) and asserts: full env → correct ordered argv;
    missing REDSHIFT_HOST → no `--host`; empty string → omitted. Fails (file absent).
  - GREEN: build_argv returns the expected argv lists; test passes.
- External surfaces: none (stdlib os/sys; imports the project's own package).
- Dependencies: none
- Independent: true
- Brief item covered: Smallest End State — "thin `server/main.py` adapter reading REDSHIFT_*
  env, server.type uv" (the spike's proven env→argv adapter).

## Task 2 — docs ×3 (the .mcpb install path)
- Description: Update README.md / README.ja.md / README.zh-TW.md to add the Claude Desktop
  `.mcpb` install path (download `.mcpb` from GitHub Releases → install in Claude Desktop →
  fill the connection form), alongside the existing Claude Code plugin path. State the `uv`
  prerequisite. Clarify "install ONE of: the plugin (for skills) OR the `.mcpb` (for the
  desktop config form)". Apply equivalent edits to all three languages (trilingual parity).
- Module: docs (root READMEs)
- Files touched: README.md, README.ja.md, README.zh-TW.md
- Context paths:
  - README.md (Quick start / "Other install paths" sections)
  - docs/code-toolkit/specs/2026-06-12-mcpb-companion.md (the settled design + naming)
- Acceptance:
  - RED: diagnostic — the three READMEs lack any `.mcpb` / Desktop-extension install section.
  - GREEN: all three describe the `.mcpb` path + `uv` prereq + "install one of"; the
    trilingual-parity + dead-reference invariants in tests/test_repo_invariants.py stay green.
- External surfaces: none (prose).
- Dependencies: none
- Independent: true
- Brief item covered: Smallest End State — "Document a 'two install paths' story (plugin for
  skills / `.mcpb` for the Desktop form)".

## Task 3 — manifest/bundle generator script
- Description: Add `scripts/generate_mcpb_manifest.py` (Python, stdlib only). Reads the root
  `pyproject.toml` version (the SSOT) + name, and writes the generated bundle files into
  `mcpb/`: `manifest.json` (manifest_version "0.4", name "redshift-comment-mcp", display_name
  "Redshift Comment MCP", author, server.type "uv", entry_point "server/main.py", mcp_config
  with command "uv" + args running the entry_point + env injecting `REDSHIFT_*` via
  `${user_config.X}`, and user_config: host/user/dbname string-required, port number default
  5439, password string sensitive required), `pyproject.toml` (dependencies =
  ["redshift-comment-mcp==<root version>"]), and `.mcpbignore` (.venv/ server/lib/ server/venv/
  __pycache__/). Single-sources the version from root pyproject.
- Module: scripts/generate_mcpb_manifest.py
- Files touched: scripts/generate_mcpb_manifest.py, tests/test_mcpb_manifest.py
- Context paths:
  - pyproject.toml ([tool.setuptools_scm] fallback_version — the version SSOT)
  - docs/code-toolkit/specs/2026-06-12-mcpb-companion.md (manifest shape, verified vs MANIFEST.md)
- Acceptance:
  - RED: tests/test_mcpb_manifest.py::test_generator_emits_valid_uv_manifest — runs the
    generator, asserts manifest_version=="0.4", name=="redshift-comment-mcp", version==root
    pyproject version, server.type=="uv", user_config has the 5 keys with
    password.sensitive is True, mcp_config.env injects REDSHIFT_PASSWORD=="${user_config.password}";
    asserts the generated bundle pyproject pins `redshift-comment-mcp==<root version>`. Fails (no script).
  - GREEN: generator produces those files; test passes. (Manual cross-check: `mcpb pack` on the
    generated mcpb/ passes schema validation — already confirmed in the spike.)
- External surfaces: Claude Desktop Extensions MCPB manifest schema (manifest_version "0.4",
  server.type "uv", user_config object, ${user_config.X} injection) — grounded in
  https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md + the passed spike.
- Dependencies: none
- Independent: true
- Brief item covered: Smallest End State — "manifest is GENERATED (auto from pyproject)" +
  the mcpb/ artifact (manifest + bundle pyproject + .mcpbignore).

## Task 4 — version-sync invariant
- Description: Extend tests/test_repo_invariants.py with a test that runs the generator
  (Task 3) and asserts the generated mcpb manifest's `version` equals BOTH the pyproject
  `fallback_version` AND the plugin.json `version` (the existing two-field SSOT) — i.e. the
  `.mcpb` is a 4th surface but auto-derived, so it can't drift.
- Module: tests/test_repo_invariants.py
- Files touched: tests/test_repo_invariants.py
- Context paths:
  - tests/test_repo_invariants.py (existing test_pyproject_plugin_version_sync L161-178)
  - scripts/generate_mcpb_manifest.py (the generator from Task 3)
- Acceptance:
  - RED: test_mcpb_manifest_version_matches_sources — fails before Task 3's generator exists
    (import error) / before the assertion is added.
  - GREEN: generates the manifest, asserts version == pyproject fallback_version == plugin.json
    version; full tests/ suite green.
- External surfaces: none (stdlib tomllib/json; runs the in-repo generator).
- Dependencies: Task 3 completes first (imports/runs the generator).
- Independent: false  # depends on Task 3 (runs its generator)
- Brief item covered: Smallest End State — "invariant test verifies generated manifest version
  == pyproject" (version-sync extended to the manifest surface).

## Task 5 — CI: pack .mcpb on release
- Description: Add a GitHub Actions job (in .github/workflows/publish.yml or a sibling
  workflow) that, on `release`, runs `python scripts/generate_mcpb_manifest.py` then
  `npx -y @anthropic-ai/mcpb pack mcpb dist/redshift-comment-mcp.mcpb`, then uploads the
  `.mcpb` as a GitHub Release asset (e.g. `gh release upload` / softprops action). Order it
  to run AFTER the existing PyPI publish job (the bundle pins the just-published version),
  e.g. `needs: publish`.
- Module: .github/workflows (publish.yml or new pack-mcpb.yml)
- Files touched: .github/workflows/publish.yml
- Context paths:
  - .github/workflows/publish.yml (existing release → PyPI publish job; the `needs:` anchor)
  - scripts/generate_mcpb_manifest.py (generator from Task 3)
- Acceptance:
  - RED: diagnostic — no workflow job runs the generator + `mcpb pack` + uploads a `.mcpb`.
  - GREEN: a job exists that generates → packs → uploads the `.mcpb` to the release, gated
    `needs: publish` (runs after PyPI publish); YAML parses (e.g. `python -c "import yaml,sys;
    yaml.safe_load(open('.github/workflows/publish.yml'))"`).
- External surfaces: GitHub Actions workflow schema + `@anthropic-ai/mcpb` CLI (`mcpb pack`)
  + `gh release upload` — grounded in the mcpb README + GitHub Actions docs.
- Dependencies: Task 3 completes first (CI invokes the generator).
- Independent: false  # depends on Task 3 (CI invokes its generator)
- Brief item covered: Smallest End State — "`mcpb pack` in CI, attach `.mcpb` to GitHub Release".

## Notes

- **Post-merge release action (human, NOT SDD-dispatched; needs user approval — outward/PyPI).**
  After Tasks 1–5 merge, cut a **v0.9.0 GitHub Release** (`gh release create v0.9.0`). This:
  (a) fires the existing `publish.yml` → publishes **0.9.0 to PyPI** (fixing the standing gap —
  PyPI is currently stuck at 0.7.1 because 0.8.0/0.9.0 were never released), and (b) triggers
  the new Task-5 job → packs the `.mcpb` (pinning 0.9.0, now on PyPI) and attaches it to the
  release. The bundle-pin↔PyPI consistency holds because the publish job runs before the pack job.
- **Final manual install verification (human gate):** after the release, download the released
  `.mcpb`, install on Claude Desktop, fill the form, and confirm a real DB tool (`list_schemas`)
  connects — the same end-to-end check the spike already passed, now against the released artifact.
- **Parallelism**: level 0 = Task 1 ∥ Task 2 ∥ Task 3 (disjoint files, no semantic dep);
  level 1 = Task 4 ∥ Task 5 (both depend on Task 3; disjoint files: test_repo_invariants.py
  vs .github/workflows/). Critical-path depth = 2.
- **Server package unchanged**: the adapter lives in the bundle (mcpb/server/main.py); the
  generated bundle pyproject installs the published package via uv. Per CLAUDE.md, this is a
  MINOR-or-additive distribution feature on top of 0.9.0; the release itself is 0.9.0 (the
  bump already on main) — the `.mcpb` ships with that release, no extra version bump needed.
