# redshift-grep-tables

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 它做什麼

`redshift-grep-tables` 回答「關於 X 的表在哪個 schema？」這個問題。它對 Redshift cluster 內的所有 schema 跑一次 cluster-wide MCP `search_tables` 呼叫，**同時比對表名稱與表註解**，命中結果按 schema 分組呈現，附帶表類型與註解。

靠 `search_tables` 的 `schema_name=None` 選項，一次 MCP 呼叫即可（10K 表以下的 cluster 約 0.2 秒）。

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

## 詳細規格

輸入解析規則、錯誤代碼的正典在 [`SKILL.md`](./SKILL.md)。
