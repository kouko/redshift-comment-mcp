# redshift_comment_mcp

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

`redshift-comment-mcp` MCP server 的 Python 原始碼。本套件對 Claude
（或任何支援 MCP 的 client）公開 **11 個只讀工具**：schema / table /
column 列舉、含 hit-count 的關鍵字搜尋、註解擷取，以及 SELECT-only
SQL 執行。全部設計上都是只讀的 —— `execute_sql` 在 parse 層直接
拒絕 DDL / DML 關鍵字。

## 模組結構

| 檔案 | 角色 |
|---|---|
| [`server.py`](server.py) | Process 入口。在 MCP server（預設）與 setup CLI 子指令（`setup` / `set-password` / `test-connection` 等）之間做路由。 |
| [`redshift_tools.py`](redshift_tools.py) | 11 個 MCP tools 的實作（`list_schemas` / `list_tables` / `list_columns` / `search_*` / `get_*_comment` / `get_all_column_comments` / `execute_sql`）。每支 tool 都有顯式的分頁、提醒 LLM 看註解的 `WARNING` 字串、嚴格的 identifier 驗證。 |
| [`config.py`](config.py) | Profile 儲存。非機密欄位放在 `~/.config/redshift-comment-mcp/config.toml`（遵循 XDG Base Directory），密碼透過 `keyring` 套件存進 OS keychain。支援多 profile。 |
| [`connection.py`](connection.py) | Per-use 連線模式（`@contextmanager`）—— 每次 tool 呼叫開新 Redshift 連線、立即關閉。刻意不維護長存的 connection pool。 |
| [`setup_cli.py`](setup_cli.py) | 上述子指令使用的對話式 Q&A CLI。密碼透過 `getpass` 收集，不會留在 shell history。 |
| [`__init__.py`](__init__.py) | 空檔 —— 套件對外的介面就是 `server.py` 註冊的東西。 |

## Charter

這裡的一切都服務於 **Guided Data Discovery（引導式資料探索）**。具體上：

- **註解是一等公民**。所有 list / search tools 在被請求時都會主動回傳
  註解。名字會騙人；註解通常是最接近語意 ground truth 的東西。
- **不允許寫入**。`execute_sql` 只接受以 `SELECT` 或 `WITH` 開頭的語句，
  並用 word-boundary regex 拒絕 `INSERT` / `UPDATE` / `DELETE` /
  `DROP` / `CREATE` / `ALTER` / `TRUNCATE`。這個限制在 server 邊界強制
  執行，`skills/` 底下的 skill 也都仰賴它。
- **Per-use 連線**。MCP server 不維護 connection pool。每次 tool 呼叫
  都是開、跑、關。理由：錯誤恢復簡單、不會踩到 stale cursor、tool 開銷
  相對於實際 query 延遲小。
- **預設分頁**。所有 list tools 都公開 `limit` / `offset`，並用
  `DEFAULT_MAX_ITEMS` 自動截斷以維持回應大小有界。

## 執行期路徑

| 路徑 | 內容 | 權限 |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | 非機密 profile 欄位（host / port / user / dbname） | `0600` |
| OS keychain（service `redshift-comment-mcp`、account `<profile-name>`） | 密碼 | OS 管理 |

## 執行方式

```bash
# 1. 安裝（一次性）
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp setup

# 2. 驗證
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp test-connection

# 3. 當 MCP server 跑（plugin.json 會自動串接）
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp --profile default
```

End-user 設定流程請看
[`skills/redshift-setup/SKILL.md`](../../skills/redshift-setup/SKILL.md)；
設計理由（per-use 連線模式、註解優先 charter、semantic layer 最佳實踐）
請看 [`implementation_guide.md`](../../implementation_guide.md)。

## 測試

測試放在 [`../../tests/`](../../tests/)，涵蓋 tool surface 與分頁計算。
從 repo 根目錄跑 `pytest` 即可。
