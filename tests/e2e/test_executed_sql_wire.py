"""End-to-end test of _executed_sql / _user_facing_message via real MCP wire.

What's exercised here that in-process and integration tests cannot reach:

  - The MCP JSON-RPC handshake: server `instructions` correctly served
  - Cross-process serialization of the new fields through stdio transport
  - The actual deployment shape (subprocess spawn, same as MCP clients use)

Each test spawns one stdio subprocess running the redshift-comment-mcp
server entrypoint. Wall-clock cost ~2-3s per test — much heavier than the
in-process tests, so the module is kept small and focused on contract
shape (not behavior breadth — that's the integration suite's job).

Assertion-leak discipline: on assertion failure pytest dumps the
expression's local variables, which includes raw server payloads. To keep
real schema / table names off CI logs and screenshots:

  - Custom assertion messages NEVER format the full payload — they cite
    keys / lengths / presence only.
  - Variables holding metadata payloads are scoped tightly and not bound
    to names that pytest displays as "interesting" (avoid `payload =`
    at module/class scope).
"""
from __future__ import annotations

import asyncio
import sys

import pytest  # noqa: F401  — fixture symbol comes from conftest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

MUST_INCLUDE_IN_INSTRUCTIONS = "EXECUTE_SQL TRANSPARENCY"


def _spawn_transport() -> StdioTransport:
    """Spawn the server as a Python subprocess via the same import path the
    pyproject.toml console-script entry uses."""
    return StdioTransport(
        command=sys.executable,
        args=["-c", "from redshift_comment_mcp.server import main; main()"],
    )


def _structured(resp) -> dict:
    """FastMCP client response carries the tool's dict under either `.data`
    or `.structured_content` depending on version. Coerce both to a plain
    dict so tests can use ordinary indexing."""
    return getattr(resp, "data", None) or getattr(resp, "structured_content", None)


async def _run_instructions_handshake_carries_transparency_block():
    """The MCP capability handshake's `instructions` field must include the
    EXECUTE_SQL TRANSPARENCY directive — agents read this once at session
    init, so a missing block silently disables the user-disclosure contract."""
    async with Client(_spawn_transport()) as client:
        init = client.initialize_result
        instructions = (init.instructions or "") if init else ""
        # Citing the marker, not the full block — keeps failure dump clean.
        assert MUST_INCLUDE_IN_INSTRUCTIONS in instructions, (
            f"server instructions missing {MUST_INCLUDE_IN_INSTRUCTIONS!r} "
            f"(length={len(instructions)})"
        )


async def _run_tools_list_registers_execute_sql_via_wire():
    """Round-trips through `tools/list` and confirms execute_sql is on the
    wire — defends against accidentally un-registering it during refactor."""
    async with Client(_spawn_transport()) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "execute_sql" in names, f"execute_sql missing (got {len(names)} tools)"


async def _run_execute_sql_round_trip_carries_transparency_fields():
    """Wire-level proof that _executed_sql + _user_facing_message survive the
    FastMCP serialization layer and reach the client intact."""
    sql = "SELECT 1 AS x"
    async with Client(_spawn_transport()) as client:
        body = _structured(await client.call_tool("execute_sql", {"sql_statement": sql}))
        assert body is not None, "execute_sql response had no structured payload"
        # _executed_sql must echo the verbatim input.
        assert body.get("_executed_sql") == [sql], (
            f"_executed_sql wrong shape "
            f"(present={'_executed_sql' in body}, "
            f"type={type(body.get('_executed_sql')).__name__})"
        )
        msg = body.get("_user_facing_message", "")
        assert "_executed_sql" in msg, (
            f"_user_facing_message lacks field-name reference (length={len(msg)})"
        )
        assert "verbatim" in msg.lower() or "do not" in msg.lower(), (
            f"_user_facing_message lacks directive language (length={len(msg)})"
        )


async def _run_metadata_tool_wire_response_omits_transparency_fields():
    """Scope guard: list_schemas must NOT carry _executed_sql /
    _user_facing_message over the wire. Metadata tools use fixed catalog
    templates whose SQL is implementation detail; pushing them to users is
    noise, not signal. This test catches accidental scope creep at the
    serialization boundary.

    Leak discipline: only assert key absence + result-list length. Do NOT
    print the response, do NOT include the response in the assertion
    message — schema names live in there.
    """
    async with Client(_spawn_transport()) as client:
        body = _structured(
            await client.call_tool(
                "list_schemas", {"limit": 2, "include_comments": False}
            )
        )
        assert body is not None, "list_schemas response had no structured payload"
        assert "_executed_sql" not in body, (
            "scope creep: list_schemas leaked _executed_sql over the wire"
        )
        assert "_user_facing_message" not in body, (
            "scope creep: list_schemas leaked _user_facing_message over the wire"
        )
        # Sanity that the call really hit the cluster (not a wire-only short-
        # circuit). Length only — no schema names.
        assert isinstance(body.get("schemas"), list), "schemas field missing or wrong type"


# ===== sync pytest entry points =====
#
# The project doesn't depend on pytest-asyncio; the test runner sees only
# these sync wrappers and runs the async work via asyncio.run. Each wrapper
# also pulls the conftest fixture, so the opt-in skip applies before the
# subprocess is spawned (saves ~1s on a skipped run).


def test_instructions_handshake_carries_transparency_block(e2e_preconditions_satisfied):
    asyncio.run(_run_instructions_handshake_carries_transparency_block())


def test_tools_list_registers_execute_sql_via_wire(e2e_preconditions_satisfied):
    asyncio.run(_run_tools_list_registers_execute_sql_via_wire())


def test_execute_sql_round_trip_carries_transparency_fields(e2e_preconditions_satisfied):
    asyncio.run(_run_execute_sql_round_trip_carries_transparency_fields())


def test_metadata_tool_wire_response_omits_transparency_fields(e2e_preconditions_satisfied):
    asyncio.run(_run_metadata_tool_wire_response_omits_transparency_fields())
