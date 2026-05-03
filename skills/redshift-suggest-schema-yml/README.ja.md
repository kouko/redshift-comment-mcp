# redshift-suggest-schema-yml

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 何をするか

[`redshift-profile`](../redshift-profile/SKILL.md) を対象テーブルの
各カラムに対して 1 回ずつ実行し、保守的なテストルールを適用して、
貼り付けるだけで使える dbt `schema.yml` の `models:` ブロックと
カラムごとの根拠テーブルをチャットに出力します。テーブル一括モードは
全カラムを、単一カラムモードは既存ファイルへ差し込む 1 エントリを
返します。

## 使うべきタイミング

- 既存の Redshift テーブルを新しい dbt プロジェクトに取り込み、
  description とテスト付きの初期 `schema.yml` が欲しいとき。
- カラム名だけが列挙された古い dbt モデルにテストを後付けしたいとき。
- `staging/` から `marts/` へ昇格させる前に、`accepted_values`
  テストでクリーンな enum かどうかを確認したいとき。

## テスト提案の保守性

中核の約束は「現データに違反するテストを提案しない」こと。
`not_null` は `null_count == 0` のときのみ、`unique` は
`distinct_count == total_rows` かつ NULL ゼロのときのみ、
`accepted_values` は string / boolean かつ低カーディナリティ
（2-20 種類）のときのみ採用します。境界事例（例：`null_pct` が
0% 超 1% 未満）はコメントアウト YAML として残し、レビュアー判断に
委ねます。貼り付け直後の `dbt test` が green になる前提です。

## 呼び出し例

テーブル一括モード：

```
/redshift-suggest-schema-yml dbt_marts.fct_orders
```

JSON 貼り付けモード（`/redshift-profile` の結果をそのまま渡す）：

```
/redshift-suggest-schema-yml
{"schema":"dbt_marts","table":"fct_orders","column":"status",
 "type":"varchar(32)","type_branch":"string","comment":"注文ライフサイクル状態",
 "total_rows":13030,"null_count":0,"null_pct":0.0,
 "distinct_count":4,"cardinality_class":"low",
 "top_values":[{"value":"active","count":12340,"pct":94.70}]}
```

## YAML 出力（抜粋）

```yaml
version: 2
models:
  - name: fct_orders
    description: "注文ファクトテーブル"
    columns:
      - name: order_id
        description: "注文の一意識別子"
        data_type: bigint
        tests: [not_null, unique]

      - name: status
        description: "注文ライフサイクル状態"
        data_type: varchar(32)
        tests:
          - not_null
          - accepted_values:
              values: ["active", "cancelled", "pending", "refunded"]

      - name: notes
        description: "TODO: describe notes"
        data_type: varchar(2000)
        # 高カーディナリティの自由記述 — テスト提案なし
```

入力フォーム、型分岐、テストルール表、エラー契約の詳細は
[SKILL.md](./SKILL.md) を参照してください。
