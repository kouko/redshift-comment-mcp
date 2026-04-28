"""Tests for the config / profile / keyring layer."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from redshift_comment_mcp import config


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
