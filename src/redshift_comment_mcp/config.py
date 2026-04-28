"""Configuration loader and keyring integration for redshift-comment-mcp.

Stores connection profiles (host/port/user/dbname) in TOML at
~/.config/redshift-comment-mcp/config.toml (XDG Base Directory spec) and
passwords in the OS keychain via the `keyring` library.

Profile schema in config.toml:

    [profile.default]
    host = "my-cluster.abc123.us-east-1.redshift.amazonaws.com"
    port = 5439
    user = "alice"
    dbname = "analytics"

    [profile.prod]
    host = "..."
    ...

Multiple profiles let one install handle multiple clusters; pass
``--profile <name>`` to ``redshift-comment-mcp`` to select one.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import keyring

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import tomli_w

KEYRING_SERVICE = "redshift-comment-mcp"


def config_path() -> Path:
    """Return the canonical config file path (XDG-compliant)."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "redshift-comment-mcp" / "config.toml"


def read_all() -> dict[str, dict[str, Any]]:
    """Read all profiles from config.toml. Returns empty dict if missing."""
    p = config_path()
    if not p.exists():
        return {}
    with p.open("rb") as f:
        data = tomllib.load(f)
    return data.get("profile", {})


def read_profile(name: str) -> Optional[dict[str, Any]]:
    """Return the profile dict for ``name``, or None if absent."""
    return read_all().get(name)


def write_profile(name: str, *, host: str, port: int, user: str, dbname: str) -> None:
    """Merge a profile into config.toml, creating the file/dir if needed.

    Sets file mode 600 to match the secret-adjacent security posture.
    """
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    profiles = read_all()
    profiles[name] = {"host": host, "port": port, "user": user, "dbname": dbname}
    with p.open("wb") as f:
        tomli_w.dump({"profile": profiles}, f)
    p.chmod(0o600)


def delete_profile(name: str) -> bool:
    """Remove a profile from config.toml AND its keyring password.

    Returns True if profile existed, False otherwise.
    """
    profiles = read_all()
    if name not in profiles:
        return False
    del profiles[name]
    p = config_path()
    with p.open("wb") as f:
        tomli_w.dump({"profile": profiles}, f)
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
    return True


def get_password(profile: str) -> Optional[str]:
    """Read password for ``profile`` from the OS keychain."""
    return keyring.get_password(KEYRING_SERVICE, profile)


def set_password(profile: str, password: str) -> None:
    """Store password for ``profile`` in the OS keychain."""
    keyring.set_password(KEYRING_SERVICE, profile, password)


def list_profiles() -> list[str]:
    """Return sorted list of configured profile names."""
    return sorted(read_all().keys())
