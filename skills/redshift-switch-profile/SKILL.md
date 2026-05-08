---
name: redshift-switch-profile
description: >-
  Switch the active Redshift profile by flipping the active-profile
  pointer file at ~/.config/redshift-comment-mcp/active-profile (no
  host / user / password re-entry). Verifies connection before
  declaring success. Single-profile users get a friendly bow-out
  pointing to /redshift-setup. Use when switching between 2+ already-
  configured Redshift clusters. Do NOT use for setting up a new profile
  (use /redshift-setup), changing passwords (use set-password CLI), or
  single-profile installs (skill bows out). Triggers:
  /redshift-switch-profile / switch cluster / change Redshift / 切換
  cluster / 切換 profile / クラスタ切替 / 接続を切替.
---

# Redshift Switch Profile

Flip the active Redshift profile pointer file at
`~/.config/redshift-comment-mcp/active-profile`. **No connection field
re-entry**: this skill assumes the target profile is already configured
(host / user / dbname in config.toml + password in OS keychain).

For single-profile users (the majority) this skill is intentionally a
no-op — see "When NOT to Use".

## When to Use

- User has 2+ configured Redshift profiles and wants to switch which
  one the MCP server connects to.
- User invokes `/redshift-switch-profile <name>` (direct form).
- User invokes `/redshift-switch-profile` (interactive — lists profiles,
  asks which one).
- User says "switch to dev cluster" / "切換到 prod" / "クラスタを切替"
  with multiple clusters configured.

## When NOT to Use

- Only `default` (or only one profile total) → friendly bow-out,
  suggest `/redshift-setup <name>` to add a second cluster.
- Zero profiles → suggest `/redshift-setup` to set up first cluster.
- User wants to set up a NEW profile → use `/redshift-setup`.
- User wants to change a profile's host / user / dbname → use
  `/redshift-setup <name>` (it offers existing values as defaults).
- User wants to change ONLY a password → use `set-password` CLI.

## Storage Model

This skill only edits the **active-profile pointer file**:

| Pointer file state | Effect on MCP server startup |
|---|---|
| Absent | Server falls back to `"default"` (canonical single-profile state) |
| Present, content = `<name>` | Server connects with `<name>` |
| Present, content = `"default"` | Unusual; this skill normalizes by **removing** the file instead of writing `"default"` |

Connection fields (host / user / dbname / password) and `[profile.<name>]`
blocks in config.toml are **never** touched by this skill.

## Flow

### Step 1 — Locate plugin install path

```bash
PLUGIN_ROOT=$(ls -d "$HOME/.claude/plugins/cache/redshift-comment-mcp/redshift-comment-mcp"/*/ 2>/dev/null | sort -V | tail -1)
test -n "$PLUGIN_ROOT" || { echo "Plugin not installed." >&2; exit 1; }
echo "$PLUGIN_ROOT"
```

### Step 2 — Inventory existing profiles

```bash
uv run --project "$PLUGIN_ROOT" redshift-comment-mcp list-profiles
```

The command prints one profile name per line. Branch on the count:

#### Case 0 — no profiles exist

Print (translate to the user's chat language; keep slash command verbatim):

```
你還沒設定任何 Redshift profile。
先跑 /redshift-comment-mcp:redshift-setup 建立第一個。
```

Stop. Do NOT touch any file.

#### Case 1 — exactly one profile exists

Single-profile state. Switching makes no sense. Print:

```
你目前只有 '<NAME>' 一個 profile，沒有切換的對象。
要新增第二個 cluster 跑 /redshift-comment-mcp:redshift-setup <名字>。
```

Stop.

#### Case 2+ — multiple profiles exist

Continue to Step 3.

### Step 3 — Resolve target profile name

#### Path A — invoked with arg (e.g., `/redshift-switch-profile prod`)

Use the arg as `<NAME>`. Validate two things:

1. **Format**: matches `^[A-Za-z0-9_-]+$`. If not, reject:

   ```
   '<arg>' 不是合法的 profile 名稱（只能用英數字 / 底線 / 連字號）。
   ```

   Stop.

2. **Existence**: must appear in the list-profiles output. If not:

   ```
   找不到 '<NAME>' profile。目前有：<LIST>
   要切到哪一個？(輸入名字)
   ```

   Wait for user reply, validate against list, retry once. On second
   failure, stop and ask the user to re-invoke.

#### Path B — invoked with no arg

Read the current active profile to inform the user:

```bash
uv run --project "$PLUGIN_ROOT" python <<'PYEOF'
from redshift_comment_mcp import config as cfg
print(cfg.read_active_profile() or "default")
PYEOF
```

Save the output as `<CURRENT>`. Then ask:

```
目前 active 是 '<CURRENT>'，可選的 profile：
  - <profile-1>
  - <profile-2>
  - <profile-3>
要切到哪一個？(輸入名字)
```

Validate the reply against the list, retry once on mismatch. On second
failure, stop.

### Step 4 — Idempotent check

If `<NAME>` == `<CURRENT>`, print:

```
'<NAME>' 已經是 active profile，沒有要切換的。
```

Stop. Do NOT touch any file.

### Step 5 — Apply pointer file change

```bash
uv run --project "$PLUGIN_ROOT" python <<'PYEOF'
from redshift_comment_mcp import config as cfg
NAME = "<NAME>"
if NAME == "default":
    cfg.clear_active_profile()
else:
    cfg.write_active_profile(NAME)
print("✓ active profile updated")
PYEOF
```

### Step 6 — Verify the target profile actually works

```bash
uv run --project "$PLUGIN_ROOT" \
  redshift-comment-mcp test-connection --profile "<NAME>"
```

Expected exit codes:

- `0` + `✓ Connected. database=X, user=Y` → success. Continue to Step 7.
- `1` → connection failed. The pointer file is **already updated**, but
  the target can't connect. Tell the user the stderr and suggest:
    - check network / VPN access to the cluster
    - rotate the password via
      `uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp set-password --profile <NAME>`
    - or run `/redshift-comment-mcp:redshift-setup <NAME>` to re-do
      connection fields (host / user / dbname)
  Do NOT auto-revert the pointer file — the user may want to debug
  while the new profile is selected.
- `2` → profile or password missing. Means the profile isn't actually
  configured (defensive — list-profiles claimed it exists).
  Suggest `/redshift-comment-mcp:redshift-setup <NAME>`.

### Step 7 — Print success + restart hint

```
✓ Active profile switched to '<NAME>'.
  下一步：重啟 Claude Code，MCP server 會用 <NAME> 連線。
```

(Translate prose; keep slash commands and CLI commands verbatim.)

## Safety Notes

- **No connection field re-entry**. This skill never asks for host /
  user / dbname / password. To update those, use `/redshift-setup
  <NAME>` instead.
- **Pointer file is mode 600**, same as config.toml.
- **Restart required**. The MCP server reads the pointer file on
  startup; mid-session pointer changes have no effect until Claude
  Code restarts.

## Reference

- Repo: <https://github.com/kouko/redshift-comment-mcp>
- Underlying CLI: `src/redshift_comment_mcp/setup_cli.py`
- Sister skill: `/redshift-comment-mcp:redshift-setup` (creates / edits
  profiles; re-collects connection fields)
