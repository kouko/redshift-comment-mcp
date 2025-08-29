import logging
import awswrangler as wr
import redshift_connector
from typing import Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class RedshiftConnectionConfig:
    """
    Redshift 連線配置類，儲存連線參數供每次使用時建立連線。
    """
    def __init__(self, host: str, port: int, user: str, password: str, dbname: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        
    def create_connection(self):
        """
        使用 redshift-connector 建立新的 Redshift 連線。
        """
        logger.debug(f"正在建立 Redshift 連線到 {self.host}:{self.port}/{self.dbname}")
        try:
            connection = redshift_connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.dbname
            )
            logger.debug("Redshift 連線建立成功")
            return connection
        except Exception as e:
            logger.error(f"建立 Redshift 連線失敗: {e}", exc_info=True)
            raise

    @contextmanager
    def get_connection(self):
        """
        Context manager 用於自動管理連線的建立和清理。
        
        使用方式:
        with config.get_connection() as conn:
            # 使用 conn 進行查詢
            df = wr.redshift.read_sql_query(sql, con=conn)
        """
        connection = None
        try:
            connection = self.create_connection()
            yield connection
        finally:
            if connection:
                try:
                    connection.close()
                    logger.debug("Redshift 連線已關閉")
                except Exception as e:
                    logger.warning(f"關閉連線時發生警告: {e}")

def create_redshift_config(host: str, port: int, user: str, password: str, dbname: str) -> RedshiftConnectionConfig:
    """
    建立 Redshift 連線配置。
    """
    logger.info(f"建立 Redshift 連線配置: {host}:{port}/{dbname}")
    
    # 立即返回配置，延遲連線驗證
    config = RedshiftConnectionConfig(host, port, user, password, dbname)
    logger.info("Redshift 連線配置已建立，連線將在首次使用工具時進行驗證。")
    
    return config