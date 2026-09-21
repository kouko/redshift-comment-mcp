"""Probe: how far does a borrowed keychain password travel?

W0-01 lets a launch that supplies host/user/dbname and no password borrow the
keychain password of a stored profile whose ``(host, user, dbname)`` all equal
the supplied values. The connection then targets the launch values.

The attack surface is the gap between "the target the password was provisioned
for" and "the target the password is now sent to". Three of the four target
fields are pinned by the match. The fourth — ``port`` — is not, and the
connection uses the launch port. So the question this file makes executable is:
can a password provisioned for one listener be delivered to a different
listener?

The probes below are written from the attacker's side of that gap, plus two
near-misses that check the match is not sloppier than advertised.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_support import isolate_store, ns  # noqa: E402

from redshift_comment_mcp import config, server  # noqa: E402


def test_borrow_portmismatch_refuses(tmp_path, monkeypatch):
    """A password provisioned for one port must not be sent to another.

    The stored profile records the whole target the operator provisioned:
    ``redshift.internal:5439``. This launch names the same host, user and
    dbname but port 9999. The identity match ignores ``port``, so the
    keychain password is lent and the connection carries it to a listener the
    password was never provisioned for.

    Why that is a scoping defect and not merely an unusual launch: the launch
    fields are not all operator-authored at runtime. On the plugin path they
    come from the Claude Code install options, a file writable by any process
    running as the same user. Such a process generally cannot read the
    keychain item (macOS scopes the item's ACL to the creating application)
    but it can (a) rewrite the stored ``port`` option and (b) bind the new
    port. The host is protected from exactly this rewrite by the match; the
    port is not. A profile recorded against ``localhost``/``127.0.0.1`` — the
    ordinary shape when Redshift is reached through an SSH tunnel or bastion
    — makes step (b) a plain unprivileged ``bind()``.

    Expected: no borrow across a port the profile was not provisioned for.
    """
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", "provisioned-for-5439")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse", port=9999)
    decision = server.resolve_connection_decision(args)

    assert decision.password != "provisioned-for-5439", (
        f"A keychain password provisioned for redshift.internal:5439 was lent to "
        f"a launch naming port {decision.port}. mechanism={decision.mechanism!r}, "
        f"borrowed_from={decision.profile_name!r}. The identity match covers "
        f"(host, user, dbname) only, so the one target field an attacker who can "
        f"write the plugin's stored options may still change without breaking the "
        f"match is the one that selects which listener receives the secret."
    )


def test_borrow_portmatch_lends(tmp_path, monkeypatch):
    """Control for the probe above: the in-scope case must keep working.

    Same profile, launch naming the port it was provisioned for. Closing the
    port gap must not cost the acceptance-1 happy path, so this pins that the
    borrow still happens when the whole target agrees.
    """
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", "provisioned-for-5439")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse", port=5439)
    decision = server.resolve_connection_decision(args)

    assert decision.mechanism == "borrowed"
    assert decision.password == "provisioned-for-5439"
    assert (decision.host, decision.port, decision.user, decision.dbname) == (
        "redshift.internal", 5439, "alice", "warehouse",
    )


def test_borrow_hostcasevariant_refuses(tmp_path, monkeypatch):
    """Near-miss: DNS is case-insensitive, the match is a string compare.

    ``REDSHIFT.Internal`` and ``redshift.internal`` resolve to the same
    listener, so a looser match would be defensible — but looser is the wrong
    direction for a credential scope. The probe pins that the compare stays
    strict, i.e. it refuses rather than guesses.
    """
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", "provisioned-lowercase")

    args = ns(host="REDSHIFT.Internal", user="alice", dbname="warehouse")
    decision = server.resolve_connection_decision(args)

    assert decision.mechanism == "inline"
    assert decision.password is None


def test_borrow_ambiguousprofiles_reportslender(tmp_path, monkeypatch):
    """Two stored profiles carry the same triple and different passwords.

    A credential rotation leaves exactly this state: ``prod`` holds the retired
    secret, ``prod-rotated`` the live one, both provisioned for the same target.
    The scan takes the first match ``config.list_profiles()`` yields, and that
    list is sorted, so the retired secret wins by alphabetical accident and can
    burn login attempts against a lockout policy.

    The attack did not break anything a caller cannot see: the choice is
    deterministic and ``get_setup_status`` names the lender. So this pins the
    two properties that make the ambiguity survivable rather than asserting a
    refusal the intent never promised.
    """
    isolate_store(monkeypatch, tmp_path)
    for name, password in (("prod", "retired-secret"), ("prod-rotated", "live-secret")):
        config.write_profile(
            name, host="redshift.internal", port=5439, user="alice", dbname="warehouse",
        )
        config.set_password(name, password)

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    first = server.resolve_connection_decision(args)
    second = server.resolve_connection_decision(args)

    assert first == second, "the lender chosen must not vary between resolutions"
    assert first.profile_name == sorted(["prod", "prod-rotated"])[0], (
        f"the lender is whichever name sorts first, not the freshest credential; "
        f"got {first.profile_name!r}"
    )
    assert first.mechanism == "borrowed"
    assert first.profile_name is not None, (
        "an ambiguous borrow must at least name the profile it borrowed from, "
        "or the operator cannot tell which credential is in flight"
    )


def test_borrow_matchingprofilenopassword_refuses(tmp_path, monkeypatch):
    """Boundary: the triple matches but that profile has no keychain entry.

    The scan must fall through to a refusal rather than to the next profile in
    the store, which is a different target's credential.
    """
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "matching", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.write_profile(
        "other", host="other.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("other", "other-targets-secret")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    decision = server.resolve_connection_decision(args)

    assert decision.password is None, (
        f"a non-matching profile's password was lent: {decision.profile_name!r}"
    )
    with pytest.raises(Exception) as caught:
        server.resolve_connection_params(args)
    assert "other-targets-secret" not in str(caught.value)
