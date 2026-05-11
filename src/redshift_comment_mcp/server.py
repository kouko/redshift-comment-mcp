import os
import sys
import argparse
import logging
from .connection import create_redshift_config
from .redshift_tools import RedshiftTools

logger = logging.getLogger(__name__)

# Subcommands handled by setup_cli.py — delegated before server arg parsing.
SETUP_SUBCOMMANDS = {
    "setup",
    "set-password",
    "test-connection",
    "list-profiles",
    "delete-profile",
    "set-fields",
}


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

    Raises ``ValueError`` with a ``/redshift-comment-mcp:redshift-setup``-
    pointing message if the profile is missing or has no keychain password,
    so a fresh install with no profile yet surfaces a helpful next step
    rather than a cryptic stack trace.
    """
    inline_complete = bool(args.host and args.user and args.dbname)
    if inline_complete:
        password = args.password or os.getenv('REDSHIFT_PASSWORD')
        if not password:
            raise ValueError(
                "必須透過 --password 參數或 REDSHIFT_PASSWORD 環境變數提供密碼。"
            )
        return args.host, args.port, args.user, password, args.dbname

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
        existing = cfg.list_profiles()
        if existing:
            raise ValueError(
                f"Profile '{profile_name}' is not configured. "
                f"Existing profiles: {', '.join(existing)}. "
                f"Run /redshift-comment-mcp:redshift-switch-profile to pick one, "
                f"or /redshift-comment-mcp:redshift-setup to add a new profile."
            )
        raise ValueError(
            f"Profile '{profile_name}' is not configured. "
            f"Run /redshift-comment-mcp:redshift-setup in chat to set up "
            f"your Redshift connection (no terminal commands needed)."
        )
    password = cfg.get_password(profile_name)
    if not password:
        raise ValueError(
            f"Password missing from keychain for profile '{profile_name}'. "
            f"Run /redshift-comment-mcp:redshift-setup to re-enter, or "
            f"`redshift-comment-mcp set-password --profile {profile_name}` from a terminal."
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
    parser.add_argument("--port", type=int, default=5439, help="Redshift 連接埠")
    parser.add_argument("--user", help="Redshift 使用者名稱 (legacy inline 模式)")
    parser.add_argument(
        "--password",
        required=False,
        help="Redshift 密碼 (legacy inline 模式；或 REDSHIFT_PASSWORD env var)",
    )
    parser.add_argument("--dbname", help="Redshift 資料庫名稱 (legacy inline 模式)")
    args = parser.parse_args()
    host, port, user, password, dbname = resolve_connection_params(args)

    logger.info(f"正在啟動 Redshift MCP 伺服器... (host={host}, db={dbname}, user={user})")

    # 1. 建立 Redshift 連線配置（不連線；per-use pattern，首次工具呼叫時才開連線）
    try:
        connection_config = create_redshift_config(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
        )
        logger.info("Redshift 連線配置建立成功")
    except Exception as e:
        logger.critical(f"無法建立 Redshift 連線配置：{e}")
        return

    # 2. 實例化工具提供者，傳入連線配置
    redshift_tools = RedshiftTools(connection_config)
    mcp_server = redshift_tools.get_server()

    # 3. 啟動 MCP 伺服器
    try:
        logger.info("MCP 伺服器啟動中...")
        mcp_server.run()  # FastMCP defaults to STDIO transport
    except KeyboardInterrupt:
        logger.info("收到中止信號，正在關閉伺服器...")
    except Exception as e:
        logger.error(f"伺服器運行時發生錯誤: {e}", exc_info=True)
    finally:
        logger.info("MCP 伺服器已關閉。")


if __name__ == "__main__":
    main()
