# redshift_comment_mcp

[English](README.md) · **日本語** · [繁體中文](README.zh-TW.md)

`redshift-comment-mcp` MCP サーバーの Python ソースです。Claude（あるいは
任意の MCP 対応クライアント）に **11 個のリードオンリーツール** を公開
します：schema / table / column の列挙、ヒット数つきキーワード検索、
コメント取得、そして SELECT 専用 SQL 実行。すべて設計上リードオンリー
で、`execute_sql` はパーサー層で DDL / DML キーワードを拒否します。

## モジュール構成

| ファイル | 役割 |
|---|---|
| [`server.py`](server.py) | プロセスエントリポイント。MCP サーバー（デフォルト）と setup CLI サブコマンド（`setup` / `set-password` / `test-connection` ほか）を振り分けます。 |
| [`redshift_tools.py`](redshift_tools.py) | 11 個の MCP ツール本体（`list_schemas` / `list_tables` / `list_columns` / `search_*` / `get_*_comment` / `get_all_column_comments` / `execute_sql`）。全ツールに明示的なページング、コメント参照を促す `WARNING` 文字列、厳格な識別子バリデーションを実装。 |
| [`config.py`](config.py) | プロファイル管理。非機密フィールドは `~/.config/redshift-comment-mcp/config.toml`（XDG Base Directory 準拠）に、パスワードは `keyring` ライブラリ経由で OS キーチェーンに保存。マルチプロファイル対応。 |
| [`connection.py`](connection.py) | Per-use 接続パターン（`@contextmanager`）— ツール呼び出しごとに新しい Redshift 接続を開いて即閉じる。意図的に長寿命プールを持ちません。 |
| [`setup_cli.py`](setup_cli.py) | 上記サブコマンド用の対話式 Q&A CLI。パスワードは `getpass` で収集し、シェル履歴に残しません。 |
| [`__init__.py`](__init__.py) | 空です — パッケージの公開面は `server.py` が登録するもの全てです。 |

## 憲章

ここにあるすべては **Guided Data Discovery（誘導型データ探索）** に
奉仕しています。具体的には：

- **コメントが第一級**。list / search 系ツールは要求があれば即座に
  コメントを返します。名前は嘘をつきますが、コメントはセマンティクス
  における唯一に近いグラウンドトゥルースです。
- **書き込み禁止**。`execute_sql` は `SELECT` または `WITH` で始まる
  文だけ受理し、`INSERT` / `UPDATE` / `DELETE` / `DROP` / `CREATE` /
  `ALTER` / `TRUNCATE` を単語境界正規表現で拒否します。これはサーバー
  境界で強制され、`skills/` 配下のスキルもこれに依存しています。
- **Per-use 接続**。MCP サーバーは接続をプールしません。ツール呼び出し
  ごとに開く・実行する・閉じる、です。理由：エラーリカバリが簡単、
  古いカーソルによる事故ゼロ、ツールオーバーヘッドは実クエリ遅延に
  比べれば小さい。
- **ページング前提**。全 list ツールが `limit` / `offset` を公開し、
  `DEFAULT_MAX_ITEMS` で自動切り詰めしてレスポンスを有界に保ちます。

## ランタイム配置

| パス | 内容 | パーミッション |
|---|---|---|
| `~/.config/redshift-comment-mcp/config.toml` | 非機密プロファイルフィールド（host / port / user / dbname） | `0600` |
| OS キーチェーン（service `redshift-comment-mcp`、account `<profile-name>`） | パスワード | OS 管理 |

## 実行方法

```bash
# 1. インストール（初回のみ）
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp setup

# 2. 検証
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp test-connection

# 3. MCP サーバーとして起動（plugin.json から自動起動されます）
uvx --from "git+https://github.com/kouko/redshift-comment-mcp.git" redshift-comment-mcp --profile default
```

エンドユーザー向けセットアップウォークスルーは
[`skills/redshift-setup/SKILL.md`](../../skills/redshift-setup/SKILL.md) を、
設計の理由（per-use 接続パターン、コメント優先憲章、セマンティック
レイヤーのベストプラクティス）は
[`implementation_guide.md`](../../implementation_guide.md) を参照して
ください。

## テスト

テストは [`../../tests/`](../../tests/) にあり、ツール群とページング
計算をカバーしています。リポジトリルートで `pytest` を実行してください。
