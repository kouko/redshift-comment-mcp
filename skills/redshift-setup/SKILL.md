---
name: redshift-setup
description: >-
  Configure a Redshift connection profile for the redshift-comment-mcp
  plugin via chat — password stored in OS keychain via dialog or
  terminal handoff (never in chat history), connection verified.
  Named form `/redshift-setup <name>` also writes profile selection
  to settings.json. Use when setting up first Redshift cluster or
  adding another. Do NOT use for password-only changes (use
  set-password CLI), profile deletion (use delete-profile), or
  non-interactive setup. Triggers: /redshift-setup / set up Redshift
  / add cluster / 設定 Redshift / 新增 cluster / 接続を設定 /
  プロファイル.
---

# Redshift Setup

Drives the connection-profile setup for the `redshift-comment-mcp` plugin
through a chat conversation, with one critical security boundary:
**the password is collected in the user's own terminal, not in chat**,
because anything typed into Claude conversation lives in the conversation
history forever (per `domain-teams:skill-team / standards/user-terminal-handoff.md`).

## When to Use

- User invokes `/redshift-setup` (default form — single cluster, profile name `default`)
- User invokes `/redshift-setup <name>` (named form — multi-cluster, picks a custom profile name)
- User says "set up Redshift" / "configure my Redshift connection" / "幫我設定 Redshift" / "Redshift の接続を設定して" or similar
- User wants to add a second / third connection profile alongside existing ones

## When NOT to Use

- User wants to change ONLY the password of an existing profile → use the
  one-liner `uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp set-password --profile <name>` instead; this skill is overkill.
- User wants to delete a profile → use `delete-profile` subcommand directly.

## Inputs

| Invocation | Profile name resolved to | Settings.json edit |
|---|---|---|
| `/redshift-setup` (no `default` profile yet) | `default` (silent — no Q1) | none (manifest already defaults to `default`) |
| `/redshift-setup` (`default` already exists) | ask user: (a) overwrite `default` OR (b) pick a new name | (a) none / (b) auto-write pluginConfigs |
| `/redshift-setup <name>` | `<name>` (validated `^[A-Za-z0-9_-]+$`) | auto-write pluginConfigs (with confirm) |

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

### Step 2 — Resolve profile name + collect connection fields

#### Step 2a — Resolve profile name (do NOT ask the user up front)

The profile name is an internal handle, not a connection detail. Most
users have one cluster and never need to think about it. So we resolve
it WITHOUT asking by default; we only ask in the rare conflict case.

1. **Args path** — if the user invoked the skill with an argument (e.g.,
   `/redshift-setup ichef-prod`), use the argument as the profile name.
   Validate it matches `^[A-Za-z0-9_-]+$`; if not, reject and re-ask once.
   Skip to Step 2b.

2. **No-args path** — list existing profiles to detect collisions:

   ```bash
   uv run --project "$PLUGIN_ROOT" redshift-comment-mcp list-profiles
   ```

   Branch on what's already there:

   - **No `default` profile exists** → use `"default"` silently. Do
     NOT ask the user a name question. Skip to Step 2b.

   - **`default` already exists** → ask the user **one** question
     (translate prose to chat language, keep the CLI verbatim):

     ```
     你已經有一個 default profile（host=<H> user=<U> db=<D>）。
       (a) 覆蓋它（用新值替換現有 default 設定，password 保留）
       (b) 建立第二個 profile，保留現有 default — 請取個名字
           （例如 ichef-prod / dev / staging）
     ```

     - Reply (a) → use `"default"`. Continue to Step 2b.
     - Reply (b) + name → validate `^[A-Za-z0-9_-]+$`; on success use
       that name. On failure re-ask once.

#### Step 2b — Collect connection fields via Q&A

Ask the user **one question at a time**. Wait for their reply before the
next question. Use the user's chat language (zh-TW / zh-CN / ja / en —
match what they used).

1. **Host**:
   "Redshift host? (the full hostname like `my-cluster.abc123.ap-northeast-1.redshift.amazonaws.com`)"

2. **Port**:
   "Port? (default: 5439 — press Enter)"

3. **DB user**:
   "DB user?"

4. **Database name**:
   "Database name?"

If the resolved profile name already has a stored row in `config.toml`
(case 2a-(a) overwrite, or user explicitly re-ran setup on an existing
named profile), recall its current values and offer them as defaults
in each prompt: `current value [shown]`.

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

### Step 4 — Collect password (OS-aware, never enters chat transcript)

⚠️ **Hard rule**: the password value MUST NEVER appear in chat, in Bash
tool stdout, or in any tool result that gets added back to the
conversation transcript. Empirically verified during dry-run:
`osascript ... text returned of result` echoed to stdout WILL surface
the typed value into the Bash tool's response → into the JSONL
transcript → durable on disk. The reference files below contain the
exact recipes that avoid that leak — follow them verbatim.

#### Step 4.1 — Detect OS

Run this decision tree once at runtime to pick exactly ONE path:

```bash
if [[ "$OSTYPE" == darwin* ]]; then
    PASSWORD_PATH=4a  # macOS native dialog
elif command -v zenity >/dev/null 2>&1; then
    PASSWORD_PATH=4b  # Linux zenity dialog
else
    PASSWORD_PATH=4c  # terminal handoff
fi
```

