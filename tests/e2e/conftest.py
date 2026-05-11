"""E2E gate — pytest opt-in mirroring tests/integration/.

These tests spawn the MCP server as a stdio subprocess and exercise the
full MCP JSON-RPC wire protocol against a real Redshift cluster, so they
share the same prerequisites as the integration tests: an active profile
and a password in keyring. The opt-in env var is the same one
(`REDSHIFT_INTEGRATION=1`) so a single deliberate flip enables both.

Why a separate folder: integration tests call `tool.fn` directly to keep
each pytest under 200ms. E2E tests pay the subprocess-spawn cost (~1s)
to validate the wire format itself — they catch serialization bugs and
`instructions` handshake regressions that in-process tests cannot.

To opt in:

    REDSHIFT_INTEGRATION=1 uv run pytest tests/e2e/
"""
from __future__ import annotations

import os

import pytest

from redshift_comment_mcp.config import get_password, read_active_profile, read_profile

OPT_IN_ENV = "REDSHIFT_INTEGRATION"


@pytest.fixture(scope="module")
def e2e_preconditions_satisfied():
    """Skips the whole module unless the opt-in env var is set AND a profile
    with a keychain password is configured. No return value — the fixture's
    presence on a test is the gate."""
    if os.environ.get(OPT_IN_ENV) != "1":
        pytest.skip(
            f"E2E tests require {OPT_IN_ENV}=1 to opt in. "
            f"Run with `{OPT_IN_ENV}=1 uv run pytest tests/e2e/`."
        )

    profile_name = read_active_profile() or "default"
    profile = read_profile(profile_name)
    if profile is None:
        pytest.skip(f"No '{profile_name}' profile in config.toml — run /redshift-setup.")

    if get_password(profile_name) is None:
        pytest.skip(f"No password in keyring for '{profile_name}' — run set-password.")
