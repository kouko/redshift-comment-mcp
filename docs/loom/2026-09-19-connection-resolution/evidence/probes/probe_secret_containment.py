"""Probe: does the borrowed secret stay inside the connector?

The intent's standing constraint is absolute — "The password value must not
reach argv, logs, stdout, or any MCP response." W0-02 introduced
``ConnectionDecision``, the first type in this codebase that carries the
password AND is handed to a reporting surface (``get_setup_status`` receives
the whole object and is trusted to read only ``has_password``). So the
question is no longer "does the status tool print the password" but "what does
this new carrier print when something else renders it".

The other secret carrier, ``connection.RedshiftConnectionConfig``, is a plain
class: its ``repr`` is ``<... object at 0x...>`` and discloses nothing. The
repo already treats rendered locals as a real leak channel — see
``docs/loom/2026-09-17-setup-dialog-write-order/evidence/probes/
probe_secret_leakage.py::test_setupviadialog_writeprofilefailstraceback_doesnotrenderthelocalpassword``.
"""
from __future__ import annotations

import io
import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_support import get_tool_fn, isolate_store, ns, tools_for  # noqa: E402

from redshift_comment_mcp import config, server  # noqa: E402

SECRET = "pr0be-B0RR0WED-s3cret"


def _borrowing_args(tmp_path, monkeypatch):
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", SECRET)
    return ns(host="redshift.internal", user="alice", dbname="warehouse", port=5439)


def test_decisionrepr_borrowedpassword_redacted(tmp_path, monkeypatch):
    """The carrier's own ``repr`` must not disclose what it carries.

    ``ConnectionDecision`` is a plain ``@dataclass(frozen=True)``, so it opts
    into a generated ``__repr__`` that renders every field including
    ``password``. Any channel that formats the object — a ``logger.debug``
    added later, a ``TracebackException(capture_locals=True)``, an f-string in
    an error message, a test runner printing the compared value — prints the
    secret in clear.

    The fix is one keyword: ``password: Optional[str] = field(repr=False)``.
    """
    args = _borrowing_args(tmp_path, monkeypatch)
    decision = server.resolve_connection_decision(args)
    assert decision.password == SECRET, "probe setup failed: nothing was borrowed"

    assert SECRET not in repr(decision), (
        f"ConnectionDecision.__repr__ renders the borrowed password in clear: "
        f"{repr(decision).replace(SECRET, '<SECRET>')} — with <SECRET> standing "
        f"where the real value appeared. The sibling secret carrier "
        f"connection.RedshiftConnectionConfig discloses nothing from its repr; "
        f"this new one does. Set field(repr=False) on `password`."
    )


def test_decisionlocals_renderedtraceback_redacted(tmp_path, monkeypatch):
    """The same disclosure through the channel this repo has already ruled in.

    A decision object is a live local in ``resolve_connection_params`` and in
    ``get_setup_status``. Rendering a traceback with captured locals — what a
    crash reporter, ``pytest -l``, or ``cgitb`` does — writes the field values
    of every local. This reproduces that rendering over a frame holding a
    real borrowed decision.
    """
    args = _borrowing_args(tmp_path, monkeypatch)

    def _frame_holding_a_decision():
        decision = server.resolve_connection_decision(args)  # noqa: F841
        raise RuntimeError("any later failure in a frame that holds the decision")

    try:
        _frame_holding_a_decision()
    except RuntimeError as exc:
        rendered = "".join(
            traceback.TracebackException.from_exception(exc, capture_locals=True).format()
        )

    assert SECRET not in rendered, (
        "a rendered traceback of a frame holding a ConnectionDecision prints "
        "the borrowed password, because the dataclass repr includes it"
    )


def test_statusresponse_borrowedmode_carriesnosecret(tmp_path, monkeypatch):
    """The MCP response itself: no value anywhere in it may be the secret.

    Scans keys and values recursively rather than checking a field list, so a
    field added later is covered without editing this probe.
    """
    args = _borrowing_args(tmp_path, monkeypatch)
    status = get_tool_fn(tools_for(args), "get_setup_status")()

    def _flatten(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield str(key)
                yield from _flatten(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                yield from _flatten(item)
        else:
            yield str(node)

    leaked = [chunk for chunk in _flatten(status) if SECRET in chunk]
    assert not leaked, f"get_setup_status response contains the borrowed secret: {leaked}"
    assert status["source"] == "borrowed", "probe setup failed: not in borrowed mode"
    assert status["borrowed_from_profile"] == "prod"


def test_startuplog_borrowedlaunch_carriesnosecret(tmp_path, monkeypatch):
    """Nothing the connector logs while borrowing may contain the secret."""
    args = _borrowing_args(tmp_path, monkeypatch)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        host, port, user, password, dbname = server.resolve_connection_params(args)
        from redshift_comment_mcp.connection import create_redshift_config

        cfg_obj = create_redshift_config(
            host=host, port=port, user=user, password=password, dbname=dbname,
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    assert password == SECRET, "probe setup failed: nothing was borrowed"
    assert SECRET not in stream.getvalue(), (
        f"the borrowed password reached the log stream: {stream.getvalue()!r}"
    )
    assert SECRET not in repr(cfg_obj), (
        "RedshiftConnectionConfig now discloses the password from its repr too"
    )


def test_refusalmessage_unmatchedprofiles_carriesnosecret(tmp_path, monkeypatch):
    """The refusal lists every existing profile's host. It must list no secret.

    ``resolve_connection_params`` builds that list by reading each profile, so
    a future edit that widened it to "and here is what is stored for each"
    would land the keychain value in an operator-visible message.
    """
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="other.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", SECRET)

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    try:
        server.resolve_connection_params(args)
    except Exception as exc:  # ConfigurationError, a ValueError subclass
        message = str(exc)
    else:
        raise AssertionError("an unmatched store must refuse, not connect")

    assert SECRET not in message, f"the refusal message leaked a stored password: {message}"
    assert "other.internal" in message, "the refusal must still name the existing profile's host"
    assert "redshift.internal" in message, "the refusal must still name the supplied target"
