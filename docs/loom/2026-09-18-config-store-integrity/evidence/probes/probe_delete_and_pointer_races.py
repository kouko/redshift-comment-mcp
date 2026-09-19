"""Adversarial probes: delete_profile's new ordering, and the unprotected pointer.

Change: 2026-09-18-config-store-integrity
Anchor: src/redshift_comment_mcp/config.py :: delete_profile, clear_active_profile,
        write_active_profile

``delete_profile`` now runs keychain -> fields -> pointer. The middle step is
inside the store lock; the first and the last are outside it, and the pointer
file has no lock, no temp file and no rename of its own. These probes take the
two unprotected steps apart: a pointer that disappears under the delete, a
pointer another process re-aims while the delete is between its read and its
clear, a delete killed in the window where the password is already gone, and
the pointer file's own write.

The interleavings are injected deterministically rather than raced: the
injection point is the exact instruction boundary a second process would land
on, so the probe reproduces every run instead of most runs.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _probe_support import install_fake_keychain, isolate_config  # noqa: E402

SERVICE = "redshift-comment-mcp"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Throwaway config dir + in-memory keychain; returns (path, module, keychain)."""
    config_file = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    from redshift_comment_mcp import config as cfg

    return config_file, cfg, keychain


def _seed(cfg, name="prod", host="h.example.com"):
    cfg.write_profile(name, host=host, port=5439, user="u", dbname="d")
    cfg.set_password(name, f"pw-{name}")


def test_deleteprofile_pointervanishesbeforetheunlink_returnsinsteadofraising(
    store, monkeypatch
):
    """Lose the race inside clear_active_profile and the whole delete raises.

    ``clear_active_profile`` is ``if p.exists(): p.unlink()`` with no
    ``missing_ok``. Anything that removes the pointer in that window — the
    ``/redshift-switch-profile`` skill clearing it, a second delete of the same
    active profile, a user with an editor open — turns the last step of a
    delete that has ALREADY removed the password and the fields into an
    uncaught ``FileNotFoundError``.

    ``cmd_delete_profile`` catches only ``KeychainDeleteError``, so what the
    user sees is a traceback from a delete that in fact succeeded.
    """
    _config_file, cfg, _keychain = store
    _seed(cfg)
    cfg.write_active_profile("prod")

    real_exists = Path.exists
    armed = {"on": False}

    def losing_exists(self, *a, **kw):
        present = real_exists(self, *a, **kw)
        if armed["on"] and present and self.name == "active-profile":
            # This is the instruction boundary a concurrent switch-profile
            # lands on: the check said "present", and then it wasn't.
            os.unlink(str(self))
        return present

    real_read = cfg.read_active_profile

    def read_then_arm():
        answer = real_read()
        armed["on"] = True
        return answer

    monkeypatch.setattr(Path, "exists", losing_exists)
    monkeypatch.setattr(cfg, "read_active_profile", read_then_arm)

    raised = None
    try:
        cfg.delete_profile("prod")
    except FileNotFoundError as e:  # noqa: PERF203 — the point of the probe
        raised = e
    finally:
        armed["on"] = False

    assert raised is None, (
        "delete_profile raised FileNotFoundError from clear_active_profile "
        f"({raised}). The password and the fields were already removed, so the "
        "delete succeeded and then crashed; the CLI's only handler is for "
        "KeychainDeleteError, so this reaches the user as a traceback. "
        "clear_active_profile needs unlink(missing_ok=True)"
    )


