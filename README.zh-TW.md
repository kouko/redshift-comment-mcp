# redshift-comment-mcp

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

一個給 Amazon Redshift 用的只讀 **Model Context Protocol** server，外加
一個基於它的 Claude Code plugin，內含 6 支 slash command skills。整個
設計建立在一個前提上：**欄位名會騙人，註解不會** —— 所以 server 主動
吐出註解，而 skills 把這些 tool 串成你每天真正在做的探索流程。

```
「dbt_marts.fct_orders.status 實際上裝的是哪些值？」
   → /redshift-profile dbt_marts.fct_orders status
   → cardinality、top-N、null 比例、min/max、既有註解 —— 一回合搞定。
```

## 為什麼要有這東西

如果你曾打開過一張不熟的 Redshift 表，盯著 `f3` / `legacy_id_v2` /
`status`（哪一種 `status`？）這種欄位名發呆，你已經懂這個痛了。dbt
manifest 涵蓋面太窄、Web GUI 太慢、手刻 SQL 太重複。

這個 plugin 的 charter 是 **Guided Data Discovery（引導式資料探索）**：

- **註解優先**。所有 list / search tools 在被請求時都會主動吐出註解。
  名字是輔助，註解才是權威。
- **結構上只讀**。`execute_sql` 在 parse 層直接拒絕 DDL / DML；本 repo
  裡的所有 skill 都不可能改動 Redshift。
- **MCP 組合型 skill**。新工作流靠串接既有 tools 實現，不會多開資料庫
  連線。
- **不做持久化**。沒有 synthesis layer、沒有 `.redshift-wiki/` markdown、
  沒有 stale tracking。（cache 是可重建的，那是另一回事。）持久化是另
  一個 plugin 的工作。

完整 charter 見 [`implementation_guide.md`](implementation_guide.md) §1.2。

## 你能拿到什麼

### MCP tools（11 支，定義在 [`src/redshift_comment_mcp/`](src/redshift_comment_mcp/)）

| 群組 | Tools |
|---|---|
| List | `list_schemas` · `list_tables` · `list_columns` |
| Search（依命中關鍵字數排序） | `search_schemas` · `search_tables` · `search_columns` |
| 註解擷取 | `get_schema_comment` · `get_table_comment` · `get_column_comment` · `get_all_column_comments` |
| Query | `execute_sql`（只接受 SELECT / WITH） |

每支 list / search 都有分頁；明確的 `WARNING` 字串會推 LLM 先讀註解
再相信名字。

### Slash command skills（6 支，定義在 [`skills/`](skills/)）

| Skill | 一句話 | 版本 |
|---|---|---|
| [/redshift-setup](skills/redshift-setup/) | 對話式逐步設定連線 profile。 | v0.2.0 |
| [/redshift-switch-profile](skills/redshift-switch-profile/) | 切換 active profile（不再次輸入 host / user / password）；單 profile 使用者會被溫和拒絕。 | v0.4.0 |
| [/redshift-profile](skills/redshift-profile/) | 一回合內回出欄位的 cardinality / top-N / null 比例 / min-max / 既有註解。 | v0.3.0 |
| [/redshift-cache-schema](skills/redshift-cache-schema/) | LLM 內部 cache：把 cluster 結構寫到本地檔，讓後續 skill 呼叫能快速解析 metadata。 | v0.3.0 |
| [/redshift-explore](skills/redshift-explore/) | 三步 wizard（schema → table → column）—— 讀註解來挑，不用記名字。 | v0.3.0 |
| [/redshift-lineage-from-stl](skills/redshift-lineage-from-stl/) | 挖 `STL_QUERY` + sqlglot 從查詢歷史還原**實際**的 table 對 table 資料流。 | v0.3.0 |

每支 skill 在自己的資料夾內都有三語 README（除了 `/redshift-setup` 與
`/redshift-switch-profile` 屬於 setup-style 內部 skill —— 直接看 SKILL.md）。

## 快速開始

最快的路徑是 Claude Code plugin。

```bash
# 1. 註冊 marketplace（一次性）
claude plugin marketplace add kouko/redshift-comment-mcp

# 2. 安裝 plugin
claude plugin install redshift-comment-mcp

# 3. 在 Claude Code 對話中設定連線 profile
/redshift-setup
```

`/redshift-setup` 會逐項問你 host / port / user / dbname / password。
**密碼會用系統對話框（macOS）/ zenity 視窗（Linux 桌面）/ 你自己的
terminal（headless）收集，絕對不進對話 transcript。** 直接寫進 OS
keychain。

設定完就直接打上面任何一個 slash command 即可。要連多個 cluster？
跑 `/redshift-setup <名字>` 加第二個 profile，再用
`/redshift-switch-profile` 在它們之間切換。

Claude Desktop / 其他 MCP client / 本地開發見下面的**其他安裝路徑**。

## 其他安裝路徑

| 情境 | 方式 |
|---|---|
| Claude Code（推薦） | `claude plugin install redshift-comment-mcp`（如上）。零設定 —— manifest 不再要求 profile name；MCP server 啟動時讀 `/redshift-setup` 寫的 active-profile 指標檔。 |
| Claude Desktop / 一般 MCP client | `pip install redshift-comment-mcp`，client config 指向 `uvx redshift-comment-mcp`（要覆蓋指標檔可加 `--profile <name>`） |
| 本地開發 | `git clone … && pip install -e ".[dev]"`，跑 `python -m redshift_comment_mcp.server` |
| 多 cluster | 每個 cluster 跑一次 `/redshift-setup <名字>`，用 `/redshift-switch-profile` 切換 |

