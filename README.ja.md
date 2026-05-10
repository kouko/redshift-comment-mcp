# redshift-comment-mcp

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

Amazon Redshift 用のリードオンリーな **Model Context Protocol** サーバー
と、その上に 6 個のスラッシュコマンドスキルを乗せた Claude Code プラグ
インです。設計の前提はひとつ：**カラム名は嘘をつくが、コメントはつか
ない** — だからサーバーはコメントを積極的に公開し、スキルはそれを日々
の探索ワークフローへ組み立て直します。

```
「dbt_marts.fct_orders.status には実際にどんな値が入ってる？」
   → /redshift-profile dbt_marts.fct_orders status
   → カーディナリティ、上位 N、NULL 率、min/max、既存コメント — 1 ラウンドで。
```

## なぜ存在するのか

未知の Redshift テーブルを開いて `f3` / `legacy_id_v2` / `status`
（どっちの `status`？）といったカラム名に困った経験があるなら、痛みは
分かるはず。dbt manifest はカバー範囲が狭く、Web GUI は遅く、手書き
SQL は繰り返しが多すぎる。

このプラグインの憲章は **Guided Data Discovery（誘導型データ探索）**：

- **コメント優先**。すべての list / search ツールは要求があれば即座に
  コメントを返します。名前は補助的、コメントが権威。
- **構造としてリードオンリー**。`execute_sql` はパース層で DDL / DML
  を拒否します。このリポジトリ内のどのスキルも Redshift を変更でき
  ません。
- **MCP コンポーズ型スキル**。新しいワークフローは既存ツールを連結
  して構築します。新しい DB 接続を増やしません。
- **永続化なし**。合成レイヤーなし、`.redshift-wiki/` markdown なし、
  stale トラッキングなし。（キャッシュは再生成可能。それは別もの。）
  永続化は別プラグインの仕事です。

完全な憲章は [`implementation_guide.md`](implementation_guide.md) §1.2
を参照。

## 含まれているもの

### MCP ツール（11 個、[`src/redshift_comment_mcp/`](src/redshift_comment_mcp/) で定義）

| グループ | ツール |
|---|---|
| List | `list_schemas` · `list_tables` · `list_columns` |
| Search（ヒット数順） | `search_schemas` · `search_tables` · `search_columns` |
| コメント取得 | `get_schema_comment` · `get_table_comment` · `get_column_comment` · `get_all_column_comments` |
| クエリ | `execute_sql`（SELECT / WITH のみ） |

list / search はすべてページング対応。コメントを読んでから名前を信じる
よう LLM を促す `WARNING` 文字列が明示的に埋め込まれています。

### スラッシュコマンドスキル（6 個、[`skills/`](skills/) で定義）

| Skill | 一言で | バージョン |
|---|---|---|
| [/redshift-setup](skills/redshift-setup/) | 接続プロファイルを対話的に設定するウォークスルー。 | v0.2.0 |
| [/redshift-switch-profile](skills/redshift-switch-profile/) | アクティブプロファイルを切り替える（host / user / password の再入力なし）。シングルプロファイルのユーザーは穏やかに辞退される。 | v0.4.0 |
| [/redshift-profile](skills/redshift-profile/) | 1 ラウンドでカラムの cardinality / top-N / NULL 率 / min-max / 既存コメントを返すプロファイラ。 | v0.3.0 |
| [/redshift-explore](skills/redshift-explore/) | 三段ウィザード（schema → table → column）— 名前を覚えるのではなくコメントを読んで選ぶ。 | v0.3.0 |
| [/redshift-lineage-from-stl](skills/redshift-lineage-from-stl/) | `STL_QUERY` + sqlglot を採掘してクエリ履歴から **実際の** テーブル間系譜を再構築。 | v0.3.0 |
| [/redshift-grep-columns](skills/redshift-grep-columns/) | 1 つまたは全スキーマを横断してカラム名／コメントをスキーマワイド MCP 呼び出しでキーワード検索。 | v0.4.0 |
| [/redshift-grep-tables](skills/redshift-grep-tables/) | 全スキーマを横断してテーブル名／コメントをクラスタワイド MCP 呼び出しでキーワード検索。 | v0.4.0 |

