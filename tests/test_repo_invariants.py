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


# ===== D2 reversed (v0.8.0): connection-field userConfig contract =====
#
# D2 (commit 3884f98, v0.4.0) removed userConfig because Claude Code then
# had NO secret type — a password would land plaintext in settings.json.
# Claude Code has SINCE added `sensitive: true` (→ OS keychain), so we
# consciously REVERSE D2 and re-add *connection-field* userConfig
# (host/port/user/dbname + password as `sensitive`). This is intentional,
# not a regression — see memory project_d2_userconfig_reversal and
# docs/code-toolkit/specs/2026-06-11-plugin-userconfig.md.
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
