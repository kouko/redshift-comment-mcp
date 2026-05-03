#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["sqlglot>=25.0"]
# ///
"""Parse Redshift STL_QUERY-derived NDJSON of (query, user, starttime, sql) and
emit aggregated lineage edges.

Input NDJSON, one object per line:
    {"query": 1234, "user": "alice", "starttime": "2026-05-01 09:12:08", "sql": "INSERT INTO …"}

Output JSON:
    {
      "edges": [
          {
            "source": "schema.table",
            "target": "schema.table" | null,
            "operation": "select" | "insert" | "ctas" | "update" | "delete" | "merge",
            "queries": int,
            "distinct_users": int,
            "users_top": [{"user": str, "count": int}, …5],
            "first_seen": iso8601,
            "last_seen": iso8601,
            "sample_query_ids": [int, …5]
          },
          …
      ],
      "summary": {"total_queries": int, "parsed": int, "parse_errors": int, "tables_seen": int, "edges": int},
      "parse_errors": [{"query": int, "error": "..."}],
      "filtered_out": {"system": int, "internal_dbt_cache": int}
    }

Exit codes: 0 success, 2 input/output error.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import sqlglot
from sqlglot import exp

SYSTEM_PREFIXES = ("pg_catalog.", "information_schema.", "stl_", "stv_", "svl_", "svv_", "sys_")
INTERNAL_DBT_PREFIXES = ("_dbt_cache.", "_airbyte_internal.")

WRITE_OPS = {
    exp.Insert: "insert",
    exp.Create: "ctas",
    exp.Update: "update",
    exp.Delete: "delete",
    exp.Merge: "merge",
}


def qualify(table: exp.Table) -> str | None:
    name = table.name
    if not name:
        return None
    schema = table.db or ""
    if schema:
        return f"{schema.lower()}.{name.lower()}"
    return name.lower()


def is_system(qualified: str) -> bool:
    return qualified.startswith(SYSTEM_PREFIXES)


def is_internal(qualified: str) -> bool:
    return qualified.startswith(INTERNAL_DBT_PREFIXES)


def extract_targets_and_sources(sql: str) -> list[tuple[str, str | None, list[str]]]:
    """Parse SQL (may contain multiple `;`-separated statements) and return
    a list of (operation, target_or_None, source_tables) — one per statement.

    Filters out CTE-introduced names (a `WITH cte AS (...) SELECT FROM cte`
    should not record `cte` as a source table).
    """
    statements = sqlglot.parse(sql, read="redshift")

    results: list[tuple[str, str | None, list[str]]] = []
    for stmt in statements:
        if stmt is None:
            continue

        cte_names: set[str] = set()
        for cte in stmt.find_all(exp.CTE):
            alias = cte.alias_or_name
            if alias:
                cte_names.add(alias.lower())

        operation = "select"
        target: str | None = None
        for cls, op_name in WRITE_OPS.items():
            if isinstance(stmt, cls):
                operation = op_name
                this = stmt.args.get("this")
                if isinstance(this, exp.Schema):
                    this = this.this
                if isinstance(this, exp.Table):
                    target = qualify(this)
                break

        sources: set[str] = set()
        for tbl in stmt.find_all(exp.Table):
            q = qualify(tbl)
            if not q:
                continue
            if not tbl.db and tbl.name and tbl.name.lower() in cte_names:
                continue
            sources.add(q)

        if target and operation in ("insert", "ctas"):
            sources.discard(target)

        results.append((operation, target, sorted(sources)))

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="NDJSON input path")
    ap.add_argument("--output", required=True, help="JSON output path")
    ap.add_argument("--filter-table", help="schema.table — keep only edges touching this table")
    ap.add_argument("--include-system", action="store_true", help="include pg_catalog/STL/etc")
    ap.add_argument("--include-internal", action="store_true", help="include dbt cache/airbyte internal")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        print(json.dumps({"_error": f"input not found: {in_path}"}), file=sys.stderr)
        return 2

    edge_acc: dict[tuple[str, str | None, str], dict] = defaultdict(lambda: {
        "queries": 0,
        "users": defaultdict(int),
        "first_seen": None,
        "last_seen": None,
        "sample_query_ids": [],
    })
    parse_errors: list[dict] = []
    filtered_system = 0
    filtered_internal = 0
    parsed_ok = 0
    total = 0
    tables_seen: set[str] = set()

    filter_target = args.filter_table.lower() if args.filter_table else None

    with in_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
                sql = row.get("sql") or ""
                user = row.get("user") or "?"
                qid = row.get("query")
                ts = row.get("starttime")
            except Exception as e:
                parse_errors.append({"query": None, "error": f"bad json: {e}"})
                continue

            if not sql:
                continue

            try:
                stmt_results = extract_targets_and_sources(sql)
            except Exception as e:
                parse_errors.append({"query": qid, "error": str(e)[:200]})
                continue

            if not stmt_results:
                continue
            parsed_ok += 1

            edges_this_query: list[tuple[str, str | None, str]] = []
            for operation, target, sources in stmt_results:
                if target:
                    for src in sources:
                        edges_this_query.append((src, target, operation))
                else:
                    for src in sources:
                        edges_this_query.append((src, None, operation))

            for src, tgt, op in edges_this_query:
                if not args.include_system and (is_system(src) or (tgt and is_system(tgt))):
                    filtered_system += 1
                    continue
                if not args.include_internal and (is_internal(src) or (tgt and is_internal(tgt))):
                    filtered_internal += 1
                    continue
                if filter_target and src != filter_target and tgt != filter_target:
                    continue

                tables_seen.add(src)
                if tgt:
                    tables_seen.add(tgt)

                key = (src, tgt, op)
                acc = edge_acc[key]
                acc["queries"] += 1
                acc["users"][user] += 1
                if ts:
                    if acc["first_seen"] is None or ts < acc["first_seen"]:
                        acc["first_seen"] = ts
                    if acc["last_seen"] is None or ts > acc["last_seen"]:
                        acc["last_seen"] = ts
                if qid is not None and len(acc["sample_query_ids"]) < 5:
                    acc["sample_query_ids"].append(qid)

    edges_out = []
    for (src, tgt, op), acc in sorted(edge_acc.items(), key=lambda kv: -kv[1]["queries"]):
        users_top = sorted(acc["users"].items(), key=lambda kv: -kv[1])[:5]
        edges_out.append({
            "source": src,
            "target": tgt,
            "operation": op,
            "queries": acc["queries"],
            "distinct_users": len(acc["users"]),
            "users_top": [{"user": u, "count": c} for u, c in users_top],
            "first_seen": acc["first_seen"],
            "last_seen": acc["last_seen"],
            "sample_query_ids": acc["sample_query_ids"],
        })

    output = {
        "edges": edges_out,
        "summary": {
            "total_queries": total,
            "parsed": parsed_ok,
            "parse_errors": len(parse_errors),
            "tables_seen": len(tables_seen),
            "edges": len(edges_out),
        },
        "parse_errors": parse_errors[:50],
        "filtered_out": {"system": filtered_system, "internal_dbt_cache": filtered_internal},
    }

    try:
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"_error": f"write failed: {e}"}), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
