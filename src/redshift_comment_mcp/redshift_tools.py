import logging
import re
import awswrangler as wr
from fastmcp import FastMCP
from typing import Dict, Any, Optional
from .connection import RedshiftConnectionConfig

logger = logging.getLogger(__name__)

# 分頁設定
DEFAULT_MAX_ITEMS = 50  # 預設最大回傳筆數（超過時自動截斷）

# Comment 大小防護
# 經 production cluster 實測（2026-05-08, n=8534）：column comment p100=471，
# table comment p90=919 / p95=1517 / p100=3680。1000 字元截斷 9% 的 table
# 長尾，column comment 完全不受影響。單筆 getter（get_table_comment 等）不
# 套用，使用者要全文時走那條路。
MAX_COMMENT_LEN = 1000

# scale_hint 觸發門檻：list_tables 回應 total_count 超過此值時附上分頁成本提示
SCALE_HINT_THRESHOLD = 100


# ===== SQL 安全驗證 =====

# str.strip() 預設只去 ASCII whitespace；MCP 傳輸／編輯器複製常會在 SQL 前面塞
# 不可見字元（BOM / ZWSP / NBSP 等），導致 startswith('SELECT'|'WITH') 誤判。
# 把這些一併剝掉。
_TRIM_CHARS = (
    " \t\n\r\f\v"
    "﻿"  # BOM
    "​"  # ZERO WIDTH SPACE
    "‌"  # ZERO WIDTH NON-JOINER
    "‍"  # ZERO WIDTH JOINER
    "⁠"  # WORD JOINER
    " "  # NO-BREAK SPACE
)

# 禁止的 mutating / privilege / IO 命令。注意這些是「禁止關鍵字」，不是
# 「禁止語句」——任何位置出現皆拒，因此包含 multi-statement piggyback。
_FORBIDDEN_KEYWORDS = (
    'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE',
    'MERGE', 'GRANT', 'REVOKE', 'COPY', 'UNLOAD',
)
_FORBIDDEN_RE = re.compile(r'\b(' + '|'.join(_FORBIDDEN_KEYWORDS) + r')\b')