各スキルはフォルダ内に三言語 README を持っています（ただし
`/redshift-setup` と `/redshift-switch-profile` はセットアップ系内部
スキルなので SKILL.md を直接参照）。

## クイックスタート

最速ルートは Claude Code プラグインです。

```bash
# 1. マーケットプレイスを登録（初回のみ）
claude plugin marketplace add kouko/redshift-comment-mcp

# 2. プラグインをインストール
claude plugin install redshift-comment-mcp

# 3. Claude Code チャット内で接続プロファイルを設定
/redshift-setup
```

`/redshift-setup` が host / port / user / dbname / password を順に
聞きます。**パスワードはシステムダイアログ（macOS）/ zenity プロンプト
（Linux デスクトップ）/ 自分のターミナル（ヘッドレス）で収集され、チャット
には絶対に入りません。** OS キーチェーンに直接保存されます。

設定後はそのままスラッシュコマンドを使うだけ。マルチクラスタ運用は
`/redshift-setup <名前>` で 2 つ目のプロファイルを追加し、
`/redshift-switch-profile` で切り替えます。

Claude Desktop / 他の MCP クライアント / ローカル開発については、下の
**他のインストール経路** を参照してください。

## 他のインストール経路

| シナリオ | 方法 |
|---|---|
| Claude Code（推奨） | `claude plugin install redshift-comment-mcp`（上記）。設定ゼロ — manifest はもうプロファイル名を尋ねない；MCP サーバーは `/redshift-setup` が書き込んだ active-profile ポインタファイルを読む。 |
| Claude Desktop / 汎用 MCP クライアント | `pip install redshift-comment-mcp`、設定ファイルで `uvx redshift-comment-mcp` を指す（ポインタファイルを上書きしたい場合は `--profile <name>` を付与） |
| ローカル開発 | `git clone … && pip install -e ".[dev]"`、`python -m redshift_comment_mcp.server` |
| マルチクラスタ | クラスタごとに `/redshift-setup <名前>` を実行し、`/redshift-switch-profile` で切り替え |

プラグインは `uv run --project ${CLAUDE_PLUGIN_ROOT}` を介してクローン
ソースから直接実行されます — プラグイン更新に PyPI リリースは不要です。

## ファイル配置

```
.
├── README.md / README.ja.md / README.zh-TW.md     (このファイル、三言語)
├── implementation_guide.md                         設計理由 + 憲章
├── src/redshift_comment_mcp/                       MCP サーバーソース — 専用 README あり
├── skills/                                         6 つのスラッシュコマンドスキル — 専用 README あり
├── commands/                                       プラグインのスラッシュコマンドスタブ
├── tests/                                          pytest スイート
├── pyproject.toml                                  パッケージングメタデータ
└── .claude-plugin/                                 プラグインマニフェスト + マーケットプレイス
```

次に読むべき 2 つの README：

- [`skills/README.md`](skills/README.md) — 6 スキルの全体像
- [`src/redshift_comment_mcp/README.md`](src/redshift_comment_mcp/README.md) — サーバー内部構造、モジュール一覧、憲章上の制約

## ランタイムのデータ配置

| パス | 内容 | パーミッション |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | 非機密プロファイルフィールド | `0600` |
| `~/.config/redshift-comment-mcp/active-profile` | アクティブプロファイル名を記録する 1 行のテキストポインタ。**ファイル不在 ↔ サーバーは `default` を使用**（シングルプロファイル正規状態。多くのユーザーはこのファイルを目にしない）。 | `0600` |
| OS キーチェーン（`redshift-comment-mcp` / `<profile>`） | パスワード | OS 管理 |

## 推奨される DB GRANT 設定（多層防御）

