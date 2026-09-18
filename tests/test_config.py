"""Tests for the config / profile / keyring layer."""
from __future__ import annotations

import errno
import os
import stat
import threading
import time
from pathlib import Path

import pytest

from redshift_comment_mcp import config

# The real module, kept aside so a test that blanks ``config._fcntl`` can put a
# working one back and check the bookkeeping survived the round trip.
_real_fcntl = config._fcntl


@pytest.fixture
def tmp_xdg(tmp_path: Path, monkeypatch):
    """Redirect XDG_CONFIG_HOME to a tmp dir so tests don't touch the user's real config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def fake_keyring(monkeypatch):
    """In-memory keyring stand-in."""
    storage: dict[tuple[str, str], str] = {}

    def _set(service, user, password):
        storage[(service, user)] = password

    def _get(service, user):
        return storage.get((service, user))

    def _delete(service, user):
        if (service, user) in storage:
            del storage[(service, user)]
        else:
            from keyring.errors import PasswordDeleteError
            raise PasswordDeleteError("not found")

    import keyring as _kr
    monkeypatch.setattr(_kr, "set_password", _set)
    monkeypatch.setattr(_kr, "get_password", _get)
    monkeypatch.setattr(_kr, "delete_password", _delete)
    return storage


def test_config_path_uses_xdg(tmp_xdg):
    p = config.config_path()
    assert str(p).startswith(str(tmp_xdg))
    assert p.name == "config.toml"


def test_read_all_returns_empty_when_missing(tmp_xdg):
    assert config.read_all() == {}


def test_read_profile_missing(tmp_xdg):
    assert config.read_profile("nope") is None


def test_write_then_read_profile_roundtrip(tmp_xdg):
    config.write_profile(
        "default",
        host="my-cluster.example.com",
        port=5439,
        user="alice",
        dbname="analytics",
    )
    p = config.read_profile("default")
    assert p == {
        "host": "my-cluster.example.com",
        "port": 5439,
        "user": "alice",
        "dbname": "analytics",
    }


def test_write_profile_sets_mode_600(tmp_xdg):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    mode = config.config_path().stat().st_mode & 0o777
    assert mode == 0o600


def test_multiple_profiles(tmp_xdg):
    config.write_profile("dev", host="dev.example.com", port=5439, user="u", dbname="d")
    config.write_profile("prod", host="prod.example.com", port=5439, user="u", dbname="d")
    assert sorted(config.read_all().keys()) == ["dev", "prod"]
    assert config.read_profile("dev")["host"] == "dev.example.com"
    assert config.read_profile("prod")["host"] == "prod.example.com"


def test_list_profiles_sorted(tmp_xdg):
    config.write_profile("zeta", host="h", port=5439, user="u", dbname="d")
    config.write_profile("alpha", host="h", port=5439, user="u", dbname="d")
    assert config.list_profiles() == ["alpha", "zeta"]


# ===== atomic config.toml writes (acceptance 2, 6) =====


def _dump_torn_mid_value(monkeypatch, *, then):
    """Patch ``tomli_w.dump`` to stop mid-value, run ``then``, then finish.

    The cut lands two bytes past the first ``"`` in the serialised output, so
    the partial bytes always end inside an unterminated string — never on a
    clean table boundary that would still parse. The bytes are flushed and
    fsynced before ``then`` runs, so ``then`` observes the exact instant a torn
    write is visible on disk.

    This is what makes the "reader never sees a partial file" property
    deterministic: rather than racing a thread against the writer and hoping to
    catch the window, the reader is invoked *inside* the window on every run.
    """
    import tomli_w

    real_dumps = tomli_w.dumps

    def fake_dump(obj, fp, **kwargs):
        payload = real_dumps(obj).encode()
        cut = payload.index(b'"') + 2
        fp.write(payload[:cut])
        fp.flush()
        os.fsync(fp.fileno())
        then()
        fp.write(payload[cut:])

    monkeypatch.setattr(tomli_w, "dump", fake_dump)


def _config_dir_entries() -> list[str]:
    return sorted(q.name for q in config.config_path().parent.iterdir())


def test_write_profile_midwrite_failure_keeps_previous_bytes(tmp_xdg, monkeypatch):
    """An ENOSPC-shaped failure mid-write must leave the previous file intact.

    Also the acceptance-6 failure case: the *unrelated* sibling profile must
    survive a failed write of another profile.
    """
    config.write_profile("prod", host="prod.example.com", port=5439, user="u", dbname="d")
    config.write_profile("dev", host="dev.example.com", port=5439, user="u", dbname="d")
    before_bytes = config.config_path().read_bytes()
    before_mode = config.config_path().stat().st_mode & 0o777
    before_profiles = config.read_all()

    def out_of_space():
        raise OSError(errno.ENOSPC, "No space left on device")

    _dump_torn_mid_value(monkeypatch, then=out_of_space)

    with pytest.raises(OSError):
        config.write_profile(
            "staging", host="staging.example.com", port=5439, user="u", dbname="d"
        )

    assert config.config_path().read_bytes() == before_bytes
    assert config.config_path().stat().st_mode & 0o777 == before_mode
    assert config.read_all() == before_profiles
    assert _config_dir_entries() == ["config.toml", "config.toml.lock"]


def test_write_profile_success_replaces_content(tmp_xdg):
    """The negative case: a successful write really does replace the content."""
    config.write_profile("default", host="old.example.com", port=5439, user="u", dbname="d")
    config.write_profile("default", host="new.example.com", port=5440, user="u2", dbname="d2")

    assert config.read_profile("default") == {
        "host": "new.example.com",
        "port": 5440,
        "user": "u2",
        "dbname": "d2",
    }
    assert config.config_path().stat().st_mode & 0o777 == 0o600
    assert _config_dir_entries() == ["config.toml", "config.toml.lock"]


def test_sibling_profiles_survive_a_write(tmp_xdg):
    """Acceptance 6: every other profile is present and unchanged after a write."""
    config.write_profile("prod", host="prod.example.com", port=5439, user="pu", dbname="pd")
    config.write_profile("dev", host="dev.example.com", port=5439, user="du", dbname="dd")
    prod_before = config.read_profile("prod")

    config.write_profile("dev", host="dev2.example.com", port=5440, user="du", dbname="dd")

    assert config.read_profile("prod") == prod_before
    assert config.read_profile("dev")["host"] == "dev2.example.com"
    assert sorted(config.read_all()) == ["dev", "prod"]


def test_reader_never_sees_a_partial_file(tmp_xdg, monkeypatch):
    """Boundary: a reader mid-write sees the whole old file or the whole new one."""
    config.write_profile("prod", host="prod.example.com", port=5439, user="u", dbname="d")
    config.write_profile("dev", host="dev.example.com", port=5439, user="u", dbname="d")
    before = config.read_all()
    observed: dict[str, object] = {}

    def read_while_the_write_is_in_flight():
        try:
            observed["profiles"] = config.read_all()
        except Exception as exc:  # noqa: BLE001 — recorded, then asserted on
            observed["error"] = exc

    _dump_torn_mid_value(monkeypatch, then=read_while_the_write_is_in_flight)

    config.write_profile(
        "staging", host="staging.example.com", port=5439, user="u", dbname="d"
    )

    assert "error" not in observed, f"reader hit a torn file: {observed.get('error')!r}"
    assert observed["profiles"] == before
    assert sorted(config.read_all()) == ["dev", "prod", "staging"]


def test_delete_profile_midwrite_failure_keeps_previous_bytes(
    tmp_xdg, fake_keyring, monkeypatch
):
    """delete_profile's write goes through the same atomic path."""
    config.write_profile("prod", host="prod.example.com", port=5439, user="u", dbname="d")
    config.write_profile("dev", host="dev.example.com", port=5439, user="u", dbname="d")
    before_bytes = config.config_path().read_bytes()

    def out_of_space():
        raise OSError(errno.ENOSPC, "No space left on device")

    _dump_torn_mid_value(monkeypatch, then=out_of_space)

    with pytest.raises(OSError):
        config.delete_profile("dev")

    assert config.config_path().read_bytes() == before_bytes
    assert sorted(config.read_all()) == ["dev", "prod"]
    assert _config_dir_entries() == ["config.toml", "config.toml.lock"]


