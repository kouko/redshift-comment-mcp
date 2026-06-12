"""Thin .mcpb (Desktop Extension, server.type "uv") entry point.

The Claude Desktop install form collects host / port / user / dbname / password
and the Extensions framework injects them as REDSHIFT_* environment variables
(wired in the bundle's manifest.json `server.mcp_config.env`). The
redshift-comment-mcp package's server reads host/user/dbname from CLI args
(inline mode — src/redshift_comment_mcp/server.py:91-99) and the password from
the REDSHIFT_PASSWORD env var directly. This adapter translates the injected env
into inline-mode argv, then hands off to the package's `main()`. The server
package itself is unchanged (installed from PyPI via the bundle's pyproject.toml
under `uv`).

`build_argv` is a pure function importable on its own; the heavy server import
is deferred into the `__main__` block so loading this module to test the mapping
does not pull in the package.
"""

import os
import sys


def build_argv(environ) -> list[str]:
    """Map injected REDSHIFT_* env vars to inline-mode CLI argv.

    Each present-and-truthy env var contributes its flag; absent or empty values
    omit the flag so the server's `_normalize_inline` treats them as unset rather
    than as a blank real value. The password is deliberately NOT placed in argv
    (process arg lists are world-readable via `ps`) — it stays in
    REDSHIFT_PASSWORD env, which inline mode reads directly.
    """
    argv = ["redshift-comment-mcp"]
    if environ.get("REDSHIFT_HOST"):
        argv += ["--host", environ["REDSHIFT_HOST"]]
    if environ.get("REDSHIFT_PORT"):
        argv += ["--port", environ["REDSHIFT_PORT"]]
    if environ.get("REDSHIFT_USER"):
        argv += ["--user", environ["REDSHIFT_USER"]]
    if environ.get("REDSHIFT_DBNAME"):
        argv += ["--dbname", environ["REDSHIFT_DBNAME"]]
    return argv


if __name__ == "__main__":
    # Lazy import: keeps build_argv importable without pulling the heavy server
    # package (and its dependencies) into the importing process.
    from redshift_comment_mcp.server import main

    sys.argv = build_argv(os.environ)
    main()
