"""Probe: does the password escape now that it exists earlier in the call?

The intent's constraint is absolute: "The password value must not be written
to argv, logs, stdout, or any MCP response." The write ordering change moved
the password's lifetime to cover the two persistence steps, so
``write_profile_failed`` and ``keychain_write_failed`` now both run with a
live password in scope, and both log their exception with ``exc_info=True``.

Every case below plants the same sentinel and then searches four exits at
once: the returned dict, the ``logging`` records the call emitted, stdout and
stderr. The repository suite checks the response for two of these branches;
nothing checks the log.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _probe_support import (  # noqa: E402
    get_tool_fn,
    install_fake_keychain,
    isolate_config,
    make_tools,
    stub_connection,
    stub_dialog,
)

SENTINEL = "s3cr3t-SENTINEL-PASSWORD-must-never-escape"


@pytest.fixture
def clean_stores(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    return keychain


def _exits(result, caplog, capsys):
    """Collect every text channel the call could have leaked through."""
    captured = capsys.readouterr()
    return {
        "response": json.dumps(result, default=str),
        "log": "\n".join(
            record.getMessage() + (record.exc_text or "")
            for record in caplog.records
        ),
        "stdout": captured.out,
        "stderr": captured.err,
    }


def _assert_clean(result, caplog, capsys, *, case):
    leaked = [name for name, text in _exits(result, caplog, capsys).items()
              if SENTINEL in text]
    assert not leaked, f"{case}: the password reached {leaked}"


def test_setupviadialog_successfulcall_keepsthepasswordoffeveryexit(
    monkeypatch, clean_stores, caplog, capsys
):
    """Baseline: the happy path must not echo what the user typed."""
    stub_dialog(monkeypatch, (SENTINEL, "ok"))
    stub_connection(monkeypatch, (True, None))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )
    assert result["status"] == "configured"
    _assert_clean(result, caplog, capsys, case="configured")


def test_setupviadialog_writeprofilefailstraceback_doesnotrenderthelocalpassword(
    monkeypatch, clean_stores, caplog, capsys
):
    """The branch that the reordering newly made password-bearing.

    Before the change, ``write_profile_failed`` fired with no password
    anywhere in the call — the dialog had not run yet. Now the password is a
    live local of the very frame whose traceback ``exc_info=True`` renders.
    Python's default traceback formatter prints no locals, but a handler that
    turns them on (rich, better-exceptions, any custom formatter) would write
    the password into the server log from this branch alone. ``write_profile``
    is never handed the password, so this probe attacks the frame, not the
    exception text.
    """
    stub_dialog(monkeypatch, (SENTINEL, "ok"))

    def refuse(name, **kw):
        raise PermissionError("config directory not writable")

    monkeypatch.setattr("redshift_comment_mcp.config.write_profile", refuse)

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )
    assert result["error"] == "write_profile_failed"
    _assert_clean(result, caplog, capsys, case="write_profile_failed")


def test_setupviadialog_keychainraisescarryingthepassword_logsnothingsecret(
    monkeypatch, clean_stores, caplog, capsys
):
    """The repository's own test already models a backend that echoes the
    password in its exception args, and pins that the response stays clean.

    The same exception is passed straight to
    ``logger.error(f"...: {e}", exc_info=True)`` one line earlier. The
    constraint names logs alongside responses, so the log must be clean too.
    """
    stub_dialog(monkeypatch, (SENTINEL, "ok"))
    monkeypatch.setattr(
        "redshift_comment_mcp.config.write_profile", lambda name, **kw: None
    )

    def refuse(name, pw):
        raise RuntimeError(f"backend rejected password {pw!r}")

    monkeypatch.setattr("redshift_comment_mcp.config.set_password", refuse)

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )
    assert result["error"] == "keychain_write_failed"
    _assert_clean(result, caplog, capsys, case="keychain_write_failed")


def test_setupviadialog_connectionerror_isrelayedverbatimtoresponseandlog(
    monkeypatch, clean_stores, caplog, capsys
):
    """The connection branch is the one exit with no sanitisation at all.

    ``write_profile_failed`` and ``keychain_write_failed`` reduce their
    third-party exception to a class name, citing CWE-209 in the comments.
    ``configured_but_connection_failed`` instead relays ``str(e)`` from the
    Redshift driver, unmodified, into both the ``connection_error`` response
    field and the server log. This probe pins that relay so the asymmetry is
    on the record: whatever the driver puts in a message crosses the MCP wire.

    The shipped ``redshift_connector`` was checked and its error paths do not
    interpolate the password value, so this is a channel, not a demonstrated
    leak. The probe asserts the channel exists rather than claiming one.
    """
    stub_dialog(monkeypatch, ("a-typed-password", "ok"))
    monkeypatch.setattr(
        "redshift_comment_mcp.config.write_profile", lambda name, **kw: None
    )
    monkeypatch.setattr(
        "redshift_comment_mcp.config.set_password", lambda name, pw: None
    )
    driver_text = "FATAL: password authentication failed for user 'alice'"
    stub_connection(monkeypatch, (False, driver_text))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )

    assert result["status"] == "configured_but_connection_failed"
    assert result["connection_error"] == driver_text, (
        "connection_error no longer relays the driver string verbatim — if it "
        "was sanitised, this probe has served its purpose and can be retired"
    )
    assert "exception_class" not in result, (
        "the connection branch grew the CWE-209 treatment its siblings have"
    )
    # Whatever it relays, the password the user typed is not part of it.
    _assert_clean(result, caplog, capsys, case="configured_but_connection_failed")


@pytest.mark.parametrize(
    "dialog_return,expected_status",
    [
        ((None, "cancelled"), "dialog_cancelled"),
        ((None, "permission_denied"), "permission_denied"),
        ((None, "unavailable"), "dialog_unavailable"),
        ((None, "unsupported"), "platform_unsupported"),
        (("", "ok"), "empty_password"),
    ],
    ids=["cancelled", "permission_denied", "unavailable", "unsupported", "empty"],
)
def test_setupviadialog_failureresponses_carrynopasswordshapedfield(
    monkeypatch, clean_stores, caplog, capsys, dialog_return, expected_status
):
    """No failure response may grow a field that could hold a secret.

    The recovery messages were all rewritten in this change; a rewrite that
    started echoing what the dialog returned would show up here.
    """
    stub_dialog(monkeypatch, dialog_return)
    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )

    assert result["status"] == expected_status
    forbidden = {"password", "secret", "credential", "pw", "passwd"}
    assert not (forbidden & {k.lower() for k in result}), f"suspicious key: {result}"
    _assert_clean(result, caplog, capsys, case=expected_status)
