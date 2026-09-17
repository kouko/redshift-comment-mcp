"""Shared scaffolding for the adversarial probes of 2026-09-17-setup-dialog-write-order.

Deliberately self-contained: the probes must run on a clean tree without
importing anything from ``tests/``, so that a later edit to the repository
suite cannot silently disarm them.

The helpers here give a probe REAL persistence — an actual ``config.toml``
under a temporary ``XDG_CONFIG_HOME`` plus an in-memory stand-in for the OS
keychain — so assertions are about persisted bytes and stored entries, not
about how many times a mock was called.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

KEYRING_SERVICE = "redshift-comment-mcp"


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


def make_tools():
    """A RedshiftTools whose connection provider always reports 'not set up'.

    Matches how the tool is reached in the field: an agent calls
    ``setup_via_dialog`` precisely because the DB tools are returning
    ``not_configured``.
    """
    from redshift_comment_mcp.config import ConfigurationError
    from redshift_comment_mcp.redshift_tools import RedshiftTools

    def provider():
        raise ConfigurationError("not yet configured")

    return RedshiftTools(provider)


def install_fake_keychain(monkeypatch) -> Dict[Tuple[str, str], str]:
    """Replace the ``keyring`` backend with a dict and return that dict.

    ``config.py`` does ``import keyring`` and calls ``keyring.set_password``
    at call time, so patching the module attributes is enough — and it keeps
    the probes from touching the developer's real login keychain.
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


def isolate_config(monkeypatch, tmp_path: Path) -> Path:
    """Point ``config_path()`` at a throwaway directory. Returns that path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    from redshift_comment_mcp import config as cfg

    return cfg.config_path()


def stub_dialog(monkeypatch, value: Tuple[Any, str]) -> None:
    """Make the password dialog return ``value`` instead of opening a window."""
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli._collect_password_via_dialog",
        lambda profile: value,
    )


def stub_connection(monkeypatch, value: Tuple[bool, Any]) -> None:
    """Make the Redshift smoke test return ``value`` instead of dialling out."""
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli._test_redshift_connection",
        lambda *a, **kw: value,
    )
