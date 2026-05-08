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
