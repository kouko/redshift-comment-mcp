# redshift-grep-columns

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 它做什麼

`redshift-grep-columns` 回答「哪些表有符合這個關鍵字的欄位？」這個問題。它在 Redshift cluster 內的單一或全部 schema 上跨表搜尋欄位元數據，**同時比對欄位名稱與欄位註解**，命中結果按 `<schema>.<table>` 分組呈現，附帶型別與註解。

Cache-first 設計：當 `/redshift-cache-schema` 已產出新鮮的本地 TSV 索引，這個 skill 會用 `bash grep` 在約 50 ms 內回應。若 cache 過期或缺失，回退到 live MCP（`search_tables` + 對每張命中表跑 `search_columns`），這條路會多次 round trip。

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

cluster 有 5 個以上 schema 且 cache 不新鮮？先跑 `/redshift-cache-schema`。Live 路徑成本隨 schema 數與命中表數線性增長；cache 路徑是常數時間。

## 詳細規格

輸入解析規則、bash 模板、錯誤代碼的正典在 [`SKILL.md`](./SKILL.md)。
