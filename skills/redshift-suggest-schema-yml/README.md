# redshift-suggest-schema-yml

**English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

## What it does

Composes the [`redshift-profile`](../redshift-profile/SKILL.md) skill once
per column of a target table, applies a small set of conservative test
rules, and emits a paste-ready dbt `schema.yml` `models:` block plus a
per-column rationale table. Whole-table mode profiles every column;
single-column mode emits one entry for splicing into an existing file.

## When to use

- Adopting an existing Redshift table into a new dbt project and
  needing a starting `schema.yml` with descriptions and tests.
- Backfilling tests on a legacy dbt model whose `schema.yml` only
  lists column names.
- Validating that a column is a clean enum before promoting it from
  `staging/` into `marts/` with an `accepted_values` test.

## Test rule conservatism

The core promise: **the skill never suggests a test the current data
violates.** `not_null` is only emitted when `null_count == 0`;
`unique` requires `distinct_count == total_rows` AND zero nulls;
`accepted_values` requires low cardinality (2-20 distinct) on
string/boolean columns. Borderline cases (e.g. `0 < null_pct < 1%`)
are emitted as commented YAML so a reviewer decides — the draft is
safe to `dbt test` immediately after paste.

## Example invocations

Whole-table mode:

```
/redshift-suggest-schema-yml dbt_marts.fct_orders
```

Pasted-JSON mode (chains from a previous `/redshift-profile` run):

```
/redshift-suggest-schema-yml
{"schema":"dbt_marts","table":"fct_orders","column":"status",
 "type":"varchar(32)","type_branch":"string","comment":"Order lifecycle state",
 "total_rows":13030,"null_count":0,"null_pct":0.0,
 "distinct_count":4,"cardinality_class":"low",
 "top_values":[{"value":"active","count":12340,"pct":94.70}]}
```

## Abbreviated YAML output

```yaml
version: 2
models:
  - name: fct_orders
    description: "Order facts table"
    columns:
      - name: order_id
        description: "Unique order identifier"
        data_type: bigint
        tests: [not_null, unique]

      - name: status
        description: "Order lifecycle state"
        data_type: varchar(32)
        tests:
          - not_null
          - accepted_values:
              values: ["active", "cancelled", "pending", "refunded"]

      - name: notes
        description: "TODO: describe notes"
        data_type: varchar(2000)
        # high-cardinality free text — no tests suggested
```

See [SKILL.md](./SKILL.md) for full input forms, type branches,
test rule table, and error contract.
