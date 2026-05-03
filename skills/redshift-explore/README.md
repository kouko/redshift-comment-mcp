# redshift-explore

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

`redshift-explore` walks you through a Redshift cluster you've never seen
before. It's a three-step wizard — **schema → table → column** — and at
every step it shows you the candidates with their comments first, so you
can **pick by reading, not by remembering names**. You don't have to know
that the orders fact table is called `fct_orders` in `dbt_marts`. You
just read down the list, find the one whose comment matches what you're
after, and reply with its number.

## When to use

Reach for this on day one with a new cluster, or any time the question
on your mind is "I don't know where to start." It's built for
**zero-context onboarding** — new analyst, new project, handed-off
warehouse, or just a corner of the data you've never touched. If you
already know the table and column you want, skip the wizard and call
`/redshift-profile` directly.

## Example flow

```
> /redshift-explore

Pick a schema:
  1. dbt_marts     — Final marts layer, business-ready facts and dims
  2. dbt_staging   — Staging models, light cleaning over raw
  3. raw_orders    — Raw event stream from the orders service
Reply: number / name / keyword.

> 1

Pick a table in dbt_marts:
  1. fct_orders     — One row per completed order, grain = order_id
  2. dim_customers  — Current-state customer attributes
  3. fct_payments   — One row per payment attempt
Reply: number / name / keyword / back.

> orders

Filtered to "orders":
  1. fct_orders     — One row per completed order
  2. fct_order_items — One row per line item
Reply: number / name / back.

> 1

You picked dbt_marts.fct_orders. Now pick a column:
  1. order_id   bigint      — Unique order identifier (PK?)
  2. status     varchar(32) — Order lifecycle state
  3. total_jpy  numeric     — Order total in JPY, tax included
...
```

After you pick a column, the wizard hands off to
[`/redshift-profile`](../redshift-profile/SKILL.md) for value
distribution, null rate, and top-N.

## Escape hatches

At any step:

- **Direct identifier** — type `dbt_marts.fct_orders` to jump straight ahead.
- **Keyword** — type `revenue` and the wizard re-filters via search.
- **`back`** — return to the previous step.
- **`cancel`** or **`quit`** — exit cleanly, nothing committed.

See [SKILL.md](./SKILL.md) for the full spec, MCP tool wiring, and error
handling.
