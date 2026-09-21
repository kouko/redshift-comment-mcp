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
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_support import server_instructions  # noqa: E402

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
        "profile whose host, user and dbname all match."
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


def test_manifest_blankpasswordrule_matchescode():
    """Attempt: make the install-dialog text contradict what the code does.

    The manifest's password field is what an operator reads at the moment they
    decide whether to leave the field blank, and the intent's Problem section
    opens with this field telling a different story from the README. So the
    attack is to find a claim in it the code does not honour.

    It does not contradict: it states the triple match, which is exactly the
    match ``server.resolve_connection_decision`` runs, and it does not claim
    the old "any profile configured via /redshift-setup" behaviour. It is
    silent about port rather than wrong about it — an omission, which is the
    reviewer's lens, not an executable break. Pinned here as the control that
    keeps it from drifting from silence into contradiction.
    """
    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    description = manifest["userConfig"]["password"]["description"]

    assert affirmatively_states(description, "host, user and dbname all match"), (
        f"the manifest no longer states the identity-match rule: {description!r}"
    )
    # The contradictions this rules out: claiming port participates in the
    # match when it does not, or claiming any profile may lend.
    lowered = description.lower()
    assert "port" not in lowered or "port is not part of the match" in lowered, (
        f"the manifest mentions port in the borrow rule but not as an exclusion, "
        f"which would contradict the code: {description!r}"
    )
    assert "a profile password configured via" not in description, (
        "the manifest reverted to the pre-change 'any profile' story"
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
