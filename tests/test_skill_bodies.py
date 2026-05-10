"""Body-level tests for redshift-setup and redshift-switch-profile skills.

The skills' SKILL.md files are prose-only artifacts whose embedded
``python <<'PYEOF' ... PYEOF`` heredocs are otherwise unexercised by the
test suite. These tests:

  - Parse every heredoc out of SKILL.md and verify it compiles after
    substituting ``<NAME>`` placeholders with a real value.
  - Exec the active-profile heredocs in-process against ``tmp_xdg``
    fixtures and assert the pointer-file state matches expectation
    (canonical "single-profile state ↔ no pointer file" rule).
  - Cross-check that every CLI subcommand referenced in skill bodies
    exists in ``setup_cli.py``.
  - Verify reference files mandated by Step 4 of redshift-setup exist.
  - Catch regression of legacy ``settings.json`` / ``pluginConfigs`` /
    ``userConfig`` references that should have been ripped out in the
    D2 refactor.

These tests do NOT exercise:
  - Actual chat-driven flow (Claude behavior, not testable in pytest)
  - Bash recipes that need a real Redshift cluster
  - The keychain / osascript / zenity password handoff (GUI-bound)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from redshift_comment_mcp import config

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
SETUP_SKILL = SKILLS_DIR / "redshift-setup" / "SKILL.md"
SWITCH_SKILL = SKILLS_DIR / "redshift-switch-profile" / "SKILL.md"
SETUP_CLI = REPO_ROOT / "src" / "redshift_comment_mcp" / "setup_cli.py"

# Subcommands the skills assume exist in `redshift-comment-mcp` CLI.
EXPECTED_CLI_SUBCOMMANDS = {
    "set-fields",
    "set-password",
    "test-connection",
    "list-profiles",
    "setup",
    "delete-profile",
}


# ===== helpers =====


def _extract_python_heredocs(skill_path: Path) -> list[str]:
    """Return every Python source block delimited by ``<<'PYEOF' ... PYEOF``."""
    text = skill_path.read_text()
    pattern = re.compile(r"<<'PYEOF'\n(.*?)\nPYEOF", re.DOTALL)
    return pattern.findall(text)


def _substitute_placeholder(src: str, name: str = "test_profile") -> str:
    """Replace `"<NAME>"` placeholders with a concrete validated name."""
    return src.replace('"<NAME>"', f'"{name}"')


@pytest.fixture
def tmp_xdg(tmp_path, monkeypatch):
    """Redirect XDG_CONFIG_HOME so heredoc exec doesn't touch real config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


# ===== syntactic validity (both skills) =====


@pytest.mark.parametrize("skill_path", [SETUP_SKILL, SWITCH_SKILL], ids=["setup", "switch"])
def test_python_heredocs_compile_after_placeholder_substitution(skill_path):
    """Every PYEOF heredoc must compile after substituting `<NAME>`."""
    blocks = _extract_python_heredocs(skill_path)
    assert blocks, f"{skill_path.name}: no PYEOF heredocs found — SKILL.md structure changed?"
    for i, src in enumerate(blocks):
        substituted = _substitute_placeholder(src, name="prod")
        try:
            compile(substituted, f"<{skill_path.parent.name}#{i}>", "exec")
        except SyntaxError as e:
            pytest.fail(
                f"{skill_path.parent.name} PYEOF block #{i} has syntax error: {e}\n"
                f"---\n{substituted}"
            )


# ===== legacy reference rot guard =====


@pytest.mark.parametrize(
    "skill_path,expected_clean",
    [
        (SETUP_SKILL, ["pluginConfigs", "userConfig.profile", "${user_config", "settings.json"]),
        (SWITCH_SKILL, ["pluginConfigs", "userConfig.profile", "${user_config", "settings.json"]),
    ],
    ids=["setup", "switch"],
)
def test_no_legacy_settings_json_references(skill_path, expected_clean):
    """D2 refactor removed all settings.json plumbing — guard against rot."""
    text = skill_path.read_text()
    leaks = [token for token in expected_clean if token in text]
    assert not leaks, (
        f"{skill_path.parent.name}: legacy tokens remain after D2 refactor: "
        f"{leaks}. The skill should reference active-profile pointer file only."
    )


