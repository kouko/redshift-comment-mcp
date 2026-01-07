import logging
import re
import awswrangler as wr
from fastmcp import FastMCP
from typing import Dict, Any, Optional
from .connection import RedshiftConnectionConfig

logger = logging.getLogger(__name__)

# 分頁設定
DEFAULT_MAX_ITEMS = 50  # 預設最大回傳筆數（超過時自動截斷）


def paginate_results(items: list, limit: Optional[int], offset: int, default_max: int) -> Dict[str, Any]:
    """
    處理分頁邏輯。
    - 如果有指定 limit，使用指定的 limit
    - 如果沒有指定 limit 且資料超過 default_max，自動截斷並提示
    """
    total_count = len(items)

    # 套用 offset
    if offset > 0:
        items = items[offset:]

    # 決定實際的 limit
    if limit is not None:
        # 使用者指定了 limit
        actual_limit = limit
        truncated = len(items) > limit
        items = items[:limit]
        auto_truncated = False
    elif len(items) > default_max:
        # 超過預設最大值，自動截斷
        actual_limit = default_max
        truncated = True
        items = items[:default_max]
        auto_truncated = True
    else:
        # 資料量在範圍內，全部回傳
        actual_limit = None
        truncated = False
        auto_truncated = False

    return {
        "items": items,
        "total_count": total_count,
        "returned_count": len(items),
        "offset": offset,
        "limit": actual_limit,
        "has_more": truncated,
        "auto_truncated": auto_truncated
    }


def calculate_hit_count(name: str, comment: str, keywords: list) -> int:
    """
    計算關鍵字在 name 和 comment 中的命中次數。
    每個關鍵字最多計為 1 次（不論出現幾次）。
    """
    hit_count = 0
    search_text = f"{name.lower()} {comment.lower()}"
    for kw in keywords:
        if kw.lower() in search_text:
            hit_count += 1
    return hit_count


