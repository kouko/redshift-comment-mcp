# Password Collection — Linux Path 4b

`zenity --password` dialog. Same security model as macOS path: the
password lives only in a subshell variable, never reaches Bash stdout.

```bash
if command -v zenity >/dev/null 2>&1; then
  PW=$(zenity --password --title="Redshift MCP Setup" \
              --text="Redshift password for profile <NAME>:" 2>/dev/null) \
    || { echo "Cancelled by user" >&2; exit 1; }
  uv run --project "$PLUGIN_ROOT" python -c "
import sys, keyring
keyring.set_password('redshift-comment-mcp', '<NAME>', sys.stdin.read().rstrip('\n'))
" <<< "$PW"
  unset PW
  echo "✓ Password stored in OS keychain"
fi
```

Replace `<NAME>` with the profile name from Step 2. Substitute
`$PLUGIN_ROOT` with the path resolved in Step 1.

## Critical safety rules

- **DO NOT add `set -x` / verbose flags** — they would echo the expanded `$PW` to stderr.
- **DO NOT log `$PW`** for debugging.
- **DO NOT add `echo "$PW"` even temporarily** — Bash stdout / stderr
  reaches the JSONL transcript on disk.
- **DO NOT remove the `2>/dev/null`** on the `zenity` call — without
  it, GTK warnings can leak environment hints (display name,
  user-installed themes) into the transcript.

## When to fall back

`zenity` is not installed by default on all distros. If the
`command -v zenity` check fails, **immediately switch** to Path 4c
(terminal handoff) — do NOT try `kdialog` as a substitute (KDE's
dialog exposes the password value in `ps` output on some distros).
There is no chat fallback.

After the `✓ Password stored` line appears, return to SKILL.md
**Step 5** (verify connection).
