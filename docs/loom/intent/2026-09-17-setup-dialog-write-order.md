# setup_via_dialog must not leave a half-written profile behind
originator: kouko
kind: engineering
needs-design: no — no interface surface changes; the tool's argument list and all ten response shapes stay identical, and config.toml's format is unchanged. Only the order of two internal writes moves.
evidence: [docs/loom/audits/2026-09-17-credential-audit.md]
status: confirmed 2026-09-17
publication: automatic — authorized 2026-09-17 by kouko

## Problem
`setup_via_dialog` (src/redshift_comment_mcp/redshift_tools.py:1327) writes the
caller-supplied host/port/user/dbname into config.toml *before* it opens the
password dialog at :1350. Every failure branch after that point — dialog
cancelled, macOS Apple Events blocked, no dialog tool, unsupported platform,
empty password — returns at :1356-1361 without restoring the previous profile,
and `cfg.set_password` at :1364 is never reached.

The profile is therefore left pointing at the new host while the keychain still
holds the *previous* password, which is still valid. `get_setup_status` reports
`configured: true` for this state, and the next DB tool call authenticates to
the new host with the user's existing Redshift password.

An agent reaches this state without malice: the server's own `instructions`
(redshift_tools.py:505-545) tell it to call `setup_via_dialog` proactively, and
this server's charter makes table comments authoritative ("trust the comment
over the name"), so comment text is an input channel that can influence which
host an agent passes. A single user "Cancel" completes the sequence.

Shipped in commit 0a77873f (2026-05-29, v0.7.0) — the ordering has been present
since the tool was introduced, across v0.7.0, v0.7.1, v0.9.0 and v0.10.0, all
published to PyPI. No existing test asserts what config.toml contains after a
failed call.

## Proposed outcome
A `setup_via_dialog` call that does not reach a stored password leaves the
profile store exactly as it was before the call.

## Acceptance
1. After a `setup_via_dialog` call whose password step fails for any of the five
   failure reasons, config.toml is byte-identical to its content before the call.
2. After such a call, the keychain entry for the named profile is unchanged.
3. A `setup_via_dialog` call that completes successfully still writes
   host/port/user/dbname and the password, and still reports the connection-test
   result, with all ten response shapes unchanged from v0.10.0.
4. The failure case is covered by a test that fails against the pre-change code.

## Constraints
- The password value must not be written to argv, logs, stdout, or any MCP
  response, as the repository already requires.
- The ten documented response shapes keep their existing field names and their
  `status` / `error` strings: seven `status` values (`configured`,
  `configured_but_connection_failed`, `dialog_cancelled`, `permission_denied`,
  `dialog_unavailable`, `platform_unsupported`, `empty_password`) and three
  `error` values (`missing_field`, `write_profile_failed`,
  `keychain_write_failed`).
- Tests run under `uv run --extra dev pytest`; the live-cluster tiers stay
  opt-in behind `REDSHIFT_INTEGRATION=1`.

## Out of scope
- How the server chooses between inline and profile connection modes.
- The password-collection mechanism itself (OS dialog, stdin, getpass).
- The duplicate dialog implementation in skills/redshift-setup/references/.
- Any change to `get_setup_status`.

## Open questions
- none
