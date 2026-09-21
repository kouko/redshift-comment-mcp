# The server must connect the way it says it will
originator: kouko
kind: engineering
needs-design: no — no new CLI argument, MCP tool signature or response field is introduced; the plugin manifest's fields and the profile schema are unchanged. Existing message text and one status field's value change, and `docs/loom/**` and `README*.md` are not declared interface surfaces.
evidence: [docs/loom/audits/2026-09-17-credential-audit.md, docs/loom/2026-09-18-config-store-integrity/attestation.json]
status: confirmed 2026-09-21
publication: automatic — authorized 2026-09-21 by kouko

## Problem
The plugin's install dialog marks every connection field optional, and
`.claude-plugin/plugin.json` tells the user the password field may be left
blank "to use a profile password configured via /redshift-setup". `README.md`
tells them the opposite — that the two paths are exclusive and all four fields
must be blank for the profile path. The code follows the README.

So a user who fills host, user and dbname and leaves the password blank gets a
hard error (`server.py:116-119`), even when `config.toml` and the keychain
already hold a complete, working profile for exactly those three values. That
is what happened on this maintainer's own machine on 2026-09-17; the workaround
was to hand-edit the plugin's stored options.

Three further defects make the server's account of itself unreliable:

1. `get_setup_status` reads the literal profile name `"default"` and never calls
   `resolve_active_profile`, so a user whose only profile has another name — the
   documented upgrade-rescue case — is told `configured: false` while the server
   connects normally. It is the only tool an agent has for "which cluster am I
   on", and it can be wrong about it.

2. `REDSHIFT_PASSWORD` is read raw (`server.py:79`, `:122`) while every other
   inline field passes through `_normalize_inline`. If the host ever leaves the
   value unsubstituted, the literal placeholder string is truthy: the server
   reports itself configured and authenticates with that string.

3. Two server-authored messages recommend the `--password` flag, the one path
   that puts the secret into argv, shell history and the session transcript.
   Both contradict the rule stated fifty lines away in the same file, and the
   reader of the second is an agent with shell access.

## Proposed outcome
Given the configuration present on a machine, the server connects the way its
own documentation and its own status tool say it will, and never to a target
the operator did not name.

## Acceptance
1. With host, user and dbname supplied at launch and no password available, the
   server connects using the stored password of a profile whose host, user and
   dbname all equal the supplied values, and connects to the supplied host.
2. With host, user and dbname supplied, no password available, and no profile
   matching all three, the server refuses to connect and its message names both
   the supplied target and each existing profile's host.
3. `get_setup_status` reports the same mechanism and the same target the server
   would actually use, including for a profile whose name is not `"default"`.
4. A launch in which the password arrives as an unsubstituted configuration
   placeholder is treated as no password rather than as a password.
5. No message emitted by the server or its CLI recommends passing a password as
   a command-line argument.
6. The plugin manifest and all three README translations state the same rule
   about leaving the password blank, and that rule is the one the code follows.
7. Every acceptance line above is covered by a test that fails against the
   pre-change code.

## Constraints
- The connection target is always a value the operator supplied at launch. A
  stored profile may contribute a password, never a host, user or dbname.
- The password value must not reach argv, logs, stdout, or any MCP response.
- Inline launch arguments remain a supported public integration path
  (`README.md`); they are not removed or deprecated here.
- The `.mcpb` bundle's env-to-argv adapter keeps working unchanged, and its
  manifest marks every field required, so the blank-password state is
  unreachable there.
- The profile schema and `config.toml` format are unchanged.
- Tests run under `uv run --extra dev pytest`; live-cluster tiers stay opt-in
  behind `REDSHIFT_INTEGRATION=1`.
- Both version fields move together in this change.

## Out of scope
- How a password is collected: the OS dialog, `--stdin`, `getpass`, and the
  duplicate shell implementation in `skills/redshift-setup/references/`.
- The blank-password gate — `if not password` accepts whitespace-only values.
- `setup_via_dialog`'s rollback, now able only to revert another process's
  completed write since the store became atomic.
- `probe_readme_lock_claims.py`'s missing keyring isolation, which writes a real
  entry into the machine's keychain on every run.
- `{profile_name}` interpolated unquoted into command strings in `server.py` and
  `setup_cli.py`; the source is operator input, so the injection path does not
  reach it.
- The `fastmcp` version ceiling and the empty `instructions` handshake under
  fastmcp 4.

## Open questions
- none
