# Skills

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

這個資料夾收錄 `redshift-comment-mcp` plugin 隨附的 skills。所有
skill 都是**只讀**、**MCP 組合型**（透過 plugin 的 MCP tools 呼叫，
不會直連 Redshift），並對齊 plugin 的 **Guided Data Discovery
（引導式資料探索）** charter。

每支 skill 各自有 `SKILL.md`（執行契約的權威來源）以及三語
README（給新讀者快速入門用）。

## Charter

這個 plugin 存在的目的，是幫分析師與工程師在不熟的 Redshift cluster
中以**註解優先**的方式找到方向。名字會騙人，註解通常是最接近 ground
truth 的東西。每支 skill 不是組合既有的 `list_*` / `search_*` /
`execute_sql` MCP tools，就是（僅一例外）為了 LLM 單獨做不穩的 SQL
解析問題加一支 sqlglot helper script。

這裡**不會**有的東西：

- 直連資料庫的程式碼（MCP server 是唯一通道）。
- 任何寫入 Redshift 的動作（`execute_sql` 限制只能 SELECT）。
- 持久化的合成層（不會有 `.redshift-wiki/` markdown、不會 track 過期、
  也不會有人工編輯的文件）。那些屬於另一個 plugin 的範疇。

## Skill 列表

| Skill | 一句話 | 版本 |
|---|---|---|
| [redshift-setup](redshift-setup/) | 對話式逐步設定連線 profile（host / port / user / dbname / password）。 | v0.2.0 |
| [redshift-profile](redshift-profile/) | 一回合內回出欄位的 cardinality / top-N / null 比例 / min-max / 既有註解。 | v0.3.0 |
| [redshift-suggest-schema-yml](redshift-suggest-schema-yml/) | 草擬可貼上的 dbt v2 `models:` 區塊，附保守的測試建議（not_null / unique / accepted_values）。 | v0.3.0 |
| [redshift-cache-schema](redshift-cache-schema/) | 把 cluster 結構 dump 成 markdown 到 `~/.cache/redshift-comment-mcp/<profile>/`，方便離線瀏覽。是 cache，不是 wiki。 | v0.3.0 |
| [redshift-erd](redshift-erd/) | 產出三層 FK 推論（pg_constraint → dbt manifest → 命名啟發式）的 Mermaid erDiagram，每條邊都標 confidence。 | v0.3.0 |
| [redshift-explore](redshift-explore/) | 三步 wizard（schema → table → column）。使用者**讀註解**來挑選，不用記名字。 | v0.3.0 |
| [redshift-lineage-from-stl](redshift-lineage-from-stl/) | 挖 `STL_QUERY` / `SYS_QUERY_HISTORY` + 用 sqlglot 解析 SQL，從查詢歷史還原**實際**的 table 對 table 資料流。 | v0.3.0 |

## 使用方式

每支 skill 在 plugin 根目錄的 `commands/` 都有對應的 slash command。
在 chat 直接打指令即可，例如 `/redshift-profile dbt_marts.fct_orders
status`，skill 會自動串起需要的 MCP 呼叫。

要看執行細節（輸入解析、確切 SQL 模板、錯誤代碼、輸出格式）→ 看該
skill 的 `SKILL.md`；要快速入門（做什麼 / 何時用 / 一個例子）→ 看該
skill 的 `README.md`，提供三種語言版本。

## 權威參考

- Plugin charter: [implementation_guide.md](../implementation_guide.md) §1.2
- MCP tools 列表: [src/redshift_comment_mcp/redshift_tools.py](../src/redshift_comment_mcp/redshift_tools.py)
- Plugin manifest: [.claude-plugin/plugin.json](../.claude-plugin/plugin.json)
