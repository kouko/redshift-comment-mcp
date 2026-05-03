# redshift-cache-schema

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

## 何をするか

`redshift-cache-schema` は読み取り専用の `redshift-comment-mcp` サーバ
経由で Redshift カタログを走査し、クラスタ構造（スキーマ／テーブル／
カラム／コメント）を `~/.cache/redshift-comment-mcp/<profile>/` 配下に
markdown として書き出します。冪等です。同じ入力で何度実行しても同じ
ファイルが生成されます。

**キャッシュであって wiki ではありません。** 全ファイルはライブ DB
から完全に再生成可能です。手で編集しないでください。`# メモ` セクション
を足さないでください。ナレッジベースとして扱わないでください。編集内容
は次回実行時に黙って上書きされます。要約・陳腐化追跡・人間が書いた
解説はこのスキルの担当外で、別プラグインの仕事です。wiki だと思って
使うと誤用になります。ドキュメンテーションツールを別途選んでください。

## 使うとき

- **オフライン参照** — 飛行機内・会議室など、クラスタに繋がらない場所
  でスキーマとコメントを読むため。
- **VPN が不安定** — トンネル切断のたびに MCP を叩き直す手間を避ける。
- **オンボーディング引き継ぎ** — 新メンバーに MCP を覚えさせる前に、
  チェックインされたディレクトリだけ渡せば済む。

## 実行例

```
/redshift-cache-schema --scope dbt_marts,dbt_staging --dry-run
```

`--scope` は走査対象スキーマを限定します。`--dry-run` は書き込み対象
ファイル名を列挙するだけでディスクに書きません — 本実行の前にプレビュー
できます。

## キャッシュのディレクトリ構成

```
~/.cache/redshift-comment-mcp/<profile>/
├── index.md
├── schemas/<schema>.md
├── tables/<schema>__<table>.md
└── _orphans/<date>/...
```

正式な契約、エラー表、孤児ファイル処理ルールは [SKILL.md](./SKILL.md)
を参照してください。
