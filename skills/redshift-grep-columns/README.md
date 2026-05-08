# redshift-grep-columns

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-grep-columns` answers the question *"which tables have a column matching this keyword?"* by grepping across the column metadata of one or all schemas in a Redshift cluster. It searches both column names AND column comments, returning every hit grouped by `<schema>.<table>` with the column type and comment inline.

Cache-first: when `/redshift-cache-schema` has produced a fresh local TSV index, this skill answers in roughly 50 ms via `bash grep`. When the cache is stale or absent, it falls back to live MCP (`search_tables` + `search_columns` per matching table), which can take many round trips.

## When to use it

Reach for this skill before composing a multi-table SQL query — particularly when you need to identify shared keys / FK candidates across tables. Typical scenarios:

- Pre-JOIN reconnaissance: "find every column commented as a foreign key to `customers`."
- Naming-consistency audits: "are we calling it `customer_id`, `cust_no`, or both?"
- Locating a metric: "which tables expose `gross_margin`?"

Skip it for single-table column lookups (use MCP `search_columns(kw, schema, table)` directly), single-column lookup with full text (use `get_column_comment`), or table-name search (use `/redshift-grep-tables`).

## Example

```
/redshift-grep-columns customer_id --schema dbt_marts
```

Sample chat reply:

> Matches for "customer_id" (4 hits in 1 schema, 3 tables):
>
> dbt_marts.fct_orders
>   customer_id   bigint   Customer reference (FK to dim_users.id)
>
> dbt_marts.fct_returns
>   customer_id   bigint   Customer who initiated the return
>
> dbt_marts.dim_users
>   id            bigint   Primary key, referenced as customer_id elsewhere
>   cust_no       bigint   Legacy customer number, alias for id

## Performance note

Cluster has > 5 schemas and you're about to grep without a fresh cache?
Run `/redshift-cache-schema` first. Live-path cost scales linearly with
schema and matching-table counts; cache-path cost is constant.

## Authoritative reference

For execution details — input parsing rules, exact bash patterns, error codes — see [`SKILL.md`](./SKILL.md).