# ===== serialised read-modify-write (acceptance 1, 5) =====


def _widen_the_write_window(monkeypatch, delay: float = 0.02):
    """Make ``_write_all`` take ``delay`` seconds, lengthening the RMW window.

    ``write_profile`` is read -> mutate -> write. The profile-losing
    interleaving is "every writer reads before any writer writes", and left to
    chance it is a race one *usually* wins. Injecting a delay in front of the
    write turns it into the certain outcome of an unserialised implementation,
    so the failure is reproducible rather than lucky.

    It costs a correct implementation nothing but time: the delay lands inside
    the critical section, so the eight writes queue and the test takes
    8 x ``delay``. Nothing in the assertion depends on how long that is.
    """
    real_write_all = config._write_all

    def slow_write_all(profiles):
        time.sleep(delay)
        real_write_all(profiles)

    monkeypatch.setattr(config, "_write_all", slow_write_all)


def test_concurrent_writes_of_distinct_profiles_keep_every_one(tmp_xdg, monkeypatch):
    """Acceptance 1: eight concurrent writers, eight names, none lost."""
    names = [f"profile{i}" for i in range(8)]
    barrier = threading.Barrier(len(names))
    errors: list[BaseException] = []
    _widen_the_write_window(monkeypatch)

    def run(name: str) -> None:
        try:
            barrier.wait(timeout=10)
            config.write_profile(
                name, host=f"{name}.example.com", port=5439, user=name, dbname=name
            )
        except BaseException as exc:  # noqa: BLE001 — recorded, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"a concurrent write raised: {errors}"
    assert not any(t.is_alive() for t in threads), "a writer never finished"

    written = config.read_all()
    assert sorted(written) == sorted(names)
    for name in names:
        assert written[name]["host"] == f"{name}.example.com"


