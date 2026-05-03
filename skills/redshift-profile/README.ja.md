# redshift-profile

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 概要

`redshift-profile` は「このカラムには実際に何が入っているのか」という問いに、`redshift-comment-mcp` サーバーの `list_columns` と `execute_sql` を 1 ラウンドで組み合わせて答えるリードオンリーのスキルです。カーディナリティ、NULL 率、上位 100 値、数値・日付型の min/max、そして既存の `COMMENT ON` テキストを 1 回のチャットターンで返します。

## 利用シーン

未知のテーブルに着いたとき、分析 SQL を書く前や `schema.yml` のドキュメントを埋める前の素早いオリエンテーションに使ってください。典型的な場面：

- `accepted_values` テストを追加する前に、`status` が列挙型かどうかと値を確認する。
- ファクトモデルで信頼する前に、結合キーの NULL 率を点検する。
- ファクトテーブルがカバーする日付範囲をざっと把握する。
- varchar をカテゴリ扱いしてよいか、低カーディナリティを確認する。

自由記述カラム（上位 100 は無意味）、全行カウント（`execute_sql` 直叩きで十分）、書き込み操作には使わないでください。親 MCP サーバーは憲章上リードオンリーです。

## 実行例

```
/redshift-profile dbt_marts.fct_orders status
```

チャット返答の例：

> **dbt_marts.fct_orders.status** — varchar(32)、13,030 行、NULL 0.30%、distinct 4。
> 上位値: `active` 94.70%、`cancelled` 3.10%、`pending` 1.50%、`refunded` 0.40%。
> ヒント: 偏った列挙型、`active` が支配的。

## 出力フォーマット

```json
{
  "schema": "dbt_marts", "table": "fct_orders", "column": "status",
  "type": "varchar(32)", "comment": "Order lifecycle state",
  "total_rows": 13030, "null_pct": 0.30,
  "distinct_count": 4, "cardinality_class": "low",
  "top_values": [{"value": "active", "count": 12340, "pct": 94.70}]
}
```

この JSON ブロックは `/redshift-suggest-schema-yml` に連鎖入力できます。

## 権威ある参照

入力パース規則、型分岐マトリクス、正確な SQL テンプレート、エラーコードなどの実行詳細は [`SKILL.md`](./SKILL.md) を参照してください。