def _strip_strings_and_comments(sql: str) -> str:
    """
    把 SQL 裡的字串字面量、quoted identifier、行註解、塊註解、dollar-quote
    全部置換成等長空白，讓後續的 keyword 掃描只看到「真實的 SQL token」。
    保持長度一致是為了之後若想回報行/列號不會偏移。

    未終結的字串或註解視為語法錯誤，直接 raise — 否則攻擊者可用 unterminated
    literal 把後續惡意關鍵字偽裝成「字串內文」。
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]

        # 行註解 -- ... \n
        if c == '-' and i + 1 < n and sql[i + 1] == '-':
            while i < n and sql[i] != '\n':
                out.append(' ')
                i += 1
            continue

        # 塊註解 /* ... */（Redshift 不支援巢狀，不處理）
        if c == '/' and i + 1 < n and sql[i + 1] == '*':
            out.append('  ')
            i += 2
            while i + 1 < n and not (sql[i] == '*' and sql[i + 1] == '/'):
                out.append(' ')
                i += 1
            if i + 1 >= n:
                raise ValueError("Unterminated block comment in SQL.")
            out.append('  ')
            i += 2
            continue

        # 單引號字串 '...'，'' 為跳脫
        if c == "'":
            out.append(' ')
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append('  ')
                        i += 2
                        continue
                    out.append(' ')
                    i += 1
                    break
                out.append(' ')
                i += 1
            else:
                raise ValueError("Unterminated string literal in SQL.")
            continue

        # 雙引號 quoted identifier "..."，"" 為跳脫
        if c == '"':
            out.append(' ')
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        out.append('  ')
                        i += 2
                        continue
                    out.append(' ')
                    i += 1
                    break
                out.append(' ')
                i += 1
            else:
                raise ValueError("Unterminated quoted identifier in SQL.")
            continue

        # Dollar-quoted $$...$$（PostgreSQL 擴充，Redshift SP 內可見）
        if c == '$' and i + 1 < n and sql[i + 1] == '$':
            out.append('  ')
            i += 2
            while i + 1 < n and not (sql[i] == '$' and sql[i + 1] == '$'):
                out.append(' ')
                i += 1
            if i + 1 >= n:
                raise ValueError("Unterminated dollar-quoted string in SQL.")
            out.append('  ')
            i += 2
            continue

        out.append(c)
        i += 1

    return ''.join(out)


def validate_read_only_sql(sql_statement: str) -> None:
    """
    驗證 sql_statement 為 read-only（SELECT / WITH 開頭，且不含禁用關鍵字）。
    不通過則 raise ValueError。

    防護重點：
    1. 剝除 BOM / ZWSP / NBSP 等不可見字元，避免 startswith 誤判
    2. 字串字面量、quoted identifier、行/塊/$$ 註解內的內容不參與關鍵字判定
       （消除 `WHERE col = 'INSERT'` / `-- DROP TABLE old` 之類誤殺）
    3. 禁用關鍵字以 `\\b` word boundary 比對，且套用在「sanitized 後」的 SQL 上
       （未終結的字串/註解會被 reject，不會被當成擋牆繞過）
    """
    raw = sql_statement.strip(_TRIM_CHARS) if sql_statement else ""
    if not raw:
        raise ValueError("Empty query.")

    head = raw.upper()
    if not (head.startswith('SELECT') or head.startswith('WITH')):
        raise ValueError("Only SELECT and WITH queries are allowed.")

    sanitized = _strip_strings_and_comments(raw).upper()

    m = _FORBIDDEN_RE.search(sanitized)
    if m:
        raise ValueError(f"{m.group(1)} statements are not allowed.")


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


def apply_comment_cap(items: list, key: str, max_len: int = MAX_COMMENT_LEN) -> int:
    """In-place truncate the comment field at ``key`` for each item in ``items``;
    returns the count of items that were truncated.

    Items whose comment is shorter than or equal to ``max_len`` are left
    untouched. Truncated comments get an ellipsis appended so the caller
    can detect truncation visually as well as via the returned count.
    """
    count = 0
    for item in items:
        original = item.get(key)
        if isinstance(original, str) and len(original) > max_len:
            item[key] = original[:max_len] + "…"
            count += 1
    return count


def build_scale_hint(total_count: int, page_size: int = DEFAULT_MAX_ITEMS) -> Optional[str]:
    """Return a one-line scale hint when total_count would force painful
    pagination, or None when the result is small enough to enumerate fully.

    The threshold (SCALE_HINT_THRESHOLD) is intentionally above one page
    so the hint only fires when full enumeration genuinely costs ≥3 round
    trips. Message includes the actual page count so the LLM can weigh
    cost objectively rather than relying on a magic threshold.
    """
    if total_count <= SCALE_HINT_THRESHOLD:
        return None
    pages = (total_count + page_size - 1) // page_size
    return (
        f"This schema has {total_count} tables. "
        f"Full enumeration would need {pages} paginated tool calls. "
        f"Consider search_tables(keywords) for goal-oriented queries."
    )


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
Redshift database exploration tools where COMMENTS are the source of
truth for schema / table / column meaning — names are unreliable and
may conflict with comments. Always retrieve comments before drafting
SQL; trust the comment over the name when they disagree.

PAGINATION: list_*, search_*, and get_all_column_comments cap at 50
items per response. Check `has_more`; if true, refetch with `offset`
until exhausted before drawing conclusions.

COMMENT TRUNCATION: Multi-item responses cap each comment at 1000
chars. Look for `comment_truncated_count` in the response; if present,
some comments were cut. Call get_table_comment / get_column_comment
on the specific item for full text. Single-item getters never truncate.

SCALE GUIDANCE: list_tables emits `scale_hint` when total_count > 100.
For schemas at that size, paginating list_tables to completion is
expensive — prefer search_tables(keywords) for goal-oriented queries.

OPTIMIZATION: list_* tools accept include_comments / include_parent_comments
flags to fold get_*_comment calls into the same response.

SEARCH KEYWORDS: search_schemas / search_tables / search_columns take
space-separated keywords (OR logic). Pick keywords in the user's
conversation language — comments usually match.

SEARCH SCOPE:
- search_tables(keywords, schema_name=None) — pass schema_name for
  one schema (faster, narrower); omit it for cluster-wide search.
- search_columns(keywords, schema_name, table_name=None) — pass
  table_name for one-table drill-down; omit it for schema-wide
  cross-table search (returns table_name on each row, the natural
  primitive for FK / JOIN-key reconnaissance).

For ad-hoc exploration, prefer list_* / search_* tools over execute_sql
against information_schema — they include comments directly.
"""
        )
        self._setup_tools()

    def _setup_tools(self):
        """設定所有 MCP 工具"""

        # ========== 列表工具 ==========

        @self.mcp.tool
        def list_schemas(limit: Optional[int] = None, offset: int = 0, include_comments: bool = True) -> Dict[str, Any]:
            """List schema names. include_comments defaults to True (cheap — schema count is small)."""
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
            """List tables in a schema. Pass include_comments=True to include table comments inline; include_parent_comments (default True) also returns the parent schema's comment."""
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

            # Comment 字元截斷（多筆回應防護；只對實際回傳的項目套用）
            truncated_count = 0
            if include_comments:
                truncated_count = apply_comment_cap(page["items"], "comment")

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

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} table comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_table_comment(schema, table) for full text."
                )

            scale_hint = build_scale_hint(page["total_count"])
            if scale_hint:
                result["scale_hint"] = scale_hint

            return result

        @self.mcp.tool
        def list_columns(schema_name: str, table_name: str, limit: Optional[int] = None, offset: int = 0, include_comments: bool = False, include_parent_comments: bool = True) -> Dict[str, Any]:
            """List columns (name, type, nullable) in a table. Pass include_comments=True to include column comments inline; include_parent_comments (default True) also returns the parent table's comment."""
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
                    LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
                    LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
                    LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
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

            # Comment 字元截斷（多筆回應防護；只對實際回傳的項目套用）
            truncated_count = 0
            if include_comments:
                truncated_count = apply_comment_cap(page["items"], "comment")

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

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} column comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_column_comment(schema, table, col) for full text."
                )

            return result

        # ========== 搜尋工具 ==========

        @self.mcp.tool
        def search_schemas(keywords: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Search schemas by keywords (space-separated, OR logic) over schema name and comment."""
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
        def search_tables(keywords: str, schema_name: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Search tables by keywords (space-separated, OR logic) over table name and comment.

            Pass schema_name to scope to one schema (faster, narrower). Omit it to
            search across all user schemas in the cluster (broader, slightly slower).
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # schema_name 是可選的，但若提供必須是合法 identifier
            if schema_name is not None and not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
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

            params: list = []
            if schema_name is not None:
                base_sql += " AND n.nspname = %s"
                params.append(schema_name)

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

            # Comment 字元截斷（search 永遠帶 comment，無 include_comments flag）
            truncated_count = apply_comment_cap(page["items"], "table_comment")

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

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} table comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_table_comment(schema, table) for full text."
                )

            return result

        @self.mcp.tool
        def search_columns(keywords: str, schema_name: str, table_name: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Search columns by keywords (space-separated, OR logic) over column name and comment.

            schema_name is required. Pass table_name to scope to one table (cheap;
            use this for routine drill-down). Omit table_name to search every table
            in the schema (schema-wide; the natural primitive for cross-table FK /
            JOIN-key reconnaissance, returns table_name on each row).
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # schema 必填且需是合法 identifier
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")
            # table_name 可選；若提供必須是合法 identifier
            if table_name is not None and not table_name.isidentifier():
                raise ValueError("Invalid table name.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            # schema-wide 模式回傳 table_name；single-table 模式為了向後相容也帶上
            base_sql = """
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                COALESCE(d.description, '') AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
            LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s
            """

            params: list = [schema_name]
            if table_name is not None:
                base_sql += " AND c.table_name = %s"
                params.append(table_name)

            # 加入關鍵字搜尋條件（OR 邏輯）
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(c.column_name ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            # schema-wide 模式按 table 名分組，再依 ordinal 排
            base_sql += " ORDER BY c.table_name, c.ordinal_position;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                columns = []
                for r in records:
                    name = r['column_name']
                    comment = r['column_comment'] if r['column_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    columns.append({
                        "table_name": r['table_name'],
                        "column_name": name,
                        "data_type": r['data_type'],
                        "is_nullable": r['is_nullable'],
                        "column_comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, table_name ASC, column_name ASC 排序
            columns.sort(key=lambda x: (-x["hit_count"], x["table_name"], x["column_name"]))

            # 分頁處理
            page = paginate_results(columns, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（search 永遠帶 comment，無 include_comments flag）
            truncated_count = apply_comment_cap(page["items"], "column_comment")

            result = {
                "keywords": keyword_list,
                "schema_name": schema_name,
                "table_name": table_name,
                "scope": "single_table" if table_name is not None else "schema_wide",
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"],
                "warning": "Column names may be misleading. Use get_column_comment for each column before using in SQL."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} column comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_column_comment(schema, table, col) for full text."
                )

            return result

        # ========== 註解查詢工具 ==========

        @self.mcp.tool
        def get_schema_comment(schema_name: str) -> Dict[str, Any]:
            """Get the authoritative comment for a schema — defines its true business purpose; trust it over the schema name."""
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
            """Get the authoritative comment for a table — defines what data it actually contains; trust it over the table name."""
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
            """Get the authoritative comment for a column — defines its business meaning and calculation logic; trust it over the column name."""
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT c.data_type, d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
            LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
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
            """Get authoritative comments for ALL columns in a table at once. Each comment overrides the column name."""
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
            LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s AND c.table_name = %s
            ORDER BY c.ordinal_position;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name])
                df['column_comment'] = df['column_comment'].fillna('(No comment available)')
                records = df.to_dict(orient='records')

            # 分頁處理
            page = paginate_results(records, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（多筆回應防護）
            truncated_count = apply_comment_cap(page["items"], "column_comment")

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

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} column comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_column_comment(schema, table, col) for full text."
                )

            return result

        # ========== SQL 執行工具 ==========

        @self.mcp.tool
        def execute_sql(sql_statement: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Execute a read-only SQL query (SELECT/WITH only). Result rows are paginated via limit/offset."""
            validate_read_only_sql(sql_statement)

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
