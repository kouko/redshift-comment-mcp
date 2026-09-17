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
# HISTORY. This block used to pin the OPPOSITE claim: that keychain_write_failed
# affirmatively told the agent the fields "were saved", because write_profile
# had run a moment earlier and nothing else warned the user that config.toml had
# been repointed at the new cluster. Finding A's fix removed the thing that was
# being warned about — the branch now snapshots config.toml before write_profile
# and restores those exact bytes when set_password raises, so on the restored
# path nothing is repointed and "the fields were saved" would be FALSE.
#
# The shipped message happens to still satisfy the old matcher, via the clause
# "rolled back to exactly what was saved before this call" — "saved" there
# refers to the PREVIOUS contents, not to anything this call wrote. That is the
# letter of the old test with none of its intent, which is precisely the kind of
# accidental pass a probe must not coast on. So the claim worth pinning flipped,
# and the pair of tests below now pins the claim that matches the fix: the
# stores were left untouched, and no repointed profile is claimed.
#
# A bare substring search would accept "the stores were not left untouched", so
# the matcher requires an affirmative verb before the pinned literal and rejects
# any negation in the same clause.

NEGATIONS = ("not", "never", "no", "nothing", "without", "n't")
AFFIRMATIVE_VERBS = ("were", "was", "are", "is", "have been", "has been")


def _contains_token(text: str, token: str) -> bool:
    """Whole-word containment, so "is" does not match inside "this".

    Substring matching here would make the affirmative test almost free to
    satisfy — "before this call" alone would supply an "is" — which is how a
    matcher quietly degrades into the plain substring search it exists to
    avoid.
    """
    return f" {token} " in f" {text} "


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
        if not any(_contains_token(before, verb) for verb in AFFIRMATIVE_VERBS):
            continue
        if any(_contains_token(clause, token) for token in NEGATIONS):
            continue
        return True
    return False


def test_prosematcher_affirmativeclausebesideanegatedone_isaccepted():
    """Self-test: the shipped message shape must register as an affirmative.

    The negation lives in a later clause (" but ... was NOT stored"), and a
    clause boundary must stop it vetoing the affirmative claim in front of it.
    """
    assert claims_affirmatively(
        "Profile 'prod' was rolled back, so both stores are untouched but the "
        "password was NOT stored.",
        "untouched",
    )


def test_prosematcher_negatedclaim_isrejected():
    """Self-test: the matcher must not be a plain substring search.

    The literal is present and an affirmative verb precedes it, so only the
    in-clause negation check can reject this one.
    """
    assert not claims_affirmatively(
        "The stores were not left untouched; check config.toml.",
        "untouched",
    )


def test_prosematcher_verbhiddeninsideanotherword_doesnotcount():
    """Self-test: "is" inside "this" must not pass as an affirmative verb.

    Without whole-word matching this sentence asserts nothing yet registers as
    a claim, which would let the pins above pass on prose that never makes the
    claim they exist to pin.
    """
    assert not claims_affirmatively(
        "Before this call the fields untouched.",
        "untouched",
    )


def test_setupviadialog_keychainwritefailsandrollbacksucceeds_saysstoresareuntouched(
    monkeypatch, working_profile
):
    """The message must match what the rollback actually achieved.

    This replaces an assertion that finding A's fix made obsolete. That
    assertion demanded the message affirmatively claim the fields "were saved",
    because before the fix write_profile had already repointed config.toml at
    the new cluster and nothing else warned the user. The fix restores the
    snapshotted bytes on this branch, so nothing is repointed and that claim
    would now be false — the shipped message satisfies the old matcher only by
    accident, through "rolled back to exactly what was saved before this call",
    where "saved" describes the PREVIOUS contents.

    What is true and worth pinning instead: when the rollback succeeds, the
    message tells the agent both stores were left untouched, and it does not
    claim a repointed profile. An agent that read a repointing claim here would
    send the user to clean up a config.toml that is already correct.
    """
    config_path, keychain = working_profile
    before_bytes = config_path.read_bytes()
    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))

    def refuse(name, pw):
        raise RuntimeError("keychain is locked")

    monkeypatch.setattr("redshift_comment_mcp.config.set_password", refuse)

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host=NEW_HOST, user="newuser", dbname="newdb", profile="prod", port=5440
    )
    assert result["error"] == "keychain_write_failed", f"got: {result}"

    # Ground the prose in the state it describes: the claim is only worth
    # pinning if it is true, so assert the stores first.
    assert config_path.read_bytes() == before_bytes, "config.toml was not restored"
    assert keychain[("redshift-comment-mcp", "prod")] == OLD_PASSWORD

    message = result["message"]
    assert claims_affirmatively(message, "untouched"), (
        "the rollback succeeded, but keychain_write_failed does not tell the "
        "agent the stores were left untouched — so the agent cannot "
        f"distinguish this from the un-rolled-back branch. Message: {message!r}"
    )
    # The mirror of the claim above: no affirmative statement that the fields
    # landed in config.toml, because on this branch they did not survive.
    for stale_claim in ("repointed", "point at the new cluster"):
        assert not claims_affirmatively(message, stale_claim), (
            f"keychain_write_failed claims {stale_claim!r} on a branch whose "
            f"rollback succeeded. Message: {message!r}"
        )


def test_setupviadialog_keychainwritefailsandrollbackfails_warnsinsteadofclaimingclean(
    monkeypatch, working_profile
):
    """The paired direction, so a hard-coded "untouched" is caught too.

    ``_restore_config_bytes`` is guarded and returns False when the restore
    itself fails (read-only filesystem, vanished directory). On that branch the
    fields really are left pointing at the new cluster while the keychain holds
    the previous password, and the message must say so rather than inherit the
    reassurance from its sibling branch.
    """
    config_path, _keychain = working_profile
    stub_dialog(monkeypatch, ("a-brand-new-password", "ok"))

    def refuse(name, pw):
        raise RuntimeError("keychain is locked")

    monkeypatch.setattr("redshift_comment_mcp.config.set_password", refuse)

    snapshot = config_path.read_bytes()
    real_write_bytes = Path.write_bytes

    def fail_the_restore(self, data):
        """Fail only the restoring write, so write_profile still lands."""
        if str(self) == str(config_path) and data == snapshot:
            raise OSError("read-only file system")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_the_restore)

    setup_via_dialog = get_tool_fn(make_tools(), "setup_via_dialog")
    result = setup_via_dialog(
        host=NEW_HOST, user="newuser", dbname="newdb", profile="prod", port=5440
    )
    assert result["error"] == "keychain_write_failed", f"got: {result}"

    from redshift_comment_mcp import config as cfg

    assert cfg.read_profile("prod")["host"] == NEW_HOST, (
        "the restore was supposed to have failed — this probe is no longer "
        "exercising the un-rolled-back branch"
    )

    message = result["message"]
    assert not claims_affirmatively(message, "untouched"), (
        "the rollback FAILED, but keychain_write_failed still tells the agent "
        f"the stores are untouched. config.toml now points at {NEW_HOST!r} "
        f"while the keychain holds the previous password. Message: {message!r}"
    )
    # Absence-of-negation machinery does not apply here: this phrase carries
    # its own negation, and its presence is the warning being pinned.
    assert "not be rolled back" in message.lower(), (
        "the un-rolled-back branch no longer warns that config.toml was left "
        f"repointed. Message: {message!r}"
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
