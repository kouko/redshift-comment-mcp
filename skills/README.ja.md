# Skills

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

このディレクトリには `redshift-comment-mcp` プラグインに同梱される
スキル群が入っています。全スキルは **リードオンリー**、**MCP コンポー
ズ型**（Redshift に直接接続せず、プラグインの MCP ツールを呼ぶ）で、
プラグインの **Guided Data Discovery（誘導型データ探索）** 憲章に
沿っています。

各スキルは固有の `SKILL.md`（実行の権威ある契約）と、新しい読者向け
オリエンテーションとしての三言語 README を持ちます。

## 憲章

このプラグインは、未知の Redshift クラスタに迷い込んだアナリストや
エンジニアが、**コメント優先**で道を見つけられるようにするために
存在します。名前は嘘をつきますが、コメントは普通グラウンドトゥルース
に最も近い情報です。各スキルは既存の `list_*` / `search_*` /
`execute_sql` MCP ツールを組み合わせるか、あるいは 1 つだけ — LLM が
単独では確実にできないパース問題のために — sqlglot ヘルパースクリプト
を追加します。

ここに **無い** ものは：

- Redshift への直接接続（MCP サーバーが唯一の経路）。
- Redshift への書き込み操作（`execute_sql` は SELECT 専用）。
- 永続化された合成レイヤー（`.redshift-wiki/` 的な markdown、stale
  トラッキング、手作業の文書化はありません）。それらは別プラグインの
  領分です。

## スキル一覧

| Skill | 一言で | バージョン |
|---|---|---|
| [redshift-setup](redshift-setup/) | 接続プロファイル（host / port / user / dbname / password）を対話的に設定するウォークスルー。 | v0.2.0 |
| [redshift-profile](redshift-profile/) | 1 回のチャットで、カラムの cardinality / top-N / null 率 / min-max / 既存コメントを返すプロファイラ。 | v0.3.0 |
| [redshift-suggest-schema-yml](redshift-suggest-schema-yml/) | 保守的なテスト提案（not_null / unique / accepted_values）入りの、貼り付けるだけの dbt v2 `models:` ブロックを下書き。 | v0.3.0 |
| [redshift-cache-schema](redshift-cache-schema/) | クラスタ構造を `~/.cache/redshift-comment-mcp/<profile>/` に markdown でダンプし、オフライン参照可能に。Wiki ではなく Cache。 | v0.3.0 |
| [redshift-erd](redshift-erd/) | 三段階の FK 推定（pg_constraint → dbt manifest → 命名ヒューリスティック）と信頼度ラベル付きの Mermaid erDiagram を生成。 | v0.3.0 |
| [redshift-explore](redshift-explore/) | 三段ウィザード（schema → table → column）。ユーザーは名前を覚えるのではなく、コメントを読んで選びます。 | v0.3.0 |
| [redshift-lineage-from-stl](redshift-lineage-from-stl/) | `STL_QUERY` / `SYS_QUERY_HISTORY` を採掘 + sqlglot で SQL を解析して、クエリ履歴から **実際の** テーブル間データフローを再構築。 | v0.3.0 |

## 使い方

各スキルにはプラグインルート `commands/` に対応するスラッシュコマンド
があります。チャットでコマンドを打つだけ — 例えば `/redshift-profile
dbt_marts.fct_orders status` — するとスキルが必要な MCP 呼び出しを
オーケストレートします。

実行詳細（入力パース、正確な SQL テンプレート、エラーコード、出力
フォーマット）は各スキルの `SKILL.md` を、オリエンテーション（何を / い
つ / 例 1 つ）は各スキルの `README.md` をご覧ください — 三言語で提供
されています。

## 権威ある参照

- プラグイン憲章: [implementation_guide.md](../implementation_guide.md) §1.2
- MCP ツール一覧: [src/redshift_comment_mcp/redshift_tools.py](../src/redshift_comment_mcp/redshift_tools.py)
- プラグインマニフェスト: [.claude-plugin/plugin.json](../.claude-plugin/plugin.json)
