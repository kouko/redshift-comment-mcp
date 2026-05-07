"""Skill description quality checks — enforce description-design.md principles.

The plugin's skill descriptions sit in every Claude Code system prompt.
Drift in their shape (workflow leak, first-person voice, missing trigger
clauses) silently degrades skill-triggering accuracy. These tests catch
the obvious anti-patterns documented in
`monkey-skills/dev-workflow/skill-creator-advance/references/description-design.md`.

Add a test here whenever a description-style mistake gets caught in code
review and you don't want it to recur.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"


def _skill_dirs():
    return sorted(
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def _description(skill_name):
    text = (SKILLS_DIR / skill_name / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return yaml.safe_load(m.group(1))["description"]


# ===== WHEN clause presence (principle 1) =====

@pytest.mark.parametrize("skill", _skill_dirs())
def test_description_has_when_clause(skill):
    """Every description must signal WHEN to trigger — either a 'Use when'
    clause or a 'Triggers:' keyword belt (or both).

    Pure-WHAT descriptions force Claude to infer when to invoke and lose
    selection competition to other skills with explicit triggers.
    """
    desc = _description(skill).lower()
    has_use_when = "use when" in desc
    has_triggers = "triggers:" in desc or "triggers " in desc
    assert has_use_when or has_triggers, (
        f"{skill}: description has no 'Use when' clause and no 'Triggers:' "
        f"belt — Claude has to infer when to invoke"
    )


# ===== third-person voice (principle 2) =====

# Words that almost certainly indicate first/second person voice in a
# description. Tuned to match standalone occurrences only — "your" inside
# "user's own terminal" is fine, but a leading "I" or "we" is not.
FIRST_SECOND_PERSON_RE = re.compile(
    r"\b(I|we|you|your|me|us|our|my)\b(?!\s*['’])",
    re.IGNORECASE,
)
# Whitelisted phrases that include `you` / `your` legitimately (third-person
# narration about the user, not addressing them).
WHITELIST_PHRASES = (
    "user's",
    "user invokes",
    "user wants",
    "user says",
    "user doesn't know",
    "user is",
)


@pytest.mark.parametrize("skill", _skill_dirs())
def test_description_third_person(skill):
    """The skill's own narration must use third-person ('user', 'when
    wanting...'), not 'I' / 'you' / 'we' / 'your'.

    Pronoun inconsistency degrades skill selection — Anthropic best-practices
    has an explicit Warning block on this.

    Excludes the 'Triggers: ...' keyword belt because trigger phrases echo
    the user's likely phrasing (e.g. "where do I look", "I don't know where
    to start") and are not the skill speaking in first person.
    """
    desc = _description(skill)

    # Strip the Triggers belt — it's verbatim user phrasing.
    prose_before_triggers = re.split(r"Triggers?:\s*", desc, maxsplit=1)[0]

    # Strip whitelisted third-person phrases (e.g. "user's own terminal").
    stripped = prose_before_triggers
    for phrase in WHITELIST_PHRASES:
        stripped = stripped.replace(phrase, "")

    matches = FIRST_SECOND_PERSON_RE.findall(stripped)
    assert not matches, (
        f"{skill}: description contains first/second-person pronouns "
        f"{sorted(set(matches))} — should use third-person ('user', 'when "
        f"wanting...'). Prose checked (Triggers belt excluded):\n{prose_before_triggers}"
    )


# ===== no workflow recap (principle 1, defensive) =====

WORKFLOW_PATTERNS = (
    re.compile(r"\bstep\s*\d", re.IGNORECASE),
    re.compile(r"\bfirst\b.*\bthen\b.*\bnext\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b1\.\s.*\b2\.\s", re.DOTALL),  # numbered process recap
)


@pytest.mark.parametrize("skill", _skill_dirs())
def test_description_no_workflow_recap(skill):
    """Description must not summarize the workflow as a numbered process.

    superpowers' rule: when a description recaps the steps, Claude shortcuts
    into following the description and skips reading SKILL.md's actual body.
    Brief WHAT clauses are fine; Step 1 / Step 2 / Step 3 prose is not.
    """
    desc = _description(skill)
    hits = [pat.pattern for pat in WORKFLOW_PATTERNS if pat.search(desc)]
    assert not hits, (
        f"{skill}: description matches workflow-recap pattern(s): {hits}. "
        f"Move process steps to SKILL.md body. Description:\n{desc}"
    )


# ===== description length soft ceiling =====

DESCRIPTION_SOFT_CEILING = 800  # description-design.md target ~500; allow buffer


@pytest.mark.parametrize("skill", _skill_dirs())
def test_description_under_soft_ceiling(skill):
    """Description should stay under ~800 chars (soft ceiling above
    description-design.md's recommended ~500).

    The hard 1024-char Anthropic ceiling is enforced separately in
    test_repo_invariants.py. This test catches descriptions sliding back
    toward the pre-trim 800-1000 char baseline.
    """
    desc = _description(skill)
    assert len(desc) <= DESCRIPTION_SOFT_CEILING, (
        f"{skill}: description {len(desc)} chars exceeds soft ceiling "
        f"{DESCRIPTION_SOFT_CEILING}. Trim per description-design.md "
        f"(workflow leak / verbose triggers / multi-language full sentences "
        f"instead of keyword belt)."
    )
