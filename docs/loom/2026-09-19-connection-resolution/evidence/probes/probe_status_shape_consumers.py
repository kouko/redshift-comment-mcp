"""Probe: W0-02 grew the ``get_setup_status`` response. Who still reads the old one?

The response gained a third ``source`` value, ``"borrowed"``, and a new
``borrowed_from_profile`` key. Every surface that tells a consumer what that
response looks like is now a candidate for staleness. The consumer that
matters most is not a document a human reads on request — it is the FastMCP
``instructions`` handshake string, which every MCP client receives up front
and which is the only place an agent is told how to interpret ``source``. An
agent that has been told ``source`` is ``"inline"`` or ``"profile"`` and
receives ``"borrowed"`` has no rule for it, and the one rule it was given —
"do NOT report 'no profile' in that mode" — was attached to ``"inline"`` only.

Prose pinning discipline
------------------------
The assertions below pin sentences of prose, so they do not merely grep for a
word. ``affirmatively_states`` requires an affirmative verb ahead of the
pinned literal inside the same clause and rejects the clause if it carries a
negation, so text that says the opposite of the pinned claim cannot satisfy
it. The two ``test_prosepinner_*`` functions are synthetic self-tests of that
checker: one affirmative example it must accept, one negated example it must
reject.

Derived expectations, not hand-edited phrases
---------------------------------------------
The manifest probe below used to hard-code the phrase the description had to
contain. That is the wrong shape for a rule that can change: when the borrow
match widened from three fields to four (W0-05), the pinned phrase became
unsatisfiable by any truthful text and the probe went red for a reason that
was not a defect. So the field list is no longer written down here at all.
``_fields_the_code_matches_on`` recovers it by experiment — vary one target
field at a time against a provisioned profile and see whether the password is
still lent — and the probe asserts the prose names exactly that set. The
pinned literals that remain are the polarity anchors ("borrow", "match") and
the reverted-story guard, not the rule itself.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_support import isolate_store, ns, server_instructions  # noqa: E402

from redshift_comment_mcp import config, server  # noqa: E402

# probes/ -> evidence/ -> <change-id>/ -> loom/ -> docs/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[5]

# A clause: what a period, a semicolon, a blank line or a bullet marker ends.
# Colons are kept inside, because "`source` says which mechanism is live:
# `borrowed` means ..." puts the verb on the near side of the colon. The
# lookbehind keeps "e.g." / "i.e." / "etc." from cutting a clause in half, which
# would otherwise make a correct fix written after an "e.g." unpinnable.
_CLAUSE_SPLIT = re.compile(r"(?<!e\.g)(?<!i\.e)(?<!etc)(?:\.\s)|;|\n\s*\n|\n\s*-\s")

_AFFIRMATIVE_VERB = re.compile(
    r"\b(?:is|are|was|were|means?|says?|reports?|returns?|indicates?|carries|"
    r"carry|names?|includes?|covers?|reads?|shows?|has|have|one of|either|"
    r"will be|can be|may be|borrows?|lends?|uses?|matches|match|applies|"
    r"leaves?|leave)\b",
    re.IGNORECASE,
)

_NEGATION = re.compile(
    r"\b(?:not|never|no|none|neither|nor|without|cannot|can't|isn't|aren't|"
    r"doesn't|don't|won't|rather than|instead of|unsupported|removed)\b",
    re.IGNORECASE,
)


def affirmatively_states(text: str, literal: str) -> bool:
    """True when some clause of ``text`` affirmatively asserts ``literal``.

    A clause qualifies when it contains ``literal``, contains an affirmative
    verb at a position before the literal, and contains no negation token.
    """
    for clause in _CLAUSE_SPLIT.split(text):
        where = clause.find(literal)
        if where < 0:
            continue
        if _NEGATION.search(clause):
            continue
        verb = _AFFIRMATIVE_VERB.search(clause)
        if verb is not None and verb.start() < where:
            return True
    return False


# ===== synthetic self-tests of the checker above =====


def test_prosepinner_affirmativeexample_accepts():
    """The shape a correct fix would take must satisfy the checker."""
    sample = (
        "The `source` field says which mechanism is live: `\"borrowed\"` means "
        "the server runs on launch args and lent its password from a stored "
        "profile whose host, port, user and dbname all match."
    )
    assert affirmatively_states(sample, '"borrowed"')


def test_prosepinner_negatedexample_rejects():
    """Text asserting the opposite must not satisfy the checker.

    Both halves matter: a clause that negates the claim is rejected, and a
    clause that merely mentions the literal with no affirmative verb ahead of
    it is rejected too.
    """
    negated = 'The `source` field is never `"borrowed"`; that mode was removed.'
    assert not affirmatively_states(negated, '"borrowed"')

    bare_mention = 'Historical note about `"borrowed"` handling.'
    assert not affirmatively_states(bare_mention, '"borrowed"')


# ===== the actual attack =====


def test_instructions_borrowedsource_documented():
    """The handshake string must tell an agent that ``source`` can be borrowed.

    It currently enumerates two values and stops. The ``"borrowed"`` value and
    the ``borrowed_from_profile`` key W0-02 added are described in the tool's
    Python docstring and nowhere in the string the MCP client is handed.
    """
    text = server_instructions()

    assert "borrowed" in text, (
        "the FastMCP `instructions` handshake never mentions the `\"borrowed\"` "
        "source value W0-02 added, so an agent that receives it has been given "
        "no rule for it. The string's SETUP RECOVERY section enumerates "
        "`\"inline\"` and `\"profile\"` only."
    )
    assert affirmatively_states(text, "borrowed"), (
        "`borrowed` appears in the instructions but no clause affirmatively "
        "states what it means"
    )


def test_instructions_sourceenumeration_iscomplete():
    """The enumeration itself must not still read as exactly two values.

    Pinned separately from the probe above so a fix that bolts "borrowed" on
    somewhere else in the string, while leaving the ``"inline"`` /
    ``"profile"`` enumeration reading as exhaustive, still fails.
    """
    text = server_instructions()
    enumerating = [
        clause for clause in _CLAUSE_SPLIT.split(text)
        if '`"inline"`' in clause or '"inline"' in clause
    ]
    assert enumerating, "no clause enumerates the `source` values at all"
    assert any("borrowed" in clause for clause in enumerating), (
        "the clause that enumerates `source` values lists inline and profile "
        f"and stops: {enumerating!r}"
    )


# ===== deriving the borrow rule from the code that runs it =====

_TARGET_FIELDS = ("host", "port", "user", "dbname")

# The target a profile is provisioned for, and a distinct value for each field
# of it. Every variant below differs from the baseline in exactly one field.
_PROVISIONED = {
    "host": "redshift.internal", "port": 5439,
    "user": "alice", "dbname": "warehouse",
}
_OTHER = {
    "host": "other.internal", "port": 9999,
    "user": "bob", "dbname": "analytics",
}
_LENDABLE_SECRET = "provisioned-for-the-baseline-target"

# An em/en dash sets off a clause the way a semicolon does, and the manifest
# uses one to hang the "never to the profile's" guarantee off the borrow
# sentence. Split on it locally rather than widening the shared _CLAUSE_SPLIT,
# which the two instructions probes above depend on.
_DASH_SPLIT = re.compile(r"\s[—–]\s")

# Which claim a clause is making. A clause that names target fields without
# stating the borrow rule (e.g. "host and port are saved to settings.json")
# is not evidence about the match and must not count as naming a match field.
_BORROW_RULE = re.compile(r"\b(?:borrows?|borrowing|borrowed|match(?:es|ing)?)\b", re.IGNORECASE)


def _borrow_happens(monkeypatch, store: Path, **launch) -> bool:
    """Provision one profile for ``_PROVISIONED`` and see if ``launch`` borrows it.

    Both halves of the isolation the probes here require: ``XDG_CONFIG_HOME``
    is redirected and ``keyring`` is replaced with a dict, so no real keychain
    entry is ever written.
    """
    isolate_store(monkeypatch, store)
    config.write_profile("provisioned", **_PROVISIONED)
    config.set_password("provisioned", _LENDABLE_SECRET)
    decision = server.resolve_connection_decision(ns(**launch))
    return decision.password == _LENDABLE_SECRET


def _fields_the_code_matches_on(monkeypatch, tmp_path: Path) -> frozenset:
    """The target fields the borrow actually requires, recovered by experiment.

    Not read off the source and not written down: vary one field at a time
    against a profile provisioned for ``_PROVISIONED``. A field whose variant
    still borrows is not part of the match; a field whose variant refuses is.
    """
    assert _borrow_happens(monkeypatch, tmp_path / "control", **_PROVISIONED), (
        "probe setup is broken: an exactly-matching launch did not borrow, so "
        "the per-field experiment below cannot tell a matched field from a "
        "fixture that never lends at all"
    )
    matched = set()
    for field in _TARGET_FIELDS:
        variant = dict(_PROVISIONED)
        variant[field] = _OTHER[field]
        if not _borrow_happens(monkeypatch, tmp_path / field, **variant):
            matched.add(field)
    return frozenset(matched)


def fields_named_in_borrow_rule(text: str) -> frozenset:
    """The target fields ``text`` affirmatively names as part of the borrow match.

    Same discipline as ``affirmatively_states``: a clause counts only when it
    states the borrow rule, carries an affirmative verb ahead of the field
    name, and carries no negation token — so "whose host, port, user and
    dbname do not all match" contributes nothing rather than contributing four
    fields.
    """
    named = set()
    for coarse in _CLAUSE_SPLIT.split(text):
        for clause in _DASH_SPLIT.split(coarse):
            if _NEGATION.search(clause):
                continue
            if not _BORROW_RULE.search(clause):
                continue
            verb = _AFFIRMATIVE_VERB.search(clause)
            if verb is None:
                continue
            for field in _TARGET_FIELDS:
                found = re.search(rf"\b{field}\b", clause, re.IGNORECASE)
                if found is not None and verb.start() < found.start():
                    named.add(field)
    return frozenset(named)


def test_fieldextractor_affirmativeexample_namesexactlywhatitstates():
    """Synthetic self-test: the shape a truthful description takes is read right.

    Two examples, because the extractor's whole job is to discriminate between
    field lists — a checker that returned all four fields for any text would
    make the probe below vacuous.
    """
    four = (
        "Database password. Leave blank to borrow the keychain password of a "
        "profile whose host, port, user and dbname all match the values above "
        "— the connection always goes to what you typed here, never to the "
        "profile's; leave every field blank to use that profile directly."
    )
    assert fields_named_in_borrow_rule(four) == frozenset(_TARGET_FIELDS)

    three = (
        "Database password. Leave blank to borrow the keychain password of a "
        "profile whose host, user and dbname all match the values above."
    )
    assert fields_named_in_borrow_rule(three) == frozenset({"host", "user", "dbname"})


def test_fieldextractor_negatedexample_namesnone():
    """Synthetic self-test: text denying the rule must not be read as stating it.

    Both halves: a clause that negates the match contributes nothing, and a
    clause that names the fields without stating the borrow rule at all
    contributes nothing either.
    """
    negated = (
        "Database password. Leaving it blank does not borrow anything: no "
        "profile lends a password however well its host, port, user and "
        "dbname line up."
    )
    assert fields_named_in_borrow_rule(negated) == frozenset()

    unrelated = "Your host, port, user and dbname are saved to settings.json."
    assert fields_named_in_borrow_rule(unrelated) == frozenset()


def test_manifest_blankpasswordrule_matchescode(tmp_path, monkeypatch):
    """Attempt: make the install-dialog text contradict what the code does.

    The manifest's password field is what an operator reads at the moment they
    decide whether to leave the field blank, and the intent's Problem section
    opens with this field telling a different story from the README. So the
    attack is to find a claim in it the code does not honour.

    The claim attacked is the one that has already drifted once: which fields
    a profile must agree on before it lends. The expectation is not written
    here — it is recovered from the running code by
    ``_fields_the_code_matches_on``, so widening or narrowing the match moves
    the expectation with it and only a description that disagrees with the
    code fails. Both directions are caught: prose that names fewer fields than
    the code requires (a borrow the operator is told to expect and will not
    get) and prose that names more (a refusal they are not warned about).
    """
    matched = _fields_the_code_matches_on(monkeypatch, tmp_path)
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    description = manifest["userConfig"]["password"]["description"]
    named = fields_named_in_borrow_rule(description)

    assert named == matched, (
        f"the manifest's borrow rule names {sorted(named)} but "
        f"`resolve_connection_decision` requires {sorted(matched)} to match "
        f"before it lends a password. Missing from the prose: "
        f"{sorted(matched - named)}; claimed but not enforced: "
        f"{sorted(named - matched)}. Description: {description!r}"
    )
    assert "a profile password configured via" not in description, (
        "the manifest reverted to the pre-change 'any profile' story"
    )


def test_refusal_existingprofiles_namestheirwholetarget(tmp_path, monkeypatch):
    """Attempt: leave the operator unable to see why nothing matched.

    W0-06 put this promise in front of the user in all three READMEs — "the
    connection refuses, naming the target you typed and each existing
    profile's target" — and acceptance 2 says the same. A target in this
    change is the four-field tuple; the constraint spells it out ("a stored
    profile may contribute a password, never a host, port, user or dbname").

    So the attack is two profiles on the same cluster that differ from the
    launch only in the fields the message might drop. If it names host and
    port alone, the two entries render identically, the field that actually
    mismatched is never shown, and the refusal's one job — telling the
    operator which profile to fix — is not done.
    """
    isolate_store(monkeypatch, tmp_path)
    for name, dbname in (("prod", "warehouse"), ("prod_analytics", "analytics")):
        config.write_profile(
            name, host="redshift.internal", port=5439, user="alice", dbname=dbname,
        )
        config.set_password(name, f"{name}-secret")

    args = ns(host="redshift.internal", port=5439, user="alice", dbname="reporting")
    with pytest.raises(Exception) as caught:
        server.resolve_connection_params(args)
    message = str(caught.value)

    for name, dbname in (("prod", "warehouse"), ("prod_analytics", "analytics")):
        assert dbname in message, (
            f"the refusal names profile {name!r} without the field that made it "
            f"mismatch. Both stored profiles are redshift.internal:5439 for user "
            f"alice, so the message renders them as two indistinguishable "
            f"entries and the operator cannot tell which one to point at "
            f"/redshift-setup: {message!r}"
        )


def test_mcpbmanifest_passwordfield_staysrequired():
    """Control: the .mcpb surface must keep the blank-password state unreachable.

    The intent relies on this ("its manifest marks every field required, so
    the blank-password state is unreachable there"). If a later edit made the
    field optional, that bundle would inherit the borrow path without any of
    the prose that explains it.
    """
    import importlib.util

    gen_path = REPO_ROOT / "scripts" / "generate_mcpb_manifest.py"
    spec = importlib.util.spec_from_file_location("generate_mcpb_manifest", gen_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    user_config = module._build_manifest_user_config() if hasattr(
        module, "_build_manifest_user_config"
    ) else None
    if user_config is None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            module.generate(repo_root=REPO_ROOT, out_dir=Path(tmp))
            manifest = json.loads((Path(tmp) / "manifest.json").read_text())
        user_config = manifest["user_config"]

    assert user_config["password"]["required"] is True
    for field in ("host", "user", "dbname"):
        assert user_config[field]["required"] is True
