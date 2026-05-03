# redshift-explore

[English](README.md) · [日本語](README.ja.md) · **繁體中文**

## 這個 skill 做什麼？

`redshift-explore` 帶你走過一個你從沒看過的 Redshift cluster。它是一
個三步驟精靈 — **schema → table → column** — 每一步都會把候選項連同
註解一起列出來，讓你**用讀的挑，不必硬記名字**。你不需要知道訂單事
實表叫 `fct_orders`、住在 `dbt_marts` 底下。你只要從列表往下讀，找
到註解符合你需求的那一個，回覆編號就好。

## 什麼時候用

第一天碰到新 cluster、接手別人留下的倉庫、或者腦中冒出「**我不知道
要從哪開始**」的時候，就是它登場的時機。它是為**零脈絡 onboarding**
設計的 — 新分析師、新專案、或單純走進一塊從沒踏過的資料區。如果你
已經知道要看哪張表、哪個欄位，那就跳過精靈直接用
`/redshift-profile`。

## 互動範例

```
> /redshift-explore

請選擇 schema:
  1. dbt_marts     — 最終 marts 層，可直接給業務使用的 facts / dims
  2. dbt_staging   — Staging 模型，對 raw 做輕量清洗
  3. raw_orders    — 訂單服務的原始事件流
回覆: 數字 / 名稱 / 關鍵字。

> 1

請在 dbt_marts 選擇 table:
  1. fct_orders     — 一筆完成訂單 = 一列，granularity = order_id
  2. dim_customers  — 顧客當前狀態屬性
回覆: 數字 / 名稱 / 關鍵字 / back。

> 1

你選了 dbt_marts.fct_orders。請選欄位:
  1. order_id   bigint      — 訂單唯一識別 (PK?)
  2. status     varchar(32) — 訂單生命週期狀態
  3. total_jpy  numeric     — 訂單總額（JPY，含稅）
...
```

挑完欄位後，精靈會交棒給 `/redshift-profile`，看數值分佈、null 比
例、top-N。

## 隨時可用的退出口

- **直接打識別字** — 輸入 `dbt_marts.fct_orders` 一次跳到底。
- **關鍵字** — 打 `revenue`，精靈用搜尋重新過濾。
- **`back`** — 回到上一步。
- **`cancel`** / **`quit`** — 乾淨退出，什麼都不會留下。

完整規格、MCP 工具串接、錯誤處理請見 [SKILL.md](./SKILL.md)。
