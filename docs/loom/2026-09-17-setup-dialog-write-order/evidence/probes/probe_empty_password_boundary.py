"""Probe: the boundary between "no password arrived" and "a password arrived".

That boundary is now the gate on every write. Before the change it only chose
a response string; now it decides whether config.toml is touched at all, so
anything that lands on the wrong side of ``if not password`` either wastes a
write or skips one.

``_collect_password_via_dialog`` is typed ``tuple[str | None, str]``, so the
values that can reach the gate are: a non-empty string, the empty string, and
None. The probe walks each, plus the values a caller would expect to behave
like "empty" but that Python's truthiness does not: a single space, a tab, a
newline, and the string "0".
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

SERVICE = "redshift-comment-mcp"


@pytest.fixture
def clean_stores(tmp_path, monkeypatch):
    config_path = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    stub_connection(monkeypatch, (True, None))
    return config_path, keychain


@pytest.mark.parametrize(
    "dialog_value",
    ["", None],
    ids=["empty-string", "none-with-ok-reason"],
)
def test_setupviadialog_falsypasswordwithokreason_writesneitherstore(
    monkeypatch, clean_stores, dialog_value
):
    """Both falsy values must reach empty_password and persist nothing.

    ``None`` paired with reason "ok" is not in the collector's documented
    return set, but the gate is ``if not password`` rather than a reason
    check, so it is reachable from any future collector bug — and it must not
    fall through into the writes.
    """
    config_path, keychain = clean_stores
    stub_dialog(monkeypatch, (dialog_value, "ok"))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )

    assert result["status"] == "empty_password", f"got: {result}"
    assert not config_path.exists(), (
        f"config.toml created for an empty password: {config_path.read_text()}"
    )
    assert keychain == {}


@pytest.mark.parametrize(
    "password",
    [" ", "\t", "\n", "   \t  "],
    ids=["single-space", "tab", "newline", "mixed-whitespace"],
)
def test_setupviadialog_whitespaceonlypassword_isstoredverbatimasarealpassword(
    monkeypatch, clean_stores, password
):
    """Whitespace is truthy, so it sails past the gate and gets persisted.

    A user who holds down the space bar, or a dialog that returns padding,
    produces a profile the tool declares ``configured`` with a password no
    cluster will accept. The probe asserts the boundary treats
    whitespace-only input as absent, which is what "the user did not type a
    password" means to the person at the dialog.
    """
    config_path, keychain = clean_stores
    stub_dialog(monkeypatch, (password, "ok"))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )

    assert result["status"] == "empty_password", (
        f"a whitespace-only password ({password!r}) was accepted as real: "
        f"status={result.get('status')}, config written="
        f"{config_path.exists()}, keychain={ {k: '***' for k in keychain} }"
    )


def test_setupviadialog_passwordstringzero_isstoredasatypedpassword(
    monkeypatch, clean_stores
):
    """The classic falsy-looking-but-real value must survive the gate.

    "0" is a legal password. ``if not password`` is string truthiness, not a
    length check, so "0" is truthy and passes — but a later "tighten the
    empty check" edit that switched to a falsiness test on a parsed value
    would silently lock the user out. This pins the correct side.
    """
    config_path, keychain = clean_stores
    stub_dialog(monkeypatch, ("0", "ok"))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )

    assert result["status"] == "configured", f"got: {result}"
    assert keychain[(SERVICE, "prod")] == "0"
    assert config_path.exists()


def test_setupviadialog_unicodeandlongpassword_roundtripsunmodified(
    monkeypatch, clean_stores
):
    """Hostile but legal password content must reach the keychain unmangled.

    A password is opaque bytes to this tool; anything it normalises, trims or
    truncates on the way through produces a stored credential that differs
    from what the user typed, and the connection test would then pass on a
    value the user cannot reproduce.
    """
    _config_path, keychain = clean_stores
    password = "pä§§word-あいう-\U0001f512-" + ("x" * 4096) + "  trailing  "
    stub_dialog(monkeypatch, (password, "ok"))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="h.example.com", user="alice", dbname="analytics",
        profile="prod", port=5439,
    )

    assert result["status"] == "configured", f"got: {result}"
    assert keychain[(SERVICE, "prod")] == password, "password was modified in transit"
