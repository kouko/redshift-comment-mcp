# redshift-grep-columns

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 它做什麼

`redshift-grep-columns` 回答「哪些表有符合這個關鍵字的欄位？」這個問題。它對 Redshift cluster 內的單一或全部 schema 跑 schema-wide MCP `search_columns` 呼叫，**同時比對欄位名稱與欄位註解**，命中結果按 `<schema>.<table>` 分組呈現，附帶型別與註解。

靠 `search_columns` 的 `table_name=None` 選項，每個 schema 只需一次 MCP 呼叫（12K 欄位規模約 0.7 秒）—— 不再對每張表 orchestrate 一次。

## 何時該用

組多表 SQL 之前使用，特別是要在多張表之間找出共用鍵 / FK 候選的情境。典型場景：

- JOIN 前偵察：「找所有註解寫著 FK to `customers` 的欄位」
- 命名一致性審計：「我們是用 `customer_id` 還是 `cust_no`？兩個都有嗎？」
- 找指標欄位：「哪些表有 `gross_margin`？」

不適合：單一已知表內的搜尋（直接用 MCP `search_columns(kw, schema, table)`）、單一欄位全文（用 `get_column_comment`）、找表名（用 `/redshift-grep-tables`）。

## 範例

```
/redshift-grep-columns customer_id --schema dbt_marts
```

聊天回應範例：

> Matches for "customer_id" (4 hits in 1 schema, 3 tables):
>
> dbt_marts.fct_orders
>   customer_id   bigint   Customer reference (FK to dim_users.id)
>
> dbt_marts.fct_returns
>   customer_id   bigint   Customer who initiated the return
>
> dbt_marts.dim_users
>   id            bigint   Primary key, referenced as customer_id elsewhere
>   cust_no       bigint   Legacy customer number, alias for id

## 效能注意

延遲隨 scope 內 schema 數線性增加。cluster 有 5 個以上 schema 時，建議提示使用者用 `--schema` 收斂範圍，避免 leader node 過載。

## 詳細規格

輸入解析規則、錯誤代碼的正典在 [`SKILL.md`](./SKILL.md)。
