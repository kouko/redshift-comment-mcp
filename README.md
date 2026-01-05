# Redshift MCP 伺服器

這是一個基於 Model Context Protocol (MCP) 的 Amazon Redshift 資料庫探索工具，專為 AI 語言模型設計，提供結構化的資料庫探索功能。

## 功能特色

- **引導式資料探索**：遵循 Schema → Table → Column 的探索流程
- **穩健連線管理**：採用每次使用時建立/切斷連線的模式確保最高穩定性
- **MCP 標準協定**：使用 FastMCP 框架實作，符合 MCP 協定標準
- **多種工具**：提供 schema、table、column 列表查詢及 SQL 執行功能

## 安裝

### 從 PyPI 安裝 (推薦)

```bash
pip install redshift-comment-mcp
```

### 本地開發安裝

```bash
git clone https://github.com/kouko/redshift-comment-mcp.git
cd redshift-comment-mcp
pip install -e ".[dev]"
```

**系統需求**：本專案需要 Python 3.10 或更高版本。

## 使用方式

### 命令列執行

```bash
redshift-comment-mcp --host your-cluster.region.redshift.amazonaws.com \
                --port 5439 \
                --user your_username \
                --password your_password \
                --dbname your_database
```

### 使用環境變數

您可以將密碼存放在環境變數中：

```bash
export REDSHIFT_PASSWORD=your_password
redshift-comment-mcp --host your-cluster.region.redshift.amazonaws.com \
                --port 5439 \
                --user your_username \
                --dbname your_database
```

## MCP Client 設定

### 方式一：使用 uvx（從 PyPI 安裝，推薦正式使用）

在 MCP Client 的設定檔中加入以下設定：

```json
{
  "mcpServers": {
    "redshift-comment-mcp": {
      "command": "uvx",
      "args": [
        "redshift-comment-mcp@latest",
        "--host", "your-cluster.region.redshift.amazonaws.com",
        "--port", "5439",
        "--user", "your_username",
        "--password", "your_password",
        "--dbname", "your_database"
      ]
    }
  }
}
```

### 方式二：本地開發設定（推薦開發使用）

對於本地開發，需要使用 **Python 的完整路徑**，否則 MCP Client 可能會找不到 Python 執行檔。

#### 步驟 1：找到 Python 完整路徑

```bash
# 如果使用 conda 環境
which python
# 例如輸出：/Users/username/opt/miniconda3/envs/redshift-comment-mcp/bin/python

# 如果使用 venv
# 例如：/path/to/project/.venv/bin/python
```

#### 步驟 2：確認套件已用 editable 模式安裝

```bash
cd /path/to/redshift-comment-mcp
pip install -e ".[dev]"
```

#### 步驟 3：設定 MCP Client

在 `~/.claude.json`（Claude Code）或 `claude_desktop_config.json`（Claude Desktop）中加入：

```json
{
  "mcpServers": {
    "redshift-local": {
      "command": "/Users/username/opt/miniconda3/envs/redshift-comment-mcp/bin/python",
      "args": [
        "-m", "redshift_comment_mcp.server",
        "--host", "your-cluster.region.redshift.amazonaws.com",
        "--port", "5439",
        "--user", "your_username",
        "--password", "your_password",
        "--dbname", "your_database"
      ]
    }
  }
}
```

> ⚠️ **重要**：`command` 必須使用 Python 的**完整絕對路徑**（如 `/Users/username/opt/miniconda3/envs/xxx/bin/python`），不能只寫 `python`，否則會出現 `executable file not found in $PATH` 錯誤。

#### 使用環境變數隱藏密碼（可選）

```json
{
  "mcpServers": {
    "redshift-local": {
      "command": "/Users/username/opt/miniconda3/envs/redshift-comment-mcp/bin/python",
      "args": [
        "-m", "redshift_comment_mcp.server",
        "--host", "your-cluster.region.redshift.amazonaws.com",
        "--port", "5439",
        "--user", "your_username",
        "--dbname", "your_database"
      ],
      "env": {
        "REDSHIFT_PASSWORD": "your_password"
      }
    }
  }
}
```

### 更新原始碼後

如果套件是用 editable 模式安裝（`pip install -e .`），更新原始碼後**不需要重新安裝**，只需要**重啟 MCP Server**（重啟 Claude Code / Claude Desktop）即可載入最新程式碼。

## 可用工具

### 1. List Schemas
列出資料庫中所有可用的 schema 及其註解。這是探索流程的第一步。

### 2. List Tables
列出指定 schema 中的所有資料表、視圖及其註解。

### 3. List Columns
列出指定資料表的所有欄位、資料型態及其註解。

### 4. Execute SQL
執行 SQL 查詢以獲取資料。僅支援 SELECT 查詢。

## 開發

### 執行測試

```bash
pytest tests/
```

### 建置套件

```bash
python -m build
```

### 發佈到 PyPI

#### 自動化發佈（推薦）
本專案使用 GitHub Actions 自動化發佈流程：

1. 更新 `pyproject.toml` 中的版本號
2. 建立 GitHub Release
3. GitHub Actions 自動執行測試、建置並發佈到 PyPI

詳細設定請參考 [.github/DEPLOYMENT.md](.github/DEPLOYMENT.md)

#### 手動發佈
```bash
python -m twine upload dist/*
```

## 資料庫註解最佳實踐

為了讓 AI 更好地理解您的資料庫結構，建議在資料庫中新增結構化的註解：

### Schema 註解範例
```sql
COMMENT ON SCHEMA sales IS '[用途] 儲存所有與線上零售相關的銷售數據。 [主要實體] 訂單, 客戶, 產品';
```

### Table 註解範例
```sql
COMMENT ON TABLE sales.orders IS '[實體] 訂單 [內容] 包含每一筆客戶訂單的詳細記錄。 [PK] order_id [FK] customer_id -> customers.customer_id';
```

### Column 註解範例
```sql
COMMENT ON COLUMN sales.orders.revenue IS '[定義] 該筆訂單的總銷售金額。 [語意類型] Metric [單位] 新台幣 [計算方式] 未稅商品總價 + 稅金 - 折扣。';
```

## 授權

MIT License

## 貢獻

歡迎提交 Issue 和 Pull Request。