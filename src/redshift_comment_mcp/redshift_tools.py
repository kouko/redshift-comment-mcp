import logging
import re
import awswrangler as wr
from fastmcp import FastMCP
from typing import List, Dict
from .connection import RedshiftConnectionConfig

logger = logging.getLogger(__name__)

# --- Redshift Tools Implementation ---
class RedshiftTools:
    """
    Provides a set of tools for interacting with Redshift databases to support guided data exploration.
    Uses a connect/disconnect pattern for each operation to ensure maximum robustness.
    """
    def __init__(self, connection_config: RedshiftConnectionConfig):
        self.config = connection_config
        self.mcp = FastMCP("Redshift Tools")
        self._setup_tools()

    def _setup_tools(self):
        """設定所有 MCP 工具"""
        
        @self.mcp.tool
        def list_schemas() -> List[Dict[str, str]]:
            """
            [功能] (探索流程第一步) 列出資料庫中所有可用的 schema 及其註解。
            [用途] 用於理解資料庫的頂層結構和各個資料主題域的用途。
            """
            sql = """
            SELECT
                n.nspname AS schema_name,
                d.description AS schema_comment
            FROM pg_namespace n
            LEFT JOIN pg_description d ON n.oid = d.objoid
            WHERE n.nspowner > 1 AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
            ORDER BY n.nspname;
            """
            
            # 每次使用時建立新連線
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn)
                df['schema_comment'] = df['schema_comment'].fillna('')
                return df.to_dict(orient='records')

        @self.mcp.tool
        def list_tables(schema_name: str) -> List[Dict[str, str]]:
            """
            [功能] (探索流程第二步) 列出指定 schema 中的所有資料表、視圖及其註解。
            [用途] 在選擇一個 schema 後，用此工具來了解該主題域下有哪些資料表以及它們的具體內容。
            """
            # 輸入驗證
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("無效的 schema 名稱。")
                
            sql = """
            SELECT
                t.table_name,
                t.table_type,
                d.description AS table_comment
            FROM information_schema.tables t
            LEFT JOIN pg_class c ON c.relname = t.table_name AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = t.table_schema)
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE t.table_schema = %s
            ORDER BY t.table_name;
            """
            
            # 每次使用時建立新連線
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name])
                df['table_comment'] = df['table_comment'].fillna('')
                return df.to_dict(orient='records')

        @self.mcp.tool
        def list_columns(schema_name: str, table_name: str) -> List[Dict[str, str]]:
            """
            [功能] (探索流程第三步) 列出指定資料表的所有欄位、資料型態及其註解。
            [用途] 在鎖定目標資料表後，用此工具來精確理解每個欄位的商業意義、格式和用途。
            """
            # 輸入驗證
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("無效的 schema 或 table 名稱。")
                
            sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_description d ON d.objoid = (
                SELECT oid FROM pg_class WHERE relname = c.table_name AND relnamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = c.table_schema
                )
            ) AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s AND c.table_name = %s
            ORDER BY c.ordinal_position;
            """
            
            # 每次使用時建立新連線
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name])
                df['column_comment'] = df['column_comment'].fillna('')
                return df.to_dict(orient='records')

        @self.mcp.tool
        def execute_sql(sql_statement: str) -> List[Dict]:
            """
            [功能] (最終執行步驟) 在探索完資料結構後，執行一個 SQL 查詢以獲取資料。
            [注意] 此工具僅能執行唯讀的 SELECT 查詢。任何 DML/DDL 操作都將失敗。
            [範例] 若要查詢 public schema 中的 users 表，SQL 應為 "SELECT * FROM public.users LIMIT 10;"
            """
            # 基本 SQL 安全檢查
            sql_upper = sql_statement.strip().upper()
            if not sql_upper.startswith('SELECT') and not sql_upper.startswith('WITH'):
                raise ValueError("此工具僅支援 SELECT 和 WITH 查詢語句。")
            
            # 檢查危險的 SQL 關鍵字
            dangerous_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE']
            for keyword in dangerous_keywords:
                # 使用 Regex 檢查是否為獨立單字，避免誤殺像 "last_update" 這樣的欄位名稱
                if re.search(r'\b' + keyword + r'\b', sql_upper):
                    raise ValueError(f"不允許使用 {keyword} 語句。")
            
            try:
                # 每次使用時建立新連線
                with self.config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql_statement, con=conn)
                    return df.to_dict(orient='records')
            except Exception as e:
                logger.error(f"執行 SQL 失敗: {sql_statement}", exc_info=True)
                error_message = f"執行 SQL 時發生錯誤，請檢查您的語法。原始錯誤訊息: {e}"
                raise ValueError(error_message)

    def get_server(self):
        """取得配置好的 MCP 伺服器"""
        return self.mcp