def test_single_writer_is_unaffected_by_the_lock(tmp_xdg):
    """Negative case: serialising must not change what one writer alone does."""
    config.write_profile("prod", host="prod.example.com", port=5439, user="u", dbname="d")
    config.write_profile("dev", host="dev.example.com", port=5440, user="u2", dbname="d2")

    assert sorted(config.read_all()) == ["dev", "prod"]
    assert config.read_profile("dev") == {
        "host": "dev.example.com",
        "port": 5440,
        "user": "u2",
        "dbname": "d2",
    }
    assert config.config_path().stat().st_mode & 0o777 == 0o600
    assert _config_dir_entries() == ["config.toml", "config.toml.lock"]


def test_lock_file_is_mode_600(tmp_xdg):
    """The lock file sits beside config.toml, so it keeps the same posture."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    assert config._lock_path().stat().st_mode & 0o777 == 0o600


def test_lock_is_released_when_the_write_raises(tmp_xdg, monkeypatch):
    """Boundary: a failed write must not leave the store locked forever.

    The lock is probed from a second descriptor with ``LOCK_NB`` rather than by
    issuing another write: a leaked lock would make a blocking re-acquire HANG
    the suite instead of failing it, and a hang is not a test result.
    """
    fcntl = pytest.importorskip("fcntl")
    config.write_profile("prod", host="prod.example.com", port=5439, user="u", dbname="d")

    def out_of_space():
        raise OSError(errno.ENOSPC, "No space left on device")

    _dump_torn_mid_value(monkeypatch, then=out_of_space)

    with pytest.raises(OSError):
        config.write_profile(
            "staging", host="staging.example.com", port=5439, user="u", dbname="d"
        )

    fd = os.open(config._lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pytest.fail("the store lock was still held after the write raised")
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_lock_still_excludes_after_the_lock_file_is_deleted_mid_write(tmp_xdg):
    """Boundary: ``rm config.toml.lock`` under a live writer must not disarm the lock.

    ``flock`` serialises holders of an *inode*, while ``_store_lock`` reaches
    for a *name*. Delete the lock file while writer A holds it and writer B
    creates a fresh inode at the same name, locks that instead, and runs its
    read-modify-write beside A's — both then rewrite the whole store and the
    later rename drops the earlier one's profile, with nothing raised anywhere.

    The second holder is joined with a timeout rather than blocked on: if the
    exclusion is off it enters immediately, and if it is on it is still parked
    when the assertion runs, so this case fails rather than hangs either way.
    """
    pytest.importorskip("fcntl")

    holding, release = threading.Event(), threading.Event()
    first_locked: list[bool] = []
    second_entered: list[bool] = []

    def first() -> None:
        with config._store_lock() as locked:
            first_locked.append(locked)
            holding.set()
            release.wait(timeout=10)

    def second() -> None:
        with config._store_lock():
            second_entered.append(True)

    holder = threading.Thread(target=first)
    holder.start()
    try:
        assert holding.wait(timeout=10), "the first writer never took the lock"
        assert first_locked == [True], f"the first writer degraded: {first_locked}"

        lock_file = config._lock_path()
        assert lock_file.exists(), "no lock file to delete"
        lock_file.unlink()

        contender = threading.Thread(target=second, daemon=True)
        contender.start()
        contender.join(timeout=2)
        entered_while_held = bool(second_entered)
    finally:
        release.set()
        holder.join(timeout=10)

    contender.join(timeout=10)

    assert not entered_while_held, (
        "a second writer entered the store lock while the first still held it, "
        "because the lock file had been unlinked and the name now points at a "
        "brand-new inode — two read-modify-write cycles over one config.toml"
    )
    assert second_entered == [True], "the second writer never acquired after the release"


def test_write_degrades_to_unlocked_when_fcntl_is_unavailable(tmp_xdg, monkeypatch):
    """Where POSIX locking is absent the write still lands — it is just unserialised.

    Windows has no ``fcntl``. Refusing to write there would be a worse failure
    than the concurrency hazard the lock removes, and no third-party locking
    dependency is added to cover it.
    """
    monkeypatch.setattr(config, "_fcntl", None)

    config.write_profile("default", host="h", port=5439, user="u", dbname="d")

    assert config.read_profile("default")["host"] == "h"
    assert _config_dir_entries() == ["config.toml"], "no lock file without fcntl"


def _lock_file_is_flocked() -> bool:
    """Is ``config.toml.lock`` held right now, as seen from a fresh descriptor?

    ``flock`` attaches to the open file description, not to the process, so a
    ``LOCK_NB`` attempt on a descriptor this helper opens itself conflicts with
    a lock the *same* process holds through another one. That is what makes it
    a usable witness for "the re-entrant path really did take the lock" — and
    ``LOCK_NB`` means a wrong answer fails the suite instead of hanging it.
    """
    import fcntl

    fd = os.open(config._lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def test_store_lock_is_reentrant_on_one_thread(tmp_xdg):
    """Boundary: taking the store lock twice on one thread must not deadlock.

    ``flock`` serialises open file descriptions and ``_store_lock`` opens a
    fresh descriptor per call, so a second acquisition on the same thread would
    block on the first with nothing left running to release it. The thread is
    then unrecoverable short of killing the process, and the symptom is a hang
    rather than an exception — the worst shape a failure can take in a server a
    user is waiting on. No caller nests today; this pins the day one does.

    The nesting runs on a daemon thread joined with a timeout so that a
    regression fails this test rather than wedging the whole suite.
    """
    pytest.importorskip("fcntl")

    finished = threading.Event()
    yielded: list[bool] = []
    held_inside: list[bool] = []

    def nested() -> None:
        with config._store_lock() as outer:
            yielded.append(outer)
            with config._store_lock() as inner:
                yielded.append(inner)
                held_inside.append(_lock_file_is_flocked())
        finished.set()

    runner = threading.Thread(target=nested, daemon=True)
    runner.start()
    runner.join(timeout=5)

    assert finished.is_set(), (
        "a re-entrant _store_lock on one thread never returned: the second "
        "acquisition blocked on the first, and any future code path that calls "
        "write_profile or delete_profile from inside the store lock would hang "
        "the MCP server with no error"
    )
    assert yielded == [True, True], (
        f"the nested acquisition should report the lock as held, got {yielded!r}"
    )
    assert held_inside == [True], (
        "the lock file was not actually locked inside the nested acquisition"
    )


def test_store_lock_releases_only_when_the_outermost_holder_exits(tmp_xdg):
    """The inner exit must not release the lock the outer holder still owns.

    Re-entrancy that released on the way out of the *inner* block would be
    worse than the deadlock it replaces: the read-modify-write would carry on
    with the protection silently off.
    """
    pytest.importorskip("fcntl")

    seen: list[bool] = []

    def nested() -> None:
        with config._store_lock():
            with config._store_lock():
                pass
            seen.append(_lock_file_is_flocked())

    runner = threading.Thread(target=nested, daemon=True)
    runner.start()
    runner.join(timeout=5)

    assert seen == [True], (
        "leaving the inner store lock released the lock the outer holder still "
        f"owns (observed held={seen!r})"
    )
    assert not _lock_file_is_flocked(), (
        "the outermost holder exited without releasing the lock"
    )


def test_store_lock_reentrancy_is_per_thread_not_global(tmp_xdg):
    """Two threads must still exclude each other while one holds the lock.

    A depth counter kept in module state rather than thread-local state would
    make a *second thread* look like a nested acquisition and walk straight
    into the critical section — turning the deadlock fix into the concurrent
    profile loss the lock exists to prevent.

    The contender is joined with a timeout rather than blocked on: if the
    exclusion is off it enters immediately, and if it is on it is still parked
    when the assertion runs, so this case fails rather than hangs either way.
    """
    pytest.importorskip("fcntl")

    holding, release = threading.Event(), threading.Event()
    second_entered: list[bool] = []

    def first() -> None:
        with config._store_lock():
            with config._store_lock():
                holding.set()
                release.wait(timeout=10)

    def second() -> None:
        with config._store_lock():
            second_entered.append(True)

    holder = threading.Thread(target=first, daemon=True)
    holder.start()
    try:
        assert holding.wait(timeout=10), "the first thread never took the lock"
        contender = threading.Thread(target=second, daemon=True)
        contender.start()
        contender.join(timeout=2)
        entered_while_held = bool(second_entered)
    finally:
        release.set()
        holder.join(timeout=10)

    contender.join(timeout=10)

    assert not entered_while_held, (
        "a second thread entered the store lock while the first still held it: "
        "the re-entrancy bookkeeping is shared across threads instead of being "
        "thread-local, so two read-modify-write cycles run over one config.toml"
    )
    assert second_entered == [True], "the second thread never acquired after the release"


def test_store_lock_depth_unwinds_when_the_body_raises(tmp_xdg):
    """Boundary: an exception inside the lock must not leave the depth inflated.

    A counter that only decremented on the happy path would make every later
    acquisition on that thread look nested — yielding without ever taking the
    lock, so the store would run unserialised for the life of the process with
    nothing raised anywhere.
    """
    pytest.importorskip("fcntl")

    outcome: list[str] = []

    def body() -> None:
        with pytest.raises(RuntimeError):
            with config._store_lock():
                with config._store_lock():
                    raise RuntimeError("inner boom")
        with pytest.raises(RuntimeError):
            with config._store_lock():
                raise RuntimeError("outer boom")
        # If either raise leaked a level, this acquisition is treated as nested
        # and never touches flock.
        with config._store_lock():
            outcome.append("held" if _lock_file_is_flocked() else "unlocked")

    runner = threading.Thread(target=body, daemon=True)
    runner.start()
    runner.join(timeout=5)

    assert outcome == ["held"], (
        "after an exception unwound the store lock, a fresh acquisition did not "
        f"actually take it (observed {outcome!r}) — the depth counter leaked"
    )
    assert not _lock_file_is_flocked(), "the lock outlived its last holder"


def test_store_lock_is_reentrant_when_fcntl_is_unavailable(tmp_xdg, monkeypatch):
    """The non-POSIX path nests too: still unserialised, still no crash, no leak.

    Windows has no ``fcntl``, so both levels degrade to False. What matters is
    that nesting there neither raises nor disturbs the bookkeeping the POSIX
    path depends on.
    """
    pytest.importorskip("fcntl")
    monkeypatch.setattr(config, "_fcntl", None)

    yielded: list[bool] = []
    with config._store_lock() as outer:
        yielded.append(outer)
        with config._store_lock() as inner:
            yielded.append(inner)

    assert yielded == [False, False], (
        f"the degraded path should report unserialised at every level, got {yielded!r}"
    )
    assert not config._lock_path().exists(), "a lock file appeared with fcntl absent"

    monkeypatch.setattr(config, "_fcntl", _real_fcntl)
    with config._store_lock() as restored:
        assert restored is True, (
            "the degraded nesting corrupted the bookkeeping: the next real "
            "acquisition was treated as nested and never took the lock"
        )
        assert _lock_file_is_flocked(), "the restored acquisition did not lock"


def test_password_set_get_roundtrip(fake_keyring):
    config.set_password("default", "s3cret")
    assert config.get_password("default") == "s3cret"


def test_password_get_missing_returns_none(fake_keyring):
    assert config.get_password("never-set") is None


def test_delete_profile_removes_both_config_and_password(tmp_xdg, fake_keyring):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    config.set_password("default", "s3cret")

    assert config.delete_profile("default") is True
    assert config.read_profile("default") is None
    assert config.get_password("default") is None


def test_delete_profile_returns_false_when_missing(tmp_xdg, fake_keyring):
    assert config.delete_profile("not-there") is False


def test_delete_profile_tolerates_missing_keyring_entry(tmp_xdg, fake_keyring):
    """Deleting a profile that has no keychain password should not raise."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    # No password set.
    assert config.delete_profile("default") is True


