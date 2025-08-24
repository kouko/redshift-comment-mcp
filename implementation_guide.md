# Redshift MCP 伺服器：規格與實作指南

這份文件總結了如何從概念到實作，建立一個**穩健且高效能**的 Amazon Redshift MCP (Model-Context Protocol) 伺服器。我們選擇 `awswrangler` 作為核心函式庫，並**採用官方 MCP Python SDK** 來確保協定合規性與開發效率。

## 1\. 核心規格與概念

### 1.1. MCP (Model-Context Protocol) 的本質

MCP 是一種標準化的溝通協定，其核心目的是讓大型語言模型 (LLM) 能夠理解並安全地呼叫外部工具。您可以將其視為專為 AI 設計的「API 文件」和「執行合約」。

### 1.2. 設計目的：引導式資料探索 (Guided Data Discovery)

此 MCP 服務的核心設計目的，是**引導 LLM 透過一個結構化的探索流程來理解資料庫**，而非漫無目的地猜測。這個流程遵循 **Schema -> Table -> Column** 的順序：

1.  **探索 Schema**：LLM 首先呼叫 `list_schemas`，透過閱讀 **Schema 的註解**，理解各個資料主題域（例如 `sales`, `marketing`, `finance`）的用途。
    
2.  **探索 Table**：在選定一個 Schema 後，LLM 接著呼叫 `list_tables`，透過閱讀 **Table 的註解**，了解該主題域下每張資料表的具體內容（例如 `sales_records` 表儲存銷售紀錄，`customers` 表儲存客戶資訊）。
    
3.  **探索 Column**：最後，在鎖定目標 Table 後，LLM 呼叫 `list_columns`，透過閱讀 **Column 的註解**，精確掌握每個欄位的商業意義（例如 `revenue` 欄位是含稅收入，`order_date` 是下單日期）。
    

透過在資料庫中完善這三個層級的註解，我們可以賦予 LLM 足夠的上下文，使其能夠自主、有效率地找到完成分析任務所需的資料，並生成高品質的 SQL 查詢。

### 1.3. LLM 如何使用工具

整個互動分為兩個階段：

*   **理解工具 (Understanding)**：透過伺服器提供的**動態工具定義**。LLM 會解析此定義來理解工具的能力：
    
    *   `description`: 用自然語言描述工具的用途，這是 LLM 決定**何時**使用此工具的**最關鍵依據**。
        
    *   `input_schema`: 以 JSON Schema 格式定義工具需要的**參數**，如同函式的簽名，告訴 LLM **如何**正確呼叫。
        
*   **決定使用 (Reasoning & Deciding)**：基於現代 LLM 內建的「工具使用」推理能力。當收到使用者問題時，LLM 會：
    
    1.  分析使用者意圖。
        
    2.  將意圖與其已知的工具 `description` 進行語意匹配。
        
    3.  若找到合適的工具，則根據 `input_schema` 規劃呼叫步驟並生成所需參數。
        
    4.  發起工具呼叫請求。
        

## 2\. 伺服器實作指南 (使用官方 SDK)

我們採用 `awswrangler` 作為與 Redshift 互動的核心，並使用 `fastmcp` 框架來建構伺服器，這將大幅簡化我們的程式碼。

### 2.1. 穩健性策略：每次使用時建立/切斷連線 (Per-Use Connection Pattern)

考量到 MCP 伺服器的使用特性（工具呼叫頻率相對較低且間歇性），我們採用**每次使用時建立/切斷連線**的模式。這種模式的優點如下：

*   **最大穩健性**：每次都是全新的連線，完全避免了長時間連線可能遇到的超時、斷線或狀態問題。
    
*   **資源效率**：避免維持不必要的空閒連線，節省資料庫端和網路資源。
    
*   **簡化管理**：無需處理連線池的複雜性，如連線失效檢測、重建邏輯等。
    
*   **適合 MCP 場景**：MCP 工具呼叫通常是間歇性的，不需要持續的高併發處理。
    

### 2.2. 專案檔案結構

為了支援打包與發佈，我們採用標準的 Python 套件結構，並新增 `pyproject.toml` 檔案來管理專案設定。

