"""Probe: inline mode now depends on the profile store. What if it is broken?

Before this change, an inline launch never touched ``config.toml`` and never
touched the keychain: ``resolve_connection_params`` took the inline branch and
returned before ``config`` was even imported (plan, Current State Evidence,
Forward). W0-01 added a store read to that branch — ``cfg.list_profiles()``,
``cfg.read_profile()``, ``cfg.get_password()`` — on the no-inline-password path.

That is a new dependency on the borrow path, so the interesting question is
what a broken dependency does to a mode that used to be independent of it. Two
failures the project already treats as real:

- No keyring backend on the host. ``redshift_tools.py`` maps
  ``NoKeyringError`` to "No keyring backend is available on this host." in
  ``setup_via_dialog``, and ``config.py:519`` catches deliberately broader
  than ``KeyringError`` elsewhere for the same reason. ``config.get_password``
  itself does not.
- A profile entry in ``config.toml`` that is not a table. The store is
  documented as machine-managed, but the 2026-09-17 incident in the intent is
  literally "the workaround was to hand-edit the plugin's stored options", so
  hand-edited stores exist on real machines.

The bar is not "never fails". It is: fail the way this server has contracted
to fail — a ``ConfigurationError``, which ``@_guarded`` turns into the
structured ``not_configured`` response with a ``next_step``, instead of an
arbitrary exception that escapes to the MCP client as an opaque tool crash.
``get_setup_status`` is deliberately not ``@_guarded`` at all, so it must not
raise here either: it is the one tool an agent has for "what state am I in".

Measured, same inline launch (host/user/dbname, no password), base 3821be8 vs
HEAD 4bb2272, via ``resolve_connection_params``:

    state                    base 3821be8           HEAD 4bb2272
    keyring unavailable      ConfigurationError     NoKeyringError
    non-table profile entry  ConfigurationError     AttributeError
    malformed config.toml    ConfigurationError     TOMLDecodeError

All three base refusals were the same actionable message, "Inline mode
requires a password — provide ... REDSHIFT_PASSWORD env var". So this is a
regression of the inline path specifically, not a pre-existing gap inherited
from profile mode (where the latter two have always crashed this way).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_support import get_tool_fn, isolate_store, ns, tools_for  # noqa: E402

from redshift_comment_mcp import config, server  # noqa: E402
from redshift_comment_mcp.config import ConfigurationError  # noqa: E402


def _matching_store_then_break_keyring(tmp_path, monkeypatch):
    """A store whose profile matches the launch triple, on a keyring-less host."""
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )

    import keyring as _kr
    from keyring.errors import NoKeyringError

    def _explode(service, user):
        raise NoKeyringError("No recommended backend was available.")

    monkeypatch.setattr(_kr, "get_password", _explode)
    return ns(host="redshift.internal", user="alice", dbname="warehouse")


def test_connector_keyringunavailable_raisesconfigurationerror(tmp_path, monkeypatch):
    """The connector must refuse the contracted way, not with a raw RuntimeError.

    An inline launch on a host with no keyring backend used to raise
    ``ConfigurationError`` naming ``REDSHIFT_PASSWORD`` — the actionable answer,
    and the one an operator on such a host needs. Now the borrow scan reaches
    the keychain first.
    """
    args = _matching_store_then_break_keyring(tmp_path, monkeypatch)

    with pytest.raises(ConfigurationError) as caught:
        server.resolve_connection_params(args)

    assert "REDSHIFT_PASSWORD" in str(caught.value), (
        "on a keyring-less host the only remaining inline channel is the env "
        "var, so the refusal has to name it"
    )


def test_status_keyringunavailable_staysanswerable(tmp_path, monkeypatch):
    """``get_setup_status`` must still answer on a keyring-less host.

    It carries no ``@_guarded``; an exception from the status provider escapes
    to the MCP client. Reporting ``has_password: false`` with a ``next_step``
    is a correct answer here. Raising is not an answer at all.
    """
    args = _matching_store_then_break_keyring(tmp_path, monkeypatch)

    status = get_tool_fn(tools_for(args), "get_setup_status")()

    assert status["has_password"] is False
    assert status["configured"] is False
    assert status["host"] == "redshift.internal"
    assert "next_step" in status


def test_borrow_nontableprofileentry_staysactionable(tmp_path, monkeypatch):
    """A hand-edited ``config.toml`` whose profile entry is a bare string.

    ``read_all()`` returns ``{"default": "oops"}``; the borrow scan then calls
    ``.get`` on a ``str``. An inline launch that used to be wholly independent
    of this file must not be taken down by it — refuse the contracted way.
    """
    isolate_store(monkeypatch, tmp_path)
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[profile]\ndefault = "hand-edited into a scalar"\n')

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")

    with pytest.raises(ConfigurationError):
        server.resolve_connection_params(args)


def test_borrow_malformedtoml_staysactionable(tmp_path, monkeypatch):
    """A truncated ``config.toml`` — the shape a half-finished hand edit leaves.

    Same bar: the inline launch must refuse with the contracted error rather
    than propagate a parser exception the degraded-mode guard does not catch.
    """
    isolate_store(monkeypatch, tmp_path)
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[profile.default]\nhost = "redshift.internal\n')

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")

    with pytest.raises(ConfigurationError):
        server.resolve_connection_params(args)


def test_borrow_inlinepasswordpresent_skipsstoreentirely(tmp_path, monkeypatch):
    """Control: a launch that supplies a password must not read the store at all.

    This is what keeps the new dependency scoped to the borrow path. Every
    store accessor is replaced with one that raises, so any read fails loudly.
    """
    isolate_store(monkeypatch, tmp_path)

    def _forbidden(*args, **kwargs):
        raise AssertionError("the store was consulted on a password-bearing launch")

    monkeypatch.setattr(config, "list_profiles", _forbidden)
    monkeypatch.setattr(config, "read_profile", _forbidden)
    monkeypatch.setattr(config, "get_password", _forbidden)

    args = ns(
        host="redshift.internal", user="alice", dbname="warehouse", password="typed-inline",
    )
    assert server.resolve_connection_params(args) == (
        "redshift.internal", 5439, "alice", "typed-inline", "warehouse",
    )