# ===== delete removes the password first (acceptance 3, 4) =====

FIELDS = {"host": "h", "port": 5439, "user": "u", "dbname": "d"}


def _keyring_locked_on_delete(monkeypatch):
    """Make ``keyring.delete_password`` fail the way a locked keychain does.

    ``KeyringLocked`` is the class the OS backends raise when the user has not
    unlocked the keychain — it is *not* a ``PasswordDeleteError``, so the
    pre-change ``except PasswordDeleteError`` never caught it.
    """
    import keyring as _kr
    from keyring.errors import KeyringLocked

    def _delete(service, user):
        raise KeyringLocked("keychain is locked")

    monkeypatch.setattr(_kr, "delete_password", _delete)


def test_delete_profile_keychain_failure_keeps_fields_and_reports(
    tmp_xdg, fake_keyring, monkeypatch
):
    """A locked keychain must leave a whole profile, and be reported.

    Acceptance 3's positive case. The failure has to reach the caller as
    something it can act on — exiting as if the delete succeeded would leave a
    password stored under a name no interface lists any more.
    """
    config.write_profile("default", **FIELDS)
    config.set_password("default", "s3cret")
    _keyring_locked_on_delete(monkeypatch)

    with pytest.raises(config.KeychainDeleteError):
        config.delete_profile("default")

    assert config.read_profile("default") == FIELDS, "fields must survive"
    assert fake_keyring[(config.KEYRING_SERVICE, "default")] == "s3cret"


