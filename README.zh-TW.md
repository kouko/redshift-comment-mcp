# redshift-comment-mcp

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

一個給 Amazon Redshift 用的只讀 **Model Context Protocol** server，外加
一個基於它的 Claude Code plugin，內含 7 支 slash command skills。整個
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

### Slash command skills（7 支，定義在 [`skills/`](skills/)）

| Skill | 一句話 | 版本 |
|---|---|---|
| [/redshift-setup](skills/redshift-setup/) | 對話式逐步設定連線 profile。 | v0.2.0 |
| [/redshift-profile](skills/redshift-profile/) | 一回合內回出欄位的 cardinality / top-N / null 比例 / min-max / 既有註解。 | v0.3.0 |
| [/redshift-suggest-schema-yml](skills/redshift-suggest-schema-yml/) | 草擬可貼上的 dbt v2 `models:` 區塊，附保守的測試建議。 | v0.3.0 |
| [/redshift-cache-schema](skills/redshift-cache-schema/) | 把 cluster 結構 dump 成 markdown 到 `~/.cache/...`，方便離線瀏覽。 | v0.3.0 |
| [/redshift-erd](skills/redshift-erd/) | 三層 FK 推論（pg_constraint → dbt manifest → 命名啟發式）的 Mermaid erDiagram，每條邊都標 confidence。 | v0.3.0 |
| [/redshift-explore](skills/redshift-explore/) | 三步 wizard（schema → table → column）—— 讀註解來挑，不用記名字。 | v0.3.0 |
| [/redshift-lineage-from-stl](skills/redshift-lineage-from-stl/) | 挖 `STL_QUERY` + sqlglot 從查詢歷史還原**實際**的 table 對 table 資料流。 | v0.3.0 |

每支 skill 在自己的資料夾內都有三語 README。

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
重跑 `/redshift-setup` 給不同的 profile 名字就行。

Claude Desktop / 其他 MCP client / 本地開發見下面的**其他安裝路徑**。

## 其他安裝路徑

| 情境 | 方式 |
|---|---|
| Claude Code（推薦） | `claude plugin install redshift-comment-mcp`（如上） |
| Claude Desktop / 一般 MCP client | `pip install redshift-comment-mcp`，client config 指向 `uvx redshift-comment-mcp --profile default` |
| 本地開發 | `git clone … && pip install -e ".[dev]"`，跑 `python -m redshift_comment_mcp.server --profile default` |
| 多 cluster | 一個 cluster 一個 profile：`redshift-comment-mcp setup --profile prod` |

Plugin 透過 `uv run --project ${CLAUDE_PLUGIN_ROOT}` 直接從 cloned source
跑 —— plugin 更新**不需要**等 PyPI 發版。

## 檔案分布

```
.
├── README.md / README.ja.md / README.zh-TW.md     (這個檔，三語)
├── implementation_guide.md                         設計理由 + charter
├── src/redshift_comment_mcp/                       MCP server 原始碼 —— 有自己的 README
├── skills/                                         7 支 slash command skills —— 有自己的 README
├── commands/                                       plugin slash command stubs
├── tests/                                          pytest 套件
├── pyproject.toml                                  packaging metadata
└── .claude-plugin/                                 plugin manifest + marketplace
```

接下來該讀的 2 個 README：

- [`skills/README.md`](skills/README.md) —— 7 支 skill 全覽
- [`src/redshift_comment_mcp/README.md`](src/redshift_comment_mcp/README.md) —— server 內部、模組地圖、charter 限制

## 執行期資料路徑

| 路徑 | 內容 | 權限 |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | 非機密 profile 欄位 | `0600` |
| OS keychain（`redshift-comment-mcp` / `<profile>`） | 密碼 | OS 管理 |
| `~/.cache/redshift-comment-mcp/<profile>/` | `/redshift-cache-schema` 寫入的可選離線結構快取 | `0700` |

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
