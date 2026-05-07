# Password Collection — Terminal Handoff Path 4c

Use this path when no GUI dialog is available — headless servers,
Cowork uncertainty, Windows without a wrapped GUI, or as the fallback
when Path 4a / 4b errors out. This is the canonical "user-terminal
handoff" pattern from `domain-teams:skill-team / standards/user-terminal-handoff.md`
(kobo-auth Flow A in monkey-skills/tsundoku is the reference
implementation).

## Print this block verbatim to the user

Substitute `<NAME>` with the profile name; translate the prose to the
user's chat language (zh-TW / zh-CN / ja / en) but **keep the command
verbatim**:

```
請在你自己的 terminal（不是 Claude 對話）跑這條指令來設定密碼：

    uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" \
        redshift-comment-mcp set-password --profile <NAME>

它會用 getpass 隱藏輸入（你打的字不會顯示），密碼會存進 OS keychain。
完成後回我「done」。
```

Then **stop and wait** for the user's "done" reply.

## Critical safety rules

- **DO NOT background-poll the keychain** to detect when the password
  lands — adds I/O noise and can race with the user's typing in the
  external terminal.
- **DO NOT call `set-password` via Bash** — that would defeat the
  entire point of this path (the password would enter Claude's
  transcript via the Bash tool's stdin / stdout / stderr).
- **DO NOT prompt the user for the password in chat as a "fallback"** —
  there is no chat fallback. The keychain entry is the only acceptable
  destination. If the user types a password in chat by mistake,
  treat it as compromised: ask them to rotate it on the DB side and
  rerun this path.
- **DO NOT translate or modify the `uvx` command line** — even adding
  `\` line continuations or quoting changes can break paste-ability
  across terminals.

## Why this path exists

Some environments (Windows, headless boxes, locked-down corporate
machines) have no GUI dialog Claude can drive. The handoff hands
control of password entry to a process Claude cannot observe — the
user's own terminal, where `getpass` masks input below the OS layer
that Claude has access to. The "done" reply is the synchronization
signal that the keychain entry is in place.

After the user's "done" reply, return to SKILL.md **Step 5** (verify
connection). Do not assume the password landed — Step 5's
`test-connection` is the only reliable check.
