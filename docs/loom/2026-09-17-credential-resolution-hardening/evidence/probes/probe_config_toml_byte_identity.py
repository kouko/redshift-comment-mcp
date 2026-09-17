"""Probe: the SUCCESS path rewrites config.toml through a TOML round trip.

RE-FILED FROM 2026-09-17-setup-dialog-write-order.

    Finding:  F — a successful call to configure one profile re-serialises the
              whole file, destroying hand-written comments and keys the tool's
              schema does not know about, in profiles the caller never named.
    Anchor:   src/redshift_comment_mcp/config.py :: write_profile
              (the ``tomli_w`` dump of the whole parsed document)
    Owner:    2026-09-17-credential-resolution-hardening
    Expected: RED until that change lands. This is correct and is the point.

Why it moved: the defect is real and reproduced below, but ``write_profile``'s
serialisation is untouched by the write-order change, which only reordered when
``write_profile`` is called relative to the password dialog. The write-order
change's first acceptance line is about the FAILURE path being byte-identical,
and that half is genuinely closed — the six sibling cases that pin it stay in
that change's evidence directory and pass. This case attacks the success path,
where a rewrite is expected to happen and the question is only what it
destroys; that is a serialisation question, and it belongs with the change that
owns ``config.py``.

The assertion below is carried over unchanged: not weakened, not made
conditional, not skipped.

Note on the split: the original file held 7 cases. The 5 password-step failure
reasons (byte identity) plus the file-mode case pass at the write-order change's
HEAD and stay there. Only this success-path case moved here.
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


def test_setupviadialog_succeeds_preservesuntouchedprofilesverbatim(
    monkeypatch, hostile_config
):
    """Collateral damage on the success path: what happens to 'staging'?

    The caller asked to configure 'prod'. Everything belonging to any other
    profile — and every byte the user hand-wrote — should survive a call that
    names a different profile.
    """
    config_path, _keychain = hostile_config
    before_text = config_path.read_text(encoding="utf-8")

    stub_dialog(monkeypatch, ("brand-new-password", "ok"))
    stub_connection(monkeypatch, (True, None))
    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")

    result = setup_via_dialog(
        host="new.example.com", user="newuser", dbname="newdb",
        profile="prod", port=5440,
    )
    assert result["status"] == "configured", f"got: {result}"

    after_text = config_path.read_text(encoding="utf-8")

    # The values of the untouched profile must still be readable.
    from redshift_comment_mcp import config as cfg

    assert cfg.read_profile("staging") == {
        "host": "staging.example.com", "port": 5439,
        "user": "bob", "dbname": "staging_db",
    }

    lost = [
        label for label, fragment in [
            ("the staging cluster comment", "# the staging cluster"),
            ("the file header comment", "do not reformat"),
            ("prod's extra sslmode key", "sslmode"),
        ]
        if fragment in before_text and fragment not in after_text
    ]
    assert not lost, (
        "a successful call to configure 'prod' silently destroyed content it "
        f"was not asked to touch: {lost}. after={after_text!r}"
    )
