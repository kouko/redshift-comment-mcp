# redshift-cache-schema

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 功能說明

`redshift-cache-schema` 透過唯讀的 `redshift-comment-mcp` server 走訪
Redshift catalog，把叢集結構（schema／table／column／comment）寫進
`~/.cache/redshift-comment-mcp/<profile>/` 之下。具備冪等性 — 相同
輸入重複執行會產出相同檔案。

**這是 LLM 內部 cache，不是給使用者看的文件。** 檔案設計給其他
skill（`/redshift-explore`、`/redshift-profile`）以及 MCP server 的
CACHE PROTOCOL 讀取使用，不是給人類用編輯器瀏覽的。註解（含多行
markdown）會原樣保留，但檔案配置是為了 LLM grep + Read 最佳化，
不是為了視覺閱讀好看。

## 使用時機

在穩定 schema 上開始繁重分析任務之前先跑一次。Cache 存在後，後續
skill 呼叫可以用本地 Read 解析 metadata，不必每次都打 MCP — 節省
tokens、每次 metadata 查詢省 ~100-1000 ms latency。

Cache 過期時（預設 TTL 168 小時 = 一週）消費端 skill 會自動 fallback
到 live MCP，並印一行 `[cache]` 提示建議跑
`/redshift-cache-schema --refresh`。schema 變動頻繁的環境可用
`--ttl 24` 縮短信任窗口。

## 執行範例

```
/redshift-cache-schema --scope dbt_marts,dbt_staging --dry-run
```

`--scope` 將走訪範圍限制在指定的 schema；`--dry-run` 只列出將要寫入
的檔名，不實際寫磁碟。其他旗標：`--tables <s>.<t>[,...]` 只快取特定
表，`--ttl <hours>` 覆寫鮮度窗口。

## Cache 目錄結構

```
~/.cache/redshift-comment-mcp/<profile>/
├── _meta.json                # 鮮度 gate (refreshed_at, ttl_hours, complete)
├── _tables_index.tsv         # schema\ttable\tsummary（一行一表，給 grep 用）
├── _columns_index.tsv        # schema\ttable\tcolumn\ttype\tsummary（給 grep 用）
└── tables/
    └── <schema>__<table>.md  # 單表完整 spec（多行 markdown 註解原樣保留）
```

完整檔案格式規範、鮮度契約、錯誤對照表、孤兒檔處理規則請見
[SKILL.md](./SKILL.md)。
