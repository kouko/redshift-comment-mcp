"""Interactive setup CLI for redshift-comment-mcp.

Subcommands (invoked as ``redshift-comment-mcp <subcommand>``):

- ``setup [--profile NAME]``        — full Q&A for one profile
- ``set-password [--profile NAME]`` — only update the password
- ``test-connection [--profile NAME]`` — verify a profile can connect
- ``list-profiles``                  — list all configured profiles
- ``delete-profile --profile NAME``  — remove a profile + its keyring entry

Subcommands route through ``main()`` in this module; the bare command
``redshift-comment-mcp`` (with no subcommand) starts the MCP server in
``server.py``.
"""
from __future__ import annotations

import argparse
import getpass
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


def cmd_set_password(args: argparse.Namespace) -> int:
    name = args.profile
    if not config.read_profile(name):
        print(
            f"Profile '{name}' not configured. "
            f"Run `redshift-comment-mcp setup --profile {name}` first.",
            file=sys.stderr,
        )
        return 2
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
    spw.set_defaults(func=cmd_set_password)

    stc = sub.add_parser("test-connection", help="Verify a profile can connect.")
    stc.add_argument("--profile", default="default")
    stc.set_defaults(func=cmd_test_connection)

    slp = sub.add_parser("list-profiles", help="List all configured profiles.")
    slp.set_defaults(func=cmd_list_profiles)

    sdp = sub.add_parser("delete-profile", help="Remove a profile + its keyring password.")
    sdp.add_argument("--profile", required=True)
    sdp.set_defaults(func=cmd_delete_profile)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