# --- Redshift Tools Implementation ---
class RedshiftTools:
    """
    Provides a set of tools for interacting with Redshift databases to support guided data exploration.
    Uses a connect/disconnect pattern for each operation to ensure maximum robustness.
    """
    def __init__(self, connection_config: RedshiftConnectionConfig):
        self.config = connection_config
        self.mcp = FastMCP(
            name="Redshift Comment MCP",
            instructions="""
This server provides Redshift database exploration tools with authoritative comments.

CRITICAL WORKFLOW - You MUST follow these rules:
1. Schema/Table/Column names are UNRELIABLE and may be misleading
2. Before using ANY schema, table, or column, you MUST retrieve its comment first
3. Comments are AUTHORITATIVE - if a name conflicts with its comment, always trust the comment
4. NEVER write SQL based on column names alone

MANDATORY PAGINATION HANDLING:
- All list tools return paginated results (max 50 items per request)
- Check "has_more" field in every response
- If has_more=true, you MUST call the tool again with offset to retrieve ALL remaining items
- NEVER proceed with incomplete data - always fetch ALL pages before making decisions
- Example: If total_count=120, you need 3 calls: offset=0, offset=50, offset=100

OPTIMIZATION - include_comments parameter:
- list_schemas, list_tables, list_columns support include_comments=True
- When enabled, comments are returned directly in the response
- Reduces API calls by eliminating separate get_*_comment calls

Recommended exploration flow:
1. Find schemas:
   a. list_schemas(include_comments=True) - browse all schemas with comments
   b. search_schemas - search schemas by keywords (no prerequisite)
2. Find tables:
   a. list_tables(include_comments=True) - browse tables with comments
   b. search_tables (requires schema_name) - search by keywords
3. Find columns:
   a. list_columns(include_comments=True) - browse columns with comments
   b. search_columns (requires schema_name and table_name) - search by keywords
4. execute_sql ONLY after you have read ALL column definitions

Alternative: Use get_schema_comment, get_table_comment, get_column_comment for targeted single-item queries.

When using search_schemas, search_tables or search_columns:
- search_schemas has no prerequisite - can be used directly
- search_tables requires schema_name (complete step 1 first)
- search_columns requires schema_name AND table_name (complete steps 1-2 first)
- IMPORTANT: Design keywords based on the user's conversation language
  - Database comments are typically written in the same language as the user
  - For example: if user speaks Chinese, use Chinese keywords for searching comments
  - English table/column names can still be searched alongside native language keywords
- Search results still require verification via get_table_comment or get_column_comment

When generating SQL:
- Cite the column comments in your reasoning before writing the query
- If a column's business definition differs from its name, use the definition from the comment
- Always verify your understanding of metrics, calculations, and business logic from comments
"""
        )
        self._setup_tools()

    def _setup_tools(self):
        """設定所有 MCP 工具"""

        # ========== 列表工具 ==========

        @self.mcp.tool
        def list_schemas(limit: Optional[int] = None, offset: int = 0, include_comments: bool = True) -> Dict[str, Any]:
            """
            List all schema names in the database. Supports pagination via limit/offset.
            Set include_comments=True to include schema comments in the response.
            WARNING: Schema names can be misleading. Use get_schema_comment before using any schema.
            """
            if include_comments:
                sql = """
                SELECT n.nspname AS schema_name, d.description AS schema_comment
                FROM pg_namespace n
                LEFT JOIN pg_description d ON n.oid = d.objoid
                WHERE n.nspowner > 1 AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                ORDER BY n.nspname;
                """
                with self.config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql, con=conn)
                    schemas = [{
                        "name": r['schema_name'],
                        "comment": r['schema_comment'] if r['schema_comment'] else "(No comment available)"
                    } for r in df.to_dict(orient='records')]
            else:
                sql = """
                SELECT n.nspname AS schema_name
                FROM pg_namespace n
                WHERE n.nspowner > 1 AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                ORDER BY n.nspname;
                """
                with self.config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql, con=conn)
                    schemas = df['schema_name'].tolist()

            # 分頁處理
            page = paginate_results(schemas, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "schemas": page["items"],
                "warning": "Schema names may be misleading. Use get_schema_comment for each schema before selection."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        @self.mcp.tool
        def list_tables(schema_name: str, limit: Optional[int] = None, offset: int = 0, include_comments: bool = False, include_parent_comments: bool = True) -> Dict[str, Any]:
            """
            List all table names in a schema. Supports pagination via limit/offset.
            Set include_comments=True to include table comments in the response.
            Set include_parent_comments=True to include schema comment in the response.
            WARNING: Table names can be misleading. Use get_table_comment before using any table.
            """
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            # 取得 schema comment (only if include_parent_comments=True)
            schema_comment = None
            if include_parent_comments:
                schema_sql = """
                SELECT d.description AS schema_comment
                FROM pg_namespace n
                LEFT JOIN pg_description d ON n.oid = d.objoid
                WHERE n.nspname = %s;
                """

            with self.config.get_connection() as conn:
                # 取得 schema comment
                if include_parent_comments:
                    schema_df = wr.redshift.read_sql_query(schema_sql, con=conn, params=[schema_name])
                    schema_comment = "(No comment available)"
                    if not schema_df.empty and schema_df['schema_comment'].iloc[0]:
                        schema_comment = schema_df['schema_comment'].iloc[0]

                # 取得 tables
                if include_comments:
                    tables_sql = """
                    SELECT
                        t.table_name,
                        t.table_type,
                        d.description AS table_comment
                    FROM information_schema.tables t
                    LEFT JOIN pg_class c ON c.relname = t.table_name
                    LEFT JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
                    LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
                    WHERE t.table_schema = %s
                    ORDER BY t.table_name;
                    """
                    df = wr.redshift.read_sql_query(tables_sql, con=conn, params=[schema_name])
                    records = df.to_dict(orient='records')
                    tables = [{
                        "name": r['table_name'],
                        "type": r['table_type'],
                        "comment": r['table_comment'] if r['table_comment'] else "(No comment available)"
                    } for r in records]
                else:
                    tables_sql = """
                    SELECT t.table_name, t.table_type
                    FROM information_schema.tables t
                    WHERE t.table_schema = %s
                    ORDER BY t.table_name;
                    """
                    df = wr.redshift.read_sql_query(tables_sql, con=conn, params=[schema_name])
                    records = df.to_dict(orient='records')
                    tables = [{"name": r['table_name'], "type": r['table_type']} for r in records]

            # 分頁處理
            page = paginate_results(tables, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "schema_name": schema_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "tables": page["items"],
                "warning": "Table names may be misleading. Use get_table_comment for each table before selection."
            }

            if include_parent_comments:
                result["schema_comment"] = schema_comment

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        @self.mcp.tool
        def list_columns(schema_name: str, table_name: str, limit: Optional[int] = None, offset: int = 0, include_comments: bool = False, include_parent_comments: bool = True) -> Dict[str, Any]:
            """
            List all column names and types in a table. Supports pagination via limit/offset.
            Set include_comments=True to include column comments in the response.
            Set include_parent_comments=True to include table comment in the response.
            WARNING: Column names can be misleading. Use get_all_column_comments before writing SQL.
            """
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            # 取得 table comment (only if include_parent_comments=True)
            table_comment = None
            if include_parent_comments:
                table_sql = """
                SELECT d.description AS table_comment
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
                WHERE n.nspname = %s AND c.relname = %s;
                """

            with self.config.get_connection() as conn:
                # 取得 table comment
                if include_parent_comments:
                    table_df = wr.redshift.read_sql_query(table_sql, con=conn, params=[schema_name, table_name])
                    table_comment = "(No comment available)"
                    if not table_df.empty and table_df['table_comment'].iloc[0]:
                        table_comment = table_df['table_comment'].iloc[0]

                # 取得 columns
                if include_comments:
                    columns_sql = """
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
                    df = wr.redshift.read_sql_query(columns_sql, con=conn, params=[schema_name, table_name])
                    records = df.to_dict(orient='records')
                    columns = [{
                        "name": r['column_name'],
                        "type": r['data_type'],
                        "nullable": r['is_nullable'],
                        "comment": r['column_comment'] if r['column_comment'] else "(No comment available)"
                    } for r in records]
                else:
                    columns_sql = """
                    SELECT c.column_name, c.data_type, c.is_nullable
                    FROM information_schema.columns c
                    WHERE c.table_schema = %s AND c.table_name = %s
                    ORDER BY c.ordinal_position;
                    """
                    df = wr.redshift.read_sql_query(columns_sql, con=conn, params=[schema_name, table_name])
                    records = df.to_dict(orient='records')
                    columns = [{"name": r['column_name'], "type": r['data_type'], "nullable": r['is_nullable']} for r in records]

            # 分頁處理
            page = paginate_results(columns, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "schema_name": schema_name,
                "table_name": table_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"],
                "warning": "Column names may be misleading. Use get_all_column_comments before writing SQL."
            }

            if include_parent_comments:
                result["table_comment"] = table_comment

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        # ========== 搜尋工具 ==========

        @self.mcp.tool
        def search_schemas(keywords: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """
            Search for schemas by keywords in schema name OR schema comment. Supports multiple space-separated keywords (OR logic).
            IMPORTANT: Design keywords based on the user's conversation language, as database comments are typically in the same language.
            This is a discovery tool - you MUST still call get_schema_comment to verify the schema's purpose before using it.
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            base_sql = """
            SELECT
                n.nspname AS schema_name,
                COALESCE(d.description, '') AS schema_comment
            FROM pg_namespace n
            LEFT JOIN pg_description d ON n.oid = d.objoid
            WHERE n.nspowner > 1
              AND n.nspname NOT LIKE 'pg_%%'
              AND n.nspname <> 'information_schema'
            """

            # 加入關鍵字搜尋條件（OR 邏輯）
            params = []
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(n.nspname ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            base_sql += " ORDER BY n.nspname;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                schemas = []
                for r in records:
                    name = r['schema_name']
                    comment = r['schema_comment'] if r['schema_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    schemas.append({
                        "name": name,
                        "comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, name ASC 排序
            schemas.sort(key=lambda x: (-x["hit_count"], x["name"]))

            # 分頁處理
            page = paginate_results(schemas, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "keywords": keyword_list,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "schemas": page["items"],
                "warning": "Schema names may be misleading. Use get_schema_comment to verify the schema's purpose."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        @self.mcp.tool
        def search_tables(keywords: str, schema_name: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """
            Search for tables by keywords in table name OR table comment. Supports multiple space-separated keywords (OR logic).
            For best results, include keywords in BOTH languages: the language used in table names AND the language used in table comments.
            REQUIRED: You must specify a schema_name. Use list_schemas and get_schema_comment first to identify the correct schema.
            This is a discovery tool - you MUST still call get_table_comment to verify the table's purpose before using it.
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # 驗證 schema_name
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            # 基礎查詢
            base_sql = """
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                CASE c.relkind WHEN 'r' THEN 'BASE TABLE' WHEN 'v' THEN 'VIEW' END AS table_type,
                COALESCE(d.description, '') AS table_comment
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE c.relkind IN ('r', 'v')
              AND n.nspowner > 1
              AND n.nspname NOT LIKE 'pg_%%'
              AND n.nspname <> 'information_schema'
            """

            # 加入 schema 過濾條件（必填）
            params = [schema_name]
            base_sql += " AND n.nspname = %s"

            # 加入關鍵字搜尋條件（OR 邏輯）
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(c.relname ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            base_sql += " ORDER BY n.nspname, c.relname;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                tables = []
                for r in records:
                    name = r['table_name']
                    comment = r['table_comment'] if r['table_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    tables.append({
                        "schema_name": r['schema_name'],
                        "table_name": name,
                        "table_type": r['table_type'],
                        "table_comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, table_name ASC 排序
            tables.sort(key=lambda x: (-x["hit_count"], x["table_name"]))

            # 分頁處理
            page = paginate_results(tables, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "keywords": keyword_list,
                "schema_filter": schema_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "tables": page["items"],
                "warning": "Table names may be misleading. Use get_table_comment for each table before selection."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        @self.mcp.tool
        def search_columns(keywords: str, schema_name: str, table_name: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """
            Search for columns by keywords in column name OR column comment. Supports multiple space-separated keywords (OR logic).
            For best results, include keywords in BOTH languages: the language used in column names AND the language used in column comments.
            REQUIRED: You must specify schema_name and table_name. Use list_schemas, get_schema_comment, list_tables/search_tables, and get_table_comment first.
            This is a discovery tool - you MUST still call get_column_comment to verify each column's definition before using it in SQL.
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # 驗證 schema_name 和 table_name
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")
            if not table_name or not table_name.isidentifier():
                raise ValueError("Invalid table name.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            base_sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                COALESCE(d.description, '') AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_description d ON d.objoid = (
                SELECT oid FROM pg_class WHERE relname = c.table_name AND relnamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = c.table_schema
                )
            ) AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s AND c.table_name = %s
            """

            # 參數列表
            params = [schema_name, table_name]

            # 加入關鍵字搜尋條件（OR 邏輯）
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(c.column_name ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            base_sql += " ORDER BY c.ordinal_position;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                columns = []
                for r in records:
                    name = r['column_name']
                    comment = r['column_comment'] if r['column_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    columns.append({
                        "column_name": name,
                        "data_type": r['data_type'],
                        "is_nullable": r['is_nullable'],
                        "column_comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, column_name ASC 排序
            columns.sort(key=lambda x: (-x["hit_count"], x["column_name"]))

            # 分頁處理
            page = paginate_results(columns, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "keywords": keyword_list,
                "schema_name": schema_name,
                "table_name": table_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"],
                "warning": "Column names may be misleading. Use get_column_comment for each column before using in SQL."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        # ========== 註解查詢工具 ==========

        @self.mcp.tool
        def get_schema_comment(schema_name: str) -> Dict[str, Any]:
            """
            Get the authoritative comment for a schema. MANDATORY: You must call this before using any schema. The comment defines the schema's true business purpose. If the comment conflicts with the schema name, trust the comment.
            """
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            sql = """
            SELECT d.description AS schema_comment
            FROM pg_namespace n
            LEFT JOIN pg_description d ON n.oid = d.objoid
            WHERE n.nspname = %s;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name])
                if df.empty:
                    raise ValueError(f"Schema '{schema_name}' not found.")
                comment = df['schema_comment'].iloc[0]
                comment = comment if comment else "(No comment available)"

            return {
                "schema_name": schema_name,
                "comment": comment
            }

        @self.mcp.tool
        def get_table_comment(schema_name: str, table_name: str) -> Dict[str, Any]:
            """
            Get the authoritative comment for a table. MANDATORY: You must call this before using any table. The comment defines what data the table actually contains. If the comment conflicts with the table name, trust the comment.
            """
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT d.description AS table_comment
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE n.nspname = %s AND c.relname = %s;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name])
                if df.empty:
                    raise ValueError(f"Table '{schema_name}.{table_name}' not found.")
                comment = df['table_comment'].iloc[0]
                comment = comment if comment else "(No comment available)"

            return {
                "schema_name": schema_name,
                "table_name": table_name,
                "comment": comment
            }

        @self.mcp.tool
        def get_column_comment(schema_name: str, table_name: str, column_name: str) -> Dict[str, Any]:
            """
            Get the authoritative comment for a column. MANDATORY: You must call this before using any column in SQL queries. The comment defines the column's business definition and calculation logic. If the comment conflicts with the column name, trust the comment.
            """
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT c.data_type, d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_description d ON d.objoid = (
                SELECT oid FROM pg_class WHERE relname = c.table_name AND relnamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = c.table_schema
                )
            ) AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s AND c.table_name = %s AND c.column_name = %s;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name, column_name])
                if df.empty:
                    raise ValueError(f"Column '{schema_name}.{table_name}.{column_name}' not found.")
                data_type = df['data_type'].iloc[0]
                comment = df['column_comment'].iloc[0]
                comment = comment if comment else "(No comment available)"

            return {
                "schema_name": schema_name,
                "table_name": table_name,
                "column_name": column_name,
                "data_type": data_type,
                "comment": comment
            }

        @self.mcp.tool
        def get_all_column_comments(schema_name: str, table_name: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """
            Get comments for ALL columns in a table. Supports pagination via limit/offset.
            Each comment is authoritative - if it conflicts with the column name, trust the comment.
            """
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

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
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name])
                df['column_comment'] = df['column_comment'].fillna('(No comment available)')
                records = df.to_dict(orient='records')

            # 分頁處理
            page = paginate_results(records, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "schema_name": schema_name,
                "table_name": table_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"]
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        # ========== SQL 執行工具 ==========

        @self.mcp.tool
        def execute_sql(sql_statement: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """
            Execute a read-only SQL query (SELECT/WITH only). Supports pagination via limit/offset for results.
            PREREQUISITE: Before calling this, you must have verified all column meanings using get_all_column_comments.
            """
            sql_upper = sql_statement.strip().upper()
            if not sql_upper.startswith('SELECT') and not sql_upper.startswith('WITH'):
                raise ValueError("Only SELECT and WITH queries are allowed.")

            dangerous_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE']
            for keyword in dangerous_keywords:
                if re.search(r'\b' + keyword + r'\b', sql_upper):
                    raise ValueError(f"{keyword} statements are not allowed.")

            try:
                with self.config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql_statement, con=conn)
                    records = df.to_dict(orient='records')
                    columns = list(df.columns)

                # 分頁處理
                page = paginate_results(records, limit, offset, DEFAULT_MAX_ITEMS)

                result = {
                    "total_count": page["total_count"],
                    "returned_count": page["returned_count"],
                    "offset": page["offset"],
                    "has_more": page["has_more"],
                    "columns": columns,
                    "data": page["items"]
                }

                if page["auto_truncated"]:
                    result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

                return result
            except Exception as e:
                logger.error(f"SQL execution failed: {sql_statement}", exc_info=True)
                raise ValueError(f"SQL execution error. Please check your syntax. Original error: {e}")

    def get_server(self):
        """取得配置好的 MCP 伺服器"""
        return self.mcp