def test_delete_profile_removes_the_password_before_the_fields(
    tmp_xdg, fake_keyring, monkeypatch
):
    """Acceptance 3's ordering half, observed from inside the store write."""
    config.write_profile("default", **FIELDS)
    config.set_password("default", "s3cret")

    observed: dict[str, object] = {}
    real_write_all = config._write_all

    def spy(profiles):
        observed["password_at_write"] = config.get_password("default")
        return real_write_all(profiles)

    monkeypatch.setattr(config, "_write_all", spy)

    assert config.delete_profile("default") is True
    assert observed["password_at_write"] is None, "password still stored at write time"
    assert config.read_profile("default") is None
    assert config.get_password("default") is None


def test_delete_profile_missing_never_touches_the_keychain(
    tmp_xdg, fake_keyring, monkeypatch
):
    """Acceptance 3's negative boundary: an absent profile changes nothing.

    Deleting the password first must not start reaching into the keychain for
    names that were never configured — on a locked keychain that would turn
    today's quiet ``False`` into a raised failure.
    """
    import keyring as _kr

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_kr, "delete_password", lambda s, u: calls.append((s, u)))

    assert config.delete_profile("not-there") is False
    assert calls == []


def test_delete_profile_clears_pointer_that_named_it(tmp_xdg, fake_keyring):
    """Acceptance 4's positive case.

    An explicit pointer beats the lone-profile fallback in
    ``resolve_active_profile``, so a pointer left naming a deleted profile
    wedges the server until a human removes the file by hand.
    """
    config.write_profile("prod", **FIELDS)
    config.set_password("prod", "s3cret")
    config.write_active_profile("prod")

    assert config.delete_profile("prod") is True
    assert config.read_active_profile() is None
    assert not config.active_profile_path().exists()


def test_delete_profile_keeps_pointer_that_named_another(tmp_xdg, fake_keyring):
    """Acceptance 4's negative case: another profile's pointer is untouched."""
    config.write_profile("dev", **FIELDS)
    config.write_profile("prod", **FIELDS)
    config.write_active_profile("prod")

    assert config.delete_profile("dev") is True
    assert config.read_active_profile() == "prod"
    assert config.active_profile_path().stat().st_mode & 0o777 == 0o600


