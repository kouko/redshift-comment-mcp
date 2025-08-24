import os
import argparse
import logging
from .connection import create_redshift_config
from .redshift_tools import RedshiftTools

logger = logging.getLogger(__name__)

def main():
    """主程式進入點，負責解析命令列參數並啟動伺服器。"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    parser = argparse.ArgumentParser(description="Redshift MCP Server")
    parser.add_argument("--host", required=True, help="Redshift 主機位址")
    parser.add_argument("--port", type=int, default=5439, help="Redshift 連接埠")
    parser.add_argument("--user", required=True, help="Redshift 使用者名稱")
    parser.add_argument("--password", required=False, help="Redshift 密碼 (若未提供，則嘗試從 REDSHIFT_PASSWORD 環境變數讀取)")
    parser.add_argument("--dbname", required=True, help="Redshift 資料庫名稱")
    args = parser.parse_args()

    password = args.password or os.getenv('REDSHIFT_PASSWORD')
    if not password:
        raise ValueError("必須透過 --password 參數或 REDSHIFT_PASSWORD 環境變數提供密碼。")

    logger.info("正在啟動 Redshift MCP 伺服器...")
    
    # 1. 建立 Redshift 連線配置（會進行連線測試）
    try:
        connection_config = create_redshift_config(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password,
            dbname=args.dbname
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