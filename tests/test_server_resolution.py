"""Tests for ``server.resolve_connection_params()``.

The MCP server's startup logic — which profile to use, where the password
comes from, what error message a fresh install sees — was 0% covered
before the D2 refactor. This file pins down the resolution priority
(CLI flag > REDSHIFT_COMMENT_PROFILE env > active-profile pointer file >
``"default"``) and the user-facing error messages that point a stuck
user back at ``/redshift-comment-mcp:redshift-setup``.
"""
from __future__ import annotations

import argparse

import pytest

from redshift_comment_mcp import config, server


def _ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace with all the fields server.main()'s argparse produces."""
    defaults = dict(
        profile=None,
        host=None,
        port=5439,
        user=None,
        password=None,
        dbname=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.fixture
def tmp_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def fake_keyring(monkeypatch):
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


# ===== legacy inline mode =====


def test_inline_mode_happy_path(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h.example.com", user="u", dbname="d", password="secret")
    assert server.resolve_connection_params(args) == (
        "h.example.com", 5439, "u", "secret", "d"
    )


def test_inline_mode_password_from_env(tmp_xdg, fake_keyring, monkeypatch):
    """args.password missing but REDSHIFT_PASSWORD env var set."""
    monkeypatch.setenv("REDSHIFT_PASSWORD", "envsecret")
    args = _ns(host="h", user="u", dbname="d", password=None)
    assert server.resolve_connection_params(args)[3] == "envsecret"


def test_inline_mode_arg_password_beats_env(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.setenv("REDSHIFT_PASSWORD", "envsecret")
    args = _ns(host="h", user="u", dbname="d", password="argsecret")
    assert server.resolve_connection_params(args)[3] == "argsecret"


def test_inline_mode_missing_password_raises(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d")
    with pytest.raises(ValueError, match="REDSHIFT_PASSWORD"):
        server.resolve_connection_params(args)


def test_inline_mode_partial_args_falls_through_to_profile(tmp_xdg, fake_keyring):
    """Only --host but no --user/--dbname → not inline-complete; profile mode
    activates and (since no profile configured) raises pointing at skill."""
    args = _ns(host="h")  # user/dbname absent
    with pytest.raises(ValueError, match="redshift-setup"):
        server.resolve_connection_params(args)


# ===== profile mode =====


def _setup_default_profile(fake_keyring):
    config.write_profile(
        "default",
        host="default.example.com", port=5439, user="alice", dbname="analytics",
    )
    config.set_password("default", "default-pw")


def _setup_prod_profile(fake_keyring):
    config.write_profile(
        "prod",
        host="prod.example.com", port=5440, user="bob", dbname="warehouse",
    )
    config.set_password("prod", "prod-pw")


def test_profile_mode_default_fallback(tmp_xdg, fake_keyring, monkeypatch):
    """No CLI flag, no env, no pointer file → 'default'."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    _setup_default_profile(fake_keyring)
    args = _ns()
    host, port, user, password, dbname = server.resolve_connection_params(args)
    assert (host, port, user, password, dbname) == (
        "default.example.com", 5439, "alice", "default-pw", "analytics",
    )


def test_profile_mode_pointer_file_picks_named_profile(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    _setup_default_profile(fake_keyring)
    _setup_prod_profile(fake_keyring)
    config.write_active_profile("prod")
    args = _ns()
    host, _, user, password, dbname = server.resolve_connection_params(args)
    assert (host, user, password, dbname) == (
        "prod.example.com", "bob", "prod-pw", "warehouse",
    )


def test_profile_mode_env_var_beats_pointer_file(tmp_xdg, fake_keyring, monkeypatch):
    _setup_default_profile(fake_keyring)
    _setup_prod_profile(fake_keyring)
    config.write_active_profile("default")  # pointer says default
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "prod")  # env says prod
    args = _ns()
    assert server.resolve_connection_params(args)[0] == "prod.example.com"


def test_profile_mode_cli_flag_beats_env_and_file(tmp_xdg, fake_keyring, monkeypatch):
    _setup_default_profile(fake_keyring)
    _setup_prod_profile(fake_keyring)
    config.write_active_profile("default")  # pointer says default
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "default")  # env says default
    args = _ns(profile="prod")  # CLI flag says prod
    assert server.resolve_connection_params(args)[0] == "prod.example.com"


# ===== profile mode error messages point at the skill =====


def test_profile_not_configured_error_points_at_skill(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "default" in msg, "Error should name the profile"
    assert "/redshift-comment-mcp:redshift-setup" in msg, (
        "Error should point at the skill, not the legacy uvx CLI command"
    )


def test_named_profile_not_configured_error_includes_name(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "ichef-prod")
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "ichef-prod" in str(excinfo.value)


def test_profile_exists_but_no_password_error_offers_two_paths(tmp_xdg, fake_keyring, monkeypatch):
    """If profile fields exist but password missing, error should offer
    BOTH the skill (preferred) AND the set-password CLI fallback."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    # No password set → keychain miss
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "/redshift-comment-mcp:redshift-setup" in msg
    assert "set-password" in msg
    assert "default" in msg
