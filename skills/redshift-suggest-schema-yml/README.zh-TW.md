# redshift-suggest-schema-yml

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 它做什麼

對目標表的每個欄位呼叫一次
[`redshift-profile`](../redshift-profile/SKILL.md)，套用一組保守的
測試規則，產生可直接貼到 dbt `schema.yml` 的 `models:` 區塊，
外加每欄理由表格。整表模式會剖析所有欄位；單欄模式只回傳一個
條目，方便插入既有檔案。

## 何時該用

- 把既有的 Redshift 表納入新的 dbt 專案，需要一份附 description 與
  測試的 `schema.yml` 起手稿。
- 為僅列出欄名的舊 dbt model 補齊測試。
- 在把欄位從 `staging/` 推到 `marts/` 之前，用 `accepted_values`
  確認它是不是乾淨的 enum。

## 測試規則的保守性

核心承諾：**不會建議現有資料會違反的測試**。`not_null` 僅在
`null_count == 0` 時提出；`unique` 必須 `distinct_count == total_rows`
且無 NULL；`accepted_values` 僅針對低基數（2-20 個 distinct）的
string / boolean 欄位。邊界情況（如 `null_pct` 介於 0% 與 1% 之間）
會輸出為註解掉的 YAML，交由 reviewer 判斷。設計目標是貼上後
`dbt test` 立即 green。

## 呼叫範例

整表模式：

```
/redshift-suggest-schema-yml dbt_marts.fct_orders
```

貼 JSON 模式（接續上一次 `/redshift-profile` 的輸出）：

```
/redshift-suggest-schema-yml
{"schema":"dbt_marts","table":"fct_orders","column":"status",
 "type":"varchar(32)","type_branch":"string","comment":"訂單生命週期狀態",
 "total_rows":13030,"null_count":0,"null_pct":0.0,
 "distinct_count":4,"cardinality_class":"low",
 "top_values":[{"value":"active","count":12340,"pct":94.70}]}
```

## YAML 輸出（節錄）

```yaml
version: 2
models:
  - name: fct_orders
    description: "訂單事實表"
    columns:
      - name: order_id
        description: "訂單唯一識別碼"
        data_type: bigint
        tests: [not_null, unique]

      - name: status
        description: "訂單生命週期狀態"
        data_type: varchar(32)
        tests:
          - not_null
          - accepted_values:
              values: ["active", "cancelled", "pending", "refunded"]

      - name: notes
        description: "TODO: describe notes"
        data_type: varchar(2000)
        # 高基數自由文字 — 不建議測試
```

完整輸入格式、型別分支、測試規則表與錯誤契約請見
[SKILL.md](./SKILL.md)。