# ===== CLI subcommand contract =====


def _setup_cli_text() -> str:
    return SETUP_CLI.read_text()


@pytest.mark.parametrize("cmd", sorted(EXPECTED_CLI_SUBCOMMANDS))
def test_cli_subcommand_exists(cmd):
    """Every subcommand the skills call must be registered in setup_cli.py."""
    cli_src = _setup_cli_text()
    pat = re.compile(rf'add_parser\(\s*["\']' + re.escape(cmd) + r'["\']')
    assert pat.search(cli_src), (
        f"setup_cli.py has no `add_parser(\"{cmd}\")` — skill body references it"
    )


@pytest.mark.parametrize("skill_path", [SETUP_SKILL, SWITCH_SKILL], ids=["setup", "switch"])
def test_skill_only_calls_known_subcommands(skill_path):
    """Every `redshift-comment-mcp <subcommand>` invocation in a skill body
    must reference a known subcommand. Catches typos / drift."""
    text = skill_path.read_text()
    # Strip YAML frontmatter — its prose may wrap "redshift-comment-mcp"
    # across a newline onto innocent English filler ("plugin", "via", ...)
    # and false-positive against the regex.
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    # Match `redshift-comment-mcp <word>` invocations.
    pattern = re.compile(r"redshift-comment-mcp\s+([a-z][a-z0-9-]*)\b")
    referenced = set(pattern.findall(body))
    unknown = referenced - EXPECTED_CLI_SUBCOMMANDS
    assert not unknown, (
        f"{skill_path.parent.name} references unknown CLI subcommands: {unknown}. "
        f"Either add to setup_cli.py or fix the skill text."
    )


# ===== reference file existence (redshift-setup Step 4) =====


def test_password_reference_files_exist():
    """Step 4 mandates reading one of three reference files; all must exist."""
    refs_dir = SETUP_SKILL.parent / "references"
    for name in ("password-macos.md", "password-zenity.md", "password-terminal-handoff.md"):
        assert (refs_dir / name).exists(), (
            f"redshift-setup Step 4 mandates reading {name} but file is missing"
        )


def test_setup_skill_references_match_existing_files():
    """Every `references/X.md` mentioned in setup SKILL.md must exist on disk."""
    refs_dir = SETUP_SKILL.parent / "references"
    text = SETUP_SKILL.read_text()
    pat = re.compile(r"references/([a-z][a-z0-9-]+\.md)")
    referenced = set(pat.findall(text))
    for name in referenced:
        assert (refs_dir / name).exists(), (
            f"redshift-setup SKILL.md references references/{name} but file is missing"
        )


# ===== active-profile heredoc behavior (redshift-setup Step 6 + redshift-switch Step 5) =====


def _heredoc_for(skill_path: Path, predicate) -> str:
    """Return the first heredoc whose source matches the predicate."""
    blocks = _extract_python_heredocs(skill_path)
    matches = [src for src in blocks if predicate(src)]
    assert len(matches) == 1, (
        f"{skill_path.parent.name}: expected exactly 1 heredoc matching predicate, "
        f"got {len(matches)}"
    )
    return matches[0]


def _has_pointer_apply(src: str) -> bool:
    """Heredoc branches on NAME == 'default' to clear vs write the pointer."""
    return "clear_active_profile" in src and "write_active_profile" in src


def _is_setup_branch_a(src: str) -> bool:
    """Setup Step 6 Branch A — print message marks single-profile-state canon."""
    return _has_pointer_apply(src) and "single-profile state" in src


def _is_pointer_apply_without_canon(src: str) -> bool:
    """Setup Branch B yes-path AND switch Step 5 share this shape."""
    return _has_pointer_apply(src) and "single-profile state" not in src


def _is_read_active_profile_heredoc(src: str) -> bool:
    return "read_active_profile" in src and "write_active_profile" not in src


