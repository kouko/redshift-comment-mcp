# The server must connect the way it says it will — plan
intent: 2026-09-19-connection-resolution@4c5c3b7
charter: 1.0

## Current State Evidence
- Forward: `server.py:112-123` takes the inline branch on host+user+dbname alone and returns before `config` is imported at :125.
- Reverse: none. No path consults a profile once inline is chosen; the only escape is blanking all three launch fields.
- Error: `server.py:116-119` raises for a missing inline password and names `--password` first, contradicting `:172-174`.
- Data: `redshift_tools.py` `get_setup_status` reads `cfg.read_profile(profile)` for the literal default; `resolve_active_profile` appears nowhere in that file.
- Boundary: `tests/test_server_resolution.py` has 24 tests over both branches; none supplies inline fields with a matching profile present.

## Task DAG

**W0-01 Borrow a password only from an identity-matched profile**  after: -  acceptance: 1, 2
- Files: src/redshift_comment_mcp/server.py, tests/test_server_resolution.py
- Test: A1 positive: matching-triple-borrows-and-uses-inline-host; negative: password-present-still-wins. A2 positive: mismatched-profile-raises-naming-both-hosts; boundary: no-profiles-at-all-raises.
- Risk: a stored profile must never supply a host; agent-decided — match on the whole `(host, user, dbname)` triple and connect to the inline values, so an unmatched store can only refuse, never redirect.

**W0-02 Make the status tool report the mechanism and target actually used**  after: W0-01  acceptance: 3
- Files: src/redshift_comment_mcp/redshift_tools.py, src/redshift_comment_mcp/server.py, tests/test_tools.py
- Test: A3 positive: borrowed-mode-reports-inline-host-and-borrowed-source; negative: profile-mode-named-other-than-default-reports-configured.
- Risk: v0.10.0 fixed this tool lying in the other direction; agent-decided — resolve once and let both the connector and the status tool read that single decision rather than recomputing.

**W0-03 Harden the password channel and stop recommending argv**  after: W0-01  acceptance: 4, 5
- Files: src/redshift_comment_mcp/server.py, src/redshift_comment_mcp/redshift_tools.py, tests/test_server_resolution.py
- Test: A4 positive: unsubstituted-placeholder-is-no-password; negative: real-password-unaffected. A5 positive: no-message-names-the-password-flag; boundary: env-var-guidance-survives.
- Risk: dropping `--password` from guidance leaves the flag itself in place; agent-decided — guidance only, since removing the flag would break a documented integration path.

**W0-04 Make the manifest and the READMEs state the rule the code follows**  after: W0-03  acceptance: 6, 7
- Files: .claude-plugin/plugin.json, README.md, README.ja.md, README.zh-TW.md, pyproject.toml, tests/test_repo_invariants.py
- Test: A6 positive: manifest-and-three-readmes-agree-on-blank-password; negative: version-fields-stay-in-sync. A7 positive: every-new-test-red-against-base; boundary: base-source-collects.
- Risk: the contradiction between the manifest and the README is what produced the original report; agent-decided — pin the agreement with an invariant test so prose cannot drift apart again.

**W0-05 Close the four defects the adversary found in the resolution code**  after: W0-04  acceptance: 1, 2, 3, 7
- Files: src/redshift_comment_mcp/server.py, src/redshift_comment_mcp/redshift_tools.py, tests/test_server_resolution.py, tests/test_tools.py
- Test: A1 positive: four-field-match-borrows; negative: port-mismatch-refuses-and-names-both-ports. A3 positive: instructions-enumerate-borrowed; boundary: store-failure-falls-through-to-inline-refusal.
- Risk: the borrow scan gave a keychain-free path a keychain dependency, and the new carrier renders its own password; agent-decided — guard the scan into the existing refusal, and mark the field `repr=False` like `RedshiftConnectionConfig`.

**W0-06 Restate the four-field rule in the manifest and the READMEs**  after: W0-05  acceptance: 6
- Files: .claude-plugin/plugin.json, README.md, README.ja.md, README.zh-TW.md, tests/test_repo_invariants.py
- Test: A6 positive: all-four-docs-state-the-four-field-rule; negative: no-doc-still-claims-port-is-excluded.
- Risk: W0-04's anchors pin the now-wrong port exclusion; agent-decided — rewrite the anchors with the rule, since an anchor that outlives the rule it pins is worse than none.

**W0-07 Close the two ways the refusal and the parser still fail quietly**  after: W0-06  acceptance: 1, 2
- Files: src/redshift_comment_mcp/server.py, tests/test_server_resolution.py
- Test: A2 positive: refusal-names-each-profile-whole-target; boundary: two-profiles-differing-only-in-dbname-render-distinctly. A1 negative: mistyped-port-refuses-to-borrow; positive: blank-and-placeholder-port-still-borrow.
- Risk: `_coerce_port` is an argparse `type=`, so raising aborts the boot it exists to protect; agent-decided — keep booting on a typo but mark the port substituted and refuse to borrow on it.

**W0-08 Stop the status tool misreporting itself to the agent that reads it**  after: W0-07  acceptance: 3, 5
- Files: src/redshift_comment_mcp/redshift_tools.py, src/redshift_comment_mcp/server.py, tests/test_tools.py, tests/test_server_resolution.py
- Test: A5 positive: no-wire-published-text-names-the-password-flag; boundary: internal-only-comments-still-allowed. A3 positive: borrowed-mode-reports-no-phantom-profile; negative: profile-mode-still-reports-its-name.
- Risk: the guard test exempts docstrings as internal, but FastMCP publishes this one verbatim; agent-decided — narrow the exemption to text that cannot reach a client, and refuse an ambiguous lender rather than picking by sort order.

## Questions asked
① — what — 這樣對嗎？
①-amend — consequence — 「密碼留空去借相符 profile 的密碼」—— 這個「相符」要比對幾個欄位？
pre-① — what — 10 項要不要切（我自行決定切分，未問使用者）

## Risks
1. user-decided 2026-09-17 — a blank password borrows the password of a profile that matches the launch target; it never borrows a target field. Both independent audits proposed this shape.
   Amended user-decided 2026-09-21 — the match is the full four-field target, port included. The adversary demonstrated a password provisioned for `host:5439` being sent to `host:9999`; the escalation story it attached to that (a same-user process cannot read the keychain item) was tested and is false on this machine — the project's own interpreter reads it silently — so the reason to close it is the shape of the failure, not privilege. A port mismatch now refuses loudly instead of sending the secret quietly.
2. Task splitting was agent-decided: PR #42 needed three review rounds for four tasks, so ten accumulated items were cut to the five that share one subject.
3. The blank-password gate still accepts whitespace-only values, so a borrowed or supplied `" "` is treated as a real password. Out of scope here, already filed.
4. `setup_via_dialog` writes a profile whose triple matches the inline values by construction, so the borrow path turns that tool into a working recovery for inline mode — previously it wrote a profile the inline branch never read.