def test_deleteprofile_pointerrepointedmidcall_leavesthenewpointeralone(
    store, monkeypatch
):
    """A switch that lands between the pointer read and the pointer clear is undone.

    ``delete_profile`` reads the pointer, decides it names the profile being
    deleted, and clears it — with nothing held across the two steps. A
    ``/redshift-switch-profile`` that completes in between has its result thrown
    away, and the server silently falls back to the implicit resolution instead
    of the profile the user just chose. This is the same lost-update shape the
    change fixed for config.toml, on the file it did not lock.
    """
    _config_file, cfg, _keychain = store
    _seed(cfg, "prod")
    _seed(cfg, "dev", host="dev.example.com")
    cfg.write_active_profile("prod")

    real_read = cfg.read_active_profile

    def read_then_switch():
        answer = real_read()
        # The concurrent switch-profile completes here, after the delete has
        # already decided the pointer names the doomed profile.
        cfg.write_active_profile("dev")
        return answer

    monkeypatch.setattr(cfg, "read_active_profile", read_then_switch)

    assert cfg.delete_profile("prod") is True
    monkeypatch.setattr(cfg, "read_active_profile", real_read)

    pointer = cfg.read_active_profile()
    assert pointer == "dev", (
        f"the pointer is {pointer!r} after a switch to 'dev' completed during a "
        "delete of 'prod'. The user's switch was silently reverted, and "
        "resolve_active_profile now falls back to the implicit rule — which "
        "picks a different cluster than the one they asked for"
    )


