# redshift-grep-columns

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 何ができるか

`redshift-grep-columns` は「このキーワードを含むカラムはどのテーブルにあるか？」という質問に答えます。Redshift クラスタ内の 1 つまたは全スキーマに対し、スキーマワイドな MCP `search_columns` 呼び出しを実行します。カラム名とコメントの両方を対象にマッチし、結果は `<schema>.<table>` ごとにグループ化され、型とコメントを併記します。

`search_columns` の `table_name=None` オプションのおかげで、スキーマあたり 1 回の MCP 呼び出し（12K カラム規模で約 0.7 秒）で完結 — テーブルごとの呼び出しオーケストレーションは不要です。

## 使うべきとき

複数テーブルにまたがる SQL を組む直前に使います。特に共有キー／FK 候補をテーブル横断で特定する場面で有用です。典型例：

- JOIN 前の偵察：「`customers` への FK としてコメントされているカラム全部」
- 命名一貫性の監査：「`customer_id` と `cust_no`、どちらを使っている？両方混在している？」
- メトリクス位置探し：「`gross_margin` を出しているテーブルはどれ？」

単一テーブル内の検索には不向き（MCP `search_columns(kw, schema, table)` を直接使う）。単一カラムの全文取得は `get_column_comment`、テーブル名検索は `/redshift-grep-tables` を使ってください。

## 例

```
/redshift-grep-columns customer_id --schema dbt_marts
```

チャット応答例：

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

## パフォーマンス注意

レイテンシはスコープ内のスキーマ数に比例します。スキーマ 5 個以上のクラスタでは、`--schema` で範囲を絞るようユーザーに促してリーダーノードの負荷を抑えてください。

## 詳細仕様

入力パース規則・エラーコードの正典は [`SKILL.md`](./SKILL.md) を参照。
