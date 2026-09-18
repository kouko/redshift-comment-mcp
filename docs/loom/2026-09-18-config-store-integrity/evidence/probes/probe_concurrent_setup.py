"""Probe: concurrent setup_via_dialog calls lose whole profiles.

RE-FILED FROM 2026-09-17-setup-dialog-write-order.

    Finding:  B — ``config.write_profile`` is an unlocked read-modify-write,
              so two concurrent writers can erase one another's profile.
    Anchor:   src/redshift_comment_mcp/config.py :: write_profile
    Owner:    2026-09-17-credential-resolution-hardening
    Expected: RED until that change lands. This is correct and is the point.

Why it moved: the defect is real and reproduced below, but it lives in
``config.py`` and predates the write-order change, which only reordered the two
writes *inside* ``setup_via_dialog``. Nothing in the write-order change's
intent, acceptance lines or diff touches ``write_profile``'s serialisation or
its locking, so leaving this red in that change's evidence directory would have
pinned it to a change that cannot close it. The credential-resolution-hardening
change already owns ``config.py``'s ``delete_profile`` ordering, so the locking
question sits with the same file and the same owner.

The assertion below is carried over unchanged: not weakened, not made
conditional, not skipped.

A password dialog is open for human-length time — tens of seconds — so two
overlapping calls are not exotic: one MCP client per editor window, or an agent
that retried while the first dialog was still up.

Note on the split: the sibling case that attacks NESTED calls on the SAME
profile (``test_setupviadialog_nestedcallsonsameprofile_leaveaselfconsistentpair``)
passes at the write-order change's HEAD and stays in that change's evidence
directory. Only the genuinely-concurrent, distinct-profile case moved here.
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
)

SERVICE = "redshift-comment-mcp"


@pytest.fixture
def clean_stores(tmp_path, monkeypatch):
    config_path = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    return config_path, keychain


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
