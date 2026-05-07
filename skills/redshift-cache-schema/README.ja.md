# redshift-cache-schema

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 何をするか

`redshift-cache-schema` は読み取り専用の `redshift-comment-mcp` サーバ
経由で Redshift カタログを走査し、クラスタ構造（スキーマ／テーブル／
カラム／コメント）を `~/.cache/redshift-comment-mcp/<profile>/` 配下に
書き出します。冪等です — 同じ入力で何度実行しても同じファイルが
生成されます。

**LLM 内部キャッシュであり、ユーザー向けドキュメントではありません。**
これらのファイルは他のスキル（`/redshift-explore`、`/redshift-profile`）
と MCP サーバーの CACHE PROTOCOL から読まれることを前提に設計されて
おり、人間がエディタで眺めるためのものではありません。コメントは
複数行 markdown を含めて原文ママ保存されますが、レイアウトは LLM の
grep + Read に最適化されており、視覚的な読みやすさのためではありません。

## 使うとき

安定したスキーマで重い分析セッションを始める前に一度実行します。
キャッシュが用意できると、以降のスキル呼び出しはメタデータをローカル
ファイル Read で解決でき、MCP に往復する必要がなくなります — トークン
節約と、メタデータ参照ごとに ~100-1000 ms のレイテンシ削減につながります。

キャッシュが古くなると（デフォルト TTL は 168 時間 = 1 週間）、消費側
スキルは自動で live MCP にフォールバックし、`[cache]` チャットヒント
で `/redshift-cache-schema --refresh` を促します。スキーマが頻繁に
変動する環境では `--ttl 24` で信頼ウィンドウを短くしてください。

## 実行例

```
/redshift-cache-schema --scope dbt_marts,dbt_staging --dry-run
```

`--scope` は走査対象スキーマを限定します。`--dry-run` は書き込み対象
ファイル名を列挙するだけで、実際にはディスクに書きません。その他の
フラグ：`--tables <s>.<t>[,...]` で特定テーブルだけ、`--ttl <hours>`
で鮮度ウィンドウを上書き。

## キャッシュのディレクトリ構成

```
~/.cache/redshift-comment-mcp/<profile>/
├── _meta.json                # 鮮度ゲート (refreshed_at, ttl_hours, complete)
├── _tables_index.tsv         # schema\ttable\tsummary (1 行 1 テーブル；grep 用)
├── _columns_index.tsv        # schema\ttable\tcolumn\ttype\tsummary (grep 用)
└── tables/
    └── <schema>__<table>.md  # テーブル完全スペック（複数行 markdown コメント保持）
```

ファイルフォーマット仕様、鮮度契約、エラー表、孤児ファイル処理ルール
は [SKILL.md](./SKILL.md) を参照してください。
