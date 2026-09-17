# Kickoff Defaults

> Minted from loom-code's contract package. From that moment it is
> THIS repo's own file — it never syncs back to the plugin; edit it
> freely.

<!-- One line per key, grammar `- <key>: <value> — <reason> (<date>)`.
Keys are declared in loom-code/contract/manifest.yaml `kickoff_defaults`;
loom_checker.py reads this file. Absent key = default. -->

- second-vendor: suggest — default non-blocking visibility (2026-09-17)
- package-tests: uv run --extra dev pytest tests/ --ignore=tests/integration --ignore=tests/e2e — the live-cluster tiers stay opt-in behind REDSHIFT_INTEGRATION=1, so the default suite is the unit tier; `--extra dev` is what installs pytest, and without it the command falls through to whatever pytest is on PATH (2026-09-17)
