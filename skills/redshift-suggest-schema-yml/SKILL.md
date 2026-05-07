---
name: redshift-suggest-schema-yml
description: >-
  Draft a dbt schema.yml v2 `models:` block for a Redshift table with
  conservative test suggestions (not_null / unique / accepted_values)
  inferred from a profile run. Read-only. Use when about to write
  schema.yml from scratch or backfill tests on an existing table. Do
  NOT use for writing YAML to disk (chat-only by charter), profiling
  alone (use /redshift-profile), or sources: blocks (models: only).
  Triggers: /redshift-suggest-schema-yml / draft schema.yml / dbt yml
  / dbt tests / dbt スキーマ提案 / 受入値テスト.
---

# Redshift → dbt schema.yml Draft

Drafts a paste-ready dbt v2 `models:` block by profiling each column
and applying conservative test rules. Read-only. Chat output only.

## When to use / NOT
- Use when adopting a Redshift table into dbt or backfilling tests.
- NOT for huge tables without user-confirmed full-scan; NOT for
  source: blocks (use sister skill); NOT for in-place YAML merging.

## Inputs
| Form | Mode |
|---|---|
| `<schema>.<table>` | whole-table — profile every column |
| `<schema>.<table> <col>` | single-column |
| (paste profile JSON) | single-column from existing profile |
| (no args) | ask user |

If both schema.table AND profile JSON given → prefer JSON; warn on mismatch.

## Flow

1. **Resolve column set**.
   - whole-table: `list_columns(schema_name, table_name, include_comments=true)`
     — MCP returns `{name, type, nullable, comment}`. Empty → error
     `table_not_found_or_no_permission`.
   - single-column from JSON: validate required fields. Step 3 rules
     read `null_count`, `null_pct`, `total_rows`, `distinct_count`,
     `cardinality_class`, `type_branch`, `top_values`, plus
     identifying fields (`schema`, `table`, `column`, `type`,
     `comment`). Any missing → error `invalid_profile_json: <fields>`.
     `min` / `max` are conditionally required — only when
     `type_branch ∈ {numeric, date}` (used by the commented
     `dbt_utils.accepted_range` suggestion); for `string` / `boolean`
     they may be `null`.
   - single-column from args: list_columns → filter to named column.

2. **Profile each column** by running Steps 2-5 of
   [redshift-profile/SKILL.md](../redshift-profile/SKILL.md). Skip
   `unsupported` types with TODO marker. Per-column failures don't abort
   — emit `# profile failed: <reason>` YAML comment and continue.

3. **Apply test rules** (conservative — never suggest a test current
   data violates):

   | Test | Rule |
   |---|---|
   | `not_null` | `null_count == 0`. If `0 < null_pct < 1%` → emit as YAML comment, not active test. |
   | `unique` | `distinct_count == total_rows` AND `null_count == 0`. |
   | `accepted_values` | `cardinality_class == "low"` AND `2 ≤ distinct_count ≤ 20` AND `type_branch ∈ {string, boolean}`. Numeric/date "low" → emit but commented (likely status code; nudge user review). |
   | `dbt_utils.accepted_range` | `numeric` / `date` with min/max — emit commented (requires dbt_utils). |

   Skipped from MVP: `relationships` (no FK info), cross-column tests.

4. **Resolve fields**:
   - `description:` from `comment`; if empty → `"TODO: describe <col>"`.
   - `data_type:` from `type` field (raw, with length/precision, lowercased).

## Output

YAML block (`yaml` fence, paste-ready):
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
Conventions:
- Empty line between columns; inline `# comment` for caveats; commented
  `- test:` lines for low-confidence suggestions.
- `version: 2` only in whole-table mode; single-column mode emits one
  column entry for splicing.

Plus rationale table (chat):
```
| column | type | distinct | null% | tests | notes |
| order_id | bigint | 13030 | 0.00 | not_null, unique | likely PK |
| status | varchar(32) | 4 | 0.30 | not_null, accepted_values | clean enum |
| notes | varchar(2000) | 11894 | 3.21 | — | high-cardinality text |
```
End with: "Drafted N columns — M with full tests, K TODO desc, P unsupported. Review before merging."

## Anti-patterns

- NEVER suggest a test current data violates — `not_null` only when `null_count == 0`; use commented-out form for `0 < null_pct < 1%`. False-positive tests erode trust in the whole `schema.yml`.
- NEVER write to disk — chat-only by charter. The user pastes; in-place merging into existing `schema.yml` is out of scope.
- NEVER suggest `accepted_values` for high-cardinality strings — `cardinality_class` must be `"low"` AND `distinct ≤ 20`. Otherwise the test churns on every new row.
- NEVER skip the per-column rationale table — without it the user can't audit why each test landed and which to drop.
- NEVER infer `relationships:` tests — no FK info from MCP; that's `/redshift-erd` territory.

## Errors
| Condition | `_error` |
|---|---|
| list_columns empty (whole-table) | `table_not_found_or_no_permission` |
| Pasted JSON missing required fields | `invalid_profile_json: <fields>` |
| JSON schema/table mismatches positional args | `json_args_mismatch` |
| Every column failed | `profile_failed_for_all_columns` |

Per-column failures degrade gracefully — partial output beats no output.

## See also

| Need | Use |
|---|---|
| Profile a column to feed this skill | `/redshift-profile` |
| Relationship inference (deliberately excluded here) | `/redshift-erd` |
| Find tables to draft yml for | `/redshift-explore` |