def test_delete_profile_keychain_failure_leaves_the_pointer(
    tmp_xdg, fake_keyring, monkeypatch
):
    """Nothing was deleted, so the pointer must still name the live profile."""
    config.write_profile("prod", **FIELDS)
    config.set_password("prod", "s3cret")
    config.write_active_profile("prod")
    _keyring_locked_on_delete(monkeypatch)

    with pytest.raises(config.KeychainDeleteError):
        config.delete_profile("prod")

    assert config.read_active_profile() == "prod"


# ===== active-profile pointer =====


def test_active_profile_path_uses_xdg(tmp_xdg):
    p = config.active_profile_path()
    assert str(p).startswith(str(tmp_xdg))
    assert p.name == "active-profile"


def test_read_active_profile_returns_none_when_missing(tmp_xdg):
    assert config.read_active_profile() is None


def test_write_then_read_active_profile_roundtrip(tmp_xdg):
    config.write_active_profile("prod")
    assert config.read_active_profile() == "prod"


def test_write_active_profile_sets_mode_600(tmp_xdg):
    config.write_active_profile("prod")
    mode = config.active_profile_path().stat().st_mode & 0o777
    assert mode == 0o600


def test_write_active_profile_overwrites(tmp_xdg):
    config.write_active_profile("prod")
    config.write_active_profile("dev")
    assert config.read_active_profile() == "dev"


def test_read_active_profile_strips_whitespace(tmp_xdg):
    p = config.active_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("  prod  \n")
    assert config.read_active_profile() == "prod"


def test_read_active_profile_empty_file_returns_none(tmp_xdg):
    p = config.active_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("   \n")
    assert config.read_active_profile() is None


def test_clear_active_profile_removes_file(tmp_xdg):
    config.write_active_profile("prod")
    assert config.active_profile_path().exists()
    config.clear_active_profile()
    assert not config.active_profile_path().exists()


def test_clear_active_profile_is_idempotent_when_absent(tmp_xdg):
    # Should not raise even when the file is absent.
    config.clear_active_profile()
    assert not config.active_profile_path().exists()


def test_resolve_active_profile_cli_arg_wins(tmp_xdg, monkeypatch):
    """CLI arg beats env var beats file beats fallback."""
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "envname")
    config.write_active_profile("filename")
    assert config.resolve_active_profile("cli-name") == "cli-name"


def test_resolve_active_profile_env_wins_over_file(tmp_xdg, monkeypatch):
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "envname")
    config.write_active_profile("filename")
    assert config.resolve_active_profile() == "envname"


def test_resolve_active_profile_file_when_no_env(tmp_xdg, monkeypatch):
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_active_profile("filename")
    assert config.resolve_active_profile() == "filename"


def test_resolve_active_profile_falls_back_to_default(tmp_xdg, monkeypatch):
    """No CLI arg, no env var, no file → 'default'. Single-profile state."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    assert config.resolve_active_profile() == "default"


def test_resolve_active_profile_empty_env_treated_as_unset(tmp_xdg, monkeypatch):
    """Empty env var should not pin to "" — fall through to next layer."""
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "")
    config.write_active_profile("filename")
    assert config.resolve_active_profile() == "filename"


def test_resolve_active_profile_empty_cli_arg_treated_as_unset(tmp_xdg, monkeypatch):
    """Empty CLI arg should not pin to "" — fall through to env var."""
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "envname")
    assert config.resolve_active_profile("") == "envname"


# ===== single-profile fallback (upgrade-rescue for PR #22) =====
#
# 3884f98 made single-profile users canonical with "absent pointer file =
# use 'default'". That works only for users whose single profile happens
# to be named "default". Pre-3884f98 setups picked the name at install
# time, so anyone with a non-"default" name got hard-broken by the
# upgrade. These tests pin the rescue: when the implicit fallback would
# hit a missing "default" profile, but exactly one profile exists, use
# that one. Multi-profile / zero-profile cases stay loud (server raises
# its existing ValueError with improved guidance from server.py).


def test_resolve_active_profile_falls_back_to_single_profile_when_no_default(
    tmp_xdg, monkeypatch
):
    """Upgrade rescue: one profile, not named 'default', no pointer file,
    no env, no CLI → use that one profile."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile("ichef-prod", host="h", port=5439, user="u", dbname="d")
    assert config.resolve_active_profile() == "ichef-prod"


def test_resolve_active_profile_prefers_default_over_other_profiles(
    tmp_xdg, monkeypatch
):
    """When 'default' exists alongside others, the implicit fallback must
    still pick 'default' — backward compatibility for users who do use
    that name."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile("default", host="h1", port=5439, user="u", dbname="d")
    config.write_profile("prod", host="h2", port=5439, user="u", dbname="d")
    assert config.resolve_active_profile() == "default"


def test_resolve_active_profile_returns_default_when_multiple_profiles_no_default(
    tmp_xdg, monkeypatch
):
    """Ambiguous case: 2+ profiles, none 'default', no pointer file.
    Return 'default' so the server raises a clear error pointing at
    /redshift-switch-profile — do NOT silently pick one of them."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile("prod", host="h1", port=5439, user="u", dbname="d")
    config.write_profile("staging", host="h2", port=5439, user="u", dbname="d")
    # Returns literal "default" — server.read_profile("default") then fails
    # cleanly, which triggers the improved error message tested in
    # test_server_resolution.py.
    assert config.resolve_active_profile() == "default"


