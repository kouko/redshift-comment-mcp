"""Adversarial probes: what the three READMEs now assert about config.toml.lock.

Change: 2026-09-18-config-store-integrity
Anchor: README.md, README.ja.md, README.zh-TW.md — the files-on-disk table
        src/redshift_comment_mcp/config.py :: _store_lock

W0-04 added a row for a new file in every user's config directory, in three
languages. These probes check that row against the code rather than against the
other two READMEs: is the lifecycle it describes what actually happens.

Pinning a sentence of prose is only sound if the pin is anchored to an
*affirmative* claim — otherwise a later edit that negates the sentence keeps
the literal and the probe stays green while the meaning inverts. Every pin
below goes through :func:`asserts_affirmatively`, which requires an affirmative
verb ahead of the pinned literal and rejects any negation token in the same
sentence. That helper carries its own synthetic self-tests at the bottom of
this file: one affirmative example it must accept, one negated example it must
reject, per language.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _probe_support import isolate_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[5]
LOCK_FILE_NAME = "config.toml.lock"

# Per language: the sentence terminators, the negation tokens that must not
# appear in the pinned sentence, the affirmative verb that must precede the
# pinned literal, and the literal itself.
CLAIMS = {
    "README.md": {
        "terminators": r"[.;]\s|\n",
        "negations": ["not ", "never", "n't", " no ", "without", "unless",
                      "except", "cannot"],
        "verb": "Appears",
        "literal": "on the first write and stays",
    },
    "README.ja.md": {
        "terminators": r"[。；]|\n",
        "negations": ["ない", "ません", "なく", "せず", "ず、", "以外"],
        "verb": "作成され",
        "literal": "そのまま残る",
    },
    "README.zh-TW.md": {
        "terminators": r"[。；]|\n",
        "negations": ["不會", "不是", "沒有", "未", "無法", "除非", "以外"],
        "verb": "建立",
        "literal": "並留著",
    },
}


def _sentences(text: str, terminators: str) -> list[str]:
    return [s for s in re.split(terminators, text) if s.strip()]


def asserts_affirmatively(text: str, spec: dict) -> bool:
    """True when ``text`` states the claim as an unnegated, affirmative sentence.

    The claim counts as affirmative when one sentence of ``text`` contains the
    pinned literal, contains the affirmative verb *ahead of* that literal, and
    contains none of the language's negation tokens. A sentence that keeps the
    literal but negates the verb — the exact edit a plain substring pin would
    sail past — is rejected.
    """
    for sentence in _sentences(text, spec["terminators"]):
        at_literal = sentence.find(spec["literal"])
        if at_literal < 0:
            continue
        at_verb = sentence.find(spec["verb"])
        if at_verb < 0 or at_verb > at_literal:
            continue
        if any(token in sentence for token in spec["negations"]):
            continue
        return True
    return False


def _lock_row(readme: str) -> str:
    """The files-on-disk table row describing the lock file, description cell only."""
    for line in (REPO_ROOT / readme).read_text().splitlines():
        if LOCK_FILE_NAME in line and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert len(cells) >= 3, f"{readme}: unexpected table shape: {line!r}"
            return cells[1]
    pytest.fail(f"{readme} has no files-on-disk table row for {LOCK_FILE_NAME}")


# ----- the claims, against the code -----


@pytest.mark.parametrize("readme", sorted(CLAIMS))
def test_readmelockrow_thelifecycleclaim_isstatedaffirmatively(readme):
    """Precondition for the probe below: the row really does make the claim.

    If this goes red the wording moved, and the case that follows is pinning
    something that is no longer there — which is the failure mode this guard
    exists to make visible rather than silent.
    """
    row = _lock_row(readme)
    assert asserts_affirmatively(row, CLAIMS[readme]), (
        f"{readme}'s {LOCK_FILE_NAME} row no longer affirmatively claims the "
        f"file is created on the first write and kept. Row: {row!r}"
    )


@pytest.mark.parametrize("readme", sorted(CLAIMS))
def test_readmelockrow_theunconditionalcreationclaim_holdsoneverysupportedplatform(
    readme, tmp_path, monkeypatch
):
    """The row promises the file appears on the first write; on Windows it does not.

    ``_store_lock`` returns before it opens anything when ``fcntl`` is absent,
    and the module docstring names that platform as supported-but-degraded. So
    on Windows no ``config.toml.lock`` is ever created, the row's mode column
    describes a file that does not exist, and — the part that matters — the
    concurrency protection the row advertises ("so two of them running at once
    can't drop each other's profiles") is not in force there either. The row
    carries no platform qualifier in any of the three languages.
    """
    row = _lock_row(readme)
    assert asserts_affirmatively(row, CLAIMS[readme]), "wording moved; see the guard above"

    qualifiers = ["POSIX", "Windows", "macOS", "Linux", "posix", "windows"]
    qualified = any(q in row for q in qualifiers)

    isolate_config(monkeypatch, tmp_path)
    from redshift_comment_mcp import config as cfg

    original = cfg._fcntl
    cfg._fcntl = None
    try:
        cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")
        created = cfg._lock_path().exists()
    finally:
        cfg._fcntl = original

    assert created or qualified, (
        f"{readme} states unconditionally that {LOCK_FILE_NAME} appears on the "
        f"first write and stays, but a first write with fcntl unavailable — the "
        f"Windows path config.py's module docstring explicitly supports — "
        f"creates no lock file at all. The row names no platform. Row: {row!r}"
    )


@pytest.mark.parametrize("readme", sorted(CLAIMS))
def test_readmelockrow_themodecolumn_matchesthefileonposix(readme, tmp_path, monkeypatch):
    """Where the file does exist, the row's 0600 is accurate."""
    line = next(
        l for l in (REPO_ROOT / readme).read_text().splitlines()
        if LOCK_FILE_NAME in l and l.lstrip().startswith("|")
    )
    assert "0600" in line, f"{readme}'s lock row does not list a mode: {line!r}"

    import stat

    isolate_config(monkeypatch, tmp_path)
    from redshift_comment_mcp import config as cfg

    cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")
    lock = cfg._lock_path()
    assert lock.exists(), "no lock file after a write on a POSIX host"
    mode = stat.S_IMODE(lock.stat().st_mode)
    assert mode == 0o600, f"{readme} says 0600; the file is {oct(mode)}"


def test_readmelockrow_theemptinessclaim_matchesthefilecontents(tmp_path, monkeypatch):
    """All three rows call it an empty file; nothing must ever write to it."""
    isolate_config(monkeypatch, tmp_path)
    from redshift_comment_mcp import config as cfg

    cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")
    cfg.set_password("prod", "pw")
    lock = cfg._lock_path()
    assert lock.stat().st_size == 0, (
        f"the lock file holds {lock.stat().st_size} bytes; all three READMEs "
        f"describe it as empty"
    )


# ----- synthetic self-tests for the affirmative-claim guard -----


AFFIRMATIVE_EXAMPLES = {
    "README.md": "Appears on the first write and stays",
    "README.ja.md": "最初の書き込みで作成されそのまま残る",
    "README.zh-TW.md": "第一次寫入時建立並留著",
}

NEGATED_EXAMPLES = {
    "README.md": "Does not appear on the first write and stays absent",
    "README.ja.md": "最初の書き込みでは作成されず、そのまま残ることはない",
    "README.zh-TW.md": "第一次寫入時不會建立，並留著舊的檔案",
}


@pytest.mark.parametrize("readme", sorted(CLAIMS))
def test_affirmativeguard_anaffirmativesentence_isaccepted(readme):
    """The guard must recognise the claim when it is genuinely made."""
    assert asserts_affirmatively(AFFIRMATIVE_EXAMPLES[readme], CLAIMS[readme]), (
        f"the guard rejected a plainly affirmative {readme} sentence: "
        f"{AFFIRMATIVE_EXAMPLES[readme]!r} — it would then fail open on the "
        f"real row for the wrong reason"
    )


@pytest.mark.parametrize("readme", sorted(CLAIMS))
def test_affirmativeguard_anegatedsentence_isrejected(readme):
    """A sentence that keeps the literal but negates the claim must not pass.

    This is the mutation a plain ``literal in text`` pin lets through: the
    words are all still there, and the meaning is the opposite.
    """
    assert not asserts_affirmatively(NEGATED_EXAMPLES[readme], CLAIMS[readme]), (
        f"the guard accepted a negated {readme} sentence: "
        f"{NEGATED_EXAMPLES[readme]!r} — the pin asserts nothing"
    )