def test_setup_branch_a_default_clears_pointer(tmp_xdg):
    """Branch A heredoc with NAME='default' must remove any stale pointer file."""
    config.write_active_profile("stale-prior-state")
    assert config.read_active_profile() == "stale-prior-state"

    src = _heredoc_for(SETUP_SKILL, _is_setup_branch_a)
    substituted = _substitute_placeholder(src, name="default")
    exec(compile(substituted, "<setup-branch-a-default>", "exec"), {})

    assert config.read_active_profile() is None, (
        "Branch A with NAME='default' must clear the pointer file (canonical "
        "single-profile state ↔ no file)."
    )


def test_setup_branch_a_named_writes_pointer(tmp_xdg):
    """Branch A heredoc with NAME='prod' must write the pointer file."""
    assert config.read_active_profile() is None  # baseline

    src = _heredoc_for(SETUP_SKILL, _is_setup_branch_a)
    substituted = _substitute_placeholder(src, name="prod")
    exec(compile(substituted, "<setup-branch-a-named>", "exec"), {})

    assert config.read_active_profile() == "prod"


def test_setup_branch_b_apply_yes_path(tmp_xdg):
    """Branch B yes-path heredoc must write or clear the pointer."""
    src = _heredoc_for(SETUP_SKILL, _is_pointer_apply_without_canon)

    # NAME='dev' should write
    substituted = _substitute_placeholder(src, name="dev")
    exec(compile(substituted, "<setup-branch-b-named>", "exec"), {})
    assert config.read_active_profile() == "dev"

    # NAME='default' should clear (returning to single-profile state)
    substituted = _substitute_placeholder(src, name="default")
    exec(compile(substituted, "<setup-branch-b-default>", "exec"), {})
    assert config.read_active_profile() is None


def test_switch_profile_step5_writes_pointer(tmp_xdg):
    """Switch-profile Step 5 must write pointer for non-default name."""
    src = _heredoc_for(SWITCH_SKILL, _is_pointer_apply_without_canon)
    substituted = _substitute_placeholder(src, name="prod")
    exec(compile(substituted, "<switch-step5-named>", "exec"), {})
    assert config.read_active_profile() == "prod"


def test_switch_profile_step5_clears_pointer_for_default(tmp_xdg):
    """Switch-profile Step 5 must clear pointer when switching to 'default'."""
    config.write_active_profile("prod")
    src = _heredoc_for(SWITCH_SKILL, _is_pointer_apply_without_canon)
    substituted = _substitute_placeholder(src, name="default")
    exec(compile(substituted, "<switch-step5-default>", "exec"), {})
    assert config.read_active_profile() is None, (
        "Switching to 'default' must clear pointer file — the canonical "
        "single-profile state ↔ no file rule."
    )


def test_switch_profile_step3_read_active_returns_default_when_unset(tmp_xdg):
    """Step 3 Path B reads current active; should print 'default' when no file."""
    src = _heredoc_for(SWITCH_SKILL, _is_read_active_profile_heredoc)
    # No <NAME> in this heredoc — exec directly.
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(src, "<switch-step3-read>", "exec"), {})
    assert buf.getvalue().strip() == "default"


def test_switch_profile_step3_read_active_returns_pointer_value(tmp_xdg):
    """Step 3 Path B should print the pointer value when set."""
    config.write_active_profile("prod")
    src = _heredoc_for(SWITCH_SKILL, _is_read_active_profile_heredoc)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(src, "<switch-step3-read-set>", "exec"), {})
    assert buf.getvalue().strip() == "prod"


# ===== safety boundary: switch-profile must not collect password =====


def test_switch_profile_does_not_reference_password_collection():
    """The whole point of /redshift-switch-profile is to avoid re-collecting
    the password. The skill is allowed to mention `set-password` as a
    remediation hint (CLI name), but must not include any actual password-
    collecting recipe (osascript / zenity / getpass / interactive prompt)."""
    text = SWITCH_SKILL.read_text()
    forbidden = ["osascript", "zenity --password", "getpass", "<<<PASSWORD"]
    leaks = [token for token in forbidden if token in text]
    assert not leaks, (
        f"redshift-switch-profile leaked password-collection tokens: {leaks}. "
        f"The skill assumes the target profile already has a password in keychain."
    )