def test_resolve_active_profile_returns_default_when_no_profiles_at_all(
    tmp_xdg, monkeypatch
):
    """Fresh install / empty config.toml: nothing to rescue with, return
    'default' so server raises the 'run /redshift-setup' error."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    assert config.resolve_active_profile() == "default"


def test_resolve_active_profile_pointer_file_overrides_single_profile_fallback(
    tmp_xdg, monkeypatch
):
    """If user explicitly set a pointer file, honor it even if it names a
    non-existent profile — explicit beats implicit, lets server raise a
    'pointer references missing profile' style error rather than silently
    redirecting to the single existing profile."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile("ichef-prod", host="h", port=5439, user="u", dbname="d")
    config.write_active_profile("ghost-profile")
    assert config.resolve_active_profile() == "ghost-profile"


# ===== the rename destination: symlinks, litter, durability =====


def _link_config_toml_to(tmp_xdg: Path, target: Path) -> Path:
    """Make config.toml a symlink to ``target`` and return the link path."""
    p = config.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.symlink_to(target)
    return p


def test_write_profile_through_a_symlinked_config_toml_keeps_the_link(tmp_xdg):
    """A config.toml symlinked into a dotfiles checkout must survive the write.

    ``os.replace(tmp, p)`` acts on the *name*: it unlinks the link and drops a
    regular file in its place, so every later write lands somewhere the user's
    dotfiles repo cannot see, with no error. The pre-change writer opened the
    path and followed the link.
    """
    target = tmp_xdg / "dotfiles" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('[profile.prod]\nhost = "old"\nport = 5439\n'
                      'user = "u"\ndbname = "d"\n')
    link = _link_config_toml_to(tmp_xdg, target)

    config.write_profile("prod", host="new", port=5439, user="u", dbname="d")

    assert link.is_symlink(), "the write replaced the symlink with a regular file"
    assert "new" in target.read_text(), "the symlink target never got the write"


def test_write_profile_through_a_dangling_symlink_creates_the_target(tmp_xdg):
    """A link whose target does not exist yet must be written *through*, not over."""
    target = tmp_xdg / "dotfiles" / "config.toml"  # neither file nor parent exists
    link = _link_config_toml_to(tmp_xdg, target)

    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")

    assert link.is_symlink(), "the write replaced the dangling link with a file"
    assert target.is_file(), "the link target was never created"
    assert config.read_profile("prod")["host"] == "h"


def test_write_profile_puts_its_temp_file_in_the_resolved_parent(tmp_xdg, monkeypatch):
    """The temp file must follow the rename destination, not the config dir.

    ``os.replace`` is atomic only within one filesystem. Once the destination
    is the symlink's target, a temp file left behind in the config directory
    can be on a different device and the rename stops being atomic — or fails
    outright with EXDEV.
    """
    target = tmp_xdg / "dotfiles" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text("")
    _link_config_toml_to(tmp_xdg, target)

    import tempfile as _tempfile

    seen: list[str] = []
    real_mkstemp = _tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        seen.append(kwargs.get("dir"))
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(_tempfile, "mkstemp", recording_mkstemp)
    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")

    assert seen == [str(target.parent)], (
        f"the temp file was created in {seen}, not beside the file the rename "
        f"actually lands on ({target.parent})"
    )


def test_write_profile_sweeps_stale_temp_files(tmp_xdg):
    """Temp files a killed process left behind must not accumulate forever."""
    config.write_profile("keepme", host="h", port=5439, user="u", dbname="d")
    config_dir = config.config_path().parent

    stale = config_dir / ".config.toml.abc123.tmp"
    stale.write_text("a full copy of the store from a crash two days ago")
    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))

    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")

    assert not stale.exists(), (
        "a two-day-old .config.toml.*.tmp survived a write; each one holds a "
        "full copy of the profile store and nothing else ever removes it"
    )
    assert config.read_profile("keepme") is not None


def test_write_profile_keeps_temp_files_a_live_writer_may_still_own(tmp_xdg):
    """The sweep is age-gated, so it cannot pull the rug from a write in flight."""
    config.write_profile("keepme", host="h", port=5439, user="u", dbname="d")
    config_dir = config.config_path().parent

    fresh = config_dir / ".config.toml.def456.tmp"
    fresh.write_text("a write that started a moment ago")

    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")

    assert fresh.exists(), "the sweep removed a temp file young enough to be live"


def test_write_profile_fsyncs_the_config_directory(tmp_xdg, monkeypatch):
    """The rename is durable only once the directory holding it is fsynced."""
    config_dir = config.config_path().parent
    config_dir.mkdir(parents=True, exist_ok=True)
    dir_inode = config_dir.stat().st_ino

    synced: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd):
        try:
            synced.append(os.fstat(fd).st_ino)
        except OSError:
            pass
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")

    assert dir_inode in synced, (
        "only the temp file's contents were fsynced; a power loss right after "
        "a successful write can lose the rename that made it visible"
    )


# ===== the active-profile pointer gets the same protections =====


