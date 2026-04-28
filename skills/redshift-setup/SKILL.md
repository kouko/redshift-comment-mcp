---
name: redshift-setup
description: >-
  Conversational walkthrough for configuring a Redshift connection profile
  for the redshift-comment-mcp plugin. Asks user host / port / user /
  dbname / profile-name in chat one question at a time, then hands off
  password collection to the user's own terminal (so password never
  enters Claude conversation history), then verifies via test-connection.
  Use when user invokes /redshift-setup or asks to configure / set up a
  Redshift connection. Redshift 連線設定対話フロー。
---

# Redshift Setup

Drives the connection-profile setup for the `redshift-comment-mcp` plugin
through a chat conversation, with one critical security boundary:
**the password is collected in the user's own terminal, not in chat**,
because anything typed into Claude conversation lives in the conversation
history forever (per `domain-teams:skill-team / standards/user-terminal-handoff.md`).

## When to Use

- User invokes `/redshift-setup`
- User says "set up Redshift" / "configure my Redshift connection" / "幫我設定 Redshift" / "Redshift の接続を設定して" or similar
- User wants to add a new connection profile alongside existing ones (multi-cluster)

## When NOT to Use

- User wants to change ONLY the password of an existing profile → use the
  one-liner `uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp set-password --profile <name>` instead; this skill is overkill.
- User wants to delete a profile → use `delete-profile` subcommand directly.

## Storage Model

| Field | Where it goes |
|---|---|
| host / port / user / dbname | `~/.config/redshift-comment-mcp/config.toml` (mode 600) under `[profile.<name>]` |
| password | OS keychain (macOS Keychain / Windows Credential Locker / Linux Secret Service), service `redshift-comment-mcp`, account `<profile-name>` |
| profile selection (which one MCP server uses) | Plugin's `userConfig.profile` in `~/.claude/settings.json` `pluginConfigs[<id>].options.profile` |

## Flow

### Step 1 — Locate the plugin install path

The plugin source is cloned by Claude Code into a versioned cache dir.
Find the latest version's path via Bash:

```bash
PLUGIN_ROOT=$(ls -d "$HOME/.claude/plugins/cache/redshift-comment-mcp/redshift-comment-mcp"/*/ 2>/dev/null | sort -V | tail -1)
test -n "$PLUGIN_ROOT" || { echo "Plugin not installed — run 'claude plugin install redshift-comment-mcp' first." >&2; exit 1; }
echo "$PLUGIN_ROOT"
```

Save the resolved path; you'll reuse it in Step 3 and Step 5.

### Step 2 — Collect non-secret fields via Q&A

Ask the user **one question at a time**. Wait for their reply before the
next question. Use the user's chat language (zh-TW / zh-CN / ja / en — match what they used).

1. **Profile name**:
   "What profile name? Press Enter for `default`. Use a custom name like `dev` / `prod` if you'll connect to multiple Redshift clusters."

2. **Host**:
   "Redshift host? (the full hostname like `my-cluster.abc123.ap-northeast-1.redshift.amazonaws.com`)"

3. **Port**:
   "Port? (default: 5439 — press Enter)"

4. **DB user**:
   "DB user?"

5. **Database name**:
   "Database name?"

If user already had a profile with the same name, recall its current values from the file and offer them as defaults (`current value [shown]`). Run this Bash to inspect:

```bash
uv run --project "$PLUGIN_ROOT" redshift-comment-mcp list-profiles
```

### Step 3 — Write non-secret fields (Bash, one call)

```bash
uv run --project "$PLUGIN_ROOT" \
  redshift-comment-mcp set-fields \
  --profile "<NAME>" \
  --host "<HOST>" \
  --port <PORT> \
  --user "<USER>" \
  --dbname "<DBNAME>"
```

Substitute `<>` with the values collected in Step 2. The `set-fields`
subcommand is non-interactive and exits with code 0 + a confirmation
line on success. If exit code != 0, surface the error to the user and
ask whether to retry.

### Step 4 — Hand off password collection to user's terminal

⚠️ **Do NOT ask the user for the password in chat.** Per the repo's
`user-terminal-handoff` convention, type-in-chat means the password
lands in conversation history (and any persisted transcript / log).
Print this block verbatim to the user — substitute `<NAME>` with the
profile name from Step 2:

```
請在你自己的 terminal（不是 Claude 對話）跑這條指令來設定密碼：

    uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" \
        redshift-comment-mcp set-password --profile <NAME>

它會用 getpass 隱藏輸入（你打的字不會顯示），密碼會存進 OS keychain。
完成後回我「done」。
```

(If the user's chat language is English / 日本語, translate the message
accordingly. Keep the command itself verbatim.)

Then **stop and wait** for the user's "done" reply. Do NOT background-poll.
Do NOT call `set-password` via Bash — that would defeat the entire point.

### Step 5 — Verify

After user replies "done":

```bash
uv run --project "$PLUGIN_ROOT" \
  redshift-comment-mcp test-connection --profile "<NAME>"
```

Expected exit codes:
- `0` + line `✓ Connected. database=X, user=Y` → success. Continue to Step 6.
- `1` → connection failed (bad password, network, DB-side issue). Print the stderr to the user and ask whether to retry password setup or check the host / network.
- `2` → profile or password missing in config.toml / keychain. Means user said "done" prematurely. Ask them to actually run the `set-password` command.

### Step 6 — Report success + next steps

After Step 5 returns 0, summarize for the user:

```
✓ Profile <NAME> configured.
  Host: <HOST>
  Database: <DBNAME>
  User: <USER>
  Password: stored in OS keychain ✓

下一步：
  1. 重啟 Claude Code（讓 MCP server 載入這個 profile）。
  2. 若這是你第一次設定，profile 預設用 'default'；
     若你用了自訂名稱（例如 'prod'），請編輯 ~/.claude/settings.json
     讓 pluginConfigs["redshift-comment-mcp@redshift-comment-mcp"].options.profile = "<NAME>"
     再重啟。
```

(Translate the prose to match user's chat language; keep the JSON path verbatim.)

## Multi-cluster Pattern

If the user wants to set up a second cluster, they invoke `/redshift-setup`
again and pick a different profile name. Each profile is independent:
separate `[profile.<name>]` block in config.toml, separate keychain entry.

To switch which profile the MCP server uses, they edit the
`pluginConfigs[…].options.profile` value in `~/.claude/settings.json`
and restart Claude Code. Or install the plugin in different scopes
(user / project / local) with different profiles.

## Safety Notes

- **Password never enters chat**. The `set-password` step is always run
  in the user's own terminal via `getpass`. This is non-negotiable.
- **`uv run --project ... set-fields` is safe to run via Bash tool**
  because it has no secret args.
- **`test-connection` is safe to run via Bash tool** because it reads
  the password from keychain, not from any arg.
- **Don't echo the password**, even if the user types it in chat by
  mistake. If they do, gently remind them to run `set-password` in
  their terminal instead, and treat the typed password as compromised
  (recommend rotating on Kobo's / DB's side if applicable).

## Reference

- Repo: <https://github.com/kouko/redshift-comment-mcp>
- Underlying CLI: `src/redshift_comment_mcp/setup_cli.py`
- Convention: `domain-teams:skill-team / standards/user-terminal-handoff.md`
  (the kobo-auth Flow A in monkey-skills/tsundoku is the canonical
  reference implementation of this pattern)
