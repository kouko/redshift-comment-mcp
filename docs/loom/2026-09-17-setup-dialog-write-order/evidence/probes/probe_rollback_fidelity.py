"""Probe: how faithful is the config.toml rollback that finding A's fix added?

This is a fresh attack on the FIX, not a re-run of the probe that found the
original defect. Finding A's fix added ``_snapshot_config_bytes`` /
``_restore_config_bytes`` (src/redshift_comment_mcp/redshift_tools.py:190-225)
and calls them around ``cfg.write_profile`` in ``setup_via_dialog``. New code on
the security-critical path earns its own boundary sweep, and the old probes
cannot supply one: they were written against a function that had no rollback at
all, so passing them proves only that the fix is reachable, not that it is
faithful.

"Faithful" is taken from the message the fix itself emits — "rolled back to
exactly what was saved before this call, so both stores are untouched" — and
from acceptance line 1's word, *byte-identical*. The sweep walks the states the
snapshot/restore pair has to survive:

  - a hand-written config.toml that no serialiser would reproduce  (PASSES)
  - no config.toml at all, so the restore means "delete it again"  (PASSES)
  - a config.toml whose permission bits the user chose            (FAILS — G)
  - a config.toml that cannot be read when the snapshot is taken   (FAILS — H)

plus the log-hygiene half of finding C, re-attacked with an exception that
carries a marker of its own rather than the password, because C's fix was to
stop logging ``str(e)`` and the old probe only ever searched for the password.

    TWO CASES ARE RED, AGAINST FINDINGS RAISED BY THIS SAME PASS:

      G — ``_restore_config_bytes`` restores the file's BYTES but not its MODE.
          ``config.write_profile`` chmods config.toml to 0600 unconditionally,
          so a rollback over a file the user had left at 0640 silently leaves it
          at 0600, and the message's "both stores are untouched" is false in
          that detail. Narrowing, never widening, so this is a truthfulness gap
          rather than an exposure. Anchor: redshift_tools.py :: _restore_config_bytes
      H — ``_snapshot_config_bytes`` catches only ``FileNotFoundError``, and its
          call site at redshift_tools.py:1427 sits outside every ``try``. Any
          other OSError — an unreadable config.toml, a directory where the file
          should be — escapes ``setup_via_dialog`` uncaught. Anchor:
          redshift_tools.py :: _snapshot_config_bytes and its call site

    Both are defects in code this change introduced, so unlike findings B, E
    and F they are NOT re-filed to a follow-up change. They stay here for Build.
"""
from __future__ import annotations

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
    stub_dialog,
)

SERVICE = "redshift-comment-mcp"
OLD_PASSWORD = "the-still-valid-old-password"
NEW_HOST = "attacker-supplied.example.com"

# Hand-written and deliberately un-canonical, so that a rollback which
# re-serialises rather than restoring raw bytes shows up as a byte difference:
# comments, a key order write_profile would not emit, a non-ASCII value, one
# CRLF line, and a key the tool's schema knows nothing about.
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
)


@pytest.fixture
def hostile_config(tmp_path, monkeypatch):
    """A hand-written config.toml plus a stored password for 'prod'.

    Yields ``(config_path, keychain)``.
    """
    config_path = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(HOSTILE_CONFIG.encode("utf-8"))

    from redshift_comment_mcp import config as cfg

    cfg.set_password("prod", OLD_PASSWORD)
    return config_path, keychain


def _refuse_keychain(monkeypatch, exc: BaseException | None = None) -> None:
    """Make ``config.set_password`` raise, which is what arms the rollback."""

    def refuse(name, pw):
        raise exc or RuntimeError("keychain is locked")

    monkeypatch.setattr("redshift_comment_mcp.config.set_password", refuse)


def _call(**overrides):
    call = dict(host=NEW_HOST, user="newuser", dbname="newdb",
                profile="prod", port=5440)
    call.update(overrides)
    return get_tool_fn(make_tools(), "setup_via_dialog")(**call)


# --- the rollback's happy paths, which the fix does get right ----------------


def test_restoreconfigbytes_handwrittentoml_comesbackbyteidentical(
    monkeypatch, hostile_config
):
    """A rollback over un-canonical TOML must restore bytes, not re-serialise.

    Restoring through ``write_profile`` would round-trip the document and drop
    the comments, the key order and the unknown ``sslmode`` key — the file would
    parse the same and fail acceptance line 1's word, *byte-identical*. This is
    the case that justifies the raw-bytes design, so it is worth pinning
    explicitly rather than inferring from the fix's docstring.
    """
    config_path, keychain = hostile_config
    before = config_path.read_bytes()

    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))
    _refuse_keychain(monkeypatch)

    result = _call()
    assert result["error"] == "keychain_write_failed", f"got: {result}"
    assert config_path.read_bytes() == before, (
        "config.toml was not restored byte-for-byte after the keychain write "
        f"failed. before={before!r} after={config_path.read_bytes()!r}"
    )
    assert keychain[(SERVICE, "prod")] == OLD_PASSWORD, (
        "the rollback disturbed the keychain entry it exists to protect"
    )


