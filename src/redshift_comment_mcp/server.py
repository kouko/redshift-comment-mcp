import os
import sys
import argparse
import logging
from typing import Optional
from .config import ConfigurationError
from .connection import create_redshift_config
from .redshift_tools import RedshiftTools

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5439


def _coerce_port(raw) -> int:
    """argparse ``type=`` for ``--port`` that tolerates optional-userConfig debris.

    A Claude Code plugin ``userConfig`` is optional: a blank port field arrives
    as ``""`` and an unset field may arrive as the unsubstituted literal
    ``${user_config.port}``. Plain ``type=int`` would make argparse abort with
    ``invalid int value`` and the server would never boot. Map any
    empty / non-numeric value to ``DEFAULT_PORT`` instead of raising; pass real
    integer strings (and already-int values) through unchanged.
    """
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_PORT


def _normalize_inline(value):
    """Return ``None`` for inline string args that aren't a real value.

    Treats an empty string OR an unsubstituted ``${user_config...}`` placeholder
    literal as "unset" so the inline-completeness check below falls through to
    profile mode instead of mistaking the placeholder for a real host/user/dbname.
    """
    if not value:
        return None
    stripped = str(value).strip()
    if stripped.startswith("${user_config") and stripped.endswith("}"):
        return None
    return value or None

# Subcommands handled by setup_cli.py — delegated before server arg parsing.
SETUP_SUBCOMMANDS = {
    "setup",
    "set-password",
    "test-connection",
    "list-profiles",
    "delete-profile",
    "set-fields",
}


def resolve_inline_params(
    args: argparse.Namespace,
) -> Optional[tuple[str, int, str, bool, str]]:
    """Detect legacy inline mode from CLI args, password presence only.

    Returns ``(host, port, user, has_password, dbname)`` when ``args.host`` /
    ``args.user`` / ``args.dbname`` all specify a real inline value (after
    the same optional-userConfig normalization ``resolve_connection_params``
    applies), else ``None``.

    ``has_password`` reflects presence of ``args.password`` or the
    ``REDSHIFT_PASSWORD`` env var — it NEVER returns the secret itself. This
    is the seam ``get_setup_status`` uses to report inline mode truthfully:
    the status tool must know "the server can connect via inline mode" without
    handling the password value.
    """
    host = _normalize_inline(args.host)
    user = _normalize_inline(args.user)
    dbname = _normalize_inline(args.dbname)
    if not (host and user and dbname):
        return None
    has_password = bool(getattr(args, "password", None) or os.getenv("REDSHIFT_PASSWORD"))
    return host, _coerce_port(args.port), user, has_password, dbname


