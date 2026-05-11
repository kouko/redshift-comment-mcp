"""Live-cluster smoke gate — exercise every MCP tool against the active
Redshift profile.

These tests require explicit opt-in via REDSHIFT_INTEGRATION=1 and a
configured active profile. See conftest.py for the skip mechanism.

Each test runs ONE small read-only query (no row data, just metadata
or `SELECT 1`). The whole module's wall time should be under a minute.
The tests are cluster-agnostic — they discover targets dynamically via
the `live_target` fixture, so any cluster with at least one BASE TABLE
will pass.

What this catches that mocks cannot:
  - SQL forms that work in mock but fail on real `pg_class` (e.g. typos
    in catalog table names, undocumented Redshift dialect quirks)
  - Tool functions that incorrectly process the live DataFrame shape
  - Identifier-validation false positives on real schema names with
    underscores or numerics
  - Pagination boundary behavior on tables with > 50 columns
  - The validate_read_only_sql guard against a real DROP-shaped query
"""
from __future__ import annotations

import pytest

from .conftest import _get_tool_fn


# ===== connection sanity =====


def test_select_one(live_redshift_tools):
    """The simplest possible round trip — proves connection + auth + read."""
    execute_sql = _get_tool_fn(live_redshift_tools, "execute_sql")
    result = execute_sql(sql_statement="SELECT 1 AS x")
    assert result["total_count"] == 1
    assert result["columns"] == ["x"]
    assert result["data"][0]["x"] == 1


def test_execute_sql_blocks_destructive(live_redshift_tools):
    """validate_read_only_sql must reject a DROP-shaped statement before it
    reaches the cluster. Live-tests this guard against the real entry point.

    DROP is rejected by the prefix check ("Only SELECT and WITH...") rather
    than the keyword check, so the message doesn't mention DROP — match the
    raise itself, not the message text.
    """
    execute_sql = _get_tool_fn(live_redshift_tools, "execute_sql")
    with pytest.raises(ValueError):
        execute_sql(sql_statement="DROP TABLE pretend_table")

    # Also verify the keyword path: a query that DOES start with SELECT but
    # contains a forbidden keyword should still be rejected (the more
    # interesting half of the guard).
    with pytest.raises(ValueError, match="DROP"):
        execute_sql(sql_statement="SELECT 1; DROP TABLE pretend_table;")


# ===== list_* against live catalog =====


def test_list_schemas_returns_user_schemas(live_redshift_tools):
    """list_schemas should return at least one user schema with shape contract."""
    list_schemas = _get_tool_fn(live_redshift_tools, "list_schemas")
    result = list_schemas()  # default include_comments=True
    assert result["total_count"] >= 1
    assert len(result["schemas"]) >= 1
    first = result["schemas"][0]
    assert "name" in first
    assert "comment" in first  # default include_comments=True


def test_list_tables_returns_tables_for_target_schema(live_redshift_tools, live_target):
    """list_tables on the discovered target schema returns ≥1 row with the
    expected fields."""
    list_tables = _get_tool_fn(live_redshift_tools, "list_tables")
    result = list_tables(schema_name=live_target["schema"], include_comments=False)
    assert result["total_count"] >= 1
    first = result["tables"][0]
    assert "name" in first
    assert "type" in first
    # include_comments=False → no comment field on each row
    assert "comment" not in first


def test_list_tables_with_comments(live_redshift_tools, live_target):
    """include_comments=True must add a comment field on every row."""
    list_tables = _get_tool_fn(live_redshift_tools, "list_tables")
    result = list_tables(schema_name=live_target["schema"], include_comments=True)
    assert result["total_count"] >= 1
    for row in result["tables"]:
        assert "comment" in row


def test_list_columns_returns_columns_for_target_table(live_redshift_tools, live_target):
    """list_columns on the discovered target table returns ≥1 column with
    the expected fields."""
    list_columns = _get_tool_fn(live_redshift_tools, "list_columns")
    result = list_columns(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
        include_comments=False,
    )
    assert result["total_count"] >= 1
    first = result["columns"][0]
    assert "name" in first
    assert "type" in first
    assert "nullable" in first


