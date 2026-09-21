"""Probe: how far does a borrowed keychain password travel?

A launch that supplies host/port/user/dbname and no password borrows the
keychain password of a stored profile whose whole ``(host, port, user,
dbname)`` target equals the supplied values (W0-01, widened to include
``port`` by W0-05). The connection then targets the launch values.

The attack surface is the gap between "the target the password was provisioned
for" and "the target the password is now sent to". The four-field match is
what closes that gap: every field the connection uses is a field the profile
had to agree on first. So the question this file makes executable is whether
anything can still prise the two apart — a field the match compares loosely,
or a launch value the code rewrites after the operator typed it and before
the match reads it.

``test_borrow_portmismatch_refuses`` is the case that found the original gap,
kept as the regression pin now that the match covers port. The rest are
near-misses and boundaries checking the match is not sloppier than advertised.
"""
from __future__ import annotations

import argparse
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
    dbname but port 9999. Under the original three-field match this lent the
    keychain password and carried it to a listener the password was never
    provisioned for; the failure was silent, which is why kouko chose to
    widen the match to all four fields on 2026-09-21 rather than accept it.

    Kept as the regression pin for that decision: a port the profile was not
    provisioned for must refuse, not lend.
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
        f"borrowed_from={decision.profile_name!r}. The match has dropped port "
        f"again, so the one target field that selects which listener receives "
        f"the secret is no longer one the profile had to agree on."
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


def _parsed_port(raw: str) -> int:
    """``--port raw`` as the launched server itself would parse it.

    Mirrors the one line of wiring in ``server.main()`` (``type=_coerce_port``,
    ``default=DEFAULT_PORT``) and reads the coercion off the module rather
    than reimplementing it, so the probe cannot drift from the real launch
    path — the point here is precisely what argparse hands the resolver.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=server._coerce_port, default=server.DEFAULT_PORT)
    return parser.parse_args(["--port", raw]).port


def test_borrow_unparseableport_refuses(tmp_path, monkeypatch):
    """A mistyped port must not silently become the port a profile matches.

    ``_coerce_port`` maps any value it cannot read as an integer to 5439. It
    was written to tolerate two specific launch artefacts — a blank optional
    userConfig field and an unsubstituted ``${user_config.port}`` placeholder
    — so the server boots instead of aborting. A non-empty, non-placeholder
    value such as ``"9999x"`` is neither: it is a typo, and the operator who
    typed it named 9999.

    Before this change that leniency cost nothing on the inline path: no
    password was available at any port, so the launch refused either way.
    The borrow makes the same leniency load-bearing. The typo collapses to
    5439, which is the port nearly every stored profile is recorded at, so
    the match now succeeds against a profile provisioned for a listener the
    operator did not name, and the keychain password is sent there — with no
    message saying the port was rewritten.

    That is the same failure the four-field match was chosen to close, and
    the same shape: silent rather than loud. The manifest states the closed
    version of it outright ("the connection always goes to what you typed
    here"). Expected: a port the operator typed and the server cannot parse
    refuses, rather than being replaced with one that borrows.
    """
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", "provisioned-for-5439")

    port = _parsed_port("9999x")
    args = ns(host="redshift.internal", user="alice", dbname="warehouse", port=port)
    decision = server.resolve_connection_decision(args)

    assert decision.password != "provisioned-for-5439", (
        f"the operator typed port 9999x; argparse rewrote it to {port} and the "
        f"profile provisioned for redshift.internal:5439 lent its keychain "
        f"password to that target (mechanism={decision.mechanism!r}, "
        f"borrowed_from={decision.profile_name!r}). Nothing in the launch says "
        f"the port was substituted, so the operator has no way to see that the "
        f"connection did not go where they typed."
    )
