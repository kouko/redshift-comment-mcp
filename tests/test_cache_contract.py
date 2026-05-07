"""Cache contract checks — keep producer (cache-schema) and consumer
(/redshift-explore, /redshift-profile, server CACHE PROTOCOL) in sync.

The cache layer is purely doc-driven: the producer skill and the consumer
skills both reference file paths and field names, but no Python code
enforces the contract. These tests verify that the SKILL.md spec remains
self-consistent — required `_meta.json` fields documented, TSV header
formats present, column heading pattern documented — so a producer-side
edit can't silently desync the consumer side.

Add a test here whenever the cache file format spec gains a field that
consumers depend on.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_SKILL = REPO_ROOT / "skills" / "redshift-cache-schema" / "SKILL.md"
EXPLORE_SKILL = REPO_ROOT / "skills" / "redshift-explore" / "SKILL.md"
PROFILE_SKILL = REPO_ROOT / "skills" / "redshift-profile" / "SKILL.md"
TOOLS_PY = REPO_ROOT / "src" / "redshift_comment_mcp" / "redshift_tools.py"


@pytest.fixture(scope="module")
def cache_spec():
    return CACHE_SKILL.read_text()


# ===== _meta.json freshness gate =====

REQUIRED_META_FIELDS = ("profile", "refreshed_at", "ttl_hours", "complete")


def test_meta_json_has_all_required_fields(cache_spec):
    """The _meta.json example block in cache-schema SKILL.md must document
    every field that consumers check for freshness.

    Consumers look at: refreshed_at + ttl_hours (TTL math), complete (gate),
    profile (sanity). If any field is dropped from the spec, the consumers'
    cache-first behavior breaks silently.
    """
    json_blocks = re.findall(r"```json\n(.*?)\n```", cache_spec, re.DOTALL)
    meta_block = next((b for b in json_blocks if "refreshed_at" in b), None)
    assert meta_block, (
        "cache-schema SKILL.md missing _meta.json example (no JSON block "
        "containing 'refreshed_at')"
    )

    missing = [f for f in REQUIRED_META_FIELDS if f'"{f}"' not in meta_block]
    assert not missing, (
        f"_meta.json example missing required fields: {missing}. "
        f"Consumers in CACHE PROTOCOL depend on these."
    )


# ===== TSV index headers =====

def test_tables_index_documents_3_columns(cache_spec):
    """_tables_index.tsv must be documented as 3 tab-separated columns
    (schema, table, summary). Consumer grep patterns assume this shape.
    """
    # Anchor on the section heading, then capture the next fenced code block.
    section = re.search(
        r"###\s+`_tables_index\.tsv`.*?```\n(.*?)\n```",
        cache_spec,
        re.DOTALL,
    )
    assert section, "_tables_index.tsv example section not found in spec"
    sample = section.group(1).splitlines()
    header = sample[0]
    cols = header.split("\t")
    assert len(cols) == 3 and cols == ["schema", "table", "summary"], (
        f"_tables_index.tsv header should be 'schema\\ttable\\tsummary' (3 cols), "
        f"got: {cols}"
    )


def test_columns_index_documents_5_columns(cache_spec):
    """_columns_index.tsv must be documented as 5 tab-separated columns
    (schema, table, column, type, summary).
    """
    section = re.search(
        r"###\s+`_columns_index\.tsv`.*?```\n(.*?)\n```",
        cache_spec,
        re.DOTALL,
    )
    assert section, "_columns_index.tsv example section not found in spec"
    sample = section.group(1).splitlines()
    header = sample[0]
    cols = header.split("\t")
    expected = ["schema", "table", "column", "type", "summary"]
    assert len(cols) == 5 and cols == expected, (
        f"_columns_index.tsv header should be {expected} (5 cols), got: {cols}"
    )


# ===== column heading pattern =====

def test_column_heading_pattern_documented(cache_spec):
    """The per-table .md must use the heading pattern
    `### `colname` (type[, NOT NULL])` so consumers can grep on `^### ``.

    PR #17 chose this pattern explicitly; deviation breaks consumer parsing.
    """
    # Example block under "tables/<schema>__<table>.md" should contain
    # at least one `### \`...\` (type` style heading.
    md_block_pattern = re.search(
        r"```markdown\n(.*?)\n```", cache_spec, re.DOTALL
    )
    assert md_block_pattern, "No markdown example block in cache-schema spec"
    md_sample = md_block_pattern.group(1)

    # Look for at least one column heading line matching the pattern.
    pat = re.compile(r"^### `[a-z_][a-z0-9_]*` \([a-z]", re.MULTILINE)
    assert pat.search(md_sample), (
        "Per-table .md example missing column heading in the form "
        "`### \\`colname\\` (type[, NOT NULL])` — consumer grep depends on it."
    )


# ===== consumer ↔ producer alignment =====

CACHE_FILE_REFS = (
    "_meta.json",
    "_tables_index.tsv",
    "_columns_index.tsv",
    "tables/<schema>__<table>.md",
)


def test_consumer_skills_only_reference_documented_paths():
    """Consumer skills (/redshift-explore, /redshift-profile) and the server
    CACHE PROTOCOL should only reference cache file paths that the producer
    SKILL.md actually documents.

    Catches typos like `_table_index.tsv` (singular) or `tables/<table>.md`
    (missing schema prefix).
    """
    cache_spec_text = CACHE_SKILL.read_text()

    consumers = [
        EXPLORE_SKILL.read_text(),
        PROFILE_SKILL.read_text(),
        TOOLS_PY.read_text(),
    ]

    # Cache file references that should ONLY appear if also in the producer.
    cache_path_re = re.compile(
        r"_(?:meta\.json|[a-z_]+_index\.tsv)|tables/<schema>__<table>\.md"
    )

    documented_paths = set(cache_path_re.findall(cache_spec_text))
    assert documented_paths, (
        "Producer spec doesn't appear to document any cache file paths — "
        "regex broken or spec moved?"
    )

    failures = []
    for idx, text in enumerate(consumers):
        consumer_label = ["redshift-explore SKILL.md", "redshift-profile SKILL.md", "redshift_tools.py"][idx]
        for ref in cache_path_re.findall(text):
            if ref not in documented_paths:
                failures.append(
                    f"{consumer_label}: references '{ref}' which is not "
                    f"documented in cache-schema SKILL.md (documented: "
                    f"{sorted(documented_paths)})"
                )
    assert not failures, "\n".join(failures)


# ===== CACHE PROTOCOL in server instructions =====

def test_cache_protocol_in_server_instructions():
    """FastMCP server instructions must contain a CACHE PROTOCOL section,
    teaching agents to prefer cache files over MCP tools when fresh.

    Without this, the cache layer is dead — tools work but agents won't read
    the cache files.
    """
    src = TOOLS_PY.read_text()
    m = re.search(r'instructions="""(.*?)"""', src, re.DOTALL)
    assert m, "FastMCP instructions block not found in redshift_tools.py"
    instructions = m.group(1)
    assert "CACHE PROTOCOL" in instructions, (
        "Server instructions must include CACHE PROTOCOL section. Without it, "
        "agents won't read cache files even when they exist."
    )
    # Must mention how to gate freshness
    for keyword in ("_meta.json", "complete", "ttl_hours"):
        assert keyword in instructions, (
            f"CACHE PROTOCOL missing reference to {keyword!r} — agent can't "
            f"gate freshness without it."
        )
