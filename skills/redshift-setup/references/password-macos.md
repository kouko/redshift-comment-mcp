# Password Collection — macOS Path 4a

Native `osascript` password dialog. The dialog appears outside the
Claude UI; the password lives only in a shell variable inside the
subshell (never echoed); only `✓ Password stored` reaches Bash stdout.

```bash
PW=$(osascript \
       -e 'tell application "System Events" to display dialog "Redshift password for profile <NAME>:" default answer "" with hidden answer with title "Redshift MCP Setup" buttons {"Cancel", "Save"} default button "Save"' \
       -e 'text returned of result' 2>/dev/null) \
  || { echo "Cancelled by user" >&2; exit 1; }
uv run --project "$PLUGIN_ROOT" python -c "
import sys, keyring
keyring.set_password('redshift-comment-mcp', '<NAME>', sys.stdin.read().rstrip('\n'))
" <<< "$PW"
unset PW
echo "✓ Password stored in OS keychain"
```

Replace `<NAME>` with the profile name from Step 2. Substitute
`$PLUGIN_ROOT` with the path resolved in Step 1 (or expand it in the
same shell session if you exported it).

## Critical safety rules

- **DO NOT add `set -x` / verbose flags** — they would echo the
  expanded `$PW` to stderr.
- **DO NOT log `$PW`** for debugging — anything in Bash stdout / stderr
  reaches the JSONL transcript on disk.
- **DO NOT add `echo "$PW"` even temporarily** — same reason.
- **DO NOT remove the `2>/dev/null`** on the `osascript` call — without
  it, dialog cancellation prints a Cocoa error containing user-visible
  state to stderr.

## Why this path is preferred on macOS

`osascript` ships with the OS — no install step. The "with hidden
answer" flag masks the typed value as dots, and the dialog runs in a
separate process so its return value never traverses the Claude
agent's conversation pipeline.

## When to fall back

If `osascript` exits non-zero with a permission error (rare; happens
when accessibility / automation prompts are denied), surface the error
to the user and offer to switch to Path 4c (terminal handoff). Do NOT
prompt for the password directly in chat — there is no chat fallback.

After the `✓ Password stored` line appears, return to SKILL.md
**Step 5** (verify connection).
