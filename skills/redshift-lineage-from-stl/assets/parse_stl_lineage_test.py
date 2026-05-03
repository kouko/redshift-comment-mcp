#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["sqlglot>=25.0"]
# ///
"""Smoke tests for parse_stl_lineage.py — runs via `uv run` so PEP 723 deps resolve.

Usage:
    ./parse_stl_lineage_test.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = HERE / "parse_stl_lineage.py"


def run_script(rows: list[dict], extra_args: list[str] | None = None) -> dict:
    with tempfile.TemporaryDirectory() as td:
        in_path = Path(td) / "in.ndjson"
        out_path = Path(td) / "out.json"
        in_path.write_text("\n".join(json.dumps(r) for r in rows))

        cmd = [str(SCRIPT), "--input", str(in_path), "--output", str(out_path)]
        if extra_args:
            cmd += extra_args
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"script failed: {proc.stderr}")
        return json.loads(out_path.read_text())


def t_simple_select():
    out = run_script([
        {"query": 1, "user": "alice", "starttime": "2026-05-01 09:00:00",
         "sql": "SELECT * FROM dbt_marts.fct_orders WHERE status='active'"}
    ])
    assert out["summary"]["parsed"] == 1
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert e["source"] == "dbt_marts.fct_orders"
    assert e["target"] is None
    assert e["operation"] == "select"
    assert e["queries"] == 1
    assert e["distinct_users"] == 1
    print("✓ simple select")


def t_insert_with_select():
    out = run_script([
        {"query": 2, "user": "bob", "starttime": "2026-05-01 10:00:00",
         "sql": "INSERT INTO dbt_marts.fct_orders SELECT * FROM dbt_staging.stg_orders"}
    ])
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert e["source"] == "dbt_staging.stg_orders"
    assert e["target"] == "dbt_marts.fct_orders"
    assert e["operation"] == "insert"
    print("✓ insert with select")


def t_ctas():
    out = run_script([
        {"query": 3, "user": "carol", "starttime": "2026-05-01 11:00:00",
         "sql": "CREATE TABLE analytics.snapshot AS SELECT * FROM dbt_marts.fct_orders"}
    ])
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert e["source"] == "dbt_marts.fct_orders"
    assert e["target"] == "analytics.snapshot"
    assert e["operation"] == "ctas"
    print("✓ ctas")


def t_join_multi_source():
    out = run_script([
        {"query": 4, "user": "dan", "starttime": "2026-05-01 12:00:00",
         "sql": """
             SELECT o.id, u.email
             FROM dbt_marts.fct_orders o
             JOIN dbt_marts.dim_users u ON u.user_id = o.user_id
         """}
    ])
    sources = sorted(e["source"] for e in out["edges"])
    assert sources == ["dbt_marts.dim_users", "dbt_marts.fct_orders"], sources
    print("✓ join multi source")


def t_system_filter():
    out = run_script([
        {"query": 5, "user": "sys", "starttime": "2026-05-01 13:00:00",
         "sql": "SELECT * FROM pg_catalog.pg_class"}
    ])
    assert len(out["edges"]) == 0
    assert out["filtered_out"]["system"] >= 1
    out_inc = run_script([
        {"query": 5, "user": "sys", "starttime": "2026-05-01 13:00:00",
         "sql": "SELECT * FROM pg_catalog.pg_class"}
    ], extra_args=["--include-system"])
    assert len(out_inc["edges"]) == 1
    print("✓ system filter (with and without --include-system)")


def t_filter_table():
    out = run_script([
        {"query": 6, "user": "e", "starttime": "2026-05-01 14:00:00",
         "sql": "SELECT * FROM dbt_marts.fct_orders"},
        {"query": 7, "user": "e", "starttime": "2026-05-01 14:01:00",
         "sql": "SELECT * FROM other_schema.other_table"},
    ], extra_args=["--filter-table", "dbt_marts.fct_orders"])
    assert len(out["edges"]) == 1
    assert out["edges"][0]["source"] == "dbt_marts.fct_orders"
    print("✓ filter-table")


def t_aggregation_users_and_count():
    out = run_script([
        {"query": 8,  "user": "a", "starttime": "2026-05-01 15:00:00", "sql": "SELECT * FROM x.y"},
        {"query": 9,  "user": "a", "starttime": "2026-05-01 15:01:00", "sql": "SELECT * FROM x.y"},
        {"query": 10, "user": "b", "starttime": "2026-05-01 15:02:00", "sql": "SELECT * FROM x.y"},
    ])
    assert len(out["edges"]) == 1
    e = out["edges"][0]
    assert e["queries"] == 3
    assert e["distinct_users"] == 2
    top = {u["user"]: u["count"] for u in e["users_top"]}
    assert top == {"a": 2, "b": 1}
    print("✓ aggregation users+count")


def t_cte_filtered():
    """CTE-introduced names should NOT show up as source tables."""
    out = run_script([
        {"query": 20, "user": "a", "starttime": "2026-05-01 17:00:00",
         "sql": """
             WITH recent AS (
                 SELECT * FROM dbt_marts.fct_orders WHERE created_at > '2026-04-01'
             )
             SELECT r.id, u.email
             FROM recent r JOIN dbt_marts.dim_users u ON u.user_id = r.user_id
         """}
    ])
    sources = sorted(e["source"] for e in out["edges"])
    assert "dbt_marts.fct_orders" in sources
    assert "dbt_marts.dim_users" in sources
    # CTE name "recent" must NOT appear as a source
    assert all("recent" not in s for s in sources), f"CTE leaked: {sources}"
    print("✓ CTE names filtered from sources")


def t_multi_statement():
    """Multiple statements separated by ; — all should be parsed."""
    out = run_script([
        {"query": 21, "user": "b", "starttime": "2026-05-01 18:00:00",
         "sql": "SELECT * FROM a.x; INSERT INTO a.y SELECT * FROM a.z;"}
    ])
    edges = sorted((e["source"], e["target"], e["operation"]) for e in out["edges"])
    # Statement 1: SELECT a.x → source a.x, target None, op select
    # Statement 2: INSERT INTO a.y SELECT FROM a.z → source a.z, target a.y, op insert
    assert ("a.x", None, "select") in edges, edges
    assert ("a.z", "a.y", "insert") in edges, edges
    print("✓ multi-statement SQL all parsed")


def t_parse_error_recorded():
    out = run_script([
        {"query": 11, "user": "x", "starttime": "2026-05-01 16:00:00",
         "sql": "this is not valid sql at all }}}"},
        {"query": 12, "user": "x", "starttime": "2026-05-01 16:01:00",
         "sql": "SELECT * FROM ok.tbl"},
    ])
    assert out["summary"]["parsed"] == 1
    assert out["summary"]["parse_errors"] == 1
    assert len(out["parse_errors"]) == 1
    assert out["parse_errors"][0]["query"] == 11
    print("✓ parse error recorded, other queries still processed")


def main():
    tests = [
        t_simple_select,
        t_insert_with_select,
        t_ctas,
        t_join_multi_source,
        t_system_filter,
        t_filter_table,
        t_aggregation_users_and_count,
        t_cte_filtered,
        t_multi_statement,
        t_parse_error_recorded,
    ]
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"✗ {t.__name__}: unexpected: {e}")
            sys.exit(1)
    print(f"\n{len(tests)}/{len(tests)} tests passed")


if __name__ == "__main__":
    main()