def test_clear_active_profile_survives_the_pointer_vanishing_mid_call(
    tmp_xdg, monkeypatch
):
    """``if exists(): unlink()`` raises when someone wins the race in between.

    ``delete_profile`` clears the pointer after the password and the fields are
    already gone, so this turns a delete that in fact succeeded into an uncaught
    ``FileNotFoundError``.
    """
    config.write_active_profile("prod")

    real_exists = Path.exists

    def vanishing_exists(self, *args, **kwargs):
        present = real_exists(self, *args, **kwargs)
        if present and self.name == "active-profile":
            os.unlink(str(self))
        return present

    monkeypatch.setattr(Path, "exists", vanishing_exists)
    config.clear_active_profile()  # must not raise

    monkeypatch.setattr(Path, "exists", real_exists)
    assert config.active_profile_path().exists() is False


def test_read_active_profile_answers_none_when_the_pointer_already_vanished(
    tmp_xdg, monkeypatch
):
    """``if exists(): read_text()`` raises when the file goes in between too.

    Same race as :func:`clear_active_profile`, on the reader that
    ``delete_profile`` consults before it clears. A stale ``exists()`` that
    still says "present" is exactly what a reader observes when it loses that
    race.
    """
    config.active_profile_path().parent.mkdir(parents=True, exist_ok=True)
    real_exists = Path.exists

    def stale_exists(self, *args, **kwargs):
        if self.name == "active-profile":
            return True
        return real_exists(self, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "exists", stale_exists)
        assert config.read_active_profile() is None


def test_delete_profile_leaves_a_pointer_re_aimed_mid_delete_alone(
    tmp_xdg, fake_keyring, monkeypatch
):
    """A switch that completes during the delete must not be silently reverted.

    The pointer read and the pointer clear had nothing held across them, so a
    ``/redshift-switch-profile`` landing in between had its result thrown away
    and the server fell back to the implicit rule — a different cluster than the
    user asked for.
    """
    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")
    config.write_profile("dev", host="d", port=5439, user="u", dbname="d")
    config.set_password("prod", "pw")
    config.write_active_profile("prod")

    real_read = config.read_active_profile
    switched: list[bool] = []

    def read_then_switch():
        answer = real_read()
        if not switched:
            switched.append(True)
            config.write_active_profile("dev")
        return answer

    with monkeypatch.context() as m:
        m.setattr(config, "read_active_profile", read_then_switch)
        assert config.delete_profile("prod") is True

    assert config.read_active_profile() == "dev", (
        "the user's switch to 'dev' was reverted by a delete of 'prod'"
    )


def test_delete_profile_still_clears_a_pointer_nobody_touched(tmp_xdg, fake_keyring):
    """The re-check must not cost the clear in the ordinary case."""
    config.write_profile("prod", host="h", port=5439, user="u", dbname="d")
    config.set_password("prod", "pw")
    config.write_active_profile("prod")

    assert config.delete_profile("prod") is True
    assert config.read_active_profile() is None


def test_write_active_profile_replaces_the_pointer_by_rename(tmp_xdg):
    """Truncate-then-write lets a reader see a zero-length pointer.

    ``read_active_profile`` maps empty to None and ``resolve_active_profile``
    then falls through to the implicit rule. A rename gives the reader either
    the whole old name or the whole new one; the inode changing is what proves
    the file was replaced rather than rewritten in place.
    """
    config.write_active_profile("prod")
    pointer = config.active_profile_path()
    before = pointer.stat().st_ino

    config.write_active_profile("dev")

    assert pointer.stat().st_ino != before, (
        "the pointer kept its inode across a rewrite: it was truncated in "
        "place, so a concurrent reader can observe it empty"
    )
    assert config.read_active_profile() == "dev"


def test_write_active_profile_failed_replace_keeps_the_previous_pointer(
    tmp_xdg, monkeypatch
):
    """A failure before the rename leaves the old pointer and no litter."""
    config.write_active_profile("prod")
    before = _config_dir_entries()

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    with monkeypatch.context() as m:
        m.setattr(os, "replace", boom)
        with pytest.raises(RuntimeError):
            config.write_active_profile("dev")

    assert config.read_active_profile() == "prod"
    assert _config_dir_entries() == before


def test_write_active_profile_never_holds_its_contents_at_mode_644(
    tmp_xdg, monkeypatch
):
    """``write_text`` creates at 0644 under the default umask, chmod second."""
    config.active_profile_path().parent.mkdir(parents=True, exist_ok=True)
    observed: list[int] = []

    real_chmod = Path.chmod

    def observing_chmod(self, mode, *args, **kwargs):
        if self.name == "active-profile":
            observed.append(stat.S_IMODE(self.stat().st_mode))
        return real_chmod(self, mode, *args, **kwargs)

    previous = os.umask(0o022)
    try:
        with monkeypatch.context() as m:
            m.setattr(Path, "chmod", observing_chmod)
            config.write_active_profile("prod")
    finally:
        os.umask(previous)

    assert observed, "write_active_profile never chmods the pointer"
    assert observed[0] == 0o600, (
        f"the pointer held its contents at {oct(observed[0])} before the chmod"
    )
