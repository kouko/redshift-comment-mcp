"""Adversarial probes: where ``config._store_lock`` stops being a lock.

Change: 2026-09-18-config-store-integrity
Anchor: src/redshift_comment_mcp/config.py :: _store_lock, _lock_path

The change serialises the profile store's read-modify-write with an exclusive
``fcntl.flock`` on a sibling file ``config.toml.lock``. A lock on a *sibling*
path is only as strong as the path: the kernel serialises holders of the same
open file description's inode, not holders of the same name. These probes push
on the four edges that turns into — a vanished lock file, a directory that
refuses the ``open``, the documented non-POSIX degradation, and a second
acquisition on the same thread.

Every probe here uses the real filesystem under a throwaway ``XDG_CONFIG_HOME``
and the real ``fcntl``; nothing about mutual exclusion is asserted through a
mock.
"""
from __future__ import annotations

import os
import stat
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _probe_support import isolate_config  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A throwaway config directory; returns (config.toml path, module)."""
    config_file = isolate_config(monkeypatch, tmp_path)
    from redshift_comment_mcp import config as cfg

    return config_file, cfg


def _hold_the_lock(cfg, held, release, took_it):
    """Take the store lock, announce it, and hold until ``release`` is set."""
    with cfg._store_lock() as ok:
        took_it.append(ok)
        held.set()
        release.wait(timeout=10)


def test_storelock_asecondholderwhilethefirstholds_waitsforthereleases(store):
    """Control case: the lock really does exclude, so a red sibling means something.

    Two threads, two separate ``open`` calls, therefore two separate open file
    descriptions — which is exactly the arrangement ``flock`` serialises. If
    this case were green only because nothing was exercised, the vanished-lock
    case below would be meaningless.
    """
    _config_file, cfg = store

    held, release = threading.Event(), threading.Event()
    took_it: list[bool] = []
    second_in: list[bool] = []

    first = threading.Thread(target=_hold_the_lock, args=(cfg, held, release, took_it))
    first.start()
    assert held.wait(timeout=10), "the first holder never acquired the lock"
    assert took_it == [True], f"the first holder degraded instead of locking: {took_it}"

    def second():
        with cfg._store_lock():
            second_in.append(True)

    runner = threading.Thread(target=second)
    runner.start()
    runner.join(timeout=2)

    entered_while_held = bool(second_in)
    release.set()
    first.join(timeout=10)
    runner.join(timeout=10)

    assert not entered_while_held, (
        "a second caller entered the store lock while the first still held it: "
        "flock is not serialising these two open file descriptions at all, so "
        "every concurrency assertion in this change rests on nothing"
    )
    assert second_in == [True], "the second holder never acquired after the release"


def test_storelock_lockfileunlinkedmidhold_keepsexcludingasecondwriter(store):
    """Delete config.toml.lock while a write holds it; a second writer walks in.

    ``_store_lock`` resolves the *name* ``config.toml.lock`` on every call and
    creates it when absent. Unlink it while writer A holds it and writer B
    creates a fresh inode, locks that instead, and runs its own
    read-modify-write concurrently with A. Both then dump the whole profile
    table over each other — the exact loss this change exists to prevent.

    The README tells the user the file is "safe to delete while nothing is
    running", and a user cannot see an MCP server that is mid-write behind an
    open password dialog.
    """
    _config_file, cfg = store

    held, release = threading.Event(), threading.Event()
    took_it: list[bool] = []
    second_in: list[bool] = []

    first = threading.Thread(target=_hold_the_lock, args=(cfg, held, release, took_it))
    first.start()
    assert held.wait(timeout=10), "the first holder never acquired the lock"

    lock_file = cfg._lock_path()
    assert lock_file.exists(), "the lock file was never created"
    lock_file.unlink()

    def second():
        with cfg._store_lock():
            second_in.append(True)

    runner = threading.Thread(target=second)
    runner.start()
    runner.join(timeout=2)

    entered_while_held = bool(second_in)
    release.set()
    first.join(timeout=10)
    runner.join(timeout=10)

    assert not entered_while_held, (
        "config.toml.lock was unlinked while a writer held it, and a second "
        "writer immediately acquired a lock on a brand-new inode. Two "
        "read-modify-write cycles are now in flight over one config.toml and "
        "the later rename drops the earlier one's profile, with no error "
        "anywhere — the pre-change failure mode, reachable through a single "
        "`rm` the README calls safe"
    )


def test_storelock_readonlyconfigdirectorywithnolockfile_degradesinsteadofraising(store):
    """A config directory the process cannot write: the lock must not explode.

    ``os.open(..., O_CREAT)`` raises ``PermissionError`` here. The contract is
    that the context manager yields False (unserialised) rather than raising —
    the caller's own write is what should fail, loudly, a moment later.
    """
    _config_file, cfg = store

    config_dir = cfg.config_path().parent
    config_dir.mkdir(parents=True, exist_ok=True)
    original_mode = stat.S_IMODE(config_dir.stat().st_mode)
    config_dir.chmod(0o500)
    try:
        with cfg._store_lock() as ok:
            degraded = ok
    finally:
        config_dir.chmod(original_mode)

    assert degraded is False, (
        "a read-only config directory should degrade the lock to unserialised, "
        f"but _store_lock yielded {degraded!r}"
    )


def test_storelock_readonlyconfigdirectory_failstheenclosingwriteloudly(store):
    """The degraded lock must not turn into a silently skipped write.

    Degrading is only acceptable because the write behind it still fails
    audibly. If ``write_profile`` swallowed the unwritable directory, the user
    would be told nothing and the profile would simply not be there.
    """
    config_file, cfg = store

    config_dir = cfg.config_path().parent
    config_dir.mkdir(parents=True, exist_ok=True)
    original_mode = stat.S_IMODE(config_dir.stat().st_mode)
    config_dir.chmod(0o500)
    try:
        with pytest.raises(OSError):
            cfg.write_profile(
                "prod", host="h.example.com", port=5439, user="u", dbname="d"
            )
    finally:
        config_dir.chmod(original_mode)

    assert not config_file.exists(), (
        "the failed write left a config.toml behind in a directory it could "
        "not write"
    )


def test_storelock_fcntlunavailable_degradeswithoutcreatingalockfile(store):
    """The documented Windows path: no fcntl, no lock, no crash — and no file.

    The module docstring promises the write "degrades to the unserialised path
    rather than failing". It does. The second assertion is the part the READMEs
    do not account for: on that platform ``config.toml.lock`` is never created,
    so the file the three READMEs describe as appearing "on the first write"
    does not exist there. See probe_readme_lock_claims.py for that claim.
    """
    config_file, cfg = store

    original = cfg._fcntl
    cfg._fcntl = None
    try:
        with cfg._store_lock() as ok:
            degraded = ok
        cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")
    finally:
        cfg._fcntl = original

    assert degraded is False, f"_store_lock yielded {degraded!r} with fcntl absent"
    assert cfg.read_profile("prod") is not None, "the degraded write lost the profile"
    assert config_file.exists()

    assert not cfg._lock_path().exists(), (
        "unexpected: a lock file appeared with fcntl absent — if this is now "
        "true, the README's lifecycle description has become accurate and this "
        "probe should be re-aimed"
    )


def test_storelock_takentwiceonthesamethread_completesinsteadofdeadlocking(store):
    """Re-entering the store lock on one thread wedges that thread forever.

    ``flock`` serialises open file descriptions, and ``_store_lock`` opens a new
    descriptor per call, so the second acquisition on the *same* thread blocks
    on the first — with nothing left running to release it. No caller nests
    today; this pins what happens the day one does, since the failure is a
    silent hang, not an exception.
    """
    _config_file, cfg = store

    finished = threading.Event()

    def nested():
        with cfg._store_lock():
            with cfg._store_lock():
                pass
        finished.set()

    runner = threading.Thread(target=nested, daemon=True)
    runner.start()
    runner.join(timeout=3)

    assert finished.is_set(), (
        "a re-entrant _store_lock on one thread never returned: the second "
        "acquisition blocks on the first, and the thread is unrecoverable "
        "short of killing the process. Any future code path that calls "
        "write_profile or delete_profile from inside the store lock hangs the "
        "MCP server with no error"
    )


def test_lockfile_createdunderapermissiveumask_ismode600(store):
    """The READMEs put 0600 in the lock file's row; the umask must not win.

    ``os.open``'s mode argument is masked by the umask, which is why
    ``_store_lock`` follows it with an explicit ``fchmod``. Under ``umask 000``
    the O_CREAT mode alone would leave the file world-writable.
    """
    _config_file, cfg = store

    previous = os.umask(0o000)
    try:
        with cfg._store_lock() as ok:
            assert ok, "the lock degraded; this case needs the locked path"
    finally:
        os.umask(previous)

    mode = stat.S_IMODE(cfg._lock_path().stat().st_mode)
    assert mode == 0o600, (
        f"config.toml.lock is mode {oct(mode)} under umask 000, but all three "
        f"READMEs list it as 0600"
    )