def test_list_columns_parent_comment_present_by_default(live_redshift_tools, live_target):
    """include_parent_comments defaults to True — table_comment should be on
    the result envelope."""
    list_columns = _get_tool_fn(live_redshift_tools, "list_columns")
    result = list_columns(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
    )
    assert "table_comment" in result


# ===== search_* against live catalog =====


def test_search_schemas_keyword_hit(live_redshift_tools, live_target):
    """search_schemas with the discovered target schema's name as keyword must
    return ≥1 hit (the target itself)."""
    search_schemas = _get_tool_fn(live_redshift_tools, "search_schemas")
    # Use the leading 3-char prefix of the target schema name as a keyword —
    # broad enough to catch the target itself plus likely siblings.
    keyword = live_target["schema"][:3]
    result = search_schemas(keywords=keyword)
    assert result["total_count"] >= 1
    found_target = any(s["name"] == live_target["schema"] for s in result["schemas"])
    assert found_target, (
        f"search_schemas({keyword!r}) didn't surface the target schema "
        f"{live_target['schema']!r} which we just discovered via list_schemas"
    )


def test_search_tables_single_schema(live_redshift_tools, live_target):
    """search_tables with schema_name must work (the only signature on main)."""
    search_tables = _get_tool_fn(live_redshift_tools, "search_tables")
    keyword = live_target["table"][:3]
    result = search_tables(keywords=keyword, schema_name=live_target["schema"])
    assert result["total_count"] >= 1
    assert result["schema_filter"] == live_target["schema"]


def test_search_columns_single_table(live_redshift_tools, live_target):
    """search_columns with schema_name + table_name must work."""
    search_columns = _get_tool_fn(live_redshift_tools, "search_columns")
    keyword = live_target["column"][:3] if len(live_target["column"]) >= 3 else live_target["column"]
    result = search_columns(
        keywords=keyword,
        schema_name=live_target["schema"],
        table_name=live_target["table"],
    )
    assert result["total_count"] >= 1
    assert result["table_name"] == live_target["table"]
    assert result["scope"] == "single_table"


# ===== cross-scope search behavior (schema_name=None / table_name=None) =====


def test_search_tables_cross_schema(live_redshift_tools, live_target):
    """search_tables(schema_name=None) searches the whole cluster."""
    search_tables = _get_tool_fn(live_redshift_tools, "search_tables")
    keyword = live_target["table"][:3]
    result = search_tables(keywords=keyword)  # no schema_name
    assert result["total_count"] >= 1
    assert result["schema_filter"] is None
    # The target row must be present somewhere in the cluster-wide result
    found_target = any(
        row["schema_name"] == live_target["schema"]
        and row["table_name"] == live_target["table"]
        for row in result["tables"]
    )
    if result["total_count"] <= result["returned_count"]:
        assert found_target, (
            f"cluster-wide search didn't find the target {live_target['schema']}.{live_target['table']} "
            f"discovered via list_tables (and not in pagination overflow)"
        )


def test_search_columns_schema_wide(live_redshift_tools, live_target):
    """search_columns(table_name=None) does schema-wide cross-table column search
    and emits scope='schema_wide'. Each row must carry table_name."""
    search_columns = _get_tool_fn(live_redshift_tools, "search_columns")
    keyword = live_target["column"][:3] if len(live_target["column"]) >= 3 else live_target["column"]
    result = search_columns(keywords=keyword, schema_name=live_target["schema"])
    assert result["total_count"] >= 1
    assert result["table_name"] is None
    assert result["scope"] == "schema_wide"
    # Each returned row must include table_name (the natural primitive for cross-table)
    for row in result["columns"]:
        assert "table_name" in row, (
            f"schema-wide search_columns row missing table_name: {row!r}"
        )


# ===== cap + scale_hint behavior on the live cluster =====


