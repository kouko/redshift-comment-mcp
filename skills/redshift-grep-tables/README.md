# redshift-grep-tables

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-grep-tables` answers the question *"which schema has a table about X?"* by grepping across the table metadata of all schemas in a Redshift cluster. It searches both table names AND table comments, returning every hit grouped by schema with the table type and comment inline.

Cache-first: when `/redshift-cache-schema` has produced a fresh local TSV index, this skill answers in roughly 50 ms via `bash grep`. When the cache is stale or absent, it falls back to live MCP (one `search_tables` call per schema), which scales linearly with schema count.

## When to use it

Reach for this skill when you know the topic but not the schema — typical of working on an unfamiliar cluster or one that mixes ingestion / staging / mart layers across many namespaces. Typical scenarios:

- Topic search: "where is the orders fact?"
- Layer-spanning audit: "which schemas have a `fct_*` table?"
- Vendor-coverage check: "which schemas ingest from Salesforce?"

Skip it when the schema is already known (use MCP `search_tables(kw, schema)` directly), for column-level search (use `/redshift-grep-columns`), or for general schema browsing (use `/redshift-explore`).

## Example

```
/redshift-grep-tables fct
```

Sample chat reply:

> Tables matching "fct" (5 hits in 3 schemas):
>
> dbt_marts (3)
>   fct_orders          BASE TABLE   Central order facts.
>   fct_returns         BASE TABLE   Return events.
>   fct_payments        BASE TABLE   Payment events.
>
> dbt_staging (1)
>   stg_fct_orders      BASE TABLE   Staging for fct_orders.
>
> reporting (1)
>   v_fct_orders_daily  VIEW         Daily aggregation of fct_orders.

## Performance note

Cluster has 10+ schemas and you're about to grep without a fresh cache?
Run `/redshift-cache-schema` first. Live path costs one tool call per
schema; cache path costs 50 ms total.

## Authoritative reference

For execution details — input parsing rules, exact bash patterns, error codes — see [`SKILL.md`](./SKILL.md).
