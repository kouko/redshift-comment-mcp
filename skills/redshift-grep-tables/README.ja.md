# redshift-grep-tables

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 何ができるか

`redshift-grep-tables` は「X についてのテーブルはどのスキーマにある？」という質問に答えます。Redshift クラスタ内の全スキーマに対しクラスタワイドな MCP `search_tables` 呼び出しを 1 回実行し、テーブル名とコメントの両方を対象にマッチさせます。結果はスキーマごとにグループ化され、テーブル型とコメントを併記します。

`search_tables` の `schema_name=None` オプションのおかげで、1 回の MCP 呼び出し（10K テーブル未満のクラスタで約 0.2 秒）で完結します。

## 使うべきとき

トピックは分かるが、どのスキーマにあるか不明なときに使います。多層構造（ingestion / staging / mart）を持つ不慣れなクラスタで特に有用です。典型例：

- トピック検索：「orders fact テーブルはどこ？」
- レイヤー横断監査：「`fct_*` テーブルがあるスキーマはどれ？」
- ベンダーカバレッジ確認：「Salesforce を取り込んでいるスキーマはどこ？」

スキーマが既に分かっている場合は不向き（MCP `search_tables(kw, schema)` を直接使う）。カラム検索は `/redshift-grep-columns`、一般的なスキーマ閲覧は `/redshift-explore` を使ってください。

## 例

```
/redshift-grep-tables fct
```

チャット応答例：

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

## 詳細仕様

入力パース規則・エラーコードの正典は [`SKILL.md`](./SKILL.md) を参照。
