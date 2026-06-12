"""Unit test for the .mcpb bundle generator (scripts/generate_mcpb_manifest.py).

WHY these assertions matter (intent, not just behavior):
- The manifest is GENERATED, never hand-written, so its `version` is
  single-sourced from the root pyproject `[tool.setuptools_scm]
  fallback_version`. A test that pins version == root fallback_version is the
  guard that the .mcpb surface can't silently drift from the package version
  (the 4th version surface; see Task 4's cross-surface invariant).
- manifest_version "0.4" + server.type "uv" + entry_point "server/main.py" are
  the exact schema shape `mcpb pack` validated in the spike. Asserting them
  catches a regression that would produce a manifest the MCPB CLI rejects.
- user_config must expose all five connection fields, and password MUST carry
  `sensitive: true` so Claude Desktop stores it in the OS keychain rather than
  plaintext — a security contract, not cosmetics.
- mcp_config.env must inject the password via `${user_config.password}` (not on
  argv) so the secret never lands in a world-readable process arg list.
- The generated bundle pyproject must pin the SAME root version so the bundle
  installs exactly the package version it was generated against.
"""

import importlib.util
import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "generate_mcpb_manifest.py"
_ROOT_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _root_fallback_version() -> str:
    text = _ROOT_PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^fallback_version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "fallback_version not found in root pyproject.toml"
    return m.group(1)


def _load_generator():
    spec = importlib.util.spec_from_file_location("_mcpb_generator", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_emits_valid_uv_manifest(tmp_path):
    gen = _load_generator()
    root_version = _root_fallback_version()

    # Generate into a tmp dir to keep the test deterministic and avoid
    # clobbering a checked-in mcpb/ tree.
    gen.generate(repo_root=_REPO_ROOT, out_dir=tmp_path)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == "0.4"
    assert manifest["name"] == "redshift-comment-mcp"
    assert manifest["version"] == root_version

    server = manifest["server"]
    assert server["type"] == "uv"
    assert server["entry_point"] == "server/main.py"

    user_config = manifest["user_config"]
    assert set(user_config.keys()) == {"host", "port", "user", "dbname", "password"}
    assert user_config["password"]["sensitive"] is True

    env = server["mcp_config"]["env"]
    assert env["REDSHIFT_PASSWORD"] == "${user_config.password}"

    bundle_pyproject = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert f'redshift-comment-mcp=={root_version}' in bundle_pyproject
