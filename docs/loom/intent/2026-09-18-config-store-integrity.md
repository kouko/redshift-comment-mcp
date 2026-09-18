# config.toml writes must not lose a profile or truncate the file
originator: kouko
kind: engineering
needs-design: no — config.py is not under any declared interface-surface glob; the profile schema, the keys and their meaning are unchanged, and no CLI argument, MCP tool signature or response shape moves.
evidence: [docs/loom/audits/2026-09-17-credential-audit.md, docs/loom/2026-09-17-setup-dialog-write-order/blind-run-report.md]
status: confirmed 2026-09-18
publication: automatic — authorized 2026-09-18 by kouko

## Problem
`config.py` writes the whole profile store by reading every profile, mutating
one entry in memory, and rewriting the file from scratch (`write_profile` at
:78-89, `delete_profile` at :92-108). Three defects follow, all confirmed by
executable probes that are red on `main` today, now filed under this change at
`docs/loom/2026-09-18-config-store-integrity/evidence/probes/`.

1. **Concurrent writes lose profiles.** Nothing serialises the
   read-modify-write. Eight concurrent `setup_via_dialog` calls for eight
   distinct profiles lost seven of them, reproducible five runs out of five,
   while the keychain kept all eight passwords — so each lost profile becomes a
   stored password with no fields behind it.

2. **A failed write can truncate the file.** `p.open("wb")` truncates before
   `tomli_w.dump` runs, so a serialisation or disk failure mid-write leaves a
   partial file. A reviewer reproduced it: the store was left at
   `b'[profile.def'`, destroying an unrelated second profile as well as the
   target.

3. **Deleting a profile can strand its password, and never clears the
   pointer.** `delete_profile` rewrites config.toml first and deletes the
   keychain entry second, swallowing only `PasswordDeleteError`. A locked or
   unavailable keychain therefore propagates after the fields are already gone,
   leaving the password stored with no remaining interface that lists it.
   Nothing calls `clear_active_profile()`, so deleting the profile the pointer
   names leaves the server unable to resolve one until a human edits the file.

The change merged as PR #41 narrowed one credential hazard but widened defect 1:
its rollback restores the whole file, so a concurrent successful write by
another process can now be reverted while that call's keychain entry survives.
That new trigger disappears once writes are serialised.

## Proposed outcome
A profile write or delete either completes or leaves the store exactly as it
was, and concurrent writes from separate processes do not lose each other's
profiles.

## Acceptance
1. Eight concurrent writes of eight distinct profiles leave all eight in the
   store.
2. A write that fails part-way leaves the previous file content intact, with no
   partial or truncated state observable at any point by a concurrent reader.
3. Deleting a profile removes its stored password before its fields, and
   reports a failure to remove the password instead of exiting as if it
   succeeded.
4. Deleting the profile named by the active-profile pointer leaves no pointer
   naming it.
5. The three probes listed in Problem pass, and each is red against the
   pre-change code.
6. Every profile the store held before an operation, other than one being
   deleted, is present and unchanged after it.
7. The profile store is documented as written only by this project's own tools,
   in the place a person would look before editing it by hand.

## Constraints
- The profile schema is unchanged: same table name, same four keys, same
  meanings. An existing config.toml stays readable with no migration step.
- File mode stays 600 on both the file and the active-profile pointer.
- No password value is read, written, logged or passed by this module beyond
  the existing keychain calls.
- Tests run under `uv run --extra dev pytest`; live-cluster tiers stay opt-in
  behind `REDSHIFT_INTEGRATION=1`.
- Both version fields move together in this change.

## Out of scope
- How the server resolves a connection (inline versus profile), the password
  collection mechanisms, and the operator-facing messages — all owned by
  `2026-09-17-credential-resolution-hardening`.
- The `fastmcp` version ceiling and the empty `instructions` handshake under
  fastmcp 4.
- Backfilling test coverage for `_test_redshift_connection`, `cmd_setup` and
  the server start-up loop.
- Preserving hand-written comments and unknown keys across a write. The store is
  machine-managed (user-decided, 2026-09-18), so dropping them is the documented
  behaviour rather than a defect, and no formatting-preserving TOML dependency is
  added. The probe that pinned it as a defect is retired with that reason
  recorded.

## Open questions
- none
