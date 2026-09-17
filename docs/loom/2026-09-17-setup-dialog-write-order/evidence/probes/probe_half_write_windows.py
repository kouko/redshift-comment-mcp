"""Probe: is there still a window where setup_via_dialog half-writes a profile?

The change claims: a ``setup_via_dialog`` call that does not reach a stored
password leaves the profile store exactly as it was before the call. Moving
``write_profile`` behind the dialog closes that window for the five
password-step failures. This probe attacks the two steps that still run
AFTER a password is in hand:

  1. ``config.set_password`` raises (locked keychain, refused backend). The
     fields for the NEW host are already on disk; the keychain still holds
     the PREVIOUS profile's still-valid password.
  2. The connection test fails after both writes landed, destroying a
     previously working profile with no way back.

Both are attacked against real persistence, and both ask ``get_setup_status``
what it reports afterwards — the audit's F1 finding is not "config.toml was
written", it is "get_setup_status says configured for a credential pair that
never existed together".
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

OLD_HOST = "old-cluster.example.com"
OLD_PASSWORD = "the-still-valid-old-password"
NEW_HOST = "attacker-supplied.example.com"


@pytest.fixture
def working_profile(tmp_path, monkeypatch):
    """A complete, working profile named 'prod': fields on disk, password stored.

    Yields ``(config_path, keychain)``.
    """
    config_path = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)

    from redshift_comment_mcp import config as cfg

    cfg.write_profile("prod", host=OLD_HOST, port=5439, user="olduser", dbname="olddb")
    cfg.set_password("prod", OLD_PASSWORD)
    return config_path, keychain


def test_setupviadialog_keychainwritefails_leavesnewhostpairedwitholdpassword(
    monkeypatch, working_profile
):
    """A keychain failure still leaves the audited half-written state behind.

    The password step succeeded (the dialog returned a value), so the new
    ordering does not cover this path: write_profile has already replaced the
    profile dict with the caller-supplied host when set_password raises. What
    remains on disk is the new host plus the old password — precisely the
    pairing the change says it eliminates.
    """
    config_path, keychain = working_profile

    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))

    def refuse(name, pw):
        raise RuntimeError("keychain is locked")

    monkeypatch.setattr("redshift_comment_mcp.config.set_password", refuse)

    tools = make_tools()
    setup_via_dialog = get_tool_fn(tools, "setup_via_dialog")
    get_setup_status = get_tool_fn(tools, "get_setup_status")

    result = setup_via_dialog(
        host=NEW_HOST, user="newuser", dbname="newdb", profile="prod", port=5440
    )
    assert result["error"] == "keychain_write_failed", f"got: {result}"

    from redshift_comment_mcp import config as cfg

    stored_fields = cfg.read_profile("prod")
    stored_password = keychain.get(("redshift-comment-mcp", "prod"))
    status = get_setup_status(profile="prod")

    # The attack succeeded if the stores disagree about which cluster this
    # profile belongs to while status still claims the profile is usable.
    assert not (
        stored_fields["host"] == NEW_HOST
        and stored_password == OLD_PASSWORD
        and status["configured"] is True
    ), (
        "HALF-WRITE SURVIVES: config.toml now points at "
        f"{stored_fields['host']!r} while the keychain still holds the "
        f"password for {OLD_HOST!r}, and get_setup_status reports "
        f"configured={status['configured']} host={status['host']!r}. "
        "The next DB tool call sends the old cluster's password to the new "
        f"host. Full status: {status}"
    )


# --- prose matcher for the one message claim this probe pins -----------------
#
# Four failure messages were rewritten in this change to promise "Nothing was
# written". The keychain branch must NOT inherit that promise, because
# write_profile ran a moment earlier — so the claim worth pinning is the
# affirmative one: the fields WERE saved. A bare substring search would accept
# "the fields were not saved", so the matcher below requires an affirmative
# verb before the pinned literal and rejects any negation in the same clause.

NEGATIONS = ("not", "never", "no", "nothing", "without", "n't")
AFFIRMATIVE_VERBS = ("were", "was", "have been", "has been")


def _clauses(text: str) -> list[str]:
    """Split prose into clauses: sentence enders first, then contrastive joins.

    "A were saved but B was NOT stored." must not let B's negation veto A's
    claim, so " but " is a boundary just like ".".
    """
    parts = [text]
    for separator in (".", ";", ":", " but ", " although ", " however "):
        nxt: list[str] = []
        for part in parts:
            nxt.extend(part.split(separator))
        parts = nxt
    return [p.strip() for p in parts if p.strip()]


def claims_affirmatively(text: str, literal: str) -> bool:
    """True when some clause asserts ``literal`` without negating it."""
    lowered_literal = literal.lower()
    for clause in _clauses(text.lower()):
        where = clause.find(lowered_literal)
        if where == -1:
            continue
        before = clause[:where]
        if not any(verb in before for verb in AFFIRMATIVE_VERBS):
            continue
        if any(f" {token} " in f" {clause} " for token in NEGATIONS):
            continue
        return True
    return False


def test_prosematcher_affirmativeclausebesideanegatedone_isaccepted():
    """Self-test: the shipped message shape must register as an affirmative."""
    assert claims_affirmatively(
        "Profile 'prod' fields were saved to config.toml but the password "
        "was NOT stored.",
        "saved",
    )


def test_prosematcher_negatedclaim_isrejected():
    """Self-test: the matcher must not be a plain substring search."""
    assert not claims_affirmatively(
        "Nothing was written: profile 'prod' fields were not saved to "
        "config.toml.",
        "saved",
    )


def test_setupviadialog_keychainwritefails_stillclaimsthefieldsweresaved(
    monkeypatch, working_profile
):
    """The keychain message must stay honest about the write that did land.

    Its four siblings now promise the stores are untouched. If a later copy
    edit gives this one the same sentence, the agent stops warning the user
    that config.toml was already repointed at the new cluster — the half-write
    becomes silent as well as real.
    """
    _config_path, _keychain = working_profile
    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))

    def refuse(name, pw):
        raise RuntimeError("keychain is locked")

    monkeypatch.setattr("redshift_comment_mcp.config.set_password", refuse)

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host=NEW_HOST, user="newuser", dbname="newdb", profile="prod", port=5440
    )

    message = result["message"]
    assert claims_affirmatively(message, "saved"), (
        "keychain_write_failed no longer tells the agent the fields were "
        f"saved, so nothing warns the user that config.toml was repointed. "
        f"Message: {message!r}"
    )
    # Absence check, so no affirmative-verb machinery applies: the phrase
    # itself carries the negation, and any occurrence of it is the defect.
    assert "nothing was written" not in message.lower(), (
        "keychain_write_failed inherited the 'nothing was written' promise, "
        f"which is false on this branch. Message: {message!r}"
    )


def test_setupviadialog_connectiontestfails_destroysthepreviousworkingprofile(
    monkeypatch, working_profile
):
    """A failed connection test leaves the old working profile unrecoverable.

    Both writes landed before the test ran, so a typo'd host costs the user
    their working configuration: the old host, user, dbname and password are
    all gone, with nothing in the response carrying what was overwritten.
    This is not covered by the change's claim (a password WAS stored), so the
    probe asserts what actually survives rather than demanding a rollback.
    """
    _config_path, keychain = working_profile
    stub_dialog(monkeypatch, ("typed-for-the-wrong-host", "ok"))
    stub_connection(monkeypatch, (False, "Connection timed out (host unreachable)"))

    tools = make_tools()
    setup_via_dialog = get_tool_fn(tools, "setup_via_dialog")
    get_setup_status = get_tool_fn(tools, "get_setup_status")

    result = setup_via_dialog(
        host=NEW_HOST, user="newuser", dbname="newdb", profile="prod", port=5440
    )
    assert result["status"] == "configured_but_connection_failed", f"got: {result}"

    from redshift_comment_mcp import config as cfg

    assert cfg.read_profile("prod")["host"] == NEW_HOST
    assert keychain[("redshift-comment-mcp", "prod")] == "typed-for-the-wrong-host"

    # Documented, accepted behaviour ("it will overwrite"). The attack line is
    # whether get_setup_status then tells the truth about a profile that has
    # just been proven not to connect.
    status = get_setup_status(profile="prod")
    assert status["configured"] is True
    assert status["host"] == NEW_HOST
    # No field distinguishes "verified" from "written but proven broken".
    assert "tested" not in status and "last_connection_error" not in status, (
        "get_setup_status grew a verification field — update this probe"
    )


def test_setupviadialog_writeprofilefails_storesnopasswordforafieldlessprofile(
    monkeypatch, tmp_path
):
    """The new ordering must not create the mirror-image half-write.

    With the dialog first, a password now exists in scope while write_profile
    runs. If the failure branch fell through instead of returning, the
    keychain would end up holding a password for a profile that has no fields
    at all — a state the pre-change code could not reach.
    """
    isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    stub_dialog(monkeypatch, ("password-typed-for-nothing", "ok"))

    def refuse(name, **kw):
        raise PermissionError("config directory not writable")

    monkeypatch.setattr("redshift_comment_mcp.config.write_profile", refuse)

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host=NEW_HOST, user="newuser", dbname="newdb", profile="fresh", port=5439
    )

    assert result["error"] == "write_profile_failed", f"got: {result}"
    assert keychain == {}, (
        f"a password was stored for a profile with no fields: {list(keychain)}"
    )