def resolve_connection_params(args: argparse.Namespace) -> tuple[str, int, str, str, str]:
    """Resolve ``(host, port, user, password, dbname)`` from parsed CLI args.

    Two modes:

    - **Legacy inline**: all of ``args.host`` / ``args.user`` / ``args.dbname``
      are present. Password from ``args.password`` or
      ``REDSHIFT_PASSWORD`` env var. Profile name is ignored.
    - **Profile mode** (the default): look up the profile name via
      ``config.resolve_active_profile(args.profile)`` (priority CLI flag >
      ``REDSHIFT_COMMENT_PROFILE`` env > active-profile pointer file >
      ``"default"``). Read host/user/dbname from
      ``~/.config/redshift-comment-mcp/config.toml``, password from OS
      keychain.

    Raises ``ConfigurationError`` (subclass of ``ValueError`` for backward-
    compat) with a dual-path message — pointing at both
    ``/redshift-comment-mcp:redshift-setup`` (Claude Code skill) and
    ``redshift-comment-mcp setup`` (CLI, e.g. ``uvx redshift-comment-mcp
    setup``) — if the profile is missing or has no keychain password.
    Surfaces a helpful next step regardless of whether the caller has the
    Claude Code plugin installed. Code paths that should react in-process
    (e.g. degraded-mode MCP tools returning a structured not_configured
    error) catch the specific subclass; legacy ``except ValueError`` still
    works.
    """
    # Inline detection (incl. optional-userConfig normalization for ""/${...}
    # placeholders) lives in resolve_inline_params so get_setup_status can reuse
    # the exact same mode decision.
    inline = resolve_inline_params(args)
    if inline:
        host, port, user, has_password, dbname = inline
        if not has_password:
            raise ConfigurationError(
                "Inline mode requires a password — provide --password CLI "
                "flag or REDSHIFT_PASSWORD env var."
            )
        # Re-derive the password value here: resolve_inline_params deliberately
        # returns only presence (has_password bool), never the secret.
        password = args.password or os.getenv('REDSHIFT_PASSWORD')
        return host, port, user, password, dbname

    from . import config as cfg
    profile_name = cfg.resolve_active_profile(args.profile)
    profile = cfg.read_profile(profile_name)
    if not profile:
        # Two distinct UX cases share this raise site:
        # - No profiles at all → user needs to run /redshift-setup
        # - ≥1 profile, just not the one we resolved → user needs to
        #   switch (typo in name, or post-upgrade multi-profile with no
        #   "default" and no pointer file). List them so the user can
        #   spot the right name without re-running setup.
        #
        # Both messages use real "\n" between bullet items so they render
        # as multi-line when shown to the user. Concatenated f-strings
        # without explicit "\n" would render as a single run-on line.
        existing = cfg.list_profiles()
        if existing:
            raise ConfigurationError(
                f"Profile '{profile_name}' is not configured.\n"
                f"Existing profiles: {', '.join(existing)}.\n"
                f"To switch to an existing profile:\n"
                f"  - Claude Code: /redshift-comment-mcp:redshift-switch-profile\n"
                f"  - Terminal: pass `--profile <name>` to redshift-comment-mcp, "
                f"or set `REDSHIFT_COMMENT_PROFILE=<name>` env var\n"
                f"To add a new profile:\n"
                f"  - Claude Code: /redshift-comment-mcp:redshift-setup\n"
                f"  - In-band MCP tool: call `setup_via_dialog(host=..., "
                f"user=..., dbname=...)` — password collected via OS dialog "
                f"server-side, never crosses MCP wire / chat\n"
                f"  - Terminal: `uvx redshift-comment-mcp setup --profile <name>`\n"
                f"  - Code-agent Bash pipeline: `set-fields ... && set-password --dialog`"
            )
        raise ConfigurationError(
            f"Profile '{profile_name}' is not configured. Configure via one of:\n"
            f"  - Claude Code: /redshift-comment-mcp:redshift-setup in chat "
            f"(password collected via system dialog, never enters chat).\n"
            f"  - In-band MCP tool: call `setup_via_dialog(host=..., "
            f"user=..., dbname=...)` — runs the same dialog mechanism inside "
            f"this MCP session; password never crosses MCP wire / chat / "
            f"tool args.\n"
            f"  - Code agent (any MCP client with Bash): "
            f"`redshift-comment-mcp set-fields --profile {profile_name} "
            f"--host H --port P --user U --dbname D` then "
            f"`redshift-comment-mcp set-password --profile {profile_name} --dialog` "
            f"(the `--dialog` flag launches an OS-native password prompt; "
            f"`--stdin` is the headless fallback).\n"
            f"  - Human in terminal: `uvx redshift-comment-mcp setup "
            f"--profile {profile_name}` (full interactive Q&A).\n"
            f"Ask the user for host/user/dbname interactively; never invent "
            f"them. Never pass the password as a tool argument or shell "
            f"argument."
        )
    password = cfg.get_password(profile_name)
    if not password:
        raise ConfigurationError(
            f"Password missing from keychain for profile '{profile_name}'. "
            f"Re-key via one of:\n"
            f"  - Claude Code: /redshift-comment-mcp:redshift-setup\n"
            f"  - In-band MCP tool: call `setup_via_dialog(host=..., "
            f"user=..., dbname=...)` with the existing or new values to "
            f"overwrite (call `get_setup_status` first if you need the "
            f"existing field values).\n"
            f"  - Terminal: `redshift-comment-mcp set-password --profile "
            f"{profile_name} --dialog` (OS dialog) or `--stdin` (headless "
            f"pipe). DO NOT use the no-flag interactive `set-password` form "
            f"from an agent — getpass reads from /dev/tty, not stdin."
        )
    return profile["host"], profile["port"], profile["user"], password, profile["dbname"]


