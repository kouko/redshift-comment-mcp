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

    The same lock is taken on the config *directory's* inode as well, right
    after the lock file's. A lock on a file is only as durable as its name:
    delete ``config.toml.lock`` while a writer holds it and the next writer
    creates a new inode at that name, locks that, and runs concurrently — the
    protection silently off. The directory is the nearest inode a ``rm`` of the
    lock file cannot detach, so it carries the exclusion across that delete.

    ``delete_profile`` holds it across its active-profile pointer step too, but
    not across its keychain call — that one can block on an OS unlock prompt
    for human-length time, and the keychain is keyed per profile with no
    whole-store rewrite to lose. The pointer is the one file written from
    inside the lock (the delete's own ``clear_active_profile``) *and* from
    outside it (``write_active_profile``, which ``/redshift-switch-profile``
    calls), so the delete re-reads it immediately before clearing rather than
    trusting an earlier read.

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

Atomic writes:

    Every file this module writes — config.toml and the active-profile pointer
    alike — goes through :func:`_replace_atomically`: a temp file beside the
    destination, fsynced, renamed over it, then the destination's directory
    fsynced. Symlinks are resolved first, so a store kept in a dotfiles
    checkout keeps its link and its target keeps receiving the writes.
"""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Optional

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

# Temp files every atomic write goes through, and the age past which one can
# only be crash litter — see :func:`_sweep_stale_temp_files`.
_TEMP_SUFFIX = ".tmp"
_CONFIG_TEMP_PREFIX = ".config.toml."
_POINTER_TEMP_PREFIX = ".active-profile."
_STALE_TEMP_AGE_SECONDS = 24 * 60 * 60

# How many times :func:`_lock_config_dir` re-takes the directory lock when the
# directory it locked turns out not to be the one at that name any more. Three
# covers a racing replacement; more would only prolong a churn loop that the
# fallback handles anyway.
_DIR_LOCK_ATTEMPTS = 3


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


def _lock_config_dir(directory: Path) -> Optional[int]:
    """Exclusively lock the config directory's inode; return the held fd or None.

    ``flock`` serialises holders of an *inode*, but :func:`_lock_path` names a
    *file*. Delete ``config.toml.lock`` while a writer holds it — a single
    ``rm``, or any cleanup script that tidies "empty" files — and the next
    writer creates a brand-new inode at that same name, locks that instead, and
    runs its read-modify-write beside the first one's. Both then rewrite the
    whole store and the later rename drops the earlier one's profile, with
    nothing raised anywhere: the protection is off and nobody can tell.

    The directory holding both files is the nearest inode that ``rm`` cannot
    detach from its name, so the exclusion that has to survive the delete rides
    on it. Locking it in addition to the lock file (never instead of it) keeps
    the file the READMEs describe a real, observable lock, and keeps the
    acquisition order the same for every caller, so the pair cannot deadlock.

    The ``fstat``/``stat`` pair is the same hazard one level up: between the
    ``open`` and the ``flock`` the directory itself can be replaced, leaving
    this lock on an orphan. Then the file we locked is no longer the file at
    that name, and the only remedy is to take the lock again on whatever is
    there now — bounded, because an ``rm -r``/``mkdir`` loop would otherwise
    spin here forever inside a write. Exhausting the attempts, or a filesystem
    that refuses a directory lock at all, falls back to the lock file alone:
    the protection this module had before, not a new hazard.
    """
    for _ in range(_DIR_LOCK_ATTEMPTS):
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return None
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX)
            held, at_name = os.fstat(fd), os.stat(directory)
        except OSError:
            os.close(fd)
            return None
        if (held.st_dev, held.st_ino) == (at_name.st_dev, at_name.st_ino):
            return fd
        os.close(fd)
    return None


@contextmanager
def _store_lock() -> Iterator[bool]:
    """Hold an exclusive lock across a whole read-modify-write of the store.

    Yields True while the lock is held, False when it could not be taken and
    the caller is therefore running unserialised — see the module docstring for
    why that degradation is preferred to failing the write.

    Two inodes are locked, in this order every time: the lock file, then the
    directory both it and config.toml live in. The second is what keeps the
    first honest when the lock file is deleted mid-write — see
    :func:`_lock_config_dir`.

    Both are released in a ``finally``, so a write that raises releases them on
    the way out; leaking one would wedge every later write in the process tree
    until the process died.
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
        dir_fd = _lock_config_dir(p.parent)
        try:
            yield True
        finally:
            if dir_fd is not None:
                os.close(dir_fd)
    finally:
        os.close(fd)


def _resolved_target(p: Path) -> Path:
    """Where a write to ``p`` has to land, with symlinks on the way followed.

    ``os.replace`` acts on the *name*: aimed at a symlink it unlinks the link
    and leaves a regular file in its place, so a store kept in a dotfiles
    checkout silently stops being written to — no error, and every later write
    lands outside the repo the user tracks. Resolving first keeps the link and
    puts the bytes in the file it names.

    Resolution is non-strict, so a dangling link resolves to the target it
    promises and the write creates it. Both the config directory and the
    resolved parent are created: the second can be somewhere else entirely, and
    the temp file must be created *there* or ``os.replace`` crosses a
    filesystem boundary and stops being atomic.
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    target = Path(os.path.realpath(p))
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _sweep_stale_temp_files(directory: Path, prefix: str) -> None:
    """Delete temp files a process was killed before it could rename.

    A SIGKILL, an OOM kill or a power loss between ``mkstemp`` and
    ``os.replace`` leaves a full copy of what was being written, and nothing
    else in the project ever removes it: the config directory accumulates one
    per crash, each holding the whole profile store.

    The threshold is 24 hours. A write here takes milliseconds — the only
    human-length pause in this module is the keychain's unlock prompt, which
    happens outside every write — so nothing younger can still belong to a
    writer that is alive, including one on the unserialised non-POSIX path
    where no lock keeps us apart. A day is also short enough that litter never
    outlives a single day's crashes. Errors are ignored throughout: a sweep
    that cannot run must never fail the write it was trying to tidy up for.
    """
    cutoff = time.time() - _STALE_TEMP_AGE_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if not (entry.name.startswith(prefix) and entry.name.endswith(_TEMP_SUFFIX)):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry so a completed rename survives power loss.

    Fsyncing the temp file makes its *contents* durable. The rename that gives
    those contents the real name lives in the directory, and is not durable
    until the directory itself is flushed — so a crash right after a write that
    reported success can come back with the pre-write file, or none at all.

    ``OSError`` is tolerated: some filesystems refuse fsync on a directory, and
    the write it would have made durable has already succeeded.
    """
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace_atomically(
    path: Path, write_body: Callable[[BinaryIO], Any], *, prefix: str
) -> None:
    """Write ``path`` through a temp file in its own directory and one rename.

    Writing straight into the destination truncates it before the first byte of
    new content lands, so a serialisation or disk failure mid-write leaves a
    partial file and a concurrent reader can observe it. Here a reader only
    ever sees the whole old file or the whole new one, and a failure before the
    rename removes the temp file and leaves the destination untouched.

    The mode is pinned to 600 on the destination after the rename rather than
    on the temp file before it. ``mkstemp`` already creates at 0600 masked by
    the umask, which can only remove bits, so the file is never more permissive
    than 0600 at any instant; the explicit chmod puts the mode back where a
    restrictive umask narrowed it, on the path the READMEs actually name.
    """
    target = _resolved_target(path)
    _sweep_stale_temp_files(target.parent, prefix)
    fd, tmp_name = tempfile.mkstemp(
        prefix=prefix, suffix=_TEMP_SUFFIX, dir=str(target.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            write_body(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    target.chmod(0o600)
    _fsync_directory(target.parent)


def _write_all(profiles: dict[str, dict[str, Any]]) -> None:
    """Replace the whole profile store atomically — see :func:`_replace_atomically`."""
    _replace_atomically(
        config_path(),
        lambda f: tomli_w.dump({"profile": profiles}, f),
        prefix=_CONFIG_TEMP_PREFIX,
    )


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
    3. **The pointer is cleared last**, only after the fields are really gone,
       and only while it still names the deleted profile. An active-profile
       pointer beats the lone-profile fallback in
       :func:`resolve_active_profile`, so a pointer left naming a deleted
       profile makes the server raise "not configured" until a human deletes
       the file by hand — and a pointer cleared after someone re-aimed it
       throws away a ``/redshift-switch-profile`` that already reported
       success. The pointer is therefore read twice: once inside the lock to
       decide whether this delete is the reason it would go stale, and again
       immediately before the unlink to confirm nobody re-aimed it in between.
       The re-read narrows the window to two syscalls rather than closing it:
       closing it would mean serialising the pointer writers on this same lock,
       and ``clear_active_profile`` runs inside it, so that would deadlock
       every delete of the active profile.

    The keychain call sits outside :func:`_store_lock`: it can block on an OS
    unlock prompt for human-length time, and the lock exists to protect
    config.toml's read-modify-write, not the keychain — which is keyed per
    profile and has no whole-store rewrite to lose. Everything that touches a
    file is inside the lock, including the pointer.
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
        pointer_named_it = read_active_profile() == name
        del profiles[name]
        _write_all(profiles)
        if pointer_named_it and read_active_profile() == name:
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

    The absence is discovered by trying the read rather than by an ``exists()``
    check first: anything that removes the pointer between the two — a
    concurrent ``/redshift-switch-profile``, a :func:`delete_profile` clearing
    it — turned a reader into a ``FileNotFoundError``. A dangling symlink
    answers None either way.
    """
    try:
        name = active_profile_path().read_text().strip()
    except FileNotFoundError:
        return None
    return name or None


def write_active_profile(name: str) -> None:
    """Write the active profile pointer file (mode 600), atomically.

    Through the same temp file and rename as config.toml — see
    :func:`_replace_atomically`. Writing in place truncated the file before the
    new name landed, and a reader in that window gets an empty file, which
    :func:`read_active_profile` reports as "no pointer" and
    :func:`resolve_active_profile` answers by falling through to the implicit
    rule: a different cluster than the pointer names, with nothing logged.

    No lock is taken, and neither does :func:`clear_active_profile`. That one
    cannot: :func:`delete_profile` calls it from inside the store lock, which
    is not re-entrant. Locking only the other half of the pair would serialise
    nothing, so both stay unlocked and the delete re-reads the pointer instead.
    """
    _replace_atomically(
        active_profile_path(),
        lambda f: f.write((name + "\n").encode()),
        prefix=_POINTER_TEMP_PREFIX,
    )


def clear_active_profile() -> None:
    """Remove the active profile pointer file if present.

    Used when switching back to ``"default"`` — single-profile state
    canonically corresponds to "no pointer file".

    ``missing_ok`` rather than a preceding ``exists()`` check: anything that
    removes the pointer between the check and the unlink — a concurrent
    ``/redshift-switch-profile``, a second delete of the same profile, a user
    with the file open — turned the last step of a :func:`delete_profile` that
    had already removed the password and the fields into an uncaught
    ``FileNotFoundError``, which reaches the CLI as a traceback from a delete
    that in fact succeeded.
    """
    active_profile_path().unlink(missing_ok=True)


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
