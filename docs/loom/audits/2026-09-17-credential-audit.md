# Credential-handling audit — 2026-09-17

Two independent fresh-context audits (security lens, design lens) were run
against `main` at `ab4d46e`, each reading the source directly rather than a
summary. Findings below were re-verified by hand before being recorded; the
`VERIFIED` marker means a line of this repository was read to confirm it.

## Context

The repository has two credential stores that never consult each other:

| | Store | Written by | Read by |
|---|---|---|---|
| **A** | the host's own keychain slot for a `sensitive` config field | Claude Code plugin `userConfig`, `.mcpb` Desktop form | injected as `REDSHIFT_PASSWORD`, consumed by inline mode |
| **B** | `keyring` service `redshift-comment-mcp`, account = profile name | `setup`, `set-password`, `setup_via_dialog`, the `/redshift-setup` skill | `config.get_password()`, consumed by profile mode |

`server.py:112-123` selects inline mode on the presence of host+user+dbname
alone and returns before `config` is imported at :125, so inline mode never
reads B.

Asymmetry worth recording: `.mcpb` marks four `user_config` fields
`required: True` (scripts/generate_mcpb_manifest.py:83,95,101,111) while
`.claude-plugin/plugin.json` marks none. The "three fields filled, password
blank" state is therefore unreachable on Desktop and reachable only through the
Claude Code plugin. VERIFIED.

## Findings

### F1 — HIGH. `setup_via_dialog` persists connection fields before collecting the password and never rolls back. VERIFIED

`redshift_tools.py:1327` writes host/port/user/dbname. The dialog runs at
:1350. The reason-keyed failure branches return at :1356-1361; `cfg.set_password`
at :1364 is unreachable from them. The profile is left pointing at the
caller-supplied host with the previous, still-valid keychain password in place,
and `get_setup_status` reports `configured: true`.

Introduced in 0a77873f (2026-05-29, v0.7.0), shipped through v0.10.0.
`tests/test_tools.py` asserts the five failure *responses* but never the
resulting config.toml.

### F2 — Plain fallback-to-profile (proposal "1a") is unsafe. VERIFIED mechanics

Inline mode's current property is that explicit launch arguments fully
determine the connection target and nothing on disk can influence it
(server.py:112-123 returns before config.toml is opened). Falling back to the
*resolved active profile* discards the three fields the user typed: a user who
enters a production host with a blank password would be connected to whatever
`resolve_active_profile` lands on, and `list_schemas` would answer from that
cluster. `config.py:196-203` makes the target harder to predict — with no
pointer file and no `"default"`, rule 2 selects the lone profile whatever its
name.

It also chains with F1: once config.toml can influence an inline-configured
server, F1's rewritten profile becomes live.

Both audits independently proposed the same narrower fix: borrow **only the
password**, and only from a profile whose `(host, user, dbname)` equals the
inline triple; connect to the inline host; otherwise raise an error naming both
the inline target and the existing profiles' hosts.

### F3 — MEDIUM. The skill's Bash dialog stores an empty password. VERIFIED

`skills/redshift-setup/references/password-macos.md:8-15` and
`password-zenity.md:8-14`: `osascript` exits 0 with empty stdout when the user
clicks Save without typing, so the `||` branch never fires and
`keyring.set_password(..., "")` runs. `config.get_password` then returns `""`
and `server.py:177` reports "Password missing from keychain" while the entry
demonstrably exists. The Python path rejects this explicitly at
`setup_cli.py:236-238`.

### F4 — MEDIUM. The skill's Bash dialog passes the password through a here-string. INFERRED

`password-macos.md:15` / `password-zenity.md:14` use `<<< "$PW"`. bash 3.2
(macOS default) and zsh back here-strings with a temp file under `$TMPDIR`.
The Python path keeps the value in process memory only. Not empirically
confirmed on this host.

### F5 — MEDIUM. Two server-authored messages recommend the `--password` flag. VERIFIED