```
redshift-comment-mcp/
├── README.md               # 專案說明、安裝與啟動指南
├── pyproject.toml          # 專案打包與依賴設定檔
├── tests/                  # 測試程式碼目錄
│   ├── __init__.py
│   └── test_tools.py
└── src/
    └── redshift_comment_mcp/    # Python 套件的根目錄
        ├── __init__.py
        ├── connection.py
        ├── redshift_tools.py
        └── server.py
```

### 2.3. 各檔案實作細節

#### `pyproject.toml`

*   **實作內容**：此檔案是專案的中央設定檔，使用 TOML 格式定義了專案的元數據（名稱、版本、作者）、建置系統、依賴套件，以及最重要的 `[project.scripts]` 進入點。它取代了傳統的 `requirements.txt` 和 `setup.py`。
    
*   **技術選型與原因**：
    
    *   **`setuptools` / `build`**：採用 PEP 517/518 標準的現代 Python 打包架構，這是目前社群的最佳實踐，確保了建置過程的可靠性與一致性。
        
    *   **`[project.scripts]`**：這是標準化定義套件可執行進入點的方式，能讓 `pip`, `uvx` 等工具在安裝後，知道如何執行我們的伺服器主程式，是實現「零設定」流程的基礎。
        
*   **預期輸入**：此檔案由 Python 的建置工具（如 `pip`, `build`）讀取，不接收執行時期的輸入。
    
*   **預期輸出**：它指導建置工具生成可發佈的套件（`.whl`, `.tar.gz`），並讓 `uvx` 等執行器知道當套件被呼叫時，應該執行 `redshift_comment_mcp.server` 模組中的 `main` 函式。
    

```
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "redshift-comment-mcp"
version = "0.1.0"
authors = [
  { name="Your Name", email="you@example.com" },
]
description = "A Model-Context Protocol server for Amazon Redshift."
readme = "README.md"
requires-python = ">=3.10"
classifiers = [
    "Programming Language :: Python :: 3",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
]
dependencies = [
    "awswrangler[redshift]",
    "redshift-connector",
    "fastmcp",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-mock",
]

[project.urls]
"Homepage" = "https://github.com/kouko/redshift-comment-mcp"
"Bug Tracker" = "https://github.com/kouko/redshift-comment-mcp/issues"

# 這是讓 `uvx` 能夠執行的關鍵
[project.scripts]
redshift-comment-mcp = "redshift_comment_mcp.server:main"
```

#### `src/redshift_comment_mcp/connection.py`

*   **實作內容**：此模組專門負責管理 Redshift 資料庫連線配置。它定義了 `RedshiftConnectionConfig` 類別來封裝連線參數，並提供 context manager 來自動管理連線的建立與清理。
    
*   **技術選型與原因**：
    
    *   **`awswrangler.redshift.connect`**：選擇 awswrangler 的原生連線函式，因為它與 `read_sql_query` 完全相容，確保了整體架構的一致性。
        
    *   **Context Manager 模式**：使用 Python 的 `@contextmanager` 裝飾器實現自動資源管理，確保每次使用後連線都會被正確關閉，避免資源洩漏。
        
*   **預期輸入**：`RedshiftConnectionConfig` 建構函式接收五個參數：`host` (字串), `port` (整數), `user` (字串), `password` (字串), `dbname` (字串)。
    
*   **預期輸出**：`get_connection()` context manager 會產生一個可用的連線物件，使用完畢後自動關閉。
    

```
import logging
import awswrangler as wr
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
        使用 awswrangler 建立新的 Redshift 連線。
        """
        logger.debug(f"正在建立 Redshift 連線到 {self.host}:{self.port}/{self.dbname}")
        try:
            connection = wr.redshift.connect(
                cluster_identifier=None,  # 使用直接連線而非 cluster identifier
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
    
    # 驗證連線配置
    config = RedshiftConnectionConfig(host, port, user, password, dbname)
    
    # 測試連線以確保配置正確
    try:
        with config.get_connection() as conn:
            # 簡單測試查詢
            test_query = "SELECT 1 AS test"
            wr.redshift.read_sql_query(test_query, con=conn)
            logger.info("Redshift 連線配置驗證成功")
    except Exception as e:
        logger.error(f"Redshift 連線配置驗證失敗: {e}", exc_info=True)
        raise ValueError(f"無法建立 Redshift 連線，請檢查連線參數。錯誤: {e}")
    
    return config
```

