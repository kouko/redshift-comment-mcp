# redshift-grep-tables

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 它做什麼

`redshift-grep-tables` 回答「關於 X 的表在哪個 schema？」這個問題。它在 Redshift cluster 內的所有 schema 上跨範圍搜尋表元數據，**同時比對表名稱與表註解**，命中結果按 schema 分組呈現，附帶表類型與註解。

Cache-first 設計：當 `/redshift-cache-schema` 已產出新鮮的本地 TSV 索引，這個 skill 會用 `bash grep` 在約 50 ms 內回應。若 cache 過期或缺失，回退到 live MCP（每個 schema 跑一次 `search_tables`），成本隨 schema 數量線性增長。

## 何時該用

知道主題但不確定在哪個 schema 時用。多層架構（ingestion / staging / mart）混合多 namespace 的不熟悉 cluster 特別適用。典型場景：

- 主題搜尋：「orders fact 表在哪？」
- 跨層審計：「哪些 schema 有 `fct_*` 表？」
- 廠商覆蓋確認：「哪些 schema 在做 Salesforce 的 ingestion？」

不適合：schema 已知（直接用 MCP `search_tables(kw, schema)`）、欄位層級搜尋（用 `/redshift-grep-columns`）、一般 schema 瀏覽（用 `/redshift-explore`）。

## 範例

```
/redshift-grep-tables fct
```

聊天回應範例：

> Tables matching "fct" (5 hits in 3 schemas):
>
> dbt_marts (3)
>   fct_orders          BASE TABLE   Central order facts.
>   fct_returns         BASE TABLE   Return events.
>   fct_payments        BASE TABLE   Payment events.
>
> dbt_staging (1)
>   stg_fct_orders      BASE TABLE   Staging for fct_orders.
>
> reporting (1)
>   v_fct_orders_daily  VIEW         Daily aggregation of fct_orders.

## 效能注意

cluster 有 10 個以上 schema 且 cache 不新鮮？先跑 `/redshift-cache-schema`。Live 路徑成本是「每 schema 一次 tool call」；cache 路徑全程 50 ms。

## 詳細規格

輸入解析規則、bash 模板、錯誤代碼的正典在 [`SKILL.md`](./SKILL.md)。
