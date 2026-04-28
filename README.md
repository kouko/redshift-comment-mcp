# Redshift MCP 伺服器

這是一個基於 Model Context Protocol (MCP) 的 Amazon Redshift 資料庫探索工具，專為 AI 語言模型設計，提供結構化的資料庫探索功能。

## 功能特色

- **引導式資料探索**：遵循 Schema → Table → Column 的探索流程
- **穩健連線管理**：採用每次使用時建立/切斷連線的模式確保最高穩定性
- **MCP 標準協定**：使用 FastMCP 框架實作，符合 MCP 協定標準
- **多種工具**：提供 schema、table、column 列表查詢、關鍵字搜尋及 SQL 執行功能
- **連線 profile 管理**（v0.2.0+）：互動式 setup CLI、密碼存於 OS keychain、多 cluster 透過 named profile 切換
- **Claude Code plugin 支援**（v0.2.0+）：一行指令安裝，無需手編 `~/.claude.json`

## 系統需求

Python 3.10+。macOS / Linux / Windows 支援（Linux 無 D-Bus 環境的 keychain 行為見[安全性](#安全性)說明）。

---

## 安裝方式

依使用情境選擇：

| 情境 | 推薦方式 |
|---|---|
| Claude Code 使用者 | [方式 A: Claude Code plugin](#方式-a-claude-code-plugin推薦)（一行裝好） |
| Claude Desktop / 其他 MCP client / 不想用 Claude Code plugin | [方式 B: PyPI 套件](#方式-b-pypi-套件) |
| 想改 source code | [方式 C: 本地開發](#方式-c-本地開發) |

### 方式 A: Claude Code plugin（推薦）

```bash
# 1. 註冊 marketplace（一次性）
claude plugin marketplace add kouko/redshift-comment-mcp

# 2. 安裝 plugin（cloned 到 ~/.claude/plugins/cache/...）
claude plugin install redshift-comment-mcp

# 3. 在你自己的 terminal 跑互動式 setup（直接從 GitHub 拉 source，不需要 PyPI 已發版）
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp setup
```

setup 會問你 4 個欄位（host / port / user / dbname），密碼用 `getpass` 隱藏輸入後存進 OS keychain，最後自動測連線。完成。

> 💡 **plugin 不從 PyPI 拉 source code**。Plugin 啟動 MCP server 時走 `uv run --project ${CLAUDE_PLUGIN_ROOT}` — 直接用 cloned repo 內的 `pyproject.toml` 建 venv，所以 PR 合併到 main 後**不需要等 PyPI 發版**就立即可用。
>
> 第一次啟動會花 ~10-15s 建 venv（uv 會 cache 下來，後續 <2s）。
>
> 一旦 v0.2.0+ 發到 PyPI，setup CLI 那條也可以簡化成 `uvx redshift-comment-mcp setup`（uvx 拉 PyPI），但兩種寫法都一樣有效。

要連多個 cluster？每個 cluster 用一個 profile 名稱：

```bash
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp setup --profile dev
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp setup --profile prod
```

然後 plugin 透過 `userConfig` 的 profile 欄位選用哪個 — 安裝時 prompt（或於 `~/.claude/settings.json` 編輯 `pluginConfigs[<id>].options.profile`）。

### 方式 B: PyPI 套件

#### 安裝

```bash
pip install redshift-comment-mcp
# 或不安裝，每次用 uvx：uvx redshift-comment-mcp ...
```

#### 設定連線（推薦：使用 setup CLI）

```bash
redshift-comment-mcp setup
# 然後在 MCP client 設定檔內：
```

```json
{
  "mcpServers": {
    "redshift-comment-mcp": {
      "command": "uvx",
      "args": ["redshift-comment-mcp", "--profile", "default"]
    }
  }
}
```

#### 設定連線（legacy：直接傳 args）

v0.1.x 的方式仍然支援，密碼建議走環境變數：

```json
{
  "mcpServers": {
    "redshift-comment-mcp": {
      "command": "uvx",
      "args": [
        "redshift-comment-mcp",
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

### 方式 C: 本地開發

```bash
git clone https://github.com/kouko/redshift-comment-mcp.git
cd redshift-comment-mcp
pip install -e ".[dev]"
```

之後要在 MCP client 跑開發版本，可以：

```bash
# 用 setup CLI 建 profile（同方式 A/B）
python -m redshift_comment_mcp.server setup
```

```json
{
  "mcpServers": {
    "redshift-local": {
      "command": "/path/to/your/python",
      "args": ["-m", "redshift_comment_mcp.server", "--profile", "default"]
    }
  }
}
```

> ⚠️ `command` 仍須是 Python 的**完整絕對路徑**（如 conda env 內的 python），不能只寫 `python`。`which python` 取得。
>
> 用 setup CLI 後 source code 改了**不需要重新安裝**，只需重啟 MCP server（重啟 Claude Code / Claude Desktop）。

---

## Setup CLI 子指令

| 子指令 | 用途 |
|---|---|
| `redshift-comment-mcp setup [--profile NAME]` | 互動式建立或更新 profile（5 個欄位 + 自動測連線）|
| `redshift-comment-mcp set-password [--profile NAME]` | 只更新密碼（getpass 隱藏輸入）|
| `redshift-comment-mcp test-connection [--profile NAME]` | 驗證 profile 能成功連線 |
| `redshift-comment-mcp list-profiles` | 列出所有 profile + 是否有密碼 |
| `redshift-comment-mcp delete-profile --profile NAME` | 刪除 profile（config + keychain）|

預設 profile 名稱是 `default`。`--profile` 不指定時皆作用於 `default`。

### 設定檔位置

- **非密碼欄位**（host / port / user / dbname）：`~/.config/redshift-comment-mcp/config.toml`（檔案 mode `600`，遵循 XDG Base Directory）
- **密碼**：OS keychain（macOS Keychain / Windows Credential Locker / Linux Secret Service），service name `redshift-comment-mcp`，username 為 profile 名稱

config.toml 範例：

```toml
[profile.default]
host = "my-cluster.abc123.us-east-1.redshift.amazonaws.com"
port = 5439
user = "alice"
dbname = "analytics"

[profile.prod]
host = "prod-cluster.xyz.ap-northeast-1.redshift.amazonaws.com"
port = 5439
user = "alice_prod"
dbname = "analytics_prod"
```

---

## 可用工具

### 1. List Schemas
列出資料庫中所有可用的 schema 及其註解。這是探索流程的第一步。

### 2. List Tables
列出指定 schema 中的所有資料表、視圖及其註解。

### 3. List Columns
列出指定資料表的所有欄位、資料型態及其註解。

### 4. Search Schemas / Tables / Columns
依關鍵字搜尋 schema / table / column 名稱與註解，按命中關鍵字數排序。

### 5. Get Schema / Table / Column Comment
取得特定 schema / table / column 的註解（含父層 context）。

### 6. Execute SQL
執行 SQL 查詢以獲取資料。僅支援 SELECT / WITH 查詢，DROP / DELETE / UPDATE / INSERT / ALTER / CREATE / TRUNCATE 一律拒絕。

---

## 安全性

- **密碼儲存**：v0.2.0+ 預設透過 Python `keyring` 套件存於 OS keychain。macOS Keychain / Windows Credential Locker / Linux Secret Service（D-Bus）都會走原生加密儲存。
- **Linux 無 D-Bus 環境**（headless server / 容器內）：`keyring` 會 fallback 到 `~/.local/share/python_keyring/keyring_pass.cfg`（檔案 mode `600`，但**內容明文**）。若是這類環境建議改用環境變數 `REDSHIFT_PASSWORD` + legacy CLI args 模式。
- **config.toml 不含密碼**，但仍建議 `~/.config/redshift-comment-mcp/` 維持 owner-only（setup CLI 寫入時自動 `chmod 600`）。
- **Plugin distribution 不含密碼**：plugin manifest 只記 profile 名稱，密碼始終留在你機器的 keychain；分享 marketplace 不會洩漏 credentials。

---

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

---

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

---

## 授權

MIT License

## 貢獻

歡迎提交 Issue 和 Pull Request。