def test_scale_hint_present_for_large_schema(live_redshift_tools):
    """If any user schema has > SCALE_HINT_THRESHOLD tables, list_tables on it
    should emit scale_hint with the actual round-trip count baked in.

    Skip cleanly if no schema in the cluster qualifies."""
    from redshift_comment_mcp.redshift_tools import SCALE_HINT_THRESHOLD

    list_schemas = _get_tool_fn(live_redshift_tools, "list_schemas")
    list_tables = _get_tool_fn(live_redshift_tools, "list_tables")

    schemas_result = list_schemas(include_comments=False)
    big_schema_name = None
    big_schema_total = 0
    for name in schemas_result["schemas"]:
        # include_comments=False returns bare strings
        try:
            r = list_tables(schema_name=name, include_comments=False, include_parent_comments=False)
        except Exception:
            continue
        if r["total_count"] > SCALE_HINT_THRESHOLD:
            big_schema_name = name
            big_schema_total = r["total_count"]
            break

    if big_schema_name is None:
        pytest.skip(
            f"No schema in cluster has > {SCALE_HINT_THRESHOLD} tables — "
            f"scale_hint live-test not applicable here."
        )

    result = list_tables(schema_name=big_schema_name, include_comments=False, include_parent_comments=False)
    assert "scale_hint" in result, (
        f"Schema {big_schema_name!r} has {big_schema_total} tables (above threshold "
        f"{SCALE_HINT_THRESHOLD}) but result lacks scale_hint"
    )
    # Hint should mention the actual table count and a round-trip count
    assert str(big_schema_total) in result["scale_hint"]


def test_scale_hint_absent_for_small_schema(live_redshift_tools):
    """list_schemas itself returns < threshold schemas in any reasonable cluster,
    so list_tables on a small schema should NOT emit scale_hint.
    Find a small schema dynamically; skip if all schemas are huge."""
    from redshift_comment_mcp.redshift_tools import SCALE_HINT_THRESHOLD

    list_schemas = _get_tool_fn(live_redshift_tools, "list_schemas")
    list_tables = _get_tool_fn(live_redshift_tools, "list_tables")

    schemas_result = list_schemas(include_comments=False)
    small_schema_name = None
    for name in schemas_result["schemas"]:
        try:
            r = list_tables(schema_name=name, include_comments=False, include_parent_comments=False)
        except Exception:
            continue
        if 0 < r["total_count"] <= SCALE_HINT_THRESHOLD:
            small_schema_name = name
            break

    if small_schema_name is None:
        pytest.skip(
            f"Every schema has either 0 or > {SCALE_HINT_THRESHOLD} tables — "
            f"no small schema to verify scale_hint suppression."
        )

    result = list_tables(schema_name=small_schema_name, include_comments=False, include_parent_comments=False)
    assert "scale_hint" not in result, (
        f"Schema {small_schema_name!r} has {result['total_count']} tables "
        f"(under threshold) but result emitted scale_hint anyway"
    )


def test_comment_cap_triggers_on_long_table_comments(live_redshift_tools):
    """search_tables cluster-wide with a broad keyword should hit the long-tail
    table comments and trigger comment_truncated_count. Skip if no schema in
    the cluster has any table comment exceeding MAX_COMMENT_LEN."""
    from redshift_comment_mcp.redshift_tools import MAX_COMMENT_LEN

    search_tables = _get_tool_fn(live_redshift_tools, "search_tables")
    # `a` matches almost any English-comment text — broad enough to surface
    # the long-tail long comments without being keyword-specific.
    result = search_tables(keywords="a")  # cluster-wide

    if result["total_count"] == 0:
        pytest.skip("No table-name-or-comment matches for 'a' in this cluster.")

    truncated = result.get("comment_truncated_count", 0)
    if truncated == 0:
        pytest.skip(
            f"No table comment in returned page exceeded {MAX_COMMENT_LEN} chars — "
            f"cap behavior not exercised on this cluster slice."
        )

    # Confirmed: cap fired. The hint should be present and reference the cap.
    assert "comment_truncated_hint" in result
    assert str(MAX_COMMENT_LEN) in result["comment_truncated_hint"]
    # Find at least one row whose comment ends with the ellipsis marker
    has_ellipsis = any(
        isinstance(row.get("table_comment"), str) and row["table_comment"].endswith("…")
        for row in result["tables"]
    )
    assert has_ellipsis, (
        f"comment_truncated_count={truncated} but no row's table_comment ends with '…'"
    )