`server.py:116-119` lists `--password` before the env var;
`redshift_tools.py:1516-1522` (`get_setup_status.next_step`) repeats it. Both
contradict `server.py:172-174` ("Never pass the password as a tool argument or
shell argument") and `redshift_tools.py:126-129`. The reader of the second
message is an agent with Bash, i.e. the reader most likely to act on it
literally, putting the secret into argv, shell history and the transcript.

### F6 — MEDIUM (latent). `REDSHIFT_PASSWORD` skips placeholder normalization. VERIFIED

`server.py:79` and `:122` read the env var raw while host/user/dbname pass
through `_normalize_inline` (:33-45). The module's own docstring states an
unset optional field may arrive as the literal `${user_config.<name>}`. If env
substitution ever behaves like argv substitution, a blank Password field yields
a truthy literal, `has_password` becomes `True`, `get_setup_status` reports
`configured: true`, and the server authenticates with that string. No test
covers the env path.

### F7 — MEDIUM/LOW. `delete_profile` can orphan the secret and never clears the pointer. VERIFIED

`config.py:97-108` rewrites config.toml first (:101-103) and deletes the
keychain entry second (:105), swallowing only `PasswordDeleteError` (:106).
`KeyringLocked`, `NoKeyringError` and `InitError` propagate after the fields are
already gone, leaving the password in the keychain with no remaining UI to
remove it. Nothing calls `clear_active_profile()`, so deleting the profile the
pointer names leaves the server raising "Profile X is not configured"
permanently, with the lone-profile rescue at `config.py:201-202` bypassed
because the pointer counts as explicit. Neither case is covered by
`tests/test_config.py:104-124`.

### F8 — LOW. `connection_error` returns third-party exception text over the wire. VERIFIED

`redshift_tools.py:1419` returns `str(e)` from `redshift_connector`
(`setup_cli.py:96-97`), about thirty lines below two blocks that refuse to do
this on CWE-209 grounds (:1336-1348, :1366-1381). A consistency finding, not a
demonstrated leak.

### F9 — LOW. `get_setup_status` ignores profile resolution. VERIFIED

`redshift_tools.py:1460` defaults to the literal `"default"` and reads that name
at :1525-1527, while the server connects via `resolve_active_profile`
(`server.py:126`). A user whose lone profile is not named `default` — the
documented upgrade-rescue case at `config.py:181-183` — is told
`configured: false` while the server connects. `setup_via_dialog` has the same
default at :1284, so an agent can provision `default` while the server resolves
another name.

### F10 — LOW. VERIFIED

`write_profile` creates the file at the umask default and `chmod(0o600)` after
writing (`config.py:87-89`); same in `write_active_profile` (:153-154). An
ambient `REDSHIFT_PASSWORD` exported for an unrelated tool is silently adopted
by inline mode (`server.py:122`).

## Checked and clean

- Neither shipped launcher puts the password in argv: `plugin.json:53-69` uses
  env; `mcpb/server/main.py:22-40` excludes it deliberately and asserts so in
  `tests/test_mcpb_adapter.py:77-87`.
- No logger or print statement in `src/` takes the password value;
  `connection.py:24,65` log host/port/dbname only.
- The keyring service and account names used by the skill's Bash path and by
  `config.py:44` are identical, so removing the Bash path strands no existing
  entry.

## Rejected proposals

- **Adopting the inline configuration into config.toml at startup.**
  `write_profile` replaces the whole profile dict (`config.py:86`) and
  `set_password` overwrites the keychain entry (:118), so a user with a working
  profile for one cluster loses it silently the first time the server starts
  with different plugin fields. The host's copy then wins on every start, so a
  rotation performed through the CLI is reverted by the next client restart.
  It does not remove the dual read.
- **Removing the connection fields from `plugin.json`.** `mcpb/server/main.py`
  is a pure env→inline-argv adapter, so inline mode cannot be deleted while the
  `.mcpb` bundle exists, and `README.md:239-243` documents inline arguments as
  the integration path for other MCP clients. This removes one of two callers,
  not the mode.

## Documentation contradiction

`.claude-plugin/plugin.json` describes the password field as "Leave blank to use
a profile password configured via /redshift-setup", while `README.md:86-99`
presents the two paths as "pick one" and instructs the user to leave *all* the
fields blank for the profile path. The implementation matches the README. This
contradiction is the origin of the reported failure.
