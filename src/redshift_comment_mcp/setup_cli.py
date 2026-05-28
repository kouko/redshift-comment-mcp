"""Interactive setup CLI for redshift-comment-mcp.

Subcommands (invoked as ``redshift-comment-mcp <subcommand>``):

- ``setup [--profile NAME]``        — full Q&A for one profile
- ``set-password [--profile NAME] [--stdin | --dialog]``
                                     — update password.
                                     Default = interactive ``getpass`` prompt.
                                     ``--stdin``: read one line from stdin
                                     (scripted / CI use; never logs to argv).
                                     ``--dialog``: OS-native password dialog
                                     (macOS ``osascript``, Linux ``zenity``);
                                     password never enters chat / stdout.
- ``test-connection [--profile NAME]`` — verify a profile can connect
- ``list-profiles``                  — list all configured profiles
- ``delete-profile --profile NAME``  — remove a profile + its keyring entry
- ``set-fields --profile NAME --host H --port P --user U --dbname D``
                                     — non-interactive write of the 4
                                     non-secret fields (agent / scripted use).

Subcommands route through ``main()`` in this module; the bare command
``redshift-comment-mcp`` (with no subcommand) starts the MCP server in
``server.py``.

Code-agent bootstrap pipeline (no Claude Code plugin required)::

    redshift-comment-mcp set-fields --profile X --host H --port P --user U --dbname D
    redshift-comment-mcp set-password --profile X --dialog
"""
from __future__ import annotations

import argparse
import getpass
import subprocess
import sys

from . import config


def cmd_setup(args: argparse.Namespace) -> int:
    name = args.profile
    print(f"Setting up Redshift profile '{name}'.")
    print("Existing values shown in [brackets]; press Enter to keep them.\n")

    existing = config.read_profile(name) or {}

    host = _prompt("Redshift host", existing.get("host"), required=True)
    port = int(_prompt("Port", str(existing.get("port", 5439))))
    user = _prompt("DB user", existing.get("user"), required=True)
    dbname = _prompt("Database name", existing.get("dbname"), required=True)

    config.write_profile(name, host=host, port=port, user=user, dbname=dbname)
    print(f"\n✓ Wrote non-secret fields to {config.config_path()}")

    existing_pw = config.get_password(name)
    keep_existing = False
    if existing_pw:
        keep_existing = _yes_no("Keep existing password?", default=True)
    if not keep_existing:
        password = getpass.getpass("DB password (input hidden): ")
        if not password:
            print("Password cannot be empty. Aborting.", file=sys.stderr)
            return 2
        config.set_password(name, password)
        print("✓ Stored password in OS keychain.")

    print()
    return cmd_test_connection(args)


