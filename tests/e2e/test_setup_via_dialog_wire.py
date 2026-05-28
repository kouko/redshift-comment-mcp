"""E2E wire-level checks for setup_via_dialog MCP tool (v0.7.0).

What's exercised here that in-process tests cannot reach:

  - tools/list registers `setup_via_dialog` after FastMCP serialization
    (catches accidental un-registration during refactor)
  - The SETUP RECOVERY block in server `instructions` reaches the client
    intact through the MCP capability handshake

Does NOT exercise the tool's runtime side effects (would touch real OS
keychain / spawn osascript dialog). Functional behavior is covered by the
unit tests in tests/test_tools.py with mocks; this file's responsibility
stops at the wire boundary.

Lighter opt-in than the other e2e file: these tests don't require a
configured profile (degraded-mode startup is what they verify), but
they still spawn a subprocess so we gate on REDSHIFT_INTEGRATION=1 for
CI cost control. Single env-var flip enables both wire tiers.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

SETUP_RECOVERY_MARKER = "SETUP RECOVERY"
OPT_IN_ENV = "REDSHIFT_INTEGRATION"


@pytest.fixture(scope="module")
def e2e_wire_opt_in():
    """Lighter gate than tests/e2e/conftest.py:e2e_preconditions_satisfied —
    only checks the opt-in env var, not profile state. v0.7.0 servers boot
    without a profile, so these wire-level tests don't need one configured."""
    if os.environ.get(OPT_IN_ENV) != "1":
        pytest.skip(
            f"Wire-level e2e tests require {OPT_IN_ENV}=1 to opt in. "
            f"Run with `{OPT_IN_ENV}=1 uv run pytest tests/e2e/`."
        )


def _spawn_transport() -> StdioTransport:
    """Spawn the server as a Python subprocess via the same import path the
    pyproject.toml console-script entry uses."""
    return StdioTransport(
        command=sys.executable,
        args=["-c", "from redshift_comment_mcp.server import main; main()"],
    )


async def _run_tools_list_registers_setup_via_dialog():
    """setup_via_dialog must appear in tools/list. Defends against
    accidental un-registration during refactor + verifies FastMCP's
    introspection sees a tool decorated WITHOUT @_guarded correctly
    (since setup_via_dialog deliberately skips that decorator)."""
    async with Client(_spawn_transport()) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "setup_via_dialog" in names, (
            f"setup_via_dialog missing from tools/list "
            f"(got {len(names)} tools total)"
        )


async def _run_instructions_handshake_carries_setup_recovery_block():
    """The SETUP RECOVERY block in `instructions=` reaches the MCP client
    via the capability handshake. This is how agents discover the
    degraded-mode flow BEFORE encountering a not_configured error — without
    it, agents must hit the error first then read the next_step field. The
    handshake-time channel is the cleaner UX."""
    async with Client(_spawn_transport()) as client:
        init = client.initialize_result
        instructions = (init.instructions or "") if init else ""
        # Cite the marker, not the full block — keeps failure dump clean.
        assert SETUP_RECOVERY_MARKER in instructions, (
            f"server instructions missing {SETUP_RECOVERY_MARKER!r} "
            f"(length={len(instructions)})"
        )


# ===== sync pytest entry points =====


def test_tools_list_registers_setup_via_dialog_via_wire(e2e_wire_opt_in):
    asyncio.run(_run_tools_list_registers_setup_via_dialog())


def test_instructions_handshake_carries_setup_recovery_block(e2e_wire_opt_in):
    asyncio.run(_run_instructions_handshake_carries_setup_recovery_block())