`execute_sql` は DDL / DML / 管理系キーワードをパーサ層で拒否します
（`DROP` / `DELETE` / `UPDATE` / `INSERT` / `ALTER` / `CREATE` /
`TRUNCATE` / `MERGE` / `GRANT` / `REVOKE` / `COPY` / `UNLOAD`）。これは
あくまで第 1 層の防御です。多層防御の定番手は **プラグイン用の Redshift
ユーザーには読み取り専用の権限のみ付与する** こと。万一パーサバイパス
が見つかっても、DB 側で書き込みが拒否されます：

```sql
-- プラグイン専用の読み取り専用ユーザー作成
CREATE USER redshift_mcp_reader WITH PASSWORD '...';

-- 必要最小限の権限のみ付与
GRANT USAGE ON SCHEMA public, dbt_marts, dbt_staging TO redshift_mcp_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, dbt_marts, dbt_staging TO redshift_mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, dbt_marts, dbt_staging
  GRANT SELECT ON TABLES TO redshift_mcp_reader;

-- 付与しない：INSERT / UPDATE / DELETE / TRUNCATE / DROP / CREATE / GRANT / superuser
```

`/redshift-lineage-from-stl` を使う場合のみ、追加で `SYSLOG ACCESS
UNRESTRICTED`（または admin）が必要です（`STL_QUERY` / `SYS_QUERY_HISTORY`
の読み取りに）。このスキルを使わないなら付与不要。

## 既知の制限

**MCP レスポンスのトークン上限（デフォルト ~25K トークン）** — Claude
Code は MCP ツールの戻り値が ~25,000 トークンを超えるとサイレントに
切り捨てます（エラーも marker もなし；
[anthropics/claude-code#2638](https://github.com/anthropics/claude-code/issues/2638)
参照）。dbt 風のリッチな markdown コメントを持つスキーマでは、ワイド
テーブルへの 1 ページ（50 行）の `list_columns(include_comments=True)`
がこの上限に近づくことがあります。プラグイン側で適用済みの緩和策：

- `include_comments` は `list_tables` / `list_columns` で **デフォルト
  False**（スキーマ数が少ない `list_schemas` だけ True）。エージェント
  が明示的に opt-in しない限りコメント込みのレスポンスは返らない。
- `MAX_COMMENT_LEN=1000` が複数アイテム応答の各コメントを上限切り
  （`comment_truncated_count` + 省略記号マーカー）。単一アイテム取得
  （`get_table_comment` / `get_column_comment`）は切り捨てない。

それでも上限を上げる必要がある場合は、Claude Code が動く環境で
`MAX_MCP_OUTPUT_TOKENS=50000` を設定してください。当該セッション内の
全 MCP サーバーに影響します（このプラグインだけではありません）。

## DB へのコメント記述ヒント

このプラグインの本領は、テーブル所有者がコメントに投資した DB で発揮
されます。具体例（中国語例 — チームの言語に合わせて調整してください）：

```sql
COMMENT ON SCHEMA   sales        IS '[用途] 線上零售銷售數據 [主要實體] 訂單, 客戶, 產品';
COMMENT ON TABLE    sales.orders IS '[實體] 訂單 [PK] order_id [FK] customer_id → customers.customer_id';
COMMENT ON COLUMN   sales.orders.revenue IS '[定義] 訂單總銷售額 [語意類型] Metric [單位] 新台幣 [計算] 未稅商品總價 + 稅 − 折扣';
```

より詳細な Semantic Layer ガイドは
[`implementation_guide.md`](implementation_guide.md) 付録 A にあります。

## 開発

```bash
pytest tests/                    # テスト実行
python -m build                  # sdist + wheel ビルド
```

CI / リリースフローは [`.github/`](.github/) 内です。

## ライセンス

[MIT](LICENSE)

## コントリビュート

Issue と PR を歓迎します。新しいスキルは [`skills/README.md`](skills/README.md)
に記載されたパターンに従ってください：リードオンリー、MCP コンポーズ型、
DB 直接接続なし、合成レイヤーなし。SKILL.md は ≤ 130 行、三言語 README、
コミット前に `dev-workflow:skill-judge` で監査。