Announce the chosen path to the user in chat ("我會跳一個系統對話框收
密碼" / "I'll show a system dialog for the password" / "我會請你在自己
的 terminal 設密碼") so they know where to look.

#### Step 4.2 — Load the matching recipe and execute it

Each path has its own complete bash recipe + caveats in a dedicated
reference file. The recipes are not interchangeable: each one's
caveats are tuned to that OS's specific transcript-leak vectors.

- **Path 4a (macOS)** — **MANDATORY: read entire file
  [`references/password-macos.md`](references/password-macos.md)**
  before executing. Run the recipe in that file verbatim.
- **Path 4b (Linux + zenity)** — **MANDATORY: read entire file
  [`references/password-zenity.md`](references/password-zenity.md)**
  before executing.
- **Path 4c (terminal handoff)** — **MANDATORY: read entire file
  [`references/password-terminal-handoff.md`](references/password-terminal-handoff.md)**
  before executing.

**Do NOT load the other two reference files** — each contains the
full bash recipe for one path; loading more than one wastes context
and can confuse which recipe to run. If the chosen path errors out
mid-execution, the reference file for that path documents the
fallback (typically Path 4c).

After the chosen path emits `✓ Password stored in OS keychain` (or
the user replies "done" on Path 4c), continue to Step 5.

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

### Step 6 — Report success + activate (only auto-write settings.json for non-default)

After Step 5 returns 0, print the success block:

```
✓ Profile <NAME> configured.
  Host: <HOST>
  Database: <DBNAME>
  User: <USER>
  Password: stored in OS keychain ✓
```

Then branch on the profile name:

#### Branch A — profile == "default"

The plugin manifest's `userConfig.profile` already defaults to `default`,
so there is nothing to activate. Print:

```
下一步：重啟 Claude Code，MCP server 會用 default profile 連線。

之後若要連第二個 cluster，跑 /redshift-comment-mcp:redshift-setup <名字>，
我會幫你寫好 ~/.claude/settings.json（不用你手挖 JSON）。
```

Stop. Do NOT touch settings.json.

#### Branch B — profile != "default"

The MCP server won't pick up the new profile until
`pluginConfigs["redshift-comment-mcp@redshift-comment-mcp"].options.profile`
is set to `<NAME>` in `~/.claude/settings.json`. Offer to do it.

**1. Read current settings (and bail out if it has comments).**

```bash
uv run --project "$PLUGIN_ROOT" python <<'PYEOF'
import json, pathlib, sys
p = pathlib.Path.home() / ".claude" / "settings.json"
if not p.exists():
    print("MISSING")
    sys.exit(0)
raw = p.read_text()
try:
    json.loads(raw)
    print("PARSEABLE")
except json.JSONDecodeError as e:
    print(f"COMMENTS_OR_INVALID: {e}")
PYEOF
```

If output starts with `COMMENTS_OR_INVALID`, skip to step 4 (manual
fallback) — we will not silently strip comments from the user's config.

**2. Compute & show the proposed diff.**

```bash
uv run --project "$PLUGIN_ROOT" python <<'PYEOF'
import json, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
data = json.loads(p.read_text()) if p.exists() else {}
pc = data.setdefault("pluginConfigs", {})
existing = pc.get("redshift-comment-mcp@redshift-comment-mcp", {}) \
             .get("options", {}).get("profile")
print(f"BEFORE: pluginConfigs[...].options.profile = {existing!r}")
print(f"AFTER : pluginConfigs[...].options.profile = '<NAME>'")
PYEOF
```

Show that two-line BEFORE/AFTER to the user. Ask one question
(translate prose to chat language):

> 我幫你把 `~/.claude/settings.json` 的 `pluginConfigs["redshift-comment-mcp@redshift-comment-mcp"].options.profile` 寫成 `<NAME>` 好嗎？(yes/no)

**3. On "yes", write the file.**

```bash
uv run --project "$PLUGIN_ROOT" python <<'PYEOF'
import json, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
data = json.loads(p.read_text()) if p.exists() else {}
data.setdefault("pluginConfigs", {}) \
    .setdefault("redshift-comment-mcp@redshift-comment-mcp", {}) \
    .setdefault("options", {})["profile"] = "<NAME>"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print("✓ settings.json updated")
PYEOF
```

Then print:

```
下一步：重啟 Claude Code，MCP server 會用 <NAME> profile 連線。
```

**4. On "no" (or the comments fallback), print manual instructions:**

```
請手動編輯 ~/.claude/settings.json，加上或修改：

  "pluginConfigs": {
    "redshift-comment-mcp@redshift-comment-mcp": {
      "options": { "profile": "<NAME>" }
    }
  }

完成後重啟 Claude Code。
```

(Translate prose. Keep the JSON snippet, CLI commands, and the
`pluginConfigs[...]` key verbatim.)

## Multi-cluster Pattern

To add a second cluster, the user invokes the skill with a name argument:

```
/redshift-comment-mcp:redshift-setup ichef-prod
```

Each profile is independent: separate `[profile.<name>]` block in
config.toml, separate keychain entry. The skill auto-writes
`pluginConfigs[…].options.profile = "<name>"` in `~/.claude/settings.json`
in Step 6 — the user does not edit JSON by hand.

To switch BETWEEN already-configured profiles without re-running setup,
the user edits the `pluginConfigs[…].options.profile` value directly
and restarts Claude Code. (Or installs the plugin in different scopes —
user / project / local — with different profiles.)

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
