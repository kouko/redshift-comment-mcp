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

Active-profile selection (which profile the MCP server uses on startup):

    Resolution priority is CLI ``--profile`` flag > ``REDSHIFT_COMMENT_PROFILE``
    env var > ``~/.config/redshift-comment-mcp/active-profile`` file (one
    line, just the profile name) > ``"default"``.

    Single-profile users never see this file — its absence means
    "use 'default'". The ``/redshift-switch-profile`` skill writes /
    removes the file; multi-profile users are the only ones it affects.
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


class ConfigurationError(ValueError):
    """Raised when the resolved profile is missing fields or keychain password.

    Subclasses ValueError so existing ``except ValueError`` clauses still catch
    it (backward-compat). Downstream code that wants to react specifically to
    "needs setup" — e.g. degraded-mode MCP tools that return a structured
    not_configured error instead of raising — should catch this subclass.
    """


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


# ===== active-profile pointer =====


def active_profile_path() -> Path:
    """Return the canonical active-profile pointer file path (XDG-compliant)."""
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "redshift-comment-mcp" / "active-profile"


def read_active_profile() -> Optional[str]:
    """Return the active profile name, or None if the pointer file is absent.

    Absent file is the canonical state for single-profile users (server
    falls back to ``"default"``). Empty / whitespace-only file is treated
    the same as absent.
    """
    p = active_profile_path()
    if not p.exists():
        return None
    name = p.read_text().strip()
    return name or None


def write_active_profile(name: str) -> None:
    """Write the active profile pointer file (mode 600)."""
    p = active_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(name + "\n")
    p.chmod(0o600)


def clear_active_profile() -> None:
    """Remove the active profile pointer file if present.

    Used when switching back to ``"default"`` — single-profile state
    canonically corresponds to "no pointer file".
    """
    p = active_profile_path()
    if p.exists():
        p.unlink()


def resolve_active_profile(cli_profile: Optional[str] = None) -> str:
    """Resolve which profile the server should use.

    Priority: explicit CLI ``--profile`` flag > ``REDSHIFT_COMMENT_PROFILE``
    env var > ``active-profile`` pointer file > implicit fallback.

    Implicit fallback (when nothing was explicit):
      1. ``"default"`` if it exists in config.toml — backward compatibility
         for users whose single profile is named "default"
      2. The lone profile if exactly one exists — **upgrade rescue** for
         pre-3884f98 users who picked a non-"default" name at install
      3. ``"default"`` as a literal — lets the server raise its existing
         "Profile 'default' is not configured" error (improved by
         server.py to surface available profiles + switch-profile skill)

    Explicit inputs are returned as-is even when they don't resolve to a
    real profile — the user told us what they want; let the downstream
    raise a typo-friendly error.
    """
    if cli_profile:
        return cli_profile
    env = os.environ.get("REDSHIFT_COMMENT_PROFILE")
    if env:
        return env
    pointer = read_active_profile()
    if pointer:
        return pointer

    # Implicit fallback path — touches config.toml because resolution now
    # depends on what's actually configured, not just on a literal name.
    profiles = read_all()
    if "default" in profiles:
        return "default"
    if len(profiles) == 1:
        return next(iter(profiles))
    return "default"