def test_deleteprofile_killedafterthekeychain_leavesarecoverableprofile(
    store, tmp_path
):
    """SIGKILL between the password delete and the field delete: what survives?

    The docstring argues this order is the recoverable one — a complete,
    still-listed profile the user can delete again. This runs it for real in a
    child process with a file-backed keychain and checks both halves of that
    claim: the fields are still there, and the password is gone.
    """
    config_file, cfg, _keychain = store
    _seed(cfg, "prod")
    _seed(cfg, "other", host="other.example.com")

    vault = tmp_path / "vault.json"
    vault.write_text(json.dumps({"prod": "pw-prod", "other": "pw-other"}))

    child = textwrap.dedent(
        """
        import json, os, signal, sys
        os.environ["XDG_CONFIG_HOME"] = sys.argv[1]
        os.environ.pop("REDSHIFT_COMMENT_PROFILE", None)
        vault = sys.argv[2]

        import keyring
        def _load():
            return json.loads(open(vault).read())
        def _save(d):
            open(vault, "w").write(json.dumps(d))
        keyring.get_password = lambda s, u: _load().get(u)
        def _delete(s, u):
            d = _load()
            d.pop(u, None)
            _save(d)
        keyring.delete_password = _delete

        from redshift_comment_mcp import config as cfg
        # The kill lands between the keychain delete and the field delete.
        cfg._write_all = lambda *a, **k: os.kill(os.getpid(), signal.SIGKILL)
        cfg.delete_profile("prod")
        """
    )
    script = tmp_path / "kill_after_keychain.py"
    script.write_text(child)

    proc = subprocess.run(
        [sys.executable, str(script), str(tmp_path), str(vault)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == -9, (
        f"the child was meant to be SIGKILLed mid-delete; it exited "
        f"{proc.returncode}. stderr: {proc.stderr}"
    )

    surviving = json.loads(vault.read_text())
    assert "prod" not in surviving, "the keychain entry outlived the kill"
    assert cfg.read_profile("prod") is not None, (
        "the interrupted delete left neither a password nor fields for 'prod': "
        "the profile is half-gone, and delete_profile's docstring claims this "
        "order leaves 'a complete, still-listed profile'"
    )
    assert "prod" in cfg.list_profiles(), "the user has no listed profile to re-delete"
    assert cfg.read_profile("other") is not None, "an unrelated profile was lost"


def test_deleteprofile_concurrentwithawriteofanother_keepsbothoperations(store):
    """A delete and an unrelated write at once: the lock must cover both sides.

    ``delete_profile`` and ``write_profile`` take the same lock, so the delete
    of 'doomed' and the creation of 'fresh' must both survive. If only writes
    were serialised, the loser's whole-file dump would resurrect or erase the
    other's profile.
    """
    _config_file, cfg, _keychain = store
    for i in range(6):
        _seed(cfg, f"doomed{i}", host=f"d{i}.example.com")

    barrier = threading.Barrier(12)
    errors: list[BaseException] = []

    def deleter(i):
        try:
            barrier.wait(timeout=15)
            cfg.delete_profile(f"doomed{i}")
        except BaseException as e:  # noqa: BLE001 — recorded and re-asserted
            errors.append(e)

    def writer(i):
        try:
            barrier.wait(timeout=15)
            cfg.write_profile(f"fresh{i}", host=f"f{i}.example.com", port=5439,
                              user="u", dbname="d")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=deleter, args=(i,)) for i in range(6)]
    threads += [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"a concurrent call raised: {errors}"

    names = set(cfg.list_profiles())
    resurrected = sorted(n for n in names if n.startswith("doomed"))
    lost = sorted({f"fresh{i}" for i in range(6)} - names)
    assert not resurrected, f"a concurrent write resurrected deleted profiles: {resurrected}"
    assert not lost, f"a concurrent delete erased freshly written profiles: {lost}"


def test_writeactiveprofile_readduringtherewrite_neverseesanemptypointer(store):
    """The pointer file is truncated in place, so a reader can see nothing at all.

    ``write_active_profile`` is ``write_text`` — open with O_TRUNC, then write.
    config.toml got a temp file and a rename precisely because that window
    loses data; the pointer did not. A reader landing in the window gets an
    empty file, ``read_active_profile`` maps that to ``None``, and
    ``resolve_active_profile`` silently falls through to the implicit rule —
    connecting the server to a different cluster than the pointer names.
    """
    _config_file, cfg, _keychain = store
    _seed(cfg, "prod")
    _seed(cfg, "dev", host="dev.example.com")
    cfg.write_active_profile("prod")

    stop = threading.Event()
    torn: list[str] = []

    def reader():
        while not stop.is_set():
            seen = cfg.read_active_profile()
            if seen not in ("prod", "dev"):
                torn.append(repr(seen))
                return

    watcher = threading.Thread(target=reader, daemon=True)
    watcher.start()
    for _ in range(4000):
        cfg.write_active_profile("prod")
        cfg.write_active_profile("dev")
        if torn:
            break
    stop.set()
    watcher.join(timeout=5)

    assert not torn, (
        f"a reader saw {torn[0]} while the pointer was being rewritten: the "
        "active-profile file is truncated before the new name is written, so a "
        "concurrent resolve_active_profile falls back to the implicit rule "
        "instead of the profile the pointer names. config.toml was given a "
        "temp file and a rename for exactly this; the pointer was not"
    )


def test_writeactiveprofile_freshfileunderumask022_isnevervisibleatmode644(store):
    """The pointer is chmod'd 0600 only after its content is already on disk.

    ``write_text`` creates the file at ``0666 & ~umask`` — 0644 under the
    default umask — and the ``chmod`` follows. The window is small and the
    contents are a profile name rather than a secret, but all three READMEs
    list this file as 0600 unconditionally.
    """
    _config_file, cfg, _keychain = store

    pointer = cfg.active_profile_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    observed: list[int] = []

    real_chmod = Path.chmod

    def observing_chmod(self, mode, *a, **kw):
        if self.name == "active-profile":
            observed.append(stat.S_IMODE(self.stat().st_mode))
        return real_chmod(self, mode, *a, **kw)

    previous = os.umask(0o022)
    Path.chmod = observing_chmod
    try:
        cfg.write_active_profile("prod")
    finally:
        Path.chmod = real_chmod
        os.umask(previous)

    assert observed, "write_active_profile did not chmod the pointer at all"
    assert observed[0] == 0o600, (
        f"the pointer file existed at {oct(observed[0])} holding its contents "
        f"before the chmod narrowed it to 0600. The READMEs list this file as "
        f"0600 with no window"
    )
