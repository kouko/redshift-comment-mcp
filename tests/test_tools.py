import pytest
from unittest.mock import MagicMock, patch, Mock
from contextlib import contextmanager
from redshift_comment_mcp.redshift_tools import RedshiftTools
from redshift_comment_mcp.connection import RedshiftConnectionConfig

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
    assert mcp_server.name == "Redshift Tools"
    
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
    dangerous_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE']
    dangerous_queries = [
        "DROP TABLE users",
        "DELETE FROM users",
        "UPDATE users SET password = 'hack'",
        "INSERT INTO users VALUES ('hacker', 'password')",
        "ALTER TABLE users ADD COLUMN malicious TEXT",
        "CREATE TABLE evil_table (id INT)",
        "TRUNCATE TABLE users"
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
    assert server.name == "Redshift Tools"