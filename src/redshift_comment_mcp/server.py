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


def main():
    """主程式進入點。

    兩種模式：
    1. ``redshift-comment-mcp <subcommand>`` → 委派給 ``setup_cli.main``
       （setup / set-password / test-connection / list-profiles /
       delete-profile）
    2. ``redshift-comment-mcp [args]`` → 啟動 MCP 伺服器，支援以下兩種
       連線方式：
       - ``--profile NAME``：從 ``~/.config/redshift-comment-mcp/config.toml``
         與 OS keychain 載入（推薦；先跑 ``setup`` 建立 profile）
       - ``--host / --user / --dbname / --password``（或 ``REDSHIFT_PASSWORD``
         env var）：原本 v0.1 的 inline 模式（保留向後相容）
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
            "Load connection from a saved profile. "
            "Run `redshift-comment-mcp setup` first to create one."
        ),
    )
    parser.add_argument("--host", help="Redshift 主機位址 (使用 --profile 時自動載入)")
    parser.add_argument("--port", type=int, default=5439, help="Redshift 連接埠")
    parser.add_argument("--user", help="Redshift 使用者名稱 (使用 --profile 時自動載入)")
    parser.add_argument(
        "--password",
        required=False,
        help="Redshift 密碼 (若未提供，則嘗試從 REDSHIFT_PASSWORD 環境變數讀取；使用 --profile 時自動從 keychain 載入)",
    )
    parser.add_argument("--dbname", help="Redshift 資料庫名稱 (使用 --profile 時自動載入)")
    args = parser.parse_args()

    # Resolve connection params.
    if args.profile:
        from . import config as cfg
        profile = cfg.read_profile(args.profile)
        if not profile:
            raise ValueError(
                f"Profile '{args.profile}' not configured. "
                f"Run `redshift-comment-mcp setup --profile {args.profile}` first."
            )
        password = cfg.get_password(args.profile)
        if not password:
            raise ValueError(
                f"No password in keychain for profile '{args.profile}'. "
                f"Run `redshift-comment-mcp set-password --profile {args.profile}`."
            )
        host = profile["host"]
        port = profile["port"]
        user = profile["user"]
        dbname = profile["dbname"]
    else:
        if not args.host or not args.user or not args.dbname:
            raise ValueError(
                "Missing connection parameters. Either provide --profile NAME, "
                "or all of --host / --user / --dbname (legacy mode)."
            )
        host = args.host
        port = args.port
        user = args.user
        dbname = args.dbname
        password = args.password or os.getenv('REDSHIFT_PASSWORD')
        if not password:
            raise ValueError("必須透過 --password 參數或 REDSHIFT_PASSWORD 環境變數提供密碼。")

    logger.info(f"正在啟動 Redshift MCP 伺服器... (host={host}, db={dbname}, user={user})")

    # 1. 建立 Redshift 連線配置（會進行連線測試）
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
