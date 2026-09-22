# The server must connect the way it says it will
originator: kouko
kind: engineering
needs-design: no — corrected 2026-09-21: the original wording claimed no response field was introduced, which is false. `get_setup_status` gained an optional non-secret `borrowed_from_profile` field and its `source` gained a third value, `borrowed`; `profile` now returns null for inline and borrowed modes. Still no spec: no new tool, no new CLI argument, no new surface — one optional field on an existing tool, whose meaning the tool's own published description carries. The profile schema is unchanged, and `docs/loom/**` and `README*.md` are not declared interface surfaces.
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
1. With connection fields supplied at launch and no password available, the
   server connects using the stored password of a profile whose host, port,
   user and dbname all equal the supplied values, and connects to the supplied
   target.
2. With connection fields supplied, no password available, and no profile
   matching all four, the server refuses to connect and its message names both
   the supplied target and each existing profile's target.
8. With connection fields supplied, no password available, and more than one
   profile matching all four, the server refuses to connect and its message
   names every tied candidate.
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

Acceptance 8 was added on 2026-09-21, during review. The tie it names was
an agent decision taken while closing an adversary finding: two profiles
recorded for the same target with different passwords are the state a
credential rotation leaves, and picking by sort order could silently prefer
the retired secret. Refusing is checkable from config.toml alone, so no
secret is compared. It is written here because it is a behaviour a launch
sees, and the maintainer accepts on a report that must describe it.

Acceptance 1 and 2 were amended on 2026-09-21, after confirmation and
before review, from a three-field match (host, user, dbname) to the full
four-field target. An adversarial probe showed that excluding port let a
password provisioned for one endpoint be sent to a different listener on
the same host. kouko chose the four-field match knowing it refuses a
profile recorded at another port; nobody is worse off than before this
change, where no borrow happened at all.

## Constraints
- The connection target is always a value the operator supplied at launch. A
  stored profile may contribute a password, never a host, port, user or dbname,
  and it may only contribute one when it is a profile for that exact target.
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
