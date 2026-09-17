"""Probe: a whitespace-only password is accepted as a real password.

RE-FILED FROM 2026-09-17-setup-dialog-write-order.

    Finding:  E — the gate is ``if not password``, which is string
              truthiness, so " ", "\\t", "\\n" and "   \\t  " all sail past it
              and get persisted as a real credential.
    Anchor:   src/redshift_comment_mcp/redshift_tools.py :: setup_via_dialog,
              the ``if not password:`` gate before the two store writes
    Owner:    2026-09-17-credential-resolution-hardening
    Expected: RED (4 parametrised cases) until that change lands. This is
              correct and is the point.

Why it moved: blank-password semantics are a decided, named part of the
credential-resolution-hardening change, which owns the blank-password gate. The
write-order change's intent puts "the password-collection mechanism itself" out
of scope, and the defect predates it — the gate's truthiness test is unchanged
by the reordering; only its position in the function moved. Asserting the
stricter semantics against the write-order change would have demanded a
behaviour its intent explicitly declined.

The assertion below is carried over unchanged: not weakened, not made
conditional, not skipped.

Note on the split: the three sibling cases in the original file — the two falsy
values (``""``, ``None``) reaching ``empty_password`` and writing neither store,
the ``"0"`` password surviving the gate, and the unicode/long password round
trip — all pass at the write-order change's HEAD and stay in that change's
evidence directory. Only the whitespace case moved here.
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
