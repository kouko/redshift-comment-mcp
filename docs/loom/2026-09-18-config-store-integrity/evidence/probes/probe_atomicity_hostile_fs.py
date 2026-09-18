"""Adversarial probes: ``_write_all``'s atomic rename against a hostile filesystem.

Change: 2026-09-18-config-store-integrity
Anchor: src/redshift_comment_mcp/config.py :: _write_all

``_write_all`` swapped an in-place ``p.open("wb")`` for mkstemp + fsync + chmod
+ ``os.replace``. That buys atomicity, and it changes what the path *is* by the
time the bytes land: ``os.replace`` operates on the name, not on whatever the
name resolved to before. These probes take the config directory and config.toml
apart — symlinked, pre-existing at a looser mode, under a permissive umask, and
with the process killed in the window the temp file is alive.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _probe_support import isolate_config  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    config_file = isolate_config(monkeypatch, tmp_path)
    from redshift_comment_mcp import config as cfg

    return config_file, cfg


def test_writeprofile_configtomlisasymlink_keepswritingthroughtothetarget(
    store, tmp_path
):
    """A config.toml symlinked into a dotfiles checkout is replaced, not followed.

    The pre-change writer opened the path ``"wb"``, which follows a symlink and
    updates the target. ``os.replace(tmp, p)`` does the opposite: it unlinks the
    *link* and puts a regular file in its place. A user who keeps their profile
    store under version control the usual way — a real file in ~/dotfiles and a
    symlink in ~/.config — loses the link on the first write after upgrading,
    and every later write goes somewhere their dotfiles repo cannot see. No
    error is printed and nothing in the change notes or the READMEs mentions it.
    """
    config_file, cfg = store

    real_store = tmp_path / "dotfiles" / "config.toml"
    real_store.parent.mkdir(parents=True, exist_ok=True)
    real_store.write_text('[profile.prod]\nhost = "old.example.com"\nport = 5439\n'
                          'user = "u"\ndbname = "d"\n')
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.symlink_to(real_store)

    cfg.write_profile("prod", host="new.example.com", port=5439, user="u", dbname="d")

    still_a_link = config_file.is_symlink()
    target_text = real_store.read_text()

    assert still_a_link, (
        "config.toml was a symlink into a dotfiles checkout before the write "
        "and is a plain file after it: os.replace destroyed the link. The "
        "pre-change writer followed it. Every subsequent profile write now "
        "lands outside the user's dotfiles repo, silently"
    )
    assert "new.example.com" in target_text, (
        "the symlink target never received the write: the new profile went to "
        f"a file the user's dotfiles repo does not track. Target still holds: "
        f"{target_text!r}"
    )


def test_writeprofile_configdirectoryisasymlink_landsintherealdirectory(
    store, tmp_path
):
    """A symlinked config *directory* is fine — the temp file stays on one device.

    ``os.replace`` is atomic only within a filesystem, which is why the temp
    file is created in ``p.parent``. When ``p.parent`` is itself a symlink, both
    the temp file and the rename resolve through it, so they remain on the same
    device and the rename still holds.
    """
    config_file, cfg = store

    real_dir = tmp_path / "elsewhere"
    real_dir.mkdir()
    link_dir = config_file.parent
    link_dir.parent.mkdir(parents=True, exist_ok=True)
    link_dir.symlink_to(real_dir, target_is_directory=True)

    cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")

    assert (real_dir / "config.toml").is_file(), (
        "the write did not reach the directory the symlink points at"
    )
    assert cfg.read_profile("prod") is not None


def test_writeprofile_killedbeforetherename_leavesnotempfilebehind(store, tmp_path):
    """SIGKILL in the mkstemp..replace window litters the config directory.

    A real child process is killed at the moment ``os.replace`` would have run.
    config.toml is correctly untouched — that is the atomicity the change
    bought. What is left is a ``.config.toml.<rand>.tmp`` file holding a full
    copy of the profile store, which nothing in the project ever cleans up; the
    directory accumulates one per crash, and the machine-managed-store section
    of the READMEs does not mention them.
    """
    config_file, cfg = store

    config_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_profile("keepme", host="h.example.com", port=5439, user="u", dbname="d")
    before = sorted(p.name for p in config_file.parent.iterdir())

    child = textwrap.dedent(
        """
        import os, signal, sys
        os.environ["XDG_CONFIG_HOME"] = sys.argv[1]
        os.environ.pop("REDSHIFT_COMMENT_PROFILE", None)
        from redshift_comment_mcp import config as cfg
        os.replace = lambda *a, **k: os.kill(os.getpid(), signal.SIGKILL)
        cfg.write_profile("victim", host="v.example.com", port=5439,
                          user="u", dbname="d")
        """
    )
    script = tmp_path / "kill_before_rename.py"
    script.write_text(child)

    proc = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == -9, (
        f"the child was meant to be SIGKILLed inside the write window; it "
        f"exited {proc.returncode}. stderr: {proc.stderr}"
    )

    after = sorted(p.name for p in config_file.parent.iterdir())
    litter = [n for n in after if n not in before]

    assert cfg.read_profile("keepme") is not None, "the killed write damaged config.toml"
    assert cfg.read_profile("victim") is None, "a killed write landed anyway"
    assert not litter, (
        f"a process killed between mkstemp and os.replace left {litter} in the "
        f"config directory. Each one is a full copy of the profile store, "
        f"nothing removes it, and they accumulate silently beside config.toml"
    )


def test_writeprofile_underapermissiveumask_leavesconfigtomlatmode600(store):
    """mkstemp's 0600 plus the explicit chmod must survive ``umask 000``."""
    config_file, cfg = store

    previous = os.umask(0o000)
    try:
        cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")
    finally:
        os.umask(previous)

    mode = stat.S_IMODE(config_file.stat().st_mode)
    assert mode == 0o600, (
        f"config.toml is {oct(mode)} under umask 000; the READMEs list it as 0600"
    )