# ===== skill body ↔ MCP signature drift =====
#
# The grep skills' Step 1b shows MCP tool calls inline (e.g.
# `search_columns(keywords, schema_name=<schema>, table_name=None)`). If the
# MCP signature changes (a kwarg renamed, removed) the skill body silently
# drifts. These tests parse the skill prose for tool-call patterns and check
# every kwarg against the actual function definition in redshift_tools.py via
# AST — no instantiation, no DB.

import ast

REDSHIFT_TOOLS_PY = REPO_ROOT / "src" / "redshift_comment_mcp" / "redshift_tools.py"
GREP_COLUMNS_SKILL = SKILLS_DIR / "redshift-grep-columns" / "SKILL.md"
GREP_TABLES_SKILL = SKILLS_DIR / "redshift-grep-tables" / "SKILL.md"


def _mcp_tool_param_names(fn_name: str) -> set[str]:
    """Return the parameter names of a function defined inside redshift_tools.py.

    Walks the AST to find the nested function (registered MCP tools live
    inside _setup_tools) and pulls its argument names. No instantiation.
    """
    tree = ast.parse(REDSHIFT_TOOLS_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            args = node.args
            return {a.arg for a in (*args.args, *args.kwonlyargs)}
    raise AssertionError(f"function {fn_name!r} not found in {REDSHIFT_TOOLS_PY.name}")


_CALL_NAME_PARAM = re.compile(
    # Match `\b(name)\(` then capture the balanced argument list.
    # This is intentionally simple — we don't try to parse Python; we just
    # extract the (...) span by walking parens, then scan for `kwarg=` patterns.
    r"\b(search_columns|search_tables)\("
)
# Match `kwarg = ...` patterns inside an argument list. Excludes `==` and
# excludes patterns that look like comparisons (`x == y`).
_KWARG = re.compile(r"\b(\w+)\s*=(?!=)")


def _extract_calls(body: str, fn_name: str) -> list[str]:
    """Yield the inner argument-text of every `fn_name(...)` call in body."""
    out: list[str] = []
    for m in re.finditer(rf"\b{re.escape(fn_name)}\(", body):
        depth = 1
        i = m.end()
        n = len(body)
        while i < n and depth > 0:
            c = body[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    out.append(body[m.end():i])
                    break
            i += 1
    return out


@pytest.mark.parametrize(
    "skill_path,fn_name",
    [
        (GREP_COLUMNS_SKILL, "search_columns"),
        (GREP_TABLES_SKILL, "search_tables"),
    ],
    ids=["grep-columns→search_columns", "grep-tables→search_tables"],
)
def test_grep_skill_calls_match_mcp_signature(skill_path, fn_name):
    """Every kwarg the skill body uses on `fn_name(...)` must exist on the
    actual MCP tool's signature.

    Catches drift like: MCP renames `table_name` to `relation_name` and
    forgets to update the skill body — the next LLM invocation would pass
    a non-existent kwarg and crash.
    """
    body = skill_path.read_text()
    actual_params = _mcp_tool_param_names(fn_name)

    calls = _extract_calls(body, fn_name)
    assert calls, (
        f"{skill_path.parent.name}: SKILL.md mentions no `{fn_name}(...)` "
        f"calls — Step 1b documentation likely drifted"
    )

    for call_text in calls:
        used_kwargs = set(_KWARG.findall(call_text))
        unknown = used_kwargs - actual_params
        assert not unknown, (
            f"{skill_path.parent.name} body uses {fn_name}({sorted(used_kwargs)}); "
            f"unknown kwargs {sorted(unknown)} not in actual signature "
            f"{sorted(actual_params)}. Update SKILL.md or revert the rename."
        )


# NOTE: bash block syntactic-validity test (bash -n on ```bash``` fences in
# grep skills) was removed when the cache mechanism was deleted. The grep
# skills no longer contain bash recipes — their flow is one MCP call per
# schema for grep-columns / one cluster-wide call for grep-tables. If a
# future skill adds bash recipes back, re-introduce a test of this shape.
