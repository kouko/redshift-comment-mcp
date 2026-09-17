"""Probe: is the failure path byte-identical, or only semantically equal?

The change's first acceptance line says config.toml is *byte-identical* after
a failed password step. The repository pin for that line builds its fixture
with ``config.write_profile``, so the file it compares is already in
``tomli_w`` canonical form — comments, key order, CRLF and non-ASCII values
have all been normalised away before the snapshot is taken. A file that is
merely re-serialised would still pass it.

This probe supplies a config.toml that no serialiser would reproduce:
hand-written comments, an unusual key order, several profiles, a non-ASCII
value, a CRLF line ending and a trailing blank line. Any rewrite at all shows
up as a byte difference.

A companion case once turned the same hostile file on the SUCCESS path, where a
rewrite does happen, to record what the user loses from the profiles they did
not ask to touch. It is red, and it is red for ``write_profile``'s
serialisation, which this change does not touch, so it was re-filed unchanged to
docs/loom/2026-09-17-credential-resolution-hardening/evidence/probes/probe_config_toml_byte_identity.py
as finding F. It stays red there until that change lands.
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
    stub_dialog,
)

# Hand-written, deliberately un-canonical. Note: comments, blank lines, a
# profile whose keys are not in write_profile's order, a non-ASCII dbname, one
# CRLF line, and an extra key (sslmode) that the tool's schema knows nothing
# about.
HOSTILE_CONFIG = (
    "# redshift-comment-mcp — hand-edited, do not reformat\r\n"
    "\n"
    "[profile.prod]\n"
    "dbname = \"分析データ\"\n"
    "user = \"アリス\"\n"
    "host = \"old-cluster.example.com\"  # VPN required\n"
    "port = 5439\n"
    "sslmode = \"require\"\n"
    "\n"
    "# the staging cluster, paused most of the week\n"
    "[profile.staging]\n"
    "host = \"staging.example.com\"\n"
    "port = 5439\n"
    "user = \"bob\"\n"
    "dbname = \"staging_db\"\n"
    "\n"
)

FAILURE_CASES = [
    ((None, "cancelled"), "dialog_cancelled"),
    ((None, "permission_denied"), "permission_denied"),
    ((None, "unavailable"), "dialog_unavailable"),
    ((None, "unsupported"), "platform_unsupported"),
    (("", "ok"), "empty_password"),
]


@pytest.fixture
def hostile_config(tmp_path, monkeypatch):
    """Write HOSTILE_CONFIG verbatim to the isolated config path.

    Yields ``(config_path, keychain)``.
    """
    config_path = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(HOSTILE_CONFIG.encode("utf-8"))

    from redshift_comment_mcp import config as cfg

    cfg.set_password("prod", "the-still-valid-old-password")
    return config_path, keychain


@pytest.mark.parametrize(
    "dialog_return,expected_status",
    FAILURE_CASES,
    ids=[status for _, status in FAILURE_CASES],
)
def test_setupviadialog_passwordstepfails_leaveshandwrittentomlbyteidentical(
    monkeypatch, hostile_config, dialog_return, expected_status
):
    """No password, no rewrite — not even a re-serialisation of the same data."""
    config_path, keychain = hostile_config
    before = config_path.read_bytes()
    keychain_before = dict(keychain)

    stub_dialog(monkeypatch, dialog_return)
    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")

    result = setup_via_dialog(
        host="new.example.com", user="newuser", dbname="newdb",
        profile="prod", port=5440,
    )

    assert result["status"] == expected_status, f"got: {result}"
    after = config_path.read_bytes()
    assert after == before, (
        f"{expected_status}: config.toml was rewritten. "
        f"before={before!r} after={after!r}"
    )
    assert keychain == keychain_before


def test_setupviadialog_passwordstepfails_leaveshandwrittentomlmodeunchanged(
    monkeypatch, hostile_config
):
    """The file's permission bits are part of "exactly as it was".

    ``write_profile`` chmods to 0600 unconditionally. A user who deliberately
    widened or narrowed the mode must not see it silently reset by a call that
    wrote nothing.
    """
    config_path, _keychain = hostile_config
    config_path.chmod(0o640)
    before_mode = config_path.stat().st_mode

    stub_dialog(monkeypatch, (None, "cancelled"))
    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host="new.example.com", user="newuser", dbname="newdb",
        profile="prod", port=5440,
    )

    assert result["status"] == "dialog_cancelled"
    assert config_path.stat().st_mode == before_mode