def test_writeprofile_overanexistingmode644file_narrowsittomode600(store):
    """An existing loose-moded store is tightened, not inherited.

    ``os.replace`` carries the *temp* file's mode over, so the outgoing file's
    permissions are irrelevant — which is the safe direction. Worth pinning:
    the opposite (inheriting 0644 from a file an older version wrote) would be
    invisible.
    """
    config_file, cfg = store

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text('[profile.old]\nhost = "h"\nport = 5439\n'
                           'user = "u"\ndbname = "d"\n')
    config_file.chmod(0o644)

    cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")

    mode = stat.S_IMODE(config_file.stat().st_mode)
    assert mode == 0o600, f"config.toml stayed at {oct(mode)} after the replace"
    assert cfg.read_profile("old") is not None, "the unrelated profile was dropped"


def test_writeprofile_afterthereplace_fsyncsthedirectoryentrytoo(store, monkeypatch):
    """The rename is durable only once the directory holding it is fsynced.

    ``_write_all`` fsyncs the temp file's *contents* and then renames. On a
    crash-consistency boundary — power loss, a hard reset — the contents are on
    disk and the directory entry pointing at them may not be, so config.toml
    can come back as the pre-write file or, on some filesystems, missing. The
    fix is an ``O_DIRECTORY`` open of ``p.parent`` and an ``fsync`` on it after
    the replace.

    The implementers named this as deliberately skipped. It is recorded here
    because a skipped step that nobody can point at later becomes an accident.
    Observed rather than raced: every ``fsync`` is recorded by inode, and the
    config directory's inode is looked for among them.
    """
    config_file, cfg = store

    config_file.parent.mkdir(parents=True, exist_ok=True)
    dir_inode = config_file.parent.stat().st_ino

    synced: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(fd):
        try:
            synced.append(os.fstat(fd).st_ino)
        except OSError:
            pass
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    cfg.write_profile("prod", host="h.example.com", port=5439, user="u", dbname="d")

    assert synced, "_write_all fsynced nothing at all"
    assert dir_inode in synced, (
        "the config directory was never fsynced after os.replace: only the "
        "temp file's contents were. The rename that makes the new file "
        "visible is not durable until the directory entry is flushed, so a "
        "power loss immediately after a successful write can lose it with no "
        "sign that anything happened"
    )


def test_writeprofile_serialisationraisesmidwrite_removesitstempfile(store, monkeypatch):
    """The in-process failure path cleans up after itself.

    Distinct from the SIGKILL case above: when the dump raises rather than the
    process dying, ``_write_all``'s ``except BaseException`` unlinks the temp
    file. This is the half of the cleanup that does work.
    """
    config_file, cfg = store

    config_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_profile("keepme", host="h.example.com", port=5439, user="u", dbname="d")
    before = sorted(p.name for p in config_file.parent.iterdir())

    import tomli_w

    def explode(*_a, **_kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tomli_w, "dump", explode)
    with pytest.raises(RuntimeError):
        cfg.write_profile("victim", host="v.example.com", port=5439, user="u", dbname="d")

    after = sorted(p.name for p in config_file.parent.iterdir())
    assert after == before, f"a failed write left {set(after) - set(before)} behind"
    assert cfg.read_profile("keepme") is not None
