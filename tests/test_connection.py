import pytest
from unittest.mock import patch, MagicMock
from redshift_comment_mcp.connection import RedshiftConnectionConfig, create_redshift_config

def test_redshift_connection_config_initialization():
    """
    測試 RedshiftConnectionConfig 初始化。
    """
    config = RedshiftConnectionConfig(
        host="test-host",
        port=5439,
        user="test-user",
        password="test-password",
        dbname="test-db"
    )
    
    assert config.host == "test-host"
    assert config.port == 5439
    assert config.user == "test-user"
    assert config.password == "test-password"
    assert config.dbname == "test-db"

@patch('redshift_connector.connect')
def test_create_connection_success(mock_connect):
    """
    測試成功建立連線。
    """
    # 設定模擬
    mock_connection = MagicMock()
    mock_connect.return_value = mock_connection
    
    # 建立配置
    config = RedshiftConnectionConfig(
        host="test-host",
        port=5439,
        user="test-user",
        password="test-password",
        dbname="test-db"
    )
    
    # 測試連線建立
    connection = config.create_connection()
    
    # 驗證
    assert connection == mock_connection
    mock_connect.assert_called_once_with(
        host="test-host",
        port=5439,
        user="test-user",
        password="test-password",
        database="test-db"
    )

@patch('redshift_connector.connect')
def test_create_connection_failure(mock_connect):
    """
    測試連線建立失敗的情況。
    """
    # 設定模擬連線失敗
    mock_connect.side_effect = Exception("連線失敗")
    
    # 建立配置
    config = RedshiftConnectionConfig(
        host="invalid-host",
        port=5439,
        user="test-user",
        password="test-password",
        dbname="test-db"
    )
    
    # 測試連線建立應該拋出異常
    with pytest.raises(Exception, match="連線失敗"):
        config.create_connection()

@patch('redshift_connector.connect')
def test_get_connection_context_manager(mock_connect):
    """
    測試連線的 context manager 功能。
    """
    # 設定模擬
    mock_connection = MagicMock()
    mock_connect.return_value = mock_connection
    
    # 建立配置
    config = RedshiftConnectionConfig(
        host="test-host",
        port=5439,
        user="test-user",
        password="test-password",
        dbname="test-db"
    )
    
    # 測試 context manager
    with config.get_connection() as conn:
        assert conn == mock_connection
    
    # 驗證連線被關閉
    mock_connection.close.assert_called_once()

@patch('redshift_connector.connect')
def test_get_connection_context_manager_with_exception(mock_connect):
    """
    測試 context manager 在發生異常時也會正確關閉連線。
    """
    # 設定模擬
    mock_connection = MagicMock()
    mock_connect.return_value = mock_connection
    
    # 建立配置
    config = RedshiftConnectionConfig(
        host="test-host",
        port=5439,
        user="test-user",
        password="test-password",
        dbname="test-db"
    )
    
    # 測試在 context manager 中發生異常
    with pytest.raises(ValueError, match="測試異常"):
        with config.get_connection() as conn:
            assert conn == mock_connection
            raise ValueError("測試異常")
    
    # 驗證連線仍然被關閉
    mock_connection.close.assert_called_once()

@patch('redshift_connector.connect')
def test_create_redshift_config_without_validation(mock_connect):
    """
    測試 create_redshift_config 函數不會立即進行連線驗證。
    """
    # 測試成功建立配置
    config = create_redshift_config(
        host="test-host",
        port=5439,
        user="test-user",
        password="test-password",
        dbname="test-db"
    )

    # 驗證配置被正確建立
    assert isinstance(config, RedshiftConnectionConfig)
    assert config.host == "test-host"

    # 驗證連線測試沒有被執行
    mock_connect.assert_not_called()