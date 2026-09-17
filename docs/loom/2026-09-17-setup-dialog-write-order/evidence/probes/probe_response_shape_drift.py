"""Probe: drift the W0-02 key-set pins let through.

``TestSetupViaDialogResponseShapeContract`` pins two things per response: the
discriminator string and the exact set of top-level keys. It deliberately does
not pin prose. Between those two lies a band of mutations that keep every key
name and every status string while changing what an agent consuming the tool
actually reads — the VALUES behind the pinned keys.

Each test below names a mutation that the key-set pin accepts and this probe
rejects.
"""
from __future__ import annotations

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


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """Isolate both stores and neutralise them; these tests read responses."""
    isolate_config(monkeypatch, tmp_path)
    install_fake_keychain(monkeypatch)
    monkeypatch.setattr(
        "redshift_comment_mcp.config.write_profile", lambda name, **kw: None
    )
    monkeypatch.setattr(
        "redshift_comment_mcp.config.set_password", lambda name, pw: None
    )
    stub_dialog(monkeypatch, ("dialog-secret", "ok"))
    stub_connection(monkeypatch, (True, None))
    return get_tool_fn(make_tools(), "setup_via_dialog")


CALL = dict(
    host="h.example.com", user="alice", dbname="analytics",
    profile="prod", port=5439,
)


def test_setupviadialog_connectionfailed_reportstestedfalse(monkeypatch, stubbed):
    """Mutation the key-set pin accepts: flip ``tested`` to True here.

    ``tested`` is the only field that tells an agent whether the profile was
    proven to work. Both success shapes carry it, so the key set is identical
    either way and the pin cannot see the flip. An agent that read
    ``tested: True`` off a connection failure would tell the user setup
    succeeded.
    """
    stub_connection(monkeypatch, (False, "Connection timed out"))
    result = stubbed(**CALL)

    assert result["status"] == "configured_but_connection_failed"
    assert result["tested"] is False, (
        f"a failed connection test reported tested={result['tested']!r}"
    )
    assert result["connection_error"], "connection_error must not be empty"


def test_setupviadialog_successfulcall_reportstestedtrue(stubbed):
    """The paired direction, so a blanket ``tested: False`` is caught too."""
    result = stubbed(**CALL)
    assert result["status"] == "configured"
    assert result["tested"] is True


@pytest.mark.parametrize(
    "stub_key,expected_status",
    [
        (None, "configured"),
        ("connection", "configured_but_connection_failed"),
    ],
    ids=["configured", "configured_but_connection_failed"],
)
def test_setupviadialog_echoedfields_matchthecallerarguments(
    monkeypatch, stubbed, stub_key, expected_status
):
    """Mutation the key-set pin accepts: echo the STORED profile instead.

    Both success shapes echo host/port/user/dbname. Sourcing them from
    ``read_profile`` after the write, or from a stale variable, keeps every
    key and would pass the pin — while showing the agent values the caller
    never supplied. ``port`` also has to stay an int; TOML and the MCP wire
    both survive a string, and the pin would not notice.
    """
    if stub_key == "connection":
        stub_connection(monkeypatch, (False, "Connection timed out"))

    result = stubbed(**CALL)

    assert result["status"] == expected_status
    assert result["profile"] == "prod"
    assert result["host"] == "h.example.com"
    assert result["user"] == "alice"
    assert result["dbname"] == "analytics"
    assert result["port"] == 5439
    assert isinstance(result["port"], int) and not isinstance(result["port"], bool)


@pytest.mark.parametrize(
    "failing,expected_error,expected_class",
    [
        ("write_profile", "write_profile_failed", "PermissionError"),
        ("set_password", "keychain_write_failed", "RuntimeError"),
    ],
    ids=["write_profile_failed", "keychain_write_failed"],
)
def test_setupviadialog_errorresponses_carryabareexceptionclassname(
    monkeypatch, stubbed, failing, expected_error, expected_class
):
    """Mutation the key-set pin accepts: put ``str(e)`` in ``exception_class``.

    The key set is unchanged, the discriminator is unchanged, and the pin
    passes — but the field is the whole point of the CWE-209 treatment in
    these two branches, which exists so the client gets a class name and not
    the exception's text. A bare class name is an identifier: no spaces, no
    slashes, no quotes.
    """
    marker = "/Users/private/.aws/credentials"
    exc = PermissionError if failing == "write_profile" else RuntimeError

    def refuse(*_a, **_kw):
        raise exc(marker)

    monkeypatch.setattr(f"redshift_comment_mcp.config.{failing}", refuse)
    result = stubbed(**CALL)

    assert result["error"] == expected_error
    cls = result["exception_class"]
    assert cls == expected_class, f"exception_class is {cls!r}"
    assert cls.isidentifier(), (
        f"exception_class {cls!r} is not a bare class name — it looks like "
        f"exception text, which is what the sanitisation exists to withhold"
    )
    assert marker not in cls


@pytest.mark.parametrize(
    "stub,call_overrides,discriminator",
    [
        ({}, {}, "status"),
        ({"connection": (False, "boom")}, {}, "status"),
        ({"dialog": (None, "cancelled")}, {}, "status"),
        ({"dialog": (None, "permission_denied")}, {}, "status"),
        ({"dialog": (None, "unavailable")}, {}, "status"),
        ({"dialog": (None, "unsupported")}, {}, "status"),
        ({"dialog": ("", "ok")}, {}, "status"),
        ({}, {"host": ""}, "error"),
        ({"write_profile": True}, {}, "error"),
        ({"set_password": True}, {}, "error"),
    ],
    ids=["configured", "connection_failed", "cancelled", "permission_denied",
         "unavailable", "unsupported", "empty", "missing_field",
         "write_profile_failed", "keychain_write_failed"],
)
def test_setupviadialog_everyresponse_usesexactlyonediscriminatorkey(
    monkeypatch, stubbed, stub, call_overrides, discriminator
):
    """Mutation the key-set pin accepts on a per-case basis, not globally.

    The pin checks each response against its own expected key set, so it
    cannot state the rule that binds them: a response carries ``status`` or
    ``error``, never both and never neither. Agents branch on that rule; a
    response carrying both would route down two paths at once.
    """
    if "connection" in stub:
        stub_connection(monkeypatch, stub["connection"])
    if "dialog" in stub:
        stub_dialog(monkeypatch, stub["dialog"])
    for name in ("write_profile", "set_password"):
        if name in stub:
            def refuse(*_a, **_kw):
                raise RuntimeError("refused")
            monkeypatch.setattr(f"redshift_comment_mcp.config.{name}", refuse)

    call = dict(CALL)
    call.update(call_overrides)
    result = stubbed(**call)

    present = {"status", "error"} & set(result)
    assert present == {discriminator}, (
        f"expected exactly {discriminator!r} as the discriminator, got "
        f"{sorted(present)}. Full response: {result}"
    )
    assert isinstance(result.get("message"), str) and result["message"], (
        "every response must carry a non-empty message for the agent"
    )
