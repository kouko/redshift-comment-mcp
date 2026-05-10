# redshift-grep-tables

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-grep-tables` answers the question *"which schema has a table about X?"* by running one cluster-wide MCP `search_tables` call across all schemas in a Redshift cluster. It searches both table names AND table comments, returning every hit grouped by schema with the table type and comment inline.

Single MCP call (~0.2s for clusters under 10K tables) thanks to the optional `schema_name=None` parameter on `search_tables`.

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

## Authoritative reference

For execution details — input parsing rules, error codes — see [`SKILL.md`](./SKILL.md).