Plugin 透過 `uv run --project ${CLAUDE_PLUGIN_ROOT}` 直接從 cloned source
跑 —— plugin 更新**不需要**等 PyPI 發版。

## 檔案分布

```
.
├── README.md / README.ja.md / README.zh-TW.md     (這個檔，三語)
├── implementation_guide.md                         設計理由 + charter
├── src/redshift_comment_mcp/                       MCP server 原始碼 —— 有自己的 README
├── skills/                                         6 支 slash command skills —— 有自己的 README
├── commands/                                       plugin slash command stubs
├── tests/                                          pytest 套件
├── pyproject.toml                                  packaging metadata
└── .claude-plugin/                                 plugin manifest + marketplace
```

接下來該讀的 2 個 README：

- [`skills/README.md`](skills/README.md) —— 6 支 skill 全覽
- [`src/redshift_comment_mcp/README.md`](src/redshift_comment_mcp/README.md) —— server 內部、模組地圖、charter 限制

## 執行期資料路徑

| 路徑 | 內容 | 權限 |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | 非機密 profile 欄位 | `0600` |
| `~/.config/redshift-comment-mcp/active-profile` | 一行純文字指標，記錄哪個 profile 是 active。**檔案不存在 ↔ server 用 `default`**（單 profile 標準狀態，多數使用者不會看到此檔）。 | `0600` |
| OS keychain（`redshift-comment-mcp` / `<profile>`） | 密碼 | OS 管理 |
| `~/.cache/redshift-comment-mcp/<profile>/` | `/redshift-cache-schema` 寫入的可選離線結構快取 | `0700` |

## 建議的 DB GRANT 設定（縱深防禦）

`execute_sql` 在 parser 層擋掉 DDL / DML / admin 關鍵字（`DROP` /
`DELETE` / `UPDATE` / `INSERT` / `ALTER` / `CREATE` / `TRUNCATE` /
`MERGE` / `GRANT` / `REVOKE` / `COPY` / `UNLOAD`），但那只是第 1 層
防禦。縱深防禦的標準作法是**讓 plugin 連線用的 Redshift user 只有
read-only 權限**，這樣就算 parser 被繞過，資料庫本身會拒絕寫入：

```sql
-- 為 plugin 建立專用的 read-only user
CREATE USER redshift_mcp_reader WITH PASSWORD '...';

-- 只給 plugin 真的需要的權限
GRANT USAGE ON SCHEMA public, dbt_marts, dbt_staging TO redshift_mcp_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, dbt_marts, dbt_staging TO redshift_mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, dbt_marts, dbt_staging
  GRANT SELECT ON TABLES TO redshift_mcp_reader;

-- 不要給：INSERT / UPDATE / DELETE / TRUNCATE / DROP / CREATE / GRANT / superuser
```

要跑 `/redshift-lineage-from-stl` 才額外需要 `SYSLOG ACCESS UNRESTRICTED`
（或 admin）來讀 `STL_QUERY` / `SYS_QUERY_HISTORY`。不跑這支 skill 就
不用給。

## 已知限制

**MCP 回傳 token 上限（預設 ~25K tokens）** — Claude Code 對 MCP 工具
回傳超過 ~25,000 tokens 的資料會**靜默截斷**（沒有錯誤、沒有 marker；
參見 [anthropics/claude-code#2638](https://github.com/anthropics/claude-code/issues/2638)）。
在 dbt 風格、欄位註解多行 markdown 的 schema 上，寬表的單一
`list_columns(include_comments=True)` 一頁（50 列）就有可能逼近此上限。
這個 plugin 已經套用的緩解策略：

- `include_comments` 在 `list_tables` / `list_columns` **預設 False**
  （只有 schema 數量小的 `list_schemas` 預設 True）—— agent 必須明確
  opt-in 才會拿到含註解的回應。
- `/redshift-cache-schema` 把單表 spec 寫進 `.md` 檔，consumer 用 Read
  tool 直接讀，**完全繞過 MCP 回傳路徑**。一旦 prime 過，後續 metadata
  查詢不受此上限限制。

如果仍然需要拉高上限（例如要一次抓重註解的欄位群），可以在 Claude Code
執行環境設 `MAX_MCP_OUTPUT_TOKENS=50000`。注意這會影響該 session 中
**所有** MCP server，不只這個 plugin。

## 寫好註解的小提醒

這個 plugin 在「table owner 願意寫註解」的資料庫上效果最好。具體建議：

```sql
COMMENT ON SCHEMA   sales        IS '[用途] 線上零售銷售數據 [主要實體] 訂單, 客戶, 產品';
COMMENT ON TABLE    sales.orders IS '[實體] 訂單 [PK] order_id [FK] customer_id → customers.customer_id';
COMMENT ON COLUMN   sales.orders.revenue IS '[定義] 訂單總銷售額 [語意類型] Metric [單位] 新台幣 [計算] 未稅商品總價 + 稅 − 折扣';
```

更完整的 Semantic Layer 指南見
[`implementation_guide.md`](implementation_guide.md) 附錄 A。

## 開發

```bash
pytest tests/                    # 跑測試
python -m build                  # 建 sdist + wheel
```

CI / release flow 在 [`.github/`](.github/) 裡。

## 授權

[MIT](LICENSE)

## 貢獻

歡迎 Issue 與 PR。新 skill 請遵守 [`skills/README.md`](skills/README.md)
裡記載的模式：只讀、MCP 組合型、不直連 DB、無 synthesis layer。
SKILL.md ≤ 130 行、三語 README、commit 前用 `dev-workflow:skill-judge`
做 audit。
