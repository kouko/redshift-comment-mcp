"""Repo-level invariants — sanity checks that catch documentation drift.

These tests don't exercise runtime code; they verify cross-file invariants
(skill ↔ command pairing, frontmatter validity, version sync, dead
references, README trilingual parity) that are easy to break with a
markdown-only change and have no other automated guard.

Add a new test here whenever a multi-PR refactor reveals a class of bug
that pure pytest of `redshift_tools.py` cannot catch.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
COMMANDS_DIR = REPO_ROOT / "commands"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"

# Skills exempt from the README trilingual rule (internal-only / setup-style).
NO_README_SKILLS = {"redshift-setup", "redshift-switch-profile"}

# Identifiers that look like a skill / plugin name but aren't a skill dir.
# - redshift-comment-mcp: the plugin / PyPI package name itself
# - redshift-comment: canonical MCP server entry key (per .claude-plugin/plugin.json)
# - redshift-prod / redshift-stg: documentation example entry names in README
#   "Setting up with `uvx`" multi-cluster snippet (not real skill names; if a
#   skill with these names is ever added, drop them from here so the test can
#   guard the real skill ref again).
NON_SKILL_VALID_NAMES = {
    "redshift-comment-mcp",
    "redshift-comment",
    "redshift-prod",
    "redshift-stg",
}


def _skill_dirs():
    """Return sorted list of skill directory names with a SKILL.md."""
    return sorted(
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def _command_stems():
    """Return sorted list of slash command file stems."""
    return sorted(f.stem for f in COMMANDS_DIR.glob("*.md"))


def _frontmatter(skill_name):
    text = (SKILLS_DIR / skill_name / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{skill_name}/SKILL.md missing YAML frontmatter"
    return yaml.safe_load(m.group(1))


# ===== command ↔ skill pairing =====

def test_no_orphan_command_files():
    """Every commands/<name>.md should have a matching skills/<name>/SKILL.md."""
    skills = set(_skill_dirs())
    commands = set(_command_stems())
    orphans = commands - skills
    assert not orphans, (
        f"Slash command files with no matching skill: {sorted(orphans)}. "
        f"Either delete the .md or add the skill."
    )


def test_no_orphan_skills():
    """Every skills/<name>/ should have a matching commands/<name>.md."""
    skills = set(_skill_dirs())
    commands = set(_command_stems())
    orphans = skills - commands
    assert not orphans, (
        f"Skills missing slash command entry: {sorted(orphans)}. "
        f"Add commands/<name>.md."
    )


# ===== frontmatter validity =====

@pytest.mark.parametrize("skill", _skill_dirs())
def test_skill_frontmatter_valid(skill):
    """Each SKILL.md has parseable YAML frontmatter with name + description."""
    fm = _frontmatter(skill)
    assert "name" in fm, f"{skill}: frontmatter missing 'name'"
    assert "description" in fm, f"{skill}: frontmatter missing 'description'"
    assert fm["name"] == skill, (
        f"{skill}: frontmatter name '{fm['name']}' != directory name '{skill}'"
    )
    desc = fm["description"]
    assert isinstance(desc, str) and desc.strip(), (
        f"{skill}: description must be a non-empty string"
    )


@pytest.mark.parametrize("skill", _skill_dirs())
def test_skill_description_within_anthropic_ceiling(skill):
    """Description must be ≤ 1024 chars (Anthropic Agent Skills spec hard ceiling).

    description-design.md notes the practical target is 100-250 chars with a
    self-imposed ~500 char soft ceiling. We enforce only the hard limit here.
    """
    fm = _frontmatter(skill)
    desc_len = len(fm["description"])
    assert desc_len <= 1024, (
        f"{skill}: description {desc_len} chars exceeds Anthropic 1024-char hard ceiling"
    )


# ===== dead skill references =====

def test_no_dead_skill_references():
    """Markdown files must not reference skills that don't exist.

    Catches the classic refactor failure: a skill is deleted but a 'See also'
    table or a description still mentions it. Scans tracked .md files for
    `redshift-X` identifiers and verifies each one is either a real skill
    or a known non-skill name (the plugin itself, etc.).
    """
    valid_names = set(_skill_dirs()) | NON_SKILL_VALID_NAMES

    # Match `redshift-` followed by identifier chars, but NOT when preceded by
    # `.` — that form (e.g. `.redshift-wiki/`) is a negative documentation
    # reference to a hypothetical external thing, not a real skill / command.
    skill_ref_re = re.compile(r"(?<![.])redshift-[a-z0-9_-]+")

    files_to_scan = [
        *REPO_ROOT.glob("README*.md"),
        *SKILLS_DIR.glob("**/*.md"),
        *COMMANDS_DIR.glob("*.md"),
    ]

    failures = []
    for path in files_to_scan:
        text = path.read_text()
        for match in skill_ref_re.finditer(text):
            ref = match.group(0)
            if ref in valid_names:
                continue
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            ctx = text[start:end].replace("\n", " ")
            failures.append(
                f"  {path.relative_to(REPO_ROOT)}: invalid reference '{ref}' "
                f"-- context: ...{ctx}..."
            )

    assert not failures, "Dead skill references found:\n" + "\n".join(failures)


# ===== version sync =====

def test_pyproject_plugin_version_sync():
    """pyproject.toml fallback_version must match plugin.json version.

    Both must be bumped together when releasing — this catches the case where
    one is updated and the other forgotten.
    """
    pyproject_text = PYPROJECT.read_text()
    m = re.search(r'^fallback_version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
    assert m, "fallback_version not found in pyproject.toml [tool.setuptools_scm]"
    pyproject_version = m.group(1)

    plugin = json.loads(PLUGIN_JSON.read_text())
    plugin_version = plugin["version"]

    assert pyproject_version == plugin_version, (
        f"Version drift: pyproject.toml fallback_version={pyproject_version!r} "
        f"vs plugin.json version={plugin_version!r}. Bump both together."
    )


def test_mcpb_manifest_version_matches_sources(tmp_path):
    """The generated .mcpb manifest version must match the version SSOT.

    The .mcpb bundle is a 4th distribution surface. Its manifest is GENERATED
    (scripts/generate_mcpb_manifest.py) from the root pyproject fallback_version
    so it cannot drift. This guards that invariant: regenerating into a tmp dir
    yields a manifest whose `version` equals BOTH the pyproject fallback_version
    (read the same regex way as test_pyproject_plugin_version_sync) and the
    plugin.json version.
    """
    import importlib.util

    gen_path = REPO_ROOT / "scripts" / "generate_mcpb_manifest.py"
    spec = importlib.util.spec_from_file_location("generate_mcpb_manifest", gen_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.generate(repo_root=REPO_ROOT, out_dir=tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest_version = manifest["version"]

    pyproject_text = PYPROJECT.read_text()
    m = re.search(r'^fallback_version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
    assert m, "fallback_version not found in pyproject.toml [tool.setuptools_scm]"
    pyproject_version = m.group(1)

    plugin_version = json.loads(PLUGIN_JSON.read_text())["version"]

    assert manifest_version == pyproject_version, (
        f"Generated .mcpb manifest version={manifest_version!r} drifted from "
        f"pyproject.toml fallback_version={pyproject_version!r}."
    )
    assert manifest_version == plugin_version, (
        f"Generated .mcpb manifest version={manifest_version!r} drifted from "
        f"plugin.json version={plugin_version!r}."
    )


# ===== D2 reversed (v0.8.0): connection-field userConfig contract =====
#
# D2 (commit 3884f98, v0.4.0) removed userConfig because Claude Code then
# had NO secret type — a password would land plaintext in settings.json.
# Claude Code has SINCE added `sensitive: true` (→ OS keychain), so we
# consciously REVERSE D2 and re-add *connection-field* userConfig
# (host/port/user/dbname + password as `sensitive`). This is intentional,
# not a regression — see memory project_d2_userconfig_reversal and
# docs/loom/specs/2026-06-11-plugin-userconfig.md.
#
# These tests now guard the REVERSED contract: userConfig MUST exist with
# the 5 connection fields, password MUST be `sensitive`, mcpServers args
# MUST inject the 4 non-secret fields via ${user_config.*}, and env MUST
# inject REDSHIFT_PASSWORD. The server still resolves the profile itself,
# so a pinned --profile flag remains forbidden.


def test_plugin_manifest_has_connection_userconfig():
    """D2 reversed: plugin.json MUST declare a connection-field userConfig.

    Re-added on 2026-06-11 once Claude Code gained `sensitive: true`
    (password → OS keychain, not plaintext settings.json). The five
    connection fields are prompted at enable time and substituted into
    mcpServers. See memory project_d2_userconfig_reversal."""
    plugin = json.loads(PLUGIN_JSON.read_text())
    assert "userConfig" in plugin, (
        "plugin.json must declare a top-level userConfig block (D2 reversed "
        "in v0.8.0). See memory project_d2_userconfig_reversal."
    )
    user_config = plugin["userConfig"]
    for key in ("host", "port", "user", "dbname", "password"):
        assert key in user_config, (
            f"userConfig missing connection field {key!r}: {sorted(user_config)}"
        )
    assert user_config["password"]["sensitive"] is True, (
        "userConfig.password must set `sensitive: true` so it routes to the "
        "OS keychain — this is the sole condition that unblocked the D2 "
        "reversal (plaintext password in settings.json was D2's blocker)."
    )
    for key, field in user_config.items():
        for prop in ("title", "description"):
            value = field.get(prop, "")
            assert isinstance(value, str) and value.strip(), (
                f"userConfig.{key} must have a non-empty {prop!r} for the "
                f"enable-time dialog; got {value!r}."
            )


def test_plugin_manifest_mcp_args_inject_userconfig_no_profile_flag():
    """D2 reversed: mcpServers must inject the 4 non-secret connection
    fields via ${user_config.*} and the password via env REDSHIFT_PASSWORD,
    while still NOT pinning a --profile (server resolves profile itself)."""
    plugin = json.loads(PLUGIN_JSON.read_text())
    server = plugin.get("mcpServers", {}).get("redshift-comment", {})
    args = server.get("args", [])
    assert "--profile" not in args, (
        f"mcpServers.redshift-comment.args still contains --profile: {args!r}. "
        f"The server resolves the active profile via env > pointer file > "
        f"'default' fallback; pinning --profile re-couples the manifest to a "
        f"profile-name userConfig (the D2-era indirection we did NOT re-add)."
    )
    for key in ("host", "port", "user", "dbname"):
        token = f"${{user_config.{key}}}"
        assert token in args, (
            f"mcpServers args must inject {token} for the {key} connection "
            f"field; got {args!r}."
        )
    env = server.get("env", {})
    assert env.get("REDSHIFT_PASSWORD") == "${user_config.password}", (
        f"mcpServers.redshift-comment.env must inject REDSHIFT_PASSWORD from "
        f"${{user_config.password}} (the server's inline-mode password "
        f"channel); got env={env!r}."
    )


def test_plugin_manifest_default_disabled():
    """Opt-in install: an external-service connector MUST ship
    `defaultEnabled: false` so it installs DISABLED and the user enables it
    deliberately — the moment the userConfig connection dialog appears.

    Grounded in fail-safe defaults (disable what connects out / costs money
    by default) and Claude Code's own guidance — `defaultEnabled: false` is
    recommended "for plugins that connect to an external service"
    (plugins-reference §Default enablement). The field exists since Claude
    Code v2.1.154; older clients ignore it and install enabled (the
    pre-existing behavior), so setting it is downside-free."""
    plugin = json.loads(PLUGIN_JSON.read_text())
    assert plugin.get("defaultEnabled") is False, (
        "plugin.json must set `defaultEnabled: false` — this plugin spawns an "
        "MCP server that connects to Redshift (an external service), so it "
        "should install disabled and be enabled opt-in. "
        f"Got defaultEnabled={plugin.get('defaultEnabled')!r}."
    )


# ===== README trilingual parity =====

@pytest.mark.parametrize("skill", _skill_dirs())
def test_skill_readme_trilingual_or_none(skill):
    """Each skill has either all 3 README languages (en/ja/zh-TW) or none.

    Prevents the case where one language is added/updated and the other two
    drift out of sync.
    """
    if skill in NO_README_SKILLS:
        pytest.skip(f"{skill} is internal-only; READMEs not expected")

    skill_dir = SKILLS_DIR / skill
    en = (skill_dir / "README.md").exists()
    ja = (skill_dir / "README.ja.md").exists()
    zh = (skill_dir / "README.zh-TW.md").exists()

    counts = sum([en, ja, zh])
    assert counts in (0, 3), (
        f"{skill}: README languages out of sync — "
        f"README.md={en}, README.ja.md={ja}, README.zh-TW.md={zh}. "
        f"Add the missing ones or remove all."
    )


# ===== the profile store is documented as machine-managed =====

# Every write to config.toml rewrites the whole file from the profiles that
# were read, so hand-written comments and any key this project does not
# recognise are dropped. That is the decided behaviour, not a defect — which
# only holds up if the person about to hand-edit the file is told first.
#
# Each language carries its own anchor because these are three idiomatic
# READMEs, not one wording translated literally; the anchors pin the two facts
# that must survive a rewrite (writes come only from this project's tools, and
# what a hand edit therefore loses) rather than the sentence around them.
MACHINE_MANAGED_ANCHORS = {
    "README.md": [
        "written only by this project's own tools",
        "dropped on the next write",
    ],
    "README.ja.md": [
        "本プロジェクト自身のツールだけが書き込みます",
        "次の書き込みで失われます",
    ],
    "README.zh-TW.md": [
        "只由本專案自己的工具寫入",
        "下一次寫入時被丟棄",
    ],
}

# W0-02 put a lock file beside config.toml. A person who finds a new file in
# their own config directory has to be able to look it up.
LOCK_FILE_NAME = "config.toml.lock"


@pytest.mark.parametrize("readme", sorted(MACHINE_MANAGED_ANCHORS))
def test_readme_documents_machine_managed_store(readme):
    """All three READMEs say the profile store is written by tooling only."""
    text = (REPO_ROOT / readme).read_text()

    missing = [a for a in MACHINE_MANAGED_ANCHORS[readme] if a not in text]
    assert not missing, (
        f"{readme} no longer documents config.toml as machine-managed. "
        f"Missing: {missing}. Someone about to hand-edit the store must be "
        f"told there that the next write drops their edits; if the wording "
        f"changed on purpose, update MACHINE_MANAGED_ANCHORS to match."
    )

    assert LOCK_FILE_NAME in text, (
        f"{readme} does not mention {LOCK_FILE_NAME}. It appears in every "
        f"user's config directory as soon as a profile is written or deleted, "
        f"so it has to be findable in the docs."
    )


# ===== W0-04/W0-06: manifest + READMEs must state the ACTUAL blank-password
# rule =====
#
# Acceptance line 6. The bug this pins: plugin.json's password field said a
# blank password "use[s] a profile password configured via /redshift-setup"
# while README.md said the opposite fifty lines away — two exclusive paths,
# and ALL FOUR fields had to be blank for the profile path. The code
# followed the README: filling host/user/dbname and leaving only the
# password blank raised (server.py:116-119, pre-W0-01), even when
# config.toml + keychain already held a profile for exactly that host, user
# and dbname. That contradiction is what produced the 2026-09-17 bug report.
#
# W0-01 first landed this as an IDENTITY MATCH on three fields (host, user,
# dbname), with port deliberately excluded, and W0-04 documented that rule.
# A fresh-context adversary then showed the exclusion itself was a bug: a
# password provisioned for host:5439 could be lent to a launch naming
# host:9999 on the same host. kouko closed it the same day (2026-09-21,
# amendment note on Acceptance 1/2 in the intent) by widening the match to
# the full FOUR-FIELD target — host, port, user AND dbname must all equal
# what was typed — and W0-05 changed the code to match. The connection
# still targets the typed values, never the profile's, and a mismatch
# refuses, naming the typed target and each existing profile's target
# (including its port) instead of silently substituting a different one.
# Leaving every field blank remains the separate, unchanged all-profile
# path. This is W0-06: restate the four-field rule in the same four files.
#
# Each anchor below is copied verbatim from this task's own prose in the
# four files, and picked so it can ONLY be true of the four-field rule: a
# docs edit that reverts to the old "two exclusive paths" story, or back to
# the three-field/port-excluded story, still contains words like "profile"
# and "blank" (a bare keyword check would miss the regression) but drops
# "host, port, user and dbname all match" / the refusal language, so it
# fails here. Each language is its own idiom, not a literal translation —
# same convention as MACHINE_MANAGED_ANCHORS above. If the wording changes
# on purpose, update these anchors to match, and check the other three
# files still say the same thing; that's what "agree" means here, not
# identical text.
#
# What this WOULD catch: any one of the four docs reverting to (or drifting
# into) a rule that no longer requires all FOUR fields to match, or that
# stops describing a refusal on no match.
# What this would NOT catch: a paraphrase that keeps every one of these
# facts but uses none of the exact pinned substrings (same limitation as
# MACHINE_MANAGED_ANCHORS — the fix is to update the anchor, not to accept
# silent drift); nor would it catch the code itself changing while the docs
# (and these anchors) stay put, since this test never imports server.py.

BLANK_PASSWORD_RULE_ANCHORS = {
    ".claude-plugin/plugin.json": [
        "host, port, user and dbname all match",
        "leave every field blank",
    ],
    "README.md": [
        "host, port, user **and** dbname all match",
        "the connection refuses",
    ],
    "README.ja.md": [
        "host・port・user・dbname がすべて一致",
        "接続を拒否し",
    ],
    "README.zh-TW.md": [
        "host、port、user、dbname 四者都對得上",
        "連線會直接拒絕",
    ],
}


@pytest.mark.parametrize("doc", sorted(BLANK_PASSWORD_RULE_ANCHORS))
def test_blank_password_rule_stated_consistently(doc):
    """A6 positive: the manifest and all 3 READMEs state the SAME
    blank-password rule — the four-field identity-match borrow the code
    actually runs (W0-05), not the old two-exclusive-paths story it never
    implemented, and not the three-field/port-excluded story W0-01/W0-04
    shipped before the 2026-09-21 amendment."""
    path = REPO_ROOT / doc
    text = path.read_text()

    missing = [a for a in BLANK_PASSWORD_RULE_ANCHORS[doc] if a not in text]
    assert not missing, (
        f"{doc} no longer states the four-field identity-match "
        f"blank-password rule (host+port+user+dbname must all match; no "
        f"match refuses). Missing: {missing}. If the wording changed on "
        f"purpose, update BLANK_PASSWORD_RULE_ANCHORS to match — and check "
        f"the other three docs still describe the same rule."
    )


# ===== W0-06 negative: no document may still claim port is excluded =====
#
# The positive test above only fails when a required phrase goes missing;
# it would not notice someone re-adding a *contradicting* sentence
# alongside a technically-still-present anchor (e.g. restoring "Port is not
# part of the match" right next to "host, port, user and dbname all
# match"). W0-04 put that exact exclusion claim in each of the three
# READMEs, one idiom per language; this is the literal text that made the
# 2026-09-19 adversary probe's attack possible, so it must never come back.
#
# This is a phrase blacklist, and phrase blacklists are brittle by nature:
# a rewrite that expresses the same excluded-port claim without reusing one
# of these exact substrings (e.g. "the listener isn't checked") would slip
# through silently. That is the same class of limitation
# BLANK_PASSWORD_RULE_ANCHORS already accepts for its positive claims, and
# it is worth shipping here for the same reason — it is cheap, it fails
# loudly on an exact revert (the most likely accident: reverting a hunk,
# copy-pasting old prose back in, or a merge picking up a stale branch),
# and it names the exact three sentences this task deleted, so anyone who
# defeats it by paraphrasing has to do so on purpose.
PORT_EXCLUDED_PHRASES = {
    "README.md": ["Port is not part of the match"],
    "README.ja.md": ["port は一致条件に含まれません"],
    "README.zh-TW.md": ["port 不算在比對條件內"],
    # plugin.json never carried an exclusion sentence (W0-04 left it silent
    # on port rather than wrong about it), but a future edit could still
    # introduce one while adding the four-field statement, so it is checked
    # too rather than assumed safe by omission.
    ".claude-plugin/plugin.json": ["port is not part of the match"],
}


@pytest.mark.parametrize("doc", sorted(PORT_EXCLUDED_PHRASES))
def test_blank_password_rule_no_longer_excludes_port(doc):
    """A6 negative: no document may claim port is excluded from the match.

    Case-insensitive substring check, since the manifest's own phrasing (if
    it were ever re-added) would likely not match the READMEs' capitalization
    exactly.
    """
    path = REPO_ROOT / doc
    lowered = path.read_text().lower()

    found = [p for p in PORT_EXCLUDED_PHRASES[doc] if p.lower() in lowered]
    assert not found, (
        f"{doc} still contains a port-excluded-from-the-match claim: "
        f"{found}. Since W0-05 the match is on host, port, user AND "
        f"dbname; a profile recorded at a different port must not lend its "
        f"password to a launch naming a different port on the same host. "
        f"If this is a deliberate design reversal, update "
        f"PORT_EXCLUDED_PHRASES (and BLANK_PASSWORD_RULE_ANCHORS) together, "
        f"and re-check server.py actually excludes port again."
    )


# ===== W0-12: the tie refusal (Acceptance 8) must be documented too, and
# the manifest must stop inviting a partially-blank dialog =====
#
# W0-08/W0-09 gave the borrow rule a SECOND refusal, after W0-06 above had
# already closed the docs task for the first one: when MORE THAN ONE stored
# profile matches the whole four-field launch target, the server refuses
# and names every tied candidate instead of picking one — the shape a
# credential rotation leaves behind (the retired profile kept alongside its
# replacement, same target). Every surface a person or an agent reads
# before anything happens said nothing about it: the manifest's password
# field, all three READMEs, and the FastMCP `instructions` string every MCP
# client receives before it can call a tool. TIE_REFUSAL_ANCHORS plus
# test_tie_refusal_documented_in_instructions_string pin one clause per
# surface, the same convention as BLANK_PASSWORD_RULE_ANCHORS above — each
# language is its own idiom, not a literal translation of the other two.
#
# A second, independent defect lived in the same manifest file:
# plugin.json's `host`, `user` and `dbname` field descriptions still read
# "Leave blank to use a profile configured via /redshift-setup" — true only
# when ALL FOUR fields are blank. Reproduced against the running server on
# 2026-09-21: typing user + dbname and leaving only host blank connects to
# the ACTIVE PROFILE's host, user AND dbname, silently discarding both
# typed values, not just the blank one.
# test_manifest_connection_fields_no_longer_invite_partial_blank pins that
# the old, incomplete phrasing is gone from those three fields. The fix is
# textual only — the resolver itself is unchanged; honouring partial input
# is a separate change with its own intent, not this task.
#
# Deferred on purpose, for the second round in a row: both the
# fresh-context docs reviewer and this task independently concluded the
# durable fix is to derive what these docs SHOULD say from the running
# code rather than pin more prose by hand — the pattern already exists in
# this repo as probe_status_shape_consumers.py's
# `_fields_the_code_matches_on` (varies one target field at a time against
# a provisioned profile to recover the borrow rule's field set by
# experiment) composed with `fields_named_in_borrow_rule` (extracts what a
# piece of prose actually claims, so the two can be compared instead of
# eyeballed). Promoting that pattern into tests/ — so this anchor dict,
# BLANK_PASSWORD_RULE_ANCHORS, and PORT_EXCLUDED_PHRASES all derive their
# expectation instead of hand-pinning it — is real new test
# infrastructure, not a fix to this task's own defects, and this review is
# round 2 of a bounded 3-round budget: spending it on infrastructure risks
# a third rejection over scope rather than over the defects themselves. It
# is recorded here, not merely decided, so a future reader does not have to
# re-derive why these anchors are still hand-pinned after two rounds of the
# same reviewer note.

TIE_REFUSAL_ANCHORS = {
    ".claude-plugin/plugin.json": [
        "more than one profile matches",
        "naming every tied candidate",
    ],
    "README.md": [
        "more than one matches",
        "every tied candidate",
    ],
    "README.ja.md": [
        "プロファイルが 2 つ以上あった場合",
        "候補をすべて挙げます",
    ],
    "README.zh-TW.md": [
        "不只一個 profile 四者都對得上",
        "列出每一個對得上的候選",
    ],
}


@pytest.mark.parametrize("doc", sorted(TIE_REFUSAL_ANCHORS))
def test_tie_refusal_documented(doc):
    """A6/A8 positive: the manifest and all 3 READMEs document the SECOND
    refusal — more than one stored profile matching the four-field target
    also refuses, naming every tied candidate — gained in W0-08/W0-09 after
    W0-06 had already closed the docs task for the first (no-match)
    refusal."""
    path = REPO_ROOT / doc
    text = path.read_text()

    missing = [a for a in TIE_REFUSAL_ANCHORS[doc] if a not in text]
    assert not missing, (
        f"{doc} does not document the tie refusal (more than one stored "
        f"profile matching the four-field target also refuses, naming "
        f"every tied candidate). Missing: {missing}. If the wording "
        f"changed on purpose, update TIE_REFUSAL_ANCHORS to match — and "
        f"check the other three docs plus the FastMCP instructions string "
        f"still describe the same rule."
    )


INSTRUCTIONS_TIE_REFUSAL_ANCHORS = [
    "MORE THAN ONE",
    "names every tied candidate",
]


def test_tie_refusal_documented_in_instructions_string():
    """A8 boundary: the FastMCP `instructions` string — the one surface
    every MCP client reads before calling anything — also names the tie
    refusal, not just the manifest and READMEs a person reads on request.

    Reads the live ``tools.mcp.instructions`` attribute the built server
    actually carries, the same way
    ``tests/test_tools.py::TestNoToolDescriptionRecommendsThePasswordFlag``
    does — not ``redshift_tools.py`` as text. A text/grep scan of the whole
    file passes as long as the anchor phrases live anywhere in the file,
    including a comment or docstring that never reaches the built
    ``instructions`` string; only the live attribute pins the surface this
    test's own docstring claims to pin.
    """
    from redshift_comment_mcp.config import ConfigurationError
    from redshift_comment_mcp.redshift_tools import RedshiftTools

    def provider():
        raise ConfigurationError("doesn't matter — instructions text is static")

    tools = RedshiftTools(provider)
    instructions = tools.mcp.instructions or ""

    assert instructions.strip(), (
        "FastMCP server exposes no non-empty `instructions` string; this "
        "guard cannot pin what it does not receive."
    )

    missing = [a for a in INSTRUCTIONS_TIE_REFUSAL_ANCHORS if a not in instructions]
    assert not missing, (
        f"the live FastMCP instructions string does not document the tie "
        f"refusal. Missing: {missing}. An agent that was never told this "
        f"rule has no way to react to it beyond retrying blindly."
    )


PARTIAL_BLANK_INVITATION_FIELDS = ("host", "user", "dbname")
PARTIAL_BLANK_INVITATION_PHRASE = (
    "Leave blank to use a profile configured via /redshift-setup"
)


def test_manifest_connection_fields_no_longer_invite_partial_blank():
    """A6 negative: plugin.json's host/user/dbname descriptions must not
    still read the old, incomplete "Leave blank to use a profile..." line.

    That phrasing is true only when ALL FOUR fields are blank; filling two
    of the three and leaving the third blank falls back to the active
    profile's host, user AND dbname wholesale, silently discarding what was
    typed in the other two (reproduced against the running server,
    2026-09-21). This is a docs-only fix — the resolver is unchanged; each
    of the three descriptions must instead state the whole-set rule.
    """
    plugin = json.loads(PLUGIN_JSON.read_text())
    user_config = plugin["userConfig"]

    offenders = [
        field for field in PARTIAL_BLANK_INVITATION_FIELDS
        if PARTIAL_BLANK_INVITATION_PHRASE in user_config[field]["description"]
    ]
    assert not offenders, (
        f"plugin.json userConfig field(s) {offenders} still invite leaving "
        f"just one of host/user/dbname blank, which silently discards "
        f"whatever was typed into the other two. Rewrite to state that the "
        f"three fields are blank together or not at all."
    )


# ===== W0-15 defect 2: the fix above must not itself contradict the
# password field's own description in the same file. =====
#
# The task that produced test_manifest_connection_fields_no_longer_invite_
# partial_blank above rewrote host/user/dbname's descriptions to say "This
# field, user, dbname AND PASSWORD are blank together or not at all" —
# widening the three-field blank-together set to four. But the password
# field's own description says a blank password alone borrows a matching
# profile's stored password (the headline feature of this whole change),
# which is only possible if password can be blank while host/user/dbname
# are NOT. Two fields of the same manifest then stated opposite rules —
# precisely the contradiction this change exists to close, reintroduced by
# its own docs fix.
#
# This test isolates the field-list ENUMERATION that immediately precedes
# the phrase "are blank together or not at all" — e.g. "This field, user
# and dbname " — and asserts it does not name `password`. It deliberately
# does NOT forbid `password` from appearing anywhere later in the same
# description: the consequence clause ("...falls back to that profile
# wholesale and ignores whatever you typed into ... password") is correct
# and required (defect 2's own fix bullets), and a whole-sentence check
# would false-positive on it since the enumeration and the consequence
# clause share one run-on sentence separated only by a colon, not a
# period. Isolating on the nearest preceding sentence boundary (". ", or
# start of string) keeps the check narrow to the actual claim being made:
# which fields form the "blank together" SET, not which fields a partial
# blank discards.
#
# It does not touch the password description (correct, and out of scope),
# and it does not re-check the partial-blank warning itself (the test
# above already pins that).
#
# What this WOULD catch: `password` reappearing in the field-list
# enumeration for any of the three fields, in this or a differently-worded
# future edit that still uses the phrase "are blank together or not at
# all". What this can still miss: a rewrite that drops that exact phrase
# while still, in different words, claiming password belongs to the same
# all-or-nothing set (e.g. "leave host, user, dbname and password blank as
# one group") — the isolation is keyed on the exact phrase, so a
# paraphrase that avoids it slips through, the same class of gap
# MACHINE_MANAGED_ANCHORS and BLANK_PASSWORD_RULE_ANCHORS above already
# accept. It also would not catch the reverse contradiction (the password
# description itself claiming it cannot be blank alone) since that
# description is deliberately not scanned here.

BLANK_TOGETHER_PHRASE = "are blank together or not at all"


def _enumeration_before_blank_together(desc: str) -> str:
    """Return the field-list clause immediately preceding
    ``BLANK_TOGETHER_PHRASE``, from the nearest preceding sentence
    boundary (". ") or the start of the description — never crossing into
    an earlier sentence (e.g. a host description's own "e.g. ..." example
    clause)."""
    idx = desc.find(BLANK_TOGETHER_PHRASE)
    assert idx != -1, f"{BLANK_TOGETHER_PHRASE!r} not found in {desc!r}"
    prefix = desc[:idx]
    boundary = prefix.rfind(". ")
    start = boundary + 2 if boundary != -1 else 0
    return prefix[start:]


@pytest.mark.parametrize("field", PARTIAL_BLANK_INVITATION_FIELDS)
def test_manifest_blank_together_set_excludes_password(field):
    """host/user/dbname's 'are blank together or not at all' claim must
    enumerate only the OTHER TWO of host/user/dbname — never password,
    which the password field's own description says CAN be left blank on
    its own (the borrow path, the headline feature of this whole change).
    Naming password in this set contradicts that description in the same
    file."""
    plugin = json.loads(PLUGIN_JSON.read_text())
    desc = plugin["userConfig"][field]["description"]

    assert BLANK_TOGETHER_PHRASE in desc, (
        f"{field}: description no longer states the 'blank together or "
        f"not at all' rule at all — expected it to name the other two of "
        f"host/user/dbname as the set that must be blank together."
    )
    enumeration = _enumeration_before_blank_together(desc)
    assert "password" not in enumeration.lower(), (
        f"{field}: the field-list enumeration right before 'are blank "
        f"together or not at all' still names `password`: {enumeration!r}. "
        f"host, user and dbname are that set; password can be left blank "
        f"on its own, so including it here contradicts the password "
        f"field's own description."
    )
