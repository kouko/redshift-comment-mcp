"""Lineage skill contract checks — keep SKILL.md spec and helper script in sync.

The lineage layer is partly executable (parse_stl_lineage.py has its own
smoke tests in skills/.../assets/parse_stl_lineage_test.py) and partly
doc-driven (the SKILL.md spec tells the model how to fetch and serialize
queries before invoking the helper). These tests verify the doc-driven
half — the parts a model follows verbatim that have no other automated
guard.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINEAGE_SKILL = REPO_ROOT / "skills" / "redshift-lineage-from-stl" / "SKILL.md"
HELPER_SCRIPT = (
    REPO_ROOT / "skills" / "redshift-lineage-from-stl" / "assets" / "parse_stl_lineage.py"
)


def test_sql_text_escape_caveat_documented():
    """SKILL.md must warn that some MCP servers serialize `sql_text` with
    literal escape sequences (`\\n` / `\\r` / `\\t`) instead of real control
    chars, and that the helper decodes defensively.

    The helper handles this transparently (idempotent decode), so the doc
    note exists purely to spare the user from debugging "literal \\n in my
    NDJSON" as if it were a write bug. If the caveat is removed, that
    diagnostic value is lost — even though the helper would still work.
    Symmetric with test_no_columns_marker_documented in test_cache_contract.
    """
    spec = LINEAGE_SKILL.read_text()

    flow_section = re.search(
        r"##\s+Flow\s*\n(.*?)(?=\n##\s+|\Z)",
        spec,
        re.DOTALL,
    )
    assert flow_section, "## Flow section not found in lineage SKILL.md"
    flow_text = flow_section.group(1)

    assert "sql_text" in flow_text and (
        "escaping" in flow_text.lower() or "escape" in flow_text.lower()
    ), (
        "Flow section missing the `sql_text` escaping caveat. Some MCP "
        "transport layers return sql_text with literal `\\n` instead of real "
        "newlines; the helper decodes defensively but a user inspecting the "
        "NDJSON manually will be confused without this note."
    )
    # The caveat must specifically tell the user the helper handles it,
    # so they trust verbatim writes.
    assert "defensively" in flow_text or "idempotent" in flow_text, (
        "sql_text caveat missing the assurance that the helper decodes "
        "defensively/idempotently. Without it, a user who sees literal `\\n` "
        "may mistakenly add their own decode pass on top."
    )


def test_helper_script_implements_defensive_decode():
    """The defensive-decode block the SKILL.md caveat promises must actually
    exist in the helper script. Catches the inverse drift: if someone removes
    the decode logic from the helper, the SKILL.md note becomes a lie.
    """
    src = HELPER_SCRIPT.read_text()

    # Look for the gating condition: "no real \n + has literal \\n".
    # The condition is what makes the decode idempotent on already-decoded
    # input, which is the contract the caveat advertises.
    assert '"\\n" not in sql' in src and '"\\\\n" in sql' in src, (
        "Helper script missing the idempotent gating condition for the "
        "defensive sql_text decode (expected `\"\\n\" not in sql and \"\\\\n\" "
        "in sql`). Without the gate, decode runs on already-decoded input and "
        "may corrupt SQL that legitimately contains backslash sequences."
    )
    assert 'unicode_escape' in src, (
        "Helper script missing `unicode_escape` decode call — the SKILL.md "
        "caveat promises the helper handles literal `\\n` / `\\r` / `\\t`."
    )
