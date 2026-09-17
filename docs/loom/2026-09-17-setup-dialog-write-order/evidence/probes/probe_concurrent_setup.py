"""Probe: two setup_via_dialog calls in flight at once.

A password dialog is open for human-length time — tens of seconds — so two
overlapping calls are not exotic: one MCP client per editor window, or an
agent that retried while the first dialog was still up. The dialog now sits
BEFORE both writes, which changes which interleavings are reachable, so the
old reasoning about this does not carry over.

Two attacks:

  1. Same profile, nested calls. Call A's dialog is still open while call B
     runs to completion. Whichever call lands last must leave a SELF-CONSISTENT
     pair — its own host together with its own password. A mixed pair is the
     audited failure mode reached by a different route.

  2. Distinct profiles, genuinely concurrent threads. ``config.write_profile`` is a
     read-modify-write over the whole file with no lock, so two writers can
     lose one another's profile entirely.
"""
from __future__ import annotations

import sys
import threading
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
    return config_path, keychain


def test_setupviadialog_nestedcallsonsameprofile_leaveaselfconsistentpair(
    monkeypatch, clean_stores
):
    """Call B completes entirely inside call A's open dialog.

    The loser of the race must lose BOTH of its writes, not just one. If the
    fields came from one call and the password from the other, the profile
    authenticates one cluster's password against another cluster's host —
    the same end state the audit's F1 describes.
    """
    _config_path, keychain = clean_stores
    stub_connection(monkeypatch, (True, None))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    inner_result = {}

    def dialog_for_a(profile):
        """A's dialog is open; B arrives, finishes, and returns."""
        monkeypatch.setattr(
            "redshift_comment_mcp.setup_cli._collect_password_via_dialog",
            lambda p: ("password-B", "ok"),
        )
        inner_result["b"] = setup_via_dialog(
            host="host-B.example.com", user="user-B", dbname="db-B",
            profile="shared", port=5439,
        )
        return "password-A", "ok"

    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli._collect_password_via_dialog", dialog_for_a
    )

    result_a = setup_via_dialog(
        host="host-A.example.com", user="user-A", dbname="db-A",
        profile="shared", port=5439,
    )

    assert inner_result["b"]["status"] == "configured"
    assert result_a["status"] == "configured"

    from redshift_comment_mcp import config as cfg

    fields = cfg.read_profile("shared")
    password = keychain[(SERVICE, "shared")]

    consistent = {
        ("host-A.example.com", "password-A"),
        ("host-B.example.com", "password-B"),
    }
    assert (fields["host"], password) in consistent, (
        "interleaved setup left a mismatched credential pair: config.toml "
        f"points at {fields['host']!r} while the keychain holds "
        f"{password!r} — one call's host with the other call's password"
    )


def test_setupviadialog_concurrentdistinctprofiles_keepseveryprofilewritten(
    monkeypatch, clean_stores
):
    """Eight threads, eight profile names, one unlocked read-modify-write.

    ``config.write_profile`` reads every profile, mutates the dict and dumps
    the whole file. Nothing serialises those three steps, so a thread that
    reads before another thread's dump and writes after it erases that
    profile. Every name asked for must be present afterwards.
    """
    _config_path, keychain = clean_stores
    stub_connection(monkeypatch, (True, None))

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    names = [f"profile{i}" for i in range(8)]
    barrier = threading.Barrier(len(names))
    errors: list[BaseException] = []

    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli._collect_password_via_dialog",
        lambda profile: (f"pw-{profile}", "ok"),
    )

    def run(name: str) -> None:
        try:
            barrier.wait(timeout=10)
            setup_via_dialog(
                host=f"{name}.example.com", user=name, dbname=name,
                profile=name, port=5439,
            )
        except BaseException as exc:  # noqa: BLE001 — recorded, re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"a concurrent call raised: {errors}"

    from redshift_comment_mcp import config as cfg

    written = set(cfg.list_profiles())
    missing = set(names) - written
    assert not missing, (
        f"{len(missing)} of {len(names)} profiles were lost to the unlocked "
        f"read-modify-write in config.write_profile: {sorted(missing)}. "
        f"Survivors: {sorted(written)}"
    )
    # The keychain is keyed per profile, so it never loses an entry — which is
    # exactly how a lost profile becomes a password with no fields behind it.
    assert {n for _s, n in keychain} == set(names)
