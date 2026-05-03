# redshift-lineage-from-stl

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 功能說明

這個 skill 回答「**到底是誰在讀寫這張 table?**」。它讀取
Redshift 的 query history 系統表、用 `sqlglot` 解析取得的 SQL,
再以 `(source → target, operation)` 為單位彙整為一列,
帶出查詢數、不重複使用者數、Top 5 使用者、最早/最近觀測時間,
以及範例 query ID。

它是 dbt manifest 的經驗補位。manifest 描述的是 **宣告的**
lineage — `ref()` 應該連起來的關係。這個 skill 描述的是
**實際的** lineage — 上週真的跑過的查詢,包含分析師臨時 SQL、
Tableau / Looker 抽取、手動補資料、臨時修補等 manifest 看不到的
使用。

## STL 保留期警告 (最重要)

Query history 壽命很短。**Provisioned** cluster 的 `STL_QUERY`
保留期大約 **2-5 天**,更舊的列會 roll-off 消失 — 任何 skill
都救不回來。**Serverless** 的 `SYS_QUERY_HISTORY` 保留較久
(通常數週),但仍有額度限制。Skill 會用 `SELECT version()` 判斷
cluster 種類,把 `--since` clamp 到實際可用區間,如果 `--since`
早於最舊那一列,footer 會警告。要做 12 個月的稽核,你需要另外
建立封存管線 — Redshift 已經丟掉的歷史,這個工具沒辦法捏造。

## 使用時機

- 把某個 model 列為下架候選時稽核 — 確認沒有 Tableau dashboard、
  排程抽取、分析師 notebook 還在打它。
- 找出 mart 的實際讀者 (manifest 只看得到其他 dbt model,
  看不到 BI 工具或臨時使用者)。
- 排查 freshness 抱怨 — 看看 report 壞掉前是誰跑了什麼 query。

## 權限要求

執行使用者需要 `SYSLOG ACCESS UNRESTRICTED` (或 admin / superuser
等級) 才能在 `STL_QUERY` 看到其他使用者的列。沒有這個權限只看得
到自己的 query,lineage 結果會嚴重失真。被擋時 skill 會回傳
`_error: stl_access_denied` 並附上 Redshift 原始訊息。

## 範例

```bash
/redshift-lineage-from-stl --since 7d --table dbt_marts.fct_orders
```

挖掘最近 7 天動到 `dbt_marts.fct_orders` 的查詢,解析每一個
statement,輸出鄰接表:

```
| from                   | →  | to                   | queries | distinct users | last seen           |
| dbt_staging.stg_orders | →  | dbt_marts.fct_orders | 31      | 1 (dbt)        | 2026-05-03 04:00:12 |
| dbt_marts.fct_orders   | →  | (read by ad-hoc)     | 243     | 12             | 2026-05-03 11:42:08 |
```

加上 `--output mermaid` 會額外輸出 Mermaid 圖。

完整輸入語法、輸出 schema、邊聚合邏輯與錯誤處理請見
[SKILL.md](SKILL.md)。