#### `src/redshift_comment_mcp/redshift_tools.py`

*   **實作內容**：此模組是 MCP 服務的核心商業邏輯。它定義了一個 `RedshiftTools` 類別，其中包含了所有提供給 LLM 使用的工具函式（`list_schemas`, `execute_sql` 等）。每個工具在執行時都會使用 `with self.config.get_connection() as conn:` 模式來確保連線的自動管理。
    
*   **技術選型與原因**：
    
    *   **`fastmcp.FastMCP`**：使用 FastMCP 2.0 框架，這是一個現代化的 MCP 伺服器實作，提供簡潔的 API 和自動的工具註冊機制。
        
    *   **`@self.mcp.tool` 裝飾器**：FastMCP 提供的裝飾器，能將一個普通的 Python 函式註冊為 MCP 工具，並自動根據函式簽名、型別提示和文件字串生成工具定義。
        
    *   **`awswrangler.redshift.read_sql_query`**：選擇此函式來執行所有 SQL 查詢，因為它極大地簡化了資料庫互動，能將查詢結果直接、高效地轉換為 Pandas DataFrame，非常適合後續處理並轉換為 JSON 回傳。
        
    *   **每次使用建立連線**：使用 `with self.config.get_connection() as conn:` 模式，確保每個工具呼叫都使用全新的連線，避免長連線可能遇到的問題。
        
*   **預期輸入**：`RedshiftTools` 的建構函式接收一個 `RedshiftConnectionConfig` 物件。每個工具函式則直接接收其所需的參數。
    
*   **預期輸出**：每個工具函式都回傳一個 `List[Dict]` 型別的結果，這是一個 JSON 可序列化的格式，代表資料庫查詢的結果。
    

```
import logging
import awswrangler as wr
from fastmcp import FastMCP
from typing import List, Dict
from .connection import RedshiftConnectionConfig

logger = logging.getLogger(__name__)

# --- Redshift Tools Implementation ---
class RedshiftTools:
    """
    提供與 Redshift 資料庫互動的工具集，以支援引導式資料探索。
    採用每次使用時建立/切斷連線的模式，確保最高穩健性。
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
                if keyword in sql_upper:
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
```

#### `src/redshift_comment_mcp/server.py`

*   **實作內容**：此模組是整個 MCP 服務的**啟動進入點**。它使用 Python 內建的 `argparse` 函式庫來解析來自命令列的連線參數，並支援從環境變數讀取密碼。接著，它呼叫 `connection` 模組來建立連線配置並進行連線驗證，然後將連線配置傳遞給 `redshift_tools` 模組來實例化工具提供者。最後，它啟動 FastMCP 伺服器並處理優雅關閉。
    
*   **技術選型與原因**：
    
    *   **`argparse`**：選擇 Python 標準函式庫中的 `argparse` 來處理命令列參數，因為它功能強大、無需額外安裝依賴，是處理此類需求的標準作法。
        
    *   **`logging`**：使用 Python 標準的日誌記錄模組取代 `print()`，以實現結構化、可分級的日誌輸出，這對於在正式環境中進行監控和除錯至關重要。
        
    *   **`FastMCP`**：使用 FastMCP 框架，它提供了簡潔的 API 並自動處理 MCP 協定細節。我們只需將實作好的工具類別傳入，框架會自動處理所有協定相關的邏輯。
        
*   **預期輸入**：執行時，從命令列接收 `--host`, `--port`, `--user`, `--dbname` 等參數，以及可選的 `--password`。若未提供密碼，則會從環境變數 `REDSHIFT_PASSWORD` 讀取。
    
