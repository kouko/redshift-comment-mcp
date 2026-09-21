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

W0-08 added a second way for the two to come apart, and closed it: when more
than one stored profile matches the whole four-field target, the scan refuses
instead of lending whichever name sorts first. The four cases named
``*tiedcandidates*`` / ``*neartie*`` / ``*ambiguityflag*`` attack that closure
from both sides — that it fires on every tie and not just a pair, that it does
not fire on a near-miss and cost the borrow that acceptance 1 promises, and
that the new ``ambiguous_profiles`` carrier can never ride along with a
password. The earlier ``test_borrow_ambiguousprofiles_reportslender`` pinned
the sort-order behaviour this replaced; it is gone because the behaviour is.
"""
from __future__ import annotations

import argparse
import re
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


TARGET = dict(host="redshift.internal", port=5439, user="alice", dbname="warehouse")
LAUNCH = dict(host="redshift.internal", user="alice", dbname="warehouse", port=5439)


def _provision(names_to_passwords, **fields):
    """Write one profile per entry, all provisioned for the same target."""
    for name, password in names_to_passwords:
        config.write_profile(name, **{**TARGET, **fields})
        if password is not None:
            config.set_password(name, password)


def test_borrow_tiedcandidates_refusalnameseveryoneofthem(tmp_path, monkeypatch):
    """Three profiles tie, not two. The refusal must name all three.

    A credential rotation leaves the two-profile shape (retired secret kept
    beside its replacement) and that is the shape W0-08 was written against,
    so a fix that reads "name both" rather than "name every one" would pass
    every two-profile case and still leave a three-way tie under-reported —
    the operator deletes the two they were shown and the launch keeps
    refusing with no explanation of what is left.

    Three names chosen so insertion order (``zeta`` first) and sort order
    (``alpha`` first) disagree: a refusal that happened to echo whichever
    candidate the scan met first would name ``zeta`` alone and pass a
    weaker assertion than this one.

    The secrets are attacked at the same time. The refusal's whole job is to
    describe a set of credentials, which is the one message in this codebase
    most tempted to quote them, so every candidate's password is checked
    absent from the message, from the decision's ``repr`` and from the new
    ``ambiguous_profiles`` tuple itself.
    """
    isolate_store(monkeypatch, tmp_path)
    secrets = {"zeta": "zeta-secret", "alpha": "alpha-secret", "mid": "mid-secret"}
    _provision(secrets.items())

    args = ns(**LAUNCH)
    first = server.resolve_connection_decision(args)
    second = server.resolve_connection_decision(args)

    assert first == second, "the refusal must not vary between resolutions"
    assert first.mechanism == "inline", (
        f"a tie must not resolve to a borrow; got {first.mechanism!r} from "
        f"{first.profile_name!r}"
    )
    assert first.has_password is False and first.password is None
    assert first.ambiguous_profiles == ("alpha", "mid", "zeta"), (
        f"the tied candidates must all be carried, in a stable order; got "
        f"{first.ambiguous_profiles!r}"
    )

    with pytest.raises(Exception) as caught:
        server.resolve_connection_params(args)
    message = str(caught.value)

    # Read the tie clause alone, not the whole message. The refusal ends with
    # an "Existing profiles:" listing that names every profile in the store
    # whether it tied or not, so a whole-message search would be satisfied by
    # that listing and would pass a refusal whose ambiguity sentence named
    # nobody — exactly the under-report this case exists to catch.
    tie_clause = message.split("\nExisting profiles:")[0]
    for name in secrets:
        assert name in tie_clause, (
            f"the refusal's ambiguity clause names only some of the tied "
            f"candidates — {name!r} is missing, so the operator cannot tell "
            f"what still has to be deleted or renamed: {tie_clause!r}"
        )
    for name, secret in secrets.items():
        assert secret not in message, (
            f"the refusal quoted {name}'s keychain password: {message!r}"
        )
        assert secret not in repr(first), (
            f"the decision's repr quoted {name}'s keychain password: {first!r}"
        )
        assert secret not in repr(first.ambiguous_profiles)


def test_borrow_tiedidenticalpasswords_refusalclaimsadifferenceitneverchecked(
    tmp_path, monkeypatch,
):
    """Two profiles, one target, the SAME password. What does the refusal say?

    Running setup twice under two names — ``prod`` and a ``prod-copy`` made
    while trying out ``redshift-switch-profile`` — leaves two entries holding
    one credential. There is no ambiguity about which secret to send: both
    candidates would send the identical bytes to the identical target.

    The scan refuses anyway, which is defensible as a "clean the store up"
    rule. What is not defensible is the sentence it refuses with: it states
    as fact that the profiles match "with different passwords". The code
    never compared them — ``lenders`` collects ``(name, password)`` pairs and
    branches on ``len(lenders) > 1`` alone — so the message asserts something
    it did not check, and here it asserts the false half. The operator is
    sent to the keychain to find a difference that is not there, and the one
    diagnosis that would actually help ("these two are interchangeable,
    delete either") is the one they are steered away from.

    This is the negative: the refusal must not claim the passwords differ
    when they are the same. Reworded, or fixed by lending the single distinct
    secret, either closes it.
    """
    isolate_store(monkeypatch, tmp_path)
    shared = "one-credential-two-names"
    _provision((("prod", shared), ("prod-copy", shared)))

    args = ns(**LAUNCH)
    decision = server.resolve_connection_decision(args)
    assert decision.ambiguous_profiles == ("prod", "prod-copy")

    with pytest.raises(Exception) as caught:
        server.resolve_connection_params(args)
    message = str(caught.value)
    assert shared not in message, f"the refusal quoted the password: {message!r}"

    claims_difference = re.search(
        r"different(?:ly)?\s+passwords?|passwords?\s+(?:that\s+)?differ",
        message,
        re.IGNORECASE,
    )
    assert claims_difference is None, (
        f"both tied profiles hold the identical password, and the refusal "
        f"still tells the operator they differ ({claims_difference.group(0)!r}). "
        f"The scan branches on how many candidates matched and never compares "
        f"their secrets, so this clause is asserted, not established — and on "
        f"this store it is false. Full message: {message!r}"
    )


def test_borrow_neartie_lendsonlyontheexactfourfieldtarget(tmp_path, monkeypatch):
    """The regression this fix could plausibly cause: a near-miss read as a tie.

    Four decoys, each differing from the launch target in exactly one of the
    four matched fields, and one profile that matches all four. If the tie
    were detected on anything narrower than the whole target — host alone,
    or host and user — the decoys would count as candidates, the scan would
    see five and refuse, and the acceptance-1 borrow would be gone for every
    operator who keeps more than one profile on the same cluster. That is a
    far more common store shape than the rotation the refusal exists for, so
    the fix costs more than it saves if it fires here.

    Pinned on the decision rather than on the message: the borrow has to
    actually happen, from the one profile provisioned for this target, and
    ``ambiguous_profiles`` has to stay unset so nothing downstream renders a
    tie that is not there.
    """
    isolate_store(monkeypatch, tmp_path)
    _provision((("exact", "the-only-provisioned-secret"),))
    for field, other in (
        ("host", "other.internal"), ("port", 9999),
        ("user", "bob"), ("dbname", "analytics"),
    ):
        _provision(((f"decoy-{field}", f"decoy-{field}-secret"),), **{field: other})

    decision = server.resolve_connection_decision(ns(**LAUNCH))

    assert decision.mechanism == "borrowed", (
        f"a store holding four one-field near-misses beside the real match "
        f"stopped borrowing; got {decision.mechanism!r} with "
        f"ambiguous_profiles={decision.ambiguous_profiles!r}, so the tie is "
        f"being detected on something narrower than the four-field target"
    )
    assert decision.password == "the-only-provisioned-secret"
    assert decision.profile_name == "exact"
    assert decision.ambiguous_profiles is None, (
        f"a single match reported tied candidates: {decision.ambiguous_profiles!r}"
    )


def test_borrow_ambiguityflag_neveraccompaniesapassword(tmp_path, monkeypatch):
    """Can a decision carry both tied candidates and a password to connect with?

    ``ambiguous_profiles`` is a new field on the carrier every other consumer
    already trusts. Two invariants hold it together, and both are one edit
    from being broken by a future branch that sets the field somewhere else:
    a decision that names tied candidates must carry no password (or the
    refusal is a refusal that still connects), and a decision that carries a
    password must name none (or a working launch renders a tie warning at
    the operator for no reason).

    Eight launches across the whole space rather than the one the fix was
    written for, because the invariant is what matters, not the case.
    """
    def decide(label, store, profiles, *, env_password=None, **launch):
        isolate_store(monkeypatch, tmp_path / store)
        if env_password is not None:
            monkeypatch.setenv("REDSHIFT_PASSWORD", env_password)
        for name, password, fields in profiles:
            config.write_profile(name, **{**TARGET, **fields})
            if password is not None:
                config.set_password(name, password)
        return label, server.resolve_connection_decision(ns(**{**LAUNCH, **launch}))

    tied = [("prod", "retired", {}), ("prod-rotated", "live", {})]
    mistyped = _parsed_port("9999x")

    cases = [
        decide("plain tie", "tie", tied),
        decide("tie + env password", "tie-env", tied, env_password="typed-by-operator"),
        decide("tie + inline password", "tie-arg", tied, password="typed-by-operator"),
        decide("single lender", "single", [("prod", "lendable", {})]),
        decide("tie in fields, one lender", "one-lender",
               [("prod", None, {}), ("prod-rotated", "live", {})]),
        decide("two near-misses", "near",
               [("a", "sa", {"host": "other.internal"}), ("b", "sb", {"user": "bob"})]),
        decide("profile mode", "profile-mode", [("default", "stored", {})],
               host=None, user=None, dbname=None),
        decide("tie behind a mistyped port", "mistyped", tied, port=mistyped),
    ]

    for label, decision in cases:
        assert not (decision.ambiguous_profiles and decision.password), (
            f"{label}: a decision names tied candidates "
            f"{decision.ambiguous_profiles!r} AND carries a password, so the "
            f"launch both refuses and connects"
        )
        assert not (decision.ambiguous_profiles and decision.has_password), (
            f"{label}: tied candidates {decision.ambiguous_profiles!r} on a "
            f"decision reporting has_password=True — get_setup_status would "
            f"call this configured"
        )
        if decision.ambiguous_profiles is not None:
            assert decision.mechanism == "inline", (
                f"{label}: tied candidates on a {decision.mechanism!r} decision"
            )
            assert decision.profile_name is None, (
                f"{label}: a refused tie still named a lender "
                f"{decision.profile_name!r}"
            )

    by_label = dict(cases)
    assert by_label["plain tie"].ambiguous_profiles == ("prod", "prod-rotated")
    assert by_label["tie + env password"].password == "typed-by-operator"
    assert by_label["tie + inline password"].password == "typed-by-operator"
    assert by_label["single lender"].mechanism == "borrowed"
    assert by_label["tie in fields, one lender"].mechanism == "borrowed", (
        "two profiles share the target but only one has a keychain entry, so "
        "there is exactly one candidate to lend and nothing to guess between"
    )
    assert by_label["two near-misses"].ambiguous_profiles is None
    assert by_label["profile mode"].mechanism == "profile"


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