def test_get_table_comment_returns_full_text_no_cap(live_redshift_tools, live_target):
    """Single-item getter is the full-text escape hatch — never truncates."""
    get_table_comment = _get_tool_fn(live_redshift_tools, "get_table_comment")
    result = get_table_comment(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
    )
    # Whatever the comment length, it must not have been truncated by the cap
    assert "…" not in (result["comment"] or "(No comment available)") or (
        # The "…" character could legitimately appear in a real comment;
        # the right check is that the result contract didn't add a
        # truncation hint. Single-item getters never set one.
        "comment_truncated_count" not in result
    )
    assert "comment_truncated_count" not in result


# ===== get_* against live catalog =====


def test_get_schema_comment(live_redshift_tools, live_target):
    """get_schema_comment returns the documented shape regardless of comment presence."""
    get_schema_comment = _get_tool_fn(live_redshift_tools, "get_schema_comment")
    result = get_schema_comment(schema_name=live_target["schema"])
    assert result["schema_name"] == live_target["schema"]
    assert "comment" in result
    assert isinstance(result["comment"], str)


def test_get_table_comment(live_redshift_tools, live_target):
    """get_table_comment returns the documented shape and full comment text
    (single-item getter, no truncation)."""
    get_table_comment = _get_tool_fn(live_redshift_tools, "get_table_comment")
    result = get_table_comment(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
    )
    assert result["schema_name"] == live_target["schema"]
    assert result["table_name"] == live_target["table"]
    assert "comment" in result


def test_get_column_comment(live_redshift_tools, live_target):
    """get_column_comment returns shape + data_type."""
    get_column_comment = _get_tool_fn(live_redshift_tools, "get_column_comment")
    result = get_column_comment(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
        column_name=live_target["column"],
    )
    assert result["schema_name"] == live_target["schema"]
    assert result["table_name"] == live_target["table"]
    assert result["column_name"] == live_target["column"]
    assert "data_type" in result
    assert "comment" in result


def test_get_all_column_comments(live_redshift_tools, live_target):
    """get_all_column_comments returns ≥1 column with full shape."""
    get_all = _get_tool_fn(live_redshift_tools, "get_all_column_comments")
    result = get_all(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
    )
    assert result["total_count"] >= 1
    first = result["columns"][0]
    assert "column_name" in first
    assert "data_type" in first
    assert "is_nullable" in first
    assert "column_comment" in first


# ===== pagination boundary =====


def test_list_columns_pagination_limit(live_redshift_tools, live_target):
    """Explicit limit=1 should cap returned rows at 1 even when more exist."""
    list_columns = _get_tool_fn(live_redshift_tools, "list_columns")
    result = list_columns(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
        limit=1,
        include_comments=False,
    )
    assert result["returned_count"] == 1
    if result["total_count"] > 1:
        assert result["has_more"] is True


def test_list_columns_offset(live_redshift_tools, live_target):
    """offset=1 should shift the window — proves offset semantics."""
    list_columns = _get_tool_fn(live_redshift_tools, "list_columns")
    full = list_columns(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
        include_comments=False,
    )
    if full["total_count"] < 2:
        pytest.skip("Target table has < 2 columns — offset test not meaningful.")
    shifted = list_columns(
        schema_name=live_target["schema"],
        table_name=live_target["table"],
        limit=1,
        offset=1,
        include_comments=False,
    )
    assert shifted["columns"][0]["name"] != full["columns"][0]["name"]
    assert shifted["offset"] == 1


# ===== execute_sql user-transparency =====


def test_execute_sql_carries_transparency_fields_on_real_response(live_redshift_tools):
    """Smoke: the live execute_sql round-trip carries both _executed_sql
    (verbatim user SQL) and _user_facing_message (display directive)."""
    execute_sql = _get_tool_fn(live_redshift_tools, "execute_sql")
    result = execute_sql(sql_statement="SELECT 1 AS x")
    assert result["_executed_sql"] == ["SELECT 1 AS x"]
    assert "_user_facing_message" in result
    assert "_executed_sql" in result["_user_facing_message"]
