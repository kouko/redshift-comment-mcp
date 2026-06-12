"""Unit tests for the .mcpb Desktop Extension entry-point adapter.

`mcpb/server/main.py` is the bundle's entry point — it is NOT on any package
import path (the bundle ships it as a loose file run by `uv`). So we load its
`build_argv` helper directly by file path via importlib, exactly the way the
bundle runtime would `python mcpb/server/main.py`. This keeps the test honest
about how the file is actually consumed.

WHY these assertions matter (intent, not just behavior):
- The server's inline mode (src/redshift_comment_mcp/server.py:91-99) only
  triggers when --host/--user/--dbname are ALL present; the adapter must map
  each REDSHIFT_* form field to its flag in a stable order so the server boots
  in inline mode rather than falling through to profile mode.
- Absent/empty env vars must OMIT the flag — passing `--host ""` would defeat
  the server's `_normalize_inline` fallthrough and look like a real (blank)
  host. Omission is the contract.
- The password must NEVER appear in argv (process arg list is world-readable
  via `ps`); it stays in REDSHIFT_PASSWORD env, which inline mode reads at
  server.py:93. A regression that leaked it into argv is a security defect.
"""

import importlib.util
from pathlib import Path

_ADAPTER_PATH = (
    Path(__file__).resolve().parent.parent / "mcpb" / "server" / "main.py"
)


def _load_build_argv():
    """Load build_argv from the loose bundle entry-point file by path.

    `__name__` is set to a non-"__main__" name so importing the module does NOT
    trigger the `if __name__ == "__main__":` block (which would import the heavy
    server package and call main()).
    """
    spec = importlib.util.spec_from_file_location("_mcpb_adapter", _ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_argv


def test_build_argv_maps_env_to_inline_flags():
    build_argv = _load_build_argv()

    # Full env → exact ordered inline argv.
    full = {
        "REDSHIFT_HOST": "h",
        "REDSHIFT_PORT": "5439",
        "REDSHIFT_USER": "u",
        "REDSHIFT_DBNAME": "d",
    }
    assert build_argv(full) == [
        "redshift-comment-mcp",
        "--host",
        "h",
        "--port",
        "5439",
        "--user",
        "u",
        "--dbname",
        "d",
    ]

    # Missing REDSHIFT_HOST → no --host flag.
    no_host = build_argv(
        {"REDSHIFT_PORT": "5439", "REDSHIFT_USER": "u", "REDSHIFT_DBNAME": "d"}
    )
    assert "--host" not in no_host

    # Empty-string REDSHIFT_USER → no --user flag (empty is "unset").
    empty_user = build_argv(
        {"REDSHIFT_HOST": "h", "REDSHIFT_USER": "", "REDSHIFT_DBNAME": "d"}
    )
    assert "--user" not in empty_user

    # Password is NEVER in argv, even when REDSHIFT_PASSWORD is set.
    with_password = build_argv(
        {
            "REDSHIFT_HOST": "h",
            "REDSHIFT_USER": "u",
            "REDSHIFT_DBNAME": "d",
            "REDSHIFT_PASSWORD": "secret",
        }
    )
    assert "secret" not in with_password
    assert "REDSHIFT_PASSWORD" not in with_password
    assert "--password" not in with_password