*   **預期輸出**：啟動一個長時間運行的伺服器進程，該進程會使用 STDIO transport 與 MCP Client 通訊。它會向標準錯誤輸出印出日誌訊息，包括啟動狀態和連線配置驗證結果。
    

```
import os
import argparse
import logging
from .connection import create_redshift_config
from .redshift_tools import RedshiftTools

# 設定基礎日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """主程式進入點，負責解析命令列參數並啟動伺服器。"""
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
```

## 3\. Client 與 Server 的互動模式

互動模式維持不變，由 SDK 在底層自動處理：

1.  **服務探索 (Discovery)**：Client 向伺服器根目錄 (`GET /`) 發送請求，SDK 自動生成工具定義並回傳。
    
2.  **工具執行 (Execution)**：Client 向 `/invoke` 端點 (`POST /invoke`) 發送請求，SDK 自動解析並執行對應的工具方法。
    

## 4\. 本地端開發與測試

在將您的 MCP 伺服器發佈到 PyPI 之前，您會需要在本地端進行大量的開發與測試。以下說明如何在您的開發環境中設定 MCP Client 來直接執行本地端的程式碼。

### 4.1. 環境設定

在執行本地端伺服器之前，請確保您已在專案根目錄下完成以下步驟：

1.  建立並啟用 Python 虛擬環境（例如 `python -m venv .venv`）。
    
2.  安裝所有開發依賴：`pip install -e ".[dev]"` (這個指令會以可編輯模式安裝主套件及 dev 依賴)。
    

### 4.2. MCP Client JSON 設定 (本地端)

此設定會直接執行您本地端的 Python 腳本，而不是從 PyPI 下載。這讓您可以即時看到程式碼修改後的效果。

```
{
  "mcpServers": {
    "redshift-comment-mcp-local": {
      "command": "python",
      "args": [
        "-m", "redshift_comment_mcp.server",
        "--host", "your-local-db-host",
        "--port", "5439",
        "--user", "your_db_user",
        "--password", "YourSecretPassword123",
        "--dbname", "dev"
      ],
      "cwd": "/path/to/your/redshift-comment-mcp"
    }
  }
}
```

**重要參數說明:**

*   `"command": "python"`: 直接使用您系統中的 `python` 指令。請確保執行 Client 的環境能找到這個指令。
    
*   `"args": ["-m", "redshift_comment_mcp.server", ...]` : 使用 `-m` 旗標來執行 `redshift_comment_mcp.server` 模組，這是 Python 建議的執行套件內模組的方式。後面跟著所有連線參數。
    
*   `"cwd": "/path/to/your/redshift-comment-mcp"`: **(關鍵)** `cwd` (Current Working Directory) 參數告訴 MCP Client 在哪個目錄下執行指令。您必須將此路徑修改為您專案在電腦上的**絕對路徑**。
    

## 5\. 部署至 PyPI 以實現「零設定」存取

此流程是將我們的專案分發給其他使用者的關鍵。

### 5.1. 使用者設定

在 Client 中提供包含連線參數的 JSON 設定。

```
{
  "mcpServers": {
    "redshift-comment-mcp": {
      "command": "uvx",
      "args": [
        "redshift-comment-mcp@latest",
        "--host", "your-cluster.region.redshift.amazonaws.com",
        "--port", "5439",
        "--user", "your_db_user",
        "--password", "YourSecretPassword123",
        "--dbname", "dev"
      ]
    }
  }
}
```

*   **安全性注意**：此方法會將資料庫密碼以明文形式儲存在 Client 的設定檔中。請確保使用此工具的電腦環境是安全的，並考慮使用權限受限的唯讀資料庫帳號，或改用下一節提到的環境變數方式。
    

### 5.2. 自動化流程

1.  Client 呼叫 `uvx` 並傳入 `args` 中的所有參數。
    
2.  `uvx` 從 PyPI 下載套件並執行，我們的 `server.py` 會接收到這些參數並建立連線。
    
3.  Client **監聽並解析**伺服器啟動時的輸出日誌，**自動捕獲**其運行的端點地址 (`http://127.0.0.1:PORT`)。
    
4.  Client **自動完成**後續的服務探索與連線。
    

