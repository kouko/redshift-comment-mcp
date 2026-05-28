"""Live-cluster smoke gate — pytest fixtures and skip mechanism.

These integration tests connect to a real Redshift cluster and exercise every
MCP tool against live metadata catalogs. They intentionally do NOT run in CI
by default — Redshift credentials are user-bound, the cluster is shared
infrastructure, and a misbehaving test could load the leader.

To opt in:

    REDSHIFT_INTEGRATION=1 uv run pytest tests/integration/

The fixture skips cleanly (not fails) when:
  - REDSHIFT_INTEGRATION env var is not set to "1"
  - No active profile is configured at ~/.config/redshift-comment-mcp/active-profile
  - The active profile has no entry in config.toml
  - The active profile has no password in the OS keyring

This makes default `pytest tests/` safe in CI; the gate becomes a deliberate
local pre-push step.
"""
from __future__ import annotations

import os

import pytest

from redshift_comment_mcp.config import get_password, read_active_profile, read_profile
from redshift_comment_mcp.connection import create_redshift_config
from redshift_comment_mcp.redshift_tools import RedshiftTools

OPT_IN_ENV = "REDSHIFT_INTEGRATION"


@pytest.fixture(scope="module")
def live_redshift_tools():
    """Returns a RedshiftTools instance wired to the active profile, OR skips
    cleanly if any precondition for live access is missing.

    Module-scoped so all tests in one file share a single configured tools
    object — connection-per-call is still per-tool (the existing config's
    `get_connection()` context manager handles that).
    """
    if os.environ.get(OPT_IN_ENV) != "1":
        pytest.skip(
            f"Live-cluster integration tests require {OPT_IN_ENV}=1 to opt in. "
            f"Run with `{OPT_IN_ENV}=1 uv run pytest tests/integration/`."
        )

    profile_name = read_active_profile() or "default"
    profile = read_profile(profile_name)
    if profile is None:
        pytest.skip(f"No '{profile_name}' profile in config.toml — run /redshift-setup.")

    password = get_password(profile_name)
    if password is None:
        pytest.skip(f"No password in keyring for '{profile_name}' — run set-password.")

    config = create_redshift_config(
        host=profile["host"],
        port=profile["port"],
        user=profile["user"],
        password=password,
        dbname=profile["dbname"],
    )
    return RedshiftTools(lambda: config)


@pytest.fixture(scope="module")
def live_target(live_redshift_tools):
    """Discover-driven target: pick a real schema and table from the live cluster
    so tests aren't pinned to a specific environment.

    Returns a dict with:
      schema:  the first non-system schema with at least one BASE TABLE
      table:   the first table in that schema
      column:  the first column of that table

    If the cluster has zero user schemas, the entire test module is skipped.
    """
    list_schemas = _get_tool_fn(live_redshift_tools, "list_schemas")
    list_tables = _get_tool_fn(live_redshift_tools, "list_tables")
    list_columns = _get_tool_fn(live_redshift_tools, "list_columns")

    # Use include_comments=True (the documented "cheap" default) so the
    # response is uniformly a list of dicts; with include_comments=False
    # the list collapses to bare strings, which we don't need here.
    schemas_result = list_schemas(include_comments=True)
    if schemas_result["total_count"] == 0:
        pytest.skip("Cluster has no user schemas — nothing to smoke-test against.")

    chosen_schema = None
    chosen_table = None
    for schema_row in schemas_result["schemas"]:
        schema_name = schema_row["name"]
        try:
            tables_result = list_tables(schema_name=schema_name, include_comments=False, include_parent_comments=False)
        except Exception:
            continue
        for table_row in tables_result["tables"]:
            if table_row.get("type") == "BASE TABLE":
                chosen_schema = schema_name
                chosen_table = table_row["name"]
                break
        if chosen_schema:
            break

    if not chosen_schema:
        pytest.skip("No BASE TABLE found in any user schema — cluster appears empty.")

    columns_result = list_columns(
        schema_name=chosen_schema,
        table_name=chosen_table,
        include_comments=False,
        include_parent_comments=False,
    )
    if columns_result["total_count"] == 0:
        pytest.skip(
            f"Target table {chosen_schema}.{chosen_table} has no columns — "
            f"likely a permission or VIEW edge case; pick a different cluster."
        )

    return {
        "schema": chosen_schema,
        "table": chosen_table,
        "column": columns_result["columns"][0]["name"],
    }


def _get_tool_fn(tools, name):
    """Pull a registered MCP tool's callable, surviving FastMCP API churn.
    Mirrors the helper in tests/test_tools.py — duplicated here to keep the
    integration test module self-contained.
    """
    import asyncio
    lister = getattr(tools.mcp, "list_tools", None) or tools.mcp._list_tools
    for t in asyncio.run(lister()):
        if t.name == name:
            return t.fn
    raise KeyError(f"tool {name!r} not registered")