def _collect_password_via_dialog(profile_name: str) -> tuple[str | None, str]:
    """Collect password via OS-native dialog without exposing to chat / stdout.

    Returns ``(password, reason)``:
      - ``("the-password", "ok")`` on success
      - ``(None, "cancelled")`` if user closed / cancelled the dialog
      - ``(None, "unavailable")`` if no dialog tool is installed
      - ``(None, "unsupported")`` if the platform has no supported dialog path

    Mirrors the security discipline of ``skills/redshift-setup/references/
    password-macos.md`` / ``password-zenity.md``: the password value is
    captured into a local Python string via ``subprocess.run(capture_output=
    True)`` and never reaches the caller's stdout. The caller is responsible
    for passing it directly to ``config.set_password()`` and deleting the
    reference immediately.
    """
    if sys.platform == "darwin":
        # macOS — native osascript dialog. "with hidden answer" masks the
        # typed value. stderr is discarded so a Cocoa permission/cancel
        # error doesn't leak user-visible state.
        script = (
            f'tell application "System Events" to display dialog '
            f'"Redshift password for profile \\"{profile_name}\\":" '
            f'default answer "" with hidden answer '
            f'with title "Redshift MCP Setup" '
            f'buttons {{"Cancel", "Save"}} default button "Save"'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script, "-e", "text returned of result"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return None, "unavailable"
        if result.returncode != 0:
            return None, "cancelled"
        return result.stdout.rstrip("\n"), "ok"

    if sys.platform.startswith("linux"):
        # Linux desktop — zenity. Exit code 1 = cancelled, 127 = not installed.
        try:
            result = subprocess.run(
                [
                    "zenity",
                    "--password",
                    "--title=Redshift MCP Setup",
                    f"--text=Redshift password for profile \"{profile_name}\":",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return None, "unavailable"
        if result.returncode == 0:
            return result.stdout.rstrip("\n"), "ok"
        return None, "cancelled"

    return None, "unsupported"


def cmd_set_password(args: argparse.Namespace) -> int:
    name = args.profile
    if not config.read_profile(name):
        print(
            f"Profile '{name}' not configured. "
            f"Run `redshift-comment-mcp setup --profile {name}` first.",
            file=sys.stderr,
        )
        return 2

    if args.dialog:
        password, reason = _collect_password_via_dialog(name)
        if reason == "cancelled":
            print("Password dialog cancelled. No change.", file=sys.stderr)
            return 2
        if reason == "unavailable":
            print(
                "No supported password dialog tool found "
                "(macOS needs `osascript`, Linux needs `zenity`). "
                "Use `--stdin` to pipe the password, or omit both flags "
                "for an interactive terminal prompt.",
                file=sys.stderr,
            )
            return 2
        if reason == "unsupported":
            print(
                f"`--dialog` is not supported on platform '{sys.platform}'. "
                f"Use `--stdin` to pipe the password, or omit both flags "
                f"for an interactive terminal prompt.",
                file=sys.stderr,
            )
            return 2
        if not password:
            print("Password from dialog is empty. Aborting.", file=sys.stderr)
            return 2
    elif args.stdin:
        # Non-interactive: scripted use + code-agent automation when no GUI
        # is available. Caller pipes one line of password text via stdin so
        # the password never lands in argv (visible to `ps`) or shell
        # history. Prefer `--dialog` on GUI hosts.
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            print(
                "Password from --stdin is empty. Aborting "
                "(pass exactly one line of password text via stdin).",
                file=sys.stderr,
            )
            return 2
    else:
        password = getpass.getpass(f"DB password for profile '{name}' (input hidden): ")
        if not password:
            print("Password cannot be empty. Aborting.", file=sys.stderr)
            return 2
    config.set_password(name, password)
    print(f"✓ Updated password for profile '{name}'.")
    return 0


def cmd_test_connection(args: argparse.Namespace) -> int:
    name = args.profile
    profile = config.read_profile(name)
    if not profile:
        print(f"Profile '{name}' not configured.", file=sys.stderr)
        return 2
    password = config.get_password(name)
    if not password:
        print(
            f"Profile '{name}' has no password in keychain. "
            f"Run `redshift-comment-mcp set-password --profile {name}`.",
            file=sys.stderr,
        )
        return 2

    try:
        import redshift_connector
    except ImportError:
        print("redshift-connector not installed.", file=sys.stderr)
        return 3

    print(
        f"Testing connection to {profile['host']}:{profile['port']}/"
        f"{profile['dbname']} as {profile['user']}..."
    )
    try:
        conn = redshift_connector.connect(
            host=profile["host"],
            port=profile["port"],
            user=profile["user"],
            password=password,
            database=profile["dbname"],
        )
        cur = conn.cursor()
        cur.execute("SELECT current_database(), current_user")
        row = cur.fetchone()
        conn.close()
        print(f"✓ Connected. database={row[0]}, user={row[1]}")
        return 0
    except Exception as e:
        print(f"✗ Connection failed: {e}", file=sys.stderr)
        return 1


def cmd_list_profiles(args: argparse.Namespace) -> int:
    profiles = config.list_profiles()
    if not profiles:
        print("(no profiles configured — run `redshift-comment-mcp setup` to create one)")
        return 0
    print("Configured profiles:\n")
    for name in profiles:
        p = config.read_profile(name) or {}
        has_pw = config.get_password(name) is not None
        pw_status = "✓" if has_pw else "✗ (no password)"
        print(
            f"  {name}: {p.get('user', '?')}@{p.get('host', '?')}:"
            f"{p.get('port', '?')}/{p.get('dbname', '?')}  [pw {pw_status}]"
        )
    return 0


def cmd_set_fields(args: argparse.Namespace) -> int:
    """Non-interactive: write the 4 non-secret fields for a profile.

    Used by the `/redshift-setup` slash command's underlying skill so a
    chat-driven flow can persist host/port/user/dbname collected via
    Claude Q&A without going through the interactive ``setup`` prompts.
    Password is intentionally NOT a flag here — see set-password (which
    uses getpass) for that.
    """
    name = args.profile
    config.write_profile(
        name,
        host=args.host,
        port=args.port,
        user=args.user,
        dbname=args.dbname,
    )
    print(f"✓ Wrote non-secret fields for profile '{name}' to {config.config_path()}")
    return 0


def cmd_delete_profile(args: argparse.Namespace) -> int:
    name = args.profile
    if not _yes_no(
        f"Delete profile '{name}' (config + keychain password)?", default=False
    ):
        print("Aborted.")
        return 0
    if config.delete_profile(name):
        print(f"✓ Deleted profile '{name}'.")
        return 0
    print(f"Profile '{name}' did not exist.", file=sys.stderr)
    return 1


def _prompt(label: str, default: str | None = None, required: bool = False) -> str:
    bracket = f" [{default}]" if default else ""
    while True:
        v = input(f"{label}{bracket}: ").strip()
        if v:
            return v
        if default is not None:
            return default
        if not required:
            return ""
        print(f"  {label} is required.")


def _yes_no(label: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    v = input(f"{label} {suffix}: ").strip().lower()
    if not v:
        return default
    return v in ("y", "yes")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="redshift-comment-mcp",
        description=(
            "Setup CLI for redshift-comment-mcp. Use without a subcommand "
            "to start the MCP server."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("setup", help="Interactively configure a profile.")
    sp.add_argument("--profile", default="default", help="Profile name (default: 'default')")
    sp.set_defaults(func=cmd_setup)

    spw = sub.add_parser("set-password", help="Update the password for an existing profile.")
    spw.add_argument("--profile", default="default")
    spw_pwsrc = spw.add_mutually_exclusive_group()
    spw_pwsrc.add_argument(
        "--stdin",
        action="store_true",
        help=(
            "Read password from stdin (one line) instead of an interactive "
            "prompt. For scripted / CI use; never logs password to argv."
        ),
    )
    spw_pwsrc.add_argument(
        "--dialog",
        action="store_true",
        help=(
            "Collect password via OS-native dialog (macOS osascript / "
            "Linux zenity). Password value never enters chat / stdout. "
            "Recommended for code-agent setup pipelines."
        ),
    )
    spw.set_defaults(func=cmd_set_password)

    stc = sub.add_parser("test-connection", help="Verify a profile can connect.")
    stc.add_argument("--profile", default="default")
    stc.set_defaults(func=cmd_test_connection)

    slp = sub.add_parser("list-profiles", help="List all configured profiles.")
    slp.set_defaults(func=cmd_list_profiles)

    sdp = sub.add_parser("delete-profile", help="Remove a profile + its keyring password.")
    sdp.add_argument("--profile", required=True)
    sdp.set_defaults(func=cmd_delete_profile)

    ssf = sub.add_parser(
        "set-fields",
        help="Non-interactive: write the 4 non-secret fields (used by /redshift-setup skill).",
    )
    ssf.add_argument("--profile", default="default")
    ssf.add_argument("--host", required=True)
    ssf.add_argument("--port", type=int, default=5439)
    ssf.add_argument("--user", required=True)
    ssf.add_argument("--dbname", required=True)
    ssf.set_defaults(func=cmd_set_fields)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
