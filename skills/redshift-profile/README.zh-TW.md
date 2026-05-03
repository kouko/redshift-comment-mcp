# redshift-profile

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 功能說明

`redshift-profile` 用來回答「這個欄位裡到底裝了什麼？」這個問題。它將 `redshift-comment-mcp` 伺服器的 `list_columns` 與 `execute_sql` 工具組合在單一只讀回合中，一次給出 cardinality、null 比例、top-100 值、數值與日期型別的 min/max，以及該欄位既有的 `COMMENT ON` 內容。

## 使用時機

當你進到一張不熟的表、需要在寫分析 SQL 或補 `schema.yml` 文件前快速摸底時，就用這支 skill。典型情境：

- 想加 `accepted_values` 測試前，先確認 `status` 是不是列舉型、有哪些值。
- 把 join key 用在 fact 模型前，先看 null 比例可不可信。
- 快速掃過 fact table 的日期涵蓋範圍。
- 在把 varchar 當分類欄位之前，確認它是低 cardinality。

不要用在自由文字欄位（top-100 沒意義）、整表 row count（直接 `execute_sql` 即可），以及任何寫入動作 — 上層 MCP 伺服器在 charter 上就是只讀的。

## 呼叫範例

```
/redshift-profile dbt_marts.fct_orders status
```

聊天回覆範例：

> **dbt_marts.fct_orders.status** — varchar(32)、13,030 列、null 0.30%、distinct 4。
> Top 值：`active` 94.70%、`cancelled` 3.10%、`pending` 1.50%、`refunded` 0.40%。
> 解讀：偏斜列舉型，由 `active` 主導。

## 輸出格式

```json
{
  "schema": "dbt_marts", "table": "fct_orders", "column": "status",
  "type": "varchar(32)", "comment": "Order lifecycle state",
  "total_rows": 13030, "null_pct": 0.30,
  "distinct_count": 4, "cardinality_class": "low",
  "top_values": [{"value": "active", "count": 12340, "pct": 94.70}]
}
```

這段 JSON 可直接串接到 `/redshift-suggest-schema-yml`。

## 權威參考

關於執行細節 — 輸入解析規則、型別分支矩陣、確切 SQL 模板、錯誤代碼 — 請見 [`SKILL.md`](./SKILL.md)。
