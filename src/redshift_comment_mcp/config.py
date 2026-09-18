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

Write serialisation (POSIX only):

    ``write_profile`` and ``delete_profile`` are read-modify-write cycles —
    read every profile, change one entry, rewrite the whole file — so each
    holds an exclusive ``fcntl.flock`` across all three steps, on a sibling
    lock file ``config.toml.lock`` (mode 600, beside config.toml in the config
    directory). Locking only the write step would not help: two callers can
    still read the same starting state, and the second rename then drops the
    first one's profile with no error anywhere.

    Where POSIX locking is unavailable — ``fcntl`` missing (Windows), or a
    filesystem that refuses the lock — the write degrades to the unserialised
    path rather than failing. Concurrent writers can then still lose a
    profile, which is the behaviour those platforms had before the lock
    existed, not a new hazard. No third-party locking dependency is added.

    Readers (``read_all``, ``read_profile``, ``get_password``) take no lock.
    The atomic rename in :func:`_write_all` already gives them either the
    whole old file or the whole new one, so queueing behind a writer would buy
    them nothing — and making ``read_all`` take the lock would deadlock every
    writer, since writers call it from inside their own critical section.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import keyring

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover — non-POSIX (Windows)
    _fcntl = None  # type: ignore[assignment]

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import tomli_w

KEYRING_SERVICE = "redshift-comment-mcp"


class KeychainDeleteError(RuntimeError):
    """Raised when a profile's stored password could not be removed.

    :func:`delete_profile` keeps its ``bool`` return — ``True`` deleted,
    ``False`` no such profile — because every caller already reads ``False`` as
    "did not exist". A keychain that refuses the delete is neither of those, so
    it travels out of band instead of being folded into the bool: the store is
    left untouched, and the caller is told why rather than being handed a
    ``False`` it would report as "profile did not exist".

    Not a ``ConfigurationError``: nothing about the configuration is wrong, the
    keychain is simply unavailable (typically locked), and retrying after
    unlocking it is the fix.
    """


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


def _lock_path() -> Path:
    """Path of the lock file that serialises writes to the profile store.

    A sibling of config.toml rather than config.toml itself: ``_write_all``
    renames a new file over the old one, so a lock held on config.toml's inode
    would be a lock on a file that no longer has that name.
    """
    return config_path().with_name("config.toml.lock")


@contextmanager
def _store_lock() -> Iterator[bool]:
    """Hold an exclusive lock across a whole read-modify-write of the store.

    Yields True while the lock is held, False when it could not be taken and
    the caller is therefore running unserialised — see the module docstring for
    why that degradation is preferred to failing the write.

    The lock is released in a ``finally``, so a write that raises releases it
    on the way out; leaking it would wedge every later write in the process
    tree until the process died.
    """
    if _fcntl is None:
        yield False
        return
    p = _lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        yield False
        return
    try:
        try:
            # O_CREAT's mode is masked by the umask; this pins 0600 to match
            # config.toml's posture whatever the umask happened to be.
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX)
        except OSError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def _write_all(profiles: dict[str, dict[str, Any]]) -> None:
    """Replace the whole profile store atomically.

    Serialises into a temp file, fsyncs it, sets mode 600 on it, then
    ``os.replace()``s it over config.toml. Writing straight into config.toml
    would truncate it before the first byte of new content lands, so a
    serialisation or disk failure mid-write would leave a partial file and
    destroy every other profile in it.

    The temp file goes in the config directory itself, never the system temp
    dir: ``os.replace`` is atomic only within one filesystem, and ``/tmp`` is
    routinely a different one. A failure before the rename removes the temp
    file and leaves config.toml — content and mode — untouched, and a
    concurrent reader only ever sees the whole old file or the whole new one.
    """
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".config.toml.", suffix=".tmp", dir=str(p.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            tomli_w.dump({"profile": profiles}, f)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_profile(name: str, *, host: str, port: int, user: str, dbname: str) -> None:
    """Merge a profile into config.toml, creating the file/dir if needed.

    Sets file mode 600 to match the secret-adjacent security posture. The
    write is atomic — see :func:`_write_all` — and the read-modify-write around
    it is serialised — see :func:`_store_lock`.
    """
    with _store_lock():
        profiles = read_all()
        profiles[name] = {"host": host, "port": port, "user": user, "dbname": dbname}
        _write_all(profiles)


def delete_profile(name: str) -> bool:
    """Remove a profile's keyring password, then its fields, then a pointer to it.

    Returns True if the profile existed, False otherwise. Raises
    :class:`KeychainDeleteError` — leaving the store exactly as it was — when
    the keychain refuses to delete the password.

    Three orderings matter here:

    1. **The password goes first.** Removing the fields first and the password
       second means a keychain failure leaves a password stored under a name
       that no longer appears in ``list_profiles`` — a credential with no
       remaining interface that lists it, let alone deletes it. This order
       fails the other way: a complete, still-listed profile the user can
       delete again once the keychain is unlocked.
    2. **Absence is checked before the keychain is touched at all.** Otherwise
       ``delete_profile("typo")`` against a locked keychain would raise where
       it used to answer False.
    3. **The pointer is cleared last**, only after the fields are really gone.
       An active-profile pointer beats the lone-profile fallback in
       :func:`resolve_active_profile`, so a pointer left naming a deleted
       profile makes the server raise "not configured" until a human deletes
       the file by hand.

    The keychain call sits outside :func:`_store_lock`: it can block on an OS
    unlock prompt for human-length time, and the lock exists to protect
    config.toml's read-modify-write, not the keychain — which is keyed per
    profile and has no whole-store rewrite to lose.
    """
    if name not in read_all():
        return False

    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        # No entry for this profile. Nothing to strand, so this is not a
        # failure — a profile whose password was never stored is deletable.
        pass
    except Exception as e:  # noqa: BLE001 — see below
        # Deliberately broader than KeyringError: a locked or unavailable
        # keychain surfaces as KeyringLocked, NoKeyringError or InitError, and
        # individual backends raise their own classes on top. Nothing is
        # swallowed — every one of them is re-raised as KeychainDeleteError
        # with the original attached — and the store has not been touched yet.
        raise KeychainDeleteError(
            f"could not delete the keychain password for profile '{name}' "
            f"({type(e).__name__}); the profile was left intact — unlock the "
            f"keychain and delete it again"
        ) from e

    with _store_lock():
        profiles = read_all()
        if name not in profiles:
            return False
        del profiles[name]
        _write_all(profiles)

    if read_active_profile() == name:
        clear_active_profile()
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
