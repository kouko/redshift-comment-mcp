# config.toml writes must not lose a profile or truncate the file — plan
intent: 2026-09-18-config-store-integrity@73e93b3
charter: 1.0

## Current State Evidence
- Forward: `config.py:84-88` reads every profile, mutates one key, then `p.open("wb")` truncates before `tomli_w.dump` writes.
- Reverse: none. No caller can undo a partial write; PR #41's rollback lives in `redshift_tools.py`, not here.
- Error: `config.py:105-107` swallows only `PasswordDeleteError`; every other keyring exception propagates after the fields are gone.
- Data: `config.py:86` replaces the whole `profile` table; `config.py:153` writes the pointer file, and nothing ever clears it on delete.
- Boundary: `tests/test_config.py:104-124` covers delete_profile's return value; no test writes concurrently or fails mid-write.

## Task DAG

**W0-01 Write through a temp file and rename**  after: -  acceptance: 2, 6
- Files: src/redshift_comment_mcp/config.py, tests/test_config.py
- Test: A2 positive: midwrite-failure-keeps-previous-bytes; negative: success-replaces-content. A6 positive: sibling-profiles-survive-a-write; boundary: reader-never-sees-partial-file.
- Risk: `os.replace` is atomic only within one filesystem; agent-decided — write the temp file in the config directory itself, never the system temp dir.

**W0-02 Serialise the read-modify-write**  after: W0-01  acceptance: 1, 5
- Files: src/redshift_comment_mcp/config.py, tests/test_config.py
- Test: A1 positive: eight-concurrent-writes-keep-eight; negative: single-writer-unaffected. A5 positive: committed-probe-green; boundary: lock-released-when-the-write-raises.
- Risk: `fcntl.flock` is POSIX-only; agent-decided — degrade to the current unlocked path where it is unavailable rather than adding a dependency, and say so in the module docstring.

**W0-03 Delete the password first and clear a stale pointer**  after: W0-01  acceptance: 3, 4
- Files: src/redshift_comment_mcp/config.py, tests/test_config.py
- Test: A3 positive: keychain-failure-keeps-fields-and-reports; negative: happy-path-removes-both. A4 positive: pointer-cleared-when-it-named-the-deleted-profile; negative: pointer-kept-when-it-named-another.
- Risk: broadening the except changes `delete_profile`'s contract from "returns bool" to "can raise"; agent-decided — keep the bool and surface the failure, since callers already treat False as "did not exist".

**W0-04 Document the store as machine-managed, bump both versions**  after: W0-03  acceptance: 7
- Files: README.md, README.ja.md, README.zh-TW.md, src/redshift_comment_mcp/redshift_tools.py, src/redshift_comment_mcp/setup_cli.py, .claude-plugin/plugin.json, pyproject.toml, tests/test_setup_cli.py
- Test: A7 positive: readme-states-tool-managed-in-all-three-languages; negative: version-fields-stay-in-sync.
- Risk: this change left three rough edges of its own — a rollback comment that now asserts the opposite of the code, an uncaught KeychainDeleteError in the delete CLI, and an undocumented config.toml.lock file. It closes all three.

## Questions asked
① — consequence — 設定檔是「機器管的」還是「人會去改的」？前者退掉那支測試並寫進文件，後者要加 tomlkit 相依套件
① — what — 這樣對嗎？
pre-① — what — 11 項要不要切成兩個變更

## Risks
1. user-decided — the profile store is machine-managed, so dropping hand-written comments and unknown keys on write is documented behaviour; no formatting-preserving TOML dependency is added.
2. The lock closes the trigger PR #41 introduced, where a whole-file rollback could revert a concurrent write. Nothing else in the repo serialises against this module.
3. Task splitting was agent-decided: eleven items across two subsystems would not converge inside one review episode's three content revisions.
4. `probe_config_toml_byte_identity.py` was retired under risk 1; `probe_empty_password_boundary.py` stays with 2026-09-17-credential-resolution-hardening.
5. An atomic write makes `setup_via_dialog`'s `write_profile_failed` rollback unreachable as a truncation repair, leaving it able only to revert another process's completed write. Whether that branch should exist is deferred to 2026-09-17-credential-resolution-hardening, which owns that file.
