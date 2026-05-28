# Project guidance for Claude Code

Conventions and pitfalls specific to this repo. The global preferences
in `~/.claude/CLAUDE.md` still apply; this file overrides or adds to
them where the project's needs differ.

## Version bumping (MUST)

This plugin has **two** version fields that must move together. Forgetting
either ships an inconsistent release:

- `.claude-plugin/plugin.json` — `"version"` field (Claude Code plugin
  marketplace + install UI read this)
- `pyproject.toml` — `[tool.setuptools_scm]` `fallback_version` field
  (the source `uv run` / `pip install` see when there is no `.git`
  directory, e.g. Claude Code's plugin cache install path)

**When to bump** (pick one per release, semver):

| Change shape | Bump |
|---|---|
| Backward-incompatible signature change, removed tool, breaking config / format change | MAJOR (`0.x.y` → `(x+1).0.0` while pre-1.0, semantically still "breaking") |
| New tool, new field on a tool response, new skill, new server `instructions` directive, additive behavior | MINOR (`x.y.z` → `x.(y+1).0`) |
| Bug fix, doc fix, test-only change | PATCH (`x.y.z` → `x.y.(z+1)`) |

Tests-only / docs-only / chore commits can ride the next feature bump —
don't open a PR just to bump for a doc typo.

**Bundle accumulated changes if needed.** If multiple MINOR / PATCH-level
PRs have merged since the last bump without one, the next bump rolls them
all up under the highest applicable level. Example: three PATCHes plus
one MINOR since `0.4.0` → ship `0.5.0` (MINOR shadows PATCH).

**Always bump on the same PR as the user-visible change.** Splitting the
bump into a separate "release" PR loses the correlation (which PR
introduced which feature) and risks shipping unbumped code if the bump
PR slips. The only acceptable exception: chore PRs that have no
user-visible effect.

## Release publishing (MUST)

Bumping the two version fields is **not** shipping. The plugin path
(`claude plugin install`) runs from cloned-repo source, so it sees the
bump the moment the PR merges. The PyPI path (used by Claude Desktop +
other MCP clients via `uvx redshift-comment-mcp`) only updates when
these three steps run after the bump PR merges to `main`:

1. Tag the merge commit and push the tag:
   ```bash
   git tag vX.Y.Z       # e.g. v0.5.0 — must match plugin.json + fallback_version
   git push origin vX.Y.Z
   ```
2. **GitHub Releases → Create release from `vX.Y.Z` → ✅ check "Set as a
   pre-release" → Publish.** This triggers
   [.github/workflows/test-publish.yml](.github/workflows/test-publish.yml)
   → TestPyPI smoke test. Wait for the workflow run to go green.
3. **Edit the same release → ❌ uncheck "Set as a pre-release" →
   Update.** This triggers
   [.github/workflows/publish.yml](.github/workflows/publish.yml) →
   PyPI live.

Verify after step 3:
```bash
curl -s https://pypi.org/pypi/redshift-comment-mcp/X.Y.Z/json | jq .info.version
```

Skipping these steps silently desyncs the two distribution channels —
exactly what happened between v0.3.0 and v0.5.0 (plugin shipped, PyPI
stuck two minor versions behind). Full SOP, manual `workflow_dispatch`
fallback, and troubleshooting:
[.github/DEPLOYMENT.md](.github/DEPLOYMENT.md).

**PyPI uploads are irreversible.** Once `vX.Y.Z` exists on PyPI, you
cannot re-upload that version (even after `yank`). The pre-release →
TestPyPI dry-run in step 2 is what protects you; don't skip it.

## Tests live in three tiers

- `tests/` — unit, runs by default
- `tests/integration/` — live Redshift cluster, opt-in via
  `REDSHIFT_INTEGRATION=1`
- `tests/e2e/` — MCP wire protocol against a real cluster, same opt-in

Run the right tier(s) for the change before merging:

| Change touches | Run |
|---|---|
| Pure code logic | `uv run pytest tests/ --ignore=tests/integration --ignore=tests/e2e` |
| Anything that hits Redshift catalog SQL or `wr.redshift.read_sql_query` | also `REDSHIFT_INTEGRATION=1 uv run pytest tests/integration/` |
| MCP server `instructions`, tool registration, response field shape, FastMCP serialization | also `REDSHIFT_INTEGRATION=1 uv run pytest tests/e2e/` |

E2E spawns a subprocess per test — ~5s for the four tests. Don't add
breadth tests there; that's the integration tier's job.

## Profile system gotchas

The active-profile resolution chain (most explicit wins):

```
--profile CLI flag > REDSHIFT_COMMENT_PROFILE env > ~/.config/.../active-profile file > implicit fallback
```

Implicit fallback rules (`resolve_active_profile`):
1. `"default"` if it exists in config.toml
2. Else if exactly one profile exists, use it (upgrade rescue for
   pre-PR-22 users)
3. Else return `"default"` as literal so server raises a clear error

Don't push implicit fallback to the explicit branches — explicit user
input should be honored verbatim so typos surface as typos, not as
"silently redirected to the lone profile."
