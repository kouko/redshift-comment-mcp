# setup_via_dialog must not leave a half-written profile behind — plan
intent: 2026-09-17-setup-dialog-write-order@7605037
charter: 1.0

## Current State Evidence
- Forward: `redshift_tools.py:1327` writes fields, `:1350` opens the dialog, `:1364` stores the password, `:1404` tests the connection.
- Reverse: none exists. No code path restores a profile after `write_profile` succeeds.
- Error: `redshift_tools.py:1356-1361` returns on four reason-keyed failures and on empty password, all after `:1327`.
- Data: `config.py:86` replaces the whole profile dict; `config.py:118` overwrites the keychain entry only on success.
- Boundary: `tests/test_tools.py:1541` covers the response bodies; none asserts config.toml or keychain content after a failure.

## Task DAG

**W0-01 Persist nothing until a password is in hand**  after: -  acceptance: 1, 2, 4
- Files: src/redshift_comment_mcp/redshift_tools.py, tests/test_tools.py
- Test: A1 positive: cancel-leaves-toml-identical; negative: success-writes-toml. A2 positive: cancel-leaves-keychain; negative: success-writes-keychain. A4 positive: red-against-pre-change; boundary: all-five-failure-reasons.
- Risk: moving `write_profile` after the dialog makes `write_profile_failed` reachable only after the user types a password; agent-decided — the security property outranks failing fast on an unwritable config directory.

**W0-02 Pin the ten response shapes, and bump the two version fields**  after: W0-01  acceptance: 3
- Files: tests/test_tools.py, .claude-plugin/plugin.json, pyproject.toml
- Test: A3 positive: success-returns-configured-with-tested-true; negative: connection-failure-returns-configured-but-connection-failed.
- Risk: W0-01 rewrote four response messages, so pinning prose would lock in wording; agent-decided — pin status strings and field names only. Bump is PATCH 0.10.0 to 0.10.1.

## Questions asked
① — consequence — 「密碼留空」這次會定案：借相符設定的密碼，或維持報錯只改文案
① — what — 這樣對嗎？特別是「密碼留空 = 去借相符設定的密碼」這一條
pre-① — what — 三種切法（一個 PR 全包／兩個 PR 同一輪做完／三個 PR）要哪個
pre-① — what — 要不要現在就做 plugin 退回純啟動器的真統合

## Risks
1. user-decided — blank password means borrow the password of an exactly matching profile, not raise. That decision governs the follow-up change; this plan only stops the half-written state.
2. `test_setup_via_dialog_write_profile_failed_returns_error` documents fail-fast-before-the-dialog as deliberate. Its rationale changes here; the response shape it asserts does not.
3. Carried details from decision point ① were scope and sequencing remarks, not flow or reaction details, so this change carries none and needs no spec.
4. Acceptance 2 held before the change: `set_password` was already unreachable on all five failure paths. Its cases are regression pins; acceptance 4 rests on the config.toml cases alone.
5. W0-01 rewrote four response messages because the old wording ("fields are saved but no password is set") became false. Prose is not pinned, so a later edit cannot be caught mechanically.
