"""Shared scaffolding for the adversarial probes of 2026-09-19-connection-resolution.

Self-contained on purpose: these probes must run on a clean tree without
importing anything from ``tests/``, so a later edit to the repository suite
cannot silently disarm them.

Isolation here is BOTH halves, never one:

- ``XDG_CONFIG_HOME`` is redirected, so ``config.toml`` lands in a throwaway
  directory.
- ``keyring`` is replaced with an in-memory dict, so nothing reaches the
  machine's real login keychain.

The second half is not optional. A prior change's probe
(``docs/loom/2026-09-17-credential-resolution-hardening/evidence/probes/
probe_readme_lock_claims.py``) redirected only ``XDG_CONFIG_HOME`` and wrote a
real macOS keychain entry on every run. Any probe here that reaches
``config.set_password`` / ``config.get_password`` calls ``isolate_store``,
which installs both.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

KEYRING_SERVICE = "redshift-comment-mcp"


def install_fake_keychain(monkeypatch) -> Dict[Tuple[str, str], str]:
    """Replace the ``keyring`` backend with a dict and return that dict.

    ``config.py`` does ``import keyring`` and calls ``keyring.get_password`` at
    call time, so patching the module attributes is enough — and it keeps the
    probes off the developer's real login keychain.
    """
    import keyring as _kr

    storage: Dict[Tuple[str, str], str] = {}

    monkeypatch.setattr(
        _kr, "set_password",
        lambda service, user, password: storage.__setitem__((service, user), password),
    )
    monkeypatch.setattr(
        _kr, "get_password",
        lambda service, user: storage.get((service, user)),
    )
    monkeypatch.setattr(
        _kr, "delete_password",
        lambda service, user: storage.pop((service, user), None),
    )
    return storage


def isolate_store(monkeypatch, tmp_path: Path) -> Dict[Tuple[str, str], str]:
    """Redirect config.toml AND the keychain. Returns the fake keychain dict."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    return install_fake_keychain(monkeypatch)


def ns(**kwargs) -> argparse.Namespace:
    """A Namespace shaped exactly like the one ``server.main()``'s argparse builds."""
    defaults: Dict[str, Any] = dict(
        profile=None,
        host=None,
        port=5439,
        user=None,
        password=None,
        dbname=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def get_tool_fn(tools, name: str) -> Callable[..., Dict[str, Any]]:
    """Pull a registered MCP tool's plain callable off a RedshiftTools instance.

    FastMCP moved the listing API between its 2.x and 3.x lines (private
    ``_list_tools`` vs public ``list_tools``); ``tool.fn`` is stable on both.
    """
    lister = getattr(tools.mcp, "list_tools", None) or tools.mcp._list_tools
    for tool in asyncio.run(lister()):
        if tool.name == name:
            return tool.fn
    raise KeyError(f"tool {name!r} not registered")


def tools_for(args: argparse.Namespace):
    """A ``RedshiftTools`` wired the way ``server.main()`` wires the live one.

    Same ``status_provider`` lambda, so ``get_setup_status`` reads the very
    decision the connector would act on — the seam W0-02 introduced.
    """
    from redshift_comment_mcp.config import ConfigurationError
    from redshift_comment_mcp.redshift_tools import RedshiftTools
    from redshift_comment_mcp import server

    def config_provider():
        raise ConfigurationError("probe: the connector is never reached here")

    return RedshiftTools(
        config_provider,
        status_provider=lambda profile: server.resolve_connection_decision(args, profile),
    )


def server_instructions() -> str:
    """The FastMCP ``instructions`` handshake string the server ships.

    Read off a constructed server rather than by scraping the source file, so
    the probe pins what an MCP client is actually handed.
    """
    tools = tools_for(ns())
    text: Optional[str] = getattr(tools.mcp, "instructions", None)
    assert isinstance(text, str) and text.strip(), (
        "FastMCP server exposes no non-empty `instructions` string; the probe "
        "cannot pin what it does not receive."
    )
    return text
