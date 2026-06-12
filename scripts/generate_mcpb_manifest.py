#!/usr/bin/env python3
"""Generate the companion .mcpb bundle files (manifest.json, pyproject.toml,
.mcpbignore) into mcpb/.

The manifest is GENERATED, not hand-written: its version is single-sourced from
the root pyproject's `[tool.setuptools_scm] fallback_version`, so the .mcpb
surface cannot drift from the package version it ships. Re-run any time the root
version changes:

    python scripts/generate_mcpb_manifest.py

Idempotent — re-running overwrites the three generated files with identical
content for an unchanged root version. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:  # py>=3.11
    import tomllib
except ImportError:  # py<3.11 — project already deps tomli
    import tomli as tomllib

PACKAGE_NAME = "redshift-comment-mcp"
DISPLAY_NAME = "Redshift Comment MCP"
DESCRIPTION = (
    "A Model-Context Protocol server for Amazon Redshift where comments are "
    "the source of truth for schema meaning."
)


def _read_root_version(repo_root: Path) -> str:
    """Read the single-source version from root pyproject [tool.setuptools_scm]."""
    pyproject = repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = data["tool"]["setuptools_scm"]["fallback_version"]
    if not version:
        raise ValueError(
            "root pyproject [tool.setuptools_scm].fallback_version is empty"
        )
    return version


def _build_manifest(version: str) -> dict:
    return {
        "manifest_version": "0.4",
        "name": PACKAGE_NAME,
        "display_name": DISPLAY_NAME,
        "version": version,
        "description": DESCRIPTION,
        "author": {
            "name": "kouko",
            "url": "https://github.com/kouko/redshift-comment-mcp",
        },
        "server": {
            "type": "uv",
            "entry_point": "server/main.py",
            "mcp_config": {
                "command": "uv",
                "args": [
                    "run",
                    "--project",
                    "${__dirname}",
                    "${__dirname}/server/main.py",
                ],
                "env": {
                    "REDSHIFT_HOST": "${user_config.host}",
                    "REDSHIFT_PORT": "${user_config.port}",
                    "REDSHIFT_USER": "${user_config.user}",
                    "REDSHIFT_DBNAME": "${user_config.dbname}",
                    "REDSHIFT_PASSWORD": "${user_config.password}",
                },
            },
        },
        "user_config": {
            "host": {
                "type": "string",
                "title": "Redshift Host",
                "description": "Cluster endpoint hostname.",
                "required": True,
            },
            "port": {
                "type": "number",
                "title": "Port",
                "description": "Cluster port. Defaults to 5439.",
                "default": 5439,
            },
            "user": {
                "type": "string",
                "title": "DB User",
                "description": "Database user to connect as.",
                "required": True,
            },
            "dbname": {
                "type": "string",
                "title": "Database",
                "description": "Database name to connect to.",
                "required": True,
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": (
                    "Database password. Stored in your OS keychain, never in "
                    "plaintext."
                ),
                "sensitive": True,
                "required": True,
            },
        },
    }


def _build_bundle_pyproject(version: str) -> str:
    return (
        "[project]\n"
        f'name = "{PACKAGE_NAME}-mcpb"\n'
        f'version = "{version}"\n'
        'requires-python = ">=3.10"\n'
        f'dependencies = ["{PACKAGE_NAME}=={version}"]\n'
    )


_MCPBIGNORE_LINES = (
    ".venv/",
    "server/lib/",
    "server/venv/",
    "__pycache__/",
    "*.pyc",
)


def generate(repo_root: Path, out_dir: Path) -> str:
    """Write the three bundle files into out_dir. Returns the version used.

    Idempotent: overwrites existing files with content derived from the root
    version. Creates out_dir if absent.
    """
    repo_root = Path(repo_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    version = _read_root_version(repo_root)

    manifest = _build_manifest(version)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "pyproject.toml").write_text(
        _build_bundle_pyproject(version), encoding="utf-8"
    )
    (out_dir / ".mcpbignore").write_text(
        "\n".join(_MCPBIGNORE_LINES) + "\n", encoding="utf-8"
    )
    return version


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "mcpb"
    version = generate(repo_root=repo_root, out_dir=out_dir)
    print(f"Generated mcpb/ bundle files for {PACKAGE_NAME} {version}", file=sys.stderr)


if __name__ == "__main__":
    main()