def main():
    """主程式進入點。

    兩種模式：
    1. ``redshift-comment-mcp <subcommand>`` → 委派給 ``setup_cli.main``
       （setup / set-password / test-connection / list-profiles /
       delete-profile / set-fields）
    2. ``redshift-comment-mcp [args]`` → 啟動 MCP 伺服器。Profile 解析
       優先級：``--profile`` flag > ``REDSHIFT_COMMENT_PROFILE`` env var
       > ``~/.config/redshift-comment-mcp/active-profile`` 檔 > ``"default"``。
       若使用者提供完整 inline 連線參數 (``--host`` / ``--user`` /
       ``--dbname`` 皆有)，則略過 profile 走 v0.1 inline 模式。
    """
    # Subcommand routing: first positional arg is one of the setup subcommands.
    if len(sys.argv) >= 2 and sys.argv[1] in SETUP_SUBCOMMANDS:
        from . import setup_cli
        sys.exit(setup_cli.main(sys.argv[1:]))

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    parser = argparse.ArgumentParser(description="Redshift MCP Server")
    parser.add_argument(
        "--profile",
        help=(
            "Override the resolved profile name. "
            "Default resolution: REDSHIFT_COMMENT_PROFILE env var > "
            "active-profile file > 'default'."
        ),
    )
    parser.add_argument("--host", help="Redshift 主機位址 (legacy inline 模式)")
    parser.add_argument(
        "--port",
        type=_coerce_port,
        default=DEFAULT_PORT,
        help="Redshift 連接埠 (空字串 / 未替換的 userConfig 佔位符 → 預設 5439)",
    )
    parser.add_argument("--user", help="Redshift 使用者名稱 (legacy inline 模式)")
    parser.add_argument(
        "--password",
        required=False,
        help="Redshift 密碼 (legacy inline 模式；或 REDSHIFT_PASSWORD env var)",
    )
    parser.add_argument("--dbname", help="Redshift 資料庫名稱 (legacy inline 模式)")
    args = parser.parse_args()

    # Degraded-mode startup contract (since v0.7.0):
    #   The server boots and enters the MCP stdio loop EVEN if no profile is
    #   configured. Profile resolution is deferred to each MCP tool call via
    #   the lazy provider below. A tool whose call raises ConfigurationError
    #   returns a structured `not_configured` error to the agent instead of
    #   crashing the server. The new `setup_via_dialog` MCP tool lets an
    #   agent provision a profile in-band — fields via args, password via OS
    #   dialog server-side; the password never crosses the MCP wire.
    #
    #   Re-resolution happens per call (no cache), so newly-written profiles
    #   become live without restarting the MCP client.
    def lazy_config_provider():
        """Resolve connection params + build a RedshiftConnectionConfig.

        Called on every MCP tool invocation that needs a DB connection.
        Re-reads config.toml + keychain each time, so updates from
        `setup_via_dialog` / `setup` / `set-password` take effect immediately.
        """
        host, port, user, password, dbname = resolve_connection_params(args)
        return create_redshift_config(
            host=host, port=port, user=user, password=password, dbname=dbname,
        )

    logger.info("MCP 伺服器啟動中（degraded-mode 啟動 — profile 在第一次 tool 呼叫時 lazy resolve）")
    # Re-evaluated per get_setup_status call (not cached) so a REDSHIFT_PASSWORD
    # env change is reflected, mirroring lazy_config_provider's re-resolution.
    redshift_tools = RedshiftTools(
        lazy_config_provider,
        inline_status_provider=lambda: resolve_inline_params(args),
    )
    mcp_server = redshift_tools.get_server()

    try:
        mcp_server.run()  # FastMCP defaults to STDIO transport
    except KeyboardInterrupt:
        logger.info("收到中止信號，正在關閉伺服器...")
    except Exception as e:
        logger.error(f"伺服器運行時發生錯誤: {e}", exc_info=True)
    finally:
        logger.info("MCP 伺服器已關閉。")


if __name__ == "__main__":
    main()