def test_restoreconfigbytes_noconfigexistedbefore_leavesnofilebehind(
    monkeypatch, tmp_path
):
    """"Absent" is a state the rollback has to restore too.

    ``write_profile`` creates config.toml on a first-ever setup. If the keychain
    then refuses, "exactly as it was before the call" means the file is gone
    again — a leftover file would advertise a profile whose password was never
    stored, which is the audited failure mode with the stores swapped.
    """
    config_path = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    assert not config_path.exists()

    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))
    _refuse_keychain(monkeypatch)

    result = _call(profile="fresh")
    assert result["error"] == "keychain_write_failed", f"got: {result}"
    assert not config_path.exists(), (
        "config.toml survived a rollback that should have removed it: "
        f"{config_path.read_text()!r}"
    )
    assert keychain == {}


def test_setpasswordfailure_exceptiontext_neverreachesthelog(
    monkeypatch, hostile_config, caplog
):
    """Finding C, re-attacked with a marker the old probe could not have found.

    C's fix dropped ``exc_info=True`` AND ``str(e)`` from this branch. The
    existing secret-leakage probe only ever searched the log for the PASSWORD,
    so it would still pass if ``str(e)`` came back — a keychain backend's
    exception text is third-party and can carry paths or environment values
    quite apart from the password. This plants a marker in the exception itself.
    """
    caplog.set_level(logging.DEBUG)
    marker = "MARKER-/Users/private/.aws/credentials-MARKER"

    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))
    _refuse_keychain(monkeypatch, RuntimeError(marker))

    result = _call()
    assert result["error"] == "keychain_write_failed", f"got: {result}"

    emitted = "\n".join(
        record.getMessage() + (record.exc_text or "") for record in caplog.records
    )
    assert marker not in emitted, (
        f"the keychain exception's text reached the log: {emitted}"
    )
    assert marker not in str(result), "the exception's text reached the response"
    assert all(record.exc_info is None for record in caplog.records), (
        "a log record still carries exc_info, so a frame-locals-rendering "
        "handler would print the password that is live in this frame"
    )


# --- finding G ---------------------------------------------------------------


def test_restoreconfigbytes_userchosenfilemode_survivestherollback(
    monkeypatch, hostile_config
):
    """RED (finding G). The rollback restores bytes but not permission bits.

    ``config.write_profile`` chmods config.toml to 0600 unconditionally, and
    ``_restore_config_bytes`` only writes bytes back — so a file the user had
    deliberately left at 0640 comes out of a failed call at 0600. The sibling
    probe probe_config_toml_byte_identity.py already holds this exact standard
    for the five password-step failures, where no write happens at all; this
    asserts the same standard on the path where a write happened and was undone,
    because that path is the one whose message promises "both stores are
    untouched".

    Direction matters for severity: 0600 is narrower than 0640, so this costs
    the user a setting rather than exposing anything.
    """
    config_path, _keychain = hostile_config
    config_path.chmod(0o640)
    before_mode = config_path.stat().st_mode

    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))
    _refuse_keychain(monkeypatch)

    result = _call()
    assert result["error"] == "keychain_write_failed", f"got: {result}"
    after_mode = config_path.stat().st_mode
    assert after_mode == before_mode, (
        f"the rollback changed config.toml's mode from {oct(before_mode)} to "
        f"{oct(after_mode)}, while the response claims both stores are "
        f"untouched. Message: {result['message']!r}"
    )


# --- finding H ---------------------------------------------------------------


def test_snapshotconfigbytes_unreadableconfig_returnsashapeinsteadofraising(
    monkeypatch, hostile_config
):
    """RED (finding H). An unreadable config.toml escapes the tool entirely.

    ``_snapshot_config_bytes`` catches ``FileNotFoundError`` and nothing else,
    and its call site sits outside every ``try`` in ``setup_via_dialog``. A
    config.toml that exists but cannot be read — mode 000, a root-owned file
    left by a sudo install, a directory where the file should be — therefore
    raises straight out of the tool.

    Three consequences, in ascending order of seriousness. The client gets a
    raw exception rather than one of the seven documented response shapes, which
    the intent's constraints require. The user has already typed a password into
    the dialog by this point, so it is wasted. And the escaping frame is the one
    holding the live ``password`` local — the exact frame-locals exposure the
    branches ten lines below deliberately drop ``exc_info=True`` to avoid, now
    reachable through an exception nobody catches at all.

    The probe asserts only that the tool returns one of its documented shapes;
    it does not prescribe which, because that is the implementer's call.
    """
    config_path, _keychain = hostile_config
    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))

    real_read_bytes = Path.read_bytes

    def unreadable(self):
        if str(self) == str(config_path):
            raise PermissionError(13, "Permission denied", str(config_path))
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    try:
        result = _call()
    except Exception as exc:  # noqa: BLE001 — the defect is that this fires
        pytest.fail(
            f"setup_via_dialog raised {type(exc).__name__}({exc}) instead of "
            f"returning a documented response shape. The password the user "
            f"just typed is a live local of the frame this exception escaped."
        )

    assert {"status", "error"} & set(result), (
        f"response carries neither discriminator key: {result}"
    )
