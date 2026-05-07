# redshift-profile

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-profile` answers the question *"what does this column actually contain?"* by composing the `redshift-comment-mcp` server's `list_columns` and `execute_sql` tools into a single read-only round. It returns cardinality, null rate, top-100 values, min/max for numeric and date types, and the column's existing `COMMENT ON` text — all in one chat turn.

## When to use it

Reach for this skill when you land on an unfamiliar table and need fast orientation before writing analysis SQL or filling in `schema.yml` documentation. Typical scenarios:

- Deciding whether `status` is an enum (and what its values are) before adding `accepted_values` tests.
- Checking null rate on a join key before trusting it in a fact model.
- Eyeballing the date range covered by a fact table.
- Confirming a varchar is low-cardinality before treating it as a category.

Skip it for free-text columns (top-100 is meaningless), full-row counts (use `execute_sql` directly), and any write operation — the parent MCP server is read-only by charter.

## Example

```
/redshift-profile dbt_marts.fct_orders status
```

Sample chat reply:

> **dbt_marts.fct_orders.status** — varchar(32), 13,030 rows, 0.30% null, 4 distinct.
> Top values: `active` 94.70%, `cancelled` 3.10%, `pending` 1.50%, `refunded` 0.40%.
> Hint: skewed enum, `active` dominates.

## Output shape

```json
{
  "schema": "dbt_marts", "table": "fct_orders", "column": "status",
  "type": "varchar(32)", "comment": "Order lifecycle state",
  "total_rows": 13030, "null_pct": 0.30,
  "distinct_count": 4, "cardinality_class": "low",
  "top_values": [{"value": "active", "count": 12340, "pct": 94.70}]
}
```

## Authoritative reference

For execution details — input parsing rules, type-branch matrix, exact SQL templates, error codes — see [`SKILL.md`](./SKILL.md).