### 5.3. 打包與發佈至 PyPI 的完整流程

1.  **前置準備**：
    
    *   在 [pypi.org](https://pypi.org/ "null") 註冊帳號並產生 API Token。
        
    *   安裝打包工具：`pip install build twine`。
        
2.  **建立 `pyproject.toml`**：
    
    *   此檔案已在 **2.3 節** 中詳細定義。請確保 `name` 欄位在 PyPI 上是獨一無二的。
        
3.  **建置套件**：
    
    *   在專案根目錄下執行：`python -m build`。
        
4.  **上傳至 PyPI**：
    
    *   執行：`python -m twine upload dist/*`。
        
    *   使用 `__token__` 作為使用者名稱，並貼上您的 API Token 作為密碼。
        

## 6\. 品質保證：測試策略

**問題**：缺乏自動化測試，難以保證程式碼品質與未來修改的穩定性。

**建議**：導入 `pytest` 框架，並撰寫單元測試與整合測試。

### 6.1. 單元測試 (Unit Tests)

*   **目標**：針對 `redshift_tools.py` 中的每個工具函式，在不實際連線資料庫的情況下，測試其內部邏輯。
    
*   **方法**：使用 `pytest` 搭配 `pytest-mock` 套件來模擬 (mock) 資料庫連線 (`conn`) 和 `awswrangler` 的回傳值。專注於驗證 SQL 語句是否按預期生成、回傳的 DataFrame 是否被正確處理為字典列表。
    
*   **位置**：測試程式碼應放在 `tests/test_tools.py` 中。
    

#### `tests/test_tools.py` 範例

```
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

@patch('awswrangler.redshift.read_sql_query')
def test_list_tables_with_validation(mock_read_sql, mock_config):
    """
    測試 list_tables 工具的輸入驗證。
    """
    config, mock_conn = mock_config
    
    # 建立工具實例
    redshift_tools = RedshiftTools(config)
    
    # 取得工具函數
    mcp_server = redshift_tools.get_server()
    tools = mcp_server._tools
    list_tables_func = None
    
    for tool_name, tool_info in tools.items():
        if tool_name == 'list_tables':
            list_tables_func = tool_info.func
            break
    
    assert list_tables_func is not None
    
    # 測試無效的 schema 名稱應該拋出異常
    with pytest.raises(ValueError, match="無效的 schema 名稱"):
        list_tables_func("")
    
    with pytest.raises(ValueError, match="無效的 schema 名稱"):
        list_tables_func("schema-with-dash")

@patch('awswrangler.redshift.read_sql_query')
def test_execute_sql_security_checks(mock_read_sql, mock_config):
    """
    測試 execute_sql 工具的安全性檢查。
    """
    config, mock_conn = mock_config
    
    # 建立工具實例
    redshift_tools = RedshiftTools(config)
    
    # 取得工具函數
    mcp_server = redshift_tools.get_server()
    tools = mcp_server._tools
    execute_sql_func = None
    
    for tool_name, tool_info in tools.items():
        if tool_name == 'execute_sql':
            execute_sql_func = tool_info.func
            break
    
    assert execute_sql_func is not None
    
    # 測試危險的 SQL 語句應該被拒絕
    dangerous_queries = [
        "DROP TABLE users",
        "DELETE FROM users", 
        "UPDATE users SET password = 'hack'",
        "INSERT INTO users VALUES ('hacker', 'password')"
    ]
    
    for query in dangerous_queries:
        with pytest.raises(ValueError):
            execute_sql_func(query)
```

### 6.2. 整合測試 (Integration Tests)

*   **目標**：驗證整個服務（從連線到 SQL 執行）在真實環境中的正確性。
    
*   **方法**：編寫少量測試，實際連線到一個**測試專用**的 Redshift 資料庫或本地端的 PostgreSQL。執行 `list_schemas` 等工具，並斷言回傳的結果符合預期。
    

## 7\. 附錄

### 附錄 A：為 LLM 撰寫資料庫註解的最佳實踐 (Semantic Layer)

為了讓 LLM 能最有效地理解您的資料庫結構，撰寫高品質的註解至關重要。這相當於在資料庫層級為 LLM 建立一個**語意層 (Semantic Layer)**，將原始的資料結構轉化為有意義的商業概念。參考 dbt Semantic Layer 的概念，我們建議遵循以下原則：

#### dbt Semantic Layer 核心概念

dbt Semantic Layer 的目標是在資料轉換層（dbt project）中，建立一個**集中、一致、可信**的業務指標（Metrics）定義中心。它讓所有人（無論是分析師、業務人員還是 AI）在討論「營業額」時，都能確保他們指的是同一個計算邏輯，從而消除歧義，確保分析結果的一致性。

其核心組件包括：

*   **Entities (實體)**：代表核心的業務概念，例如「顧客」、「訂單」。它們是資料之間關聯的基礎。
    
*   **Dimensions (維度)**：用來**切割**和**篩選**指標的屬性，例如「顧客的所在地區」、「訂單的日期」。
    
*   **Metrics (指標)**：對資料進行的**量化計算**，例如「總銷售額」、「活躍用戶數」。
    

#### 將 Semantic Layer 概念應用於註解

我們可以借鑑這個概念，透過結構化的註解，將這些語意資訊直接提供給 LLM。

*   **核心原則**：
    
    *   **清晰與直接 (Be Clear and Direct)**：像對一位聰明的初級數據分析師解釋一樣，直接說明用途，避免使用模糊或內部才懂的術語。
        
    *   **提供完整上下文 (Provide Full Context)**：不要假設 LLM 知道任何業務術語或隱含的規則。明確說明單位、計算方式、關聯等。
        
    *   **結構化格式 (Use a Structured Format)**：使用簡單的標籤（如 `[用途]`, `[PK]`, `[語意類型]`）來區分不同類型的資訊。這能幫助 LLM 更精確地解析註解內容，如同在 Prompt 中使用 XML 標籤一樣。
        
*   **註解範例**：
    
    *   **Schema 註解**：
        
        *   **目的**：描述這個資料主題域的**商業用途**和包含的**主要實體 (Entities)**。
            
        *   **格式建議**：`[用途] <商業用途描述> [主要實體] <實體1>, <實體2>, ...`
            
        *   **範例**：
            
            *   🔴 **不好**: `銷售資料`
                
            *   🟢 **很好**: `[用途] 儲存所有與線上零售相關的銷售數據。 [主要實體] 訂單, 客戶, 產品`
                
    *   **Table 註解**：
        
        *   **目的**：描述這張表所代表的**實體**、**主鍵 (PK)** 以及與其他表的**外鍵 (FK) 關聯**。
            
        *   **格式建議**：`[實體] <實體名稱> [內容] <具體內容描述> [PK] <主鍵欄位> [FK] <本表欄位> -> <關聯表.關聯欄位>`
            
        *   **範例**：
            
            *   🔴 **不好**: `訂單紀錄`
                
            *   🟢 **很好**: `[實體] 訂單 [內容] 包含每一筆客戶訂單的詳細記錄。 [PK] order_id [FK] customer_id -> customers.customer_id`
                
    *   **Column 註解**：
        
        *   **目的**：提供欄位的**精確商業定義**，並標示其**語意類型 (Semantic Type)**，如指標、維度或鍵。
            
        *   **格式建議**：`[定義] <商業定義> [語意類型] <Metric|Dimension|TimeDimension|PrimaryKey|ForeignKey> [單位] <單位> [計算方式] <計算方式> [枚舉值] <值1: 意義1, 值2: 意義2...>`
            
        *   **範例**：
            
            *   **範例 1 (指標 Metric)**
                
                *   🔴 **不好**: `revenue`
                    
                *   🟢 **很好**: `[定義] 該筆訂單的總銷售金額。 [語意類型] Metric [單位] 新台幣 [計算方式] 未稅商品總價 + 稅金 - 折扣。`
                    
            *   **範例 2 (維度 Dimension)**
                
                *   🔴 **不好**: `status`
                    
                *   🟢 **很好**: `[定義] 訂單的處理狀態。 [語意類型] Dimension [枚舉值] 1: 待處理, 2: 已出貨, 3: 已完成, 4: 已取消。`
                    
            *   **範例 3 (時間維度 TimeDimension)**
                
                *   🔴 **不好**: `order_date`
                    
                *   🟢 **很好**: `[定義] 客戶下訂單的日期。 [語意類型] TimeDimension`
                    
            *   **範例 4 (主鍵 PrimaryKey)**
                
                *   🔴 **不好**: `order_id`
                    
                *   🟢 **很好**: `[定義] 訂單的唯一識別碼。 [語意類型] PrimaryKey`
                    

### 附錄 B：為 LLM 設計工具描述的最佳實踐 (基於 Prompt Engineering 原則)

在 MCP 框架中，您在程式碼中為工具撰寫的**文件字串 (docstring)**，就是您提供給 LLM 的 **Prompt**。一個設計良好的 Prompt 能顯著提升 LLM 正確選擇和使用工具的能力。

*   **核心原則**：將每個工具的 `docstring` 視為一個迷你 Prompt，清晰地告訴 LLM 這個工具的**角色、能力、限制和使用範例**。
    
*   **最佳實踐**：
    
    1.  **使用結構化標籤 (Use Tags for Structure)**：
        
        *   **原因**：LLM 對於被 `<tag></tag>` 或 `[TAG]` 包裹的結構化內容有很好的理解能力。這能幫助它區分不同類型的資訊。
            
        *   **實作**：在 docstring 中使用 `[功能]`, `[用途]`, `[注意]`, `[範例]` 等標籤來組織您的描述。
            
        *   **範例** (已在 `redshift_tools.py` 中實作):
            
            ```
            """
            [功能] (最終執行步驟) 在探索完資料結構後，執行一個 SQL 查詢以獲取資料。
            [注意] 此工具僅能執行唯讀的 SELECT 查詢。任何 DML/DDL 操作都將失敗。
            [範例] 若要查詢 public schema 中的 users 表，SQL 應為 "SELECT * FROM public.users LIMIT 10;"
            """
            ```
            
    2.  **明確指示行動與目的 (Be Clear, Direct, and Action-Oriented)**：
        
        *   **原因**：避免模糊的描述。直接告訴 LLM 這個工具「做什麼」以及「為什麼要用它」。
            
        *   **實作**：使用動詞開頭的祈使句，並明確指出它在整個工作流程中的位置。
            
        *   **範例** (已在 `redshift_tools.py` 中實作):
            
            *   🔴 **不好**: `關於 schema 的資訊。`
                
            *   🟢 **很好**: `(探索流程第一步) 列出資料庫中所有可用的 schema 及其註解。`
                
    3.  **提供高品質範例 (Provide "Few-shot" Examples)**：
        
        *   **原因**：LLM 擅長從範例中學習。一個好的範例能讓 LLM 更快地掌握如何正確格式化輸入，特別是對於 `execute_sql` 這種需要生成程式碼的工具。
            
        *   **實作**：在 `[範例]` 標籤中，提供一個或多個具體的、可直接使用的呼叫範例。
            
        *   **範例** (已在 `redshift_tools.py` 中實作): `[範例] 若要查詢 public schema 中的 users 表，SQL 應為 "SELECT * FROM public.users LIMIT 10;"`
            
    4.  **明確指出限制 (State Limitations Explicitly)**：
        
        *   **原因**：告訴 LLM 工具「不能做什麼」和「能做什麼」一樣重要。這有助於防止錯誤的使用，並引導 LLM 在工具不適用時尋找其他解決方案。
            
        *   **實作**：在 `[注意]` 標籤中，清楚說明工具的限制。
            
        *   **範例** (已在 `redshift_tools.py` 中實作): `[注意] 此工具僅能執行唯讀的 SELECT 查詢。任何 DML/DDL 操作都將失敗。`
            

透過遵循以上原則，您提供給 LLM 的工具定義將不再只是一份單純的 API 文件，而是一份**高品質的、引導式的 Prompt**，能讓您的 AI Agent 表現得更聰明、更可靠。