# redshift-cache-schema

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 功能說明

`redshift-cache-schema` 透過唯讀的 `redshift-comment-mcp` server 走訪
Redshift catalog，把叢集結構（schema／table／column／comment）寫成
markdown，放在 `~/.cache/redshift-comment-mcp/<profile>/` 之下。
具備冪等性 — 相同輸入重複執行會產出相同檔案。

**這是 cache，不是 wiki。** 所有檔案都能 100% 從 live DB 重建。請勿
手動修改、請勿新增 `# 備註` 段落、請勿當成知識庫使用。手寫內容會在
下次執行時被靜默覆蓋。摘要、stale 追蹤、人工撰寫的說明都不在本 skill
的職責範圍，那是另一個 plugin 該做的事。如果你把它當 wiki 用，就會用
錯 — 請改選文件工具。

## 使用時機

- **離線瀏覽** — 在飛機上、會議室、或任何連不到叢集的地方，仍能查閱
  schema 與欄位 comment。
- **VPN 不穩** — 避免每次 tunnel 斷線就要重新打 MCP query。
- **新人交接** — 直接交付一份已 commit 的目錄，不必先教 MCP。

## 執行範例

```
/redshift-cache-schema --scope dbt_marts,dbt_staging --dry-run
```

`--scope` 將走訪範圍限制在指定的 schema。`--dry-run` 只列出將要寫入
的檔名，不實際寫磁碟 — 正式執行前可先預覽。

## Cache 目錄結構

```
~/.cache/redshift-comment-mcp/<profile>/
├── index.md
├── schemas/<schema>.md
├── tables/<schema>__<table>.md
└── _orphans/<date>/...
```

完整契約、錯誤對照表、孤兒檔處理規則請見 [SKILL.md](./SKILL.md)。
