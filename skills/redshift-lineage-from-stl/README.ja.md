# redshift-lineage-from-stl

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 概要

このスキルは「**この table を実際に読み書きしているのは誰か?**」
に答えます。Redshift のクエリ履歴システムテーブルを読み取り、
取得した SQL を `sqlglot` で解析し、`(source → target, operation)`
ごとに 1 行に集約して、クエリ数・ユニークユーザー数・トップ 5
ユーザー・初回/最終観測時刻・サンプル query ID を出力します。

dbt manifest に対する経験的な補完です。manifest が示すのは
**宣言された** lineage — `ref()` で接続されているはずの関係です。
このスキルが示すのは **実際の** lineage — 先週本当に走った
クエリで、アナリストのアドホック SQL、Tableau / Looker の抽出、
手動バックフィル、緊急修正など、manifest が捉えない使用も含みます。

## STL 保持期間の警告 (最重要)

クエリ履歴は短命です。**プロビジョンド** クラスターの
`STL_QUERY` の保持期間はおおむね **2-5 日** で、それより古い行は
ロールオフして消えます — どのスキルでも復元できません。
**サーバーレス** の `SYS_QUERY_HISTORY` はより長く保持されますが
(通常数週間)、それでも上限はあります。スキルは `SELECT version()`
でクラスター種別を判定し、`--since` を実際に利用可能な範囲に
クランプし、`--since` が最古の行より前であればフッターで警告します。
12 ヶ月の監査が必要ならアーカイブパイプラインが別途必要で、
Redshift がすでに破棄した履歴をこのツールは作り出せません。

## 使う場面

- model を廃止候補として監査するとき — Tableau ダッシュボード、
  定期抽出、アナリストのノートブックが本当に止まっているかを確認。
- mart の実際の利用者を特定 (manifest では他の dbt model しか
  見えず、BI ツールやアドホックユーザーは見えない)。
- 鮮度クレームの調査 — レポートが壊れる直前に誰が何を流したか。

## 権限

実行ユーザーには `STL_QUERY` で他ユーザーの行を見るために
`SYSLOG ACCESS UNRESTRICTED` (または admin / superuser 相当) が
必要です。これがないと自分のクエリしか見えず、lineage 結果は
誤解を招きます。アクセス拒否時は `_error: stl_access_denied` と
Redshift の生メッセージを返します。

## 使用例

```bash
/redshift-lineage-from-stl --since 7d --table dbt_marts.fct_orders
```

直近 7 日間で `dbt_marts.fct_orders` に触れたクエリを採掘し、
各文を解析して隣接テーブルを出力します:

```
| from                   | →  | to                   | queries | distinct users | last seen           |
| dbt_staging.stg_orders | →  | dbt_marts.fct_orders | 31      | 1 (dbt)        | 2026-05-03 04:00:12 |
| dbt_marts.fct_orders   | →  | (read by ad-hoc)     | 243     | 12             | 2026-05-03 11:42:08 |
```

`--output mermaid` を付けると Mermaid グラフも出力します。

入力構文、出力スキーマ、エッジ集約ロジック、エラー処理の詳細は
[SKILL.md](SKILL.md) を参照してください。
