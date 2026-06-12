"""Tests for ``server.resolve_connection_params()``.

The MCP server's startup logic — which profile to use, where the password
comes from, what error message a fresh install sees — was 0% covered
before the D2 refactor. This file pins down the resolution priority
(CLI flag > REDSHIFT_COMMENT_PROFILE env > active-profile pointer file >
``"default"``) and the user-facing error messages that point a stuck
user back at both ``/redshift-comment-mcp:redshift-setup`` (Claude
Code skill) and ``redshift-comment-mcp setup`` (CLI fallback for
uvx-only / non-Claude-Code installs).
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


# ===== optional plugin userConfig hardening =====
# A Claude Code plugin `userConfig` is OPTIONAL: when the user leaves a field
# blank, Claude Code substitutes "" into `--host ${user_config.host}` etc., and
# may even leave the literal `${user_config.port}` unsubstituted. Neither must
# crash the server; both must be treated as "unset" so resolution falls back to
# profile mode. The port arg is the sharpest edge — `type=int` makes `--port ""`
# raise `invalid int value` at argparse and the server never boots.


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", 5439),                       # blank optional userConfig field
        ("${user_config.port}", 5439),    # unsubstituted placeholder literal
        ("not-a-number", 5439),           # any non-numeric → default, not crash
        (None, 5439),                     # arg omitted entirely
        ("5439", 5439),                   # real value passes through
        ("5440", 5440),                   # real non-default value preserved
        (5439, 5439),                     # already an int (defensive)
    ],
)
def test_coerce_port_maps_blank_or_placeholder_to_default(raw, expected):
    """The argparse `type=` coercion must never raise on userConfig debris."""
    assert server._coerce_port(raw) == expected


def test_coerce_port_via_argparse_does_not_crash_on_empty():
    """Regression for the headline bug: `--port ""` must parse, not raise
    SystemExit from argparse's `invalid int value` path."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=server._coerce_port, default=5439)
    assert parser.parse_args(["--port", ""]).port == 5439
    assert parser.parse_args(["--port", "5440"]).port == 5440


@pytest.mark.parametrize(
    "host, user, dbname",
    [
        ("", "", ""),                                  # all blank optional fields
        ("${user_config.host}", "${user_config.user}", "${user_config.dbname}"),  # all literals
        ("${user_config.host}", "", ""),               # mixed literal + blank
        ("real.example.com", "", "d"),                 # one real, rest unset → still incomplete
    ],
)
def test_inline_args_empty_or_placeholder_fall_back_to_profile(
    tmp_xdg, fake_keyring, monkeypatch, host, user, dbname
):
    """Empty-string or unsubstituted-placeholder inline args must be treated as
    unset, so the inline-completeness check fails and we fall through to profile
    mode. With no profile configured, that surfaces the existing
    /redshift-setup-pointing error — NOT a crash and NOT a bogus inline connect."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host=host, user=user, dbname=dbname, port="")
    with pytest.raises(ValueError, match="redshift-setup"):
        server.resolve_connection_params(args)


def test_inline_args_real_values_still_resolve_to_inline(tmp_xdg, fake_keyring, monkeypatch):
    """Control: genuine full inline args (and a real --port) still take the
    inline path unchanged — the hardening must not regress legacy inline mode."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h.example.com", user="u", dbname="d", password="secret", port=5439)
    assert server.resolve_connection_params(args) == (
        "h.example.com", 5439, "u", "secret", "d"
    )


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


# ===== profile mode error messages point at both skill and CLI =====


def test_profile_not_configured_error_offers_recovery_paths(tmp_xdg, fake_keyring, monkeypatch):
    """Error must surface all setup paths so any caller can recover:
    Claude Code skill, in-band MCP tool setup_via_dialog, code-agent
    pipeline (set-fields + set-password --dialog), and human terminal
    (uvx redshift-comment-mcp setup). Name kept path-agnostic so adding
    a 5th option later doesn't require a test rename."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "default" in msg, "Error should name the profile"
    assert "/redshift-comment-mcp:redshift-setup" in msg, (
        "Path 1 — Claude Code skill — should be mentioned"
    )
    assert "set-fields" in msg and "--dialog" in msg, (
        "Path 2 — code-agent pipeline (set-fields + set-password --dialog) — "
        "should be mentioned so non-Claude-Code agents can bootstrap without "
        "the password entering chat"
    )
    assert "redshift-comment-mcp setup" in msg, (
        "Path 3 — human terminal (uvx redshift-comment-mcp setup) — should "
        "be mentioned for users running the setup themselves interactively"
    )


def test_named_profile_not_configured_error_includes_name(tmp_xdg, fake_keyring, monkeypatch):
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "ichef-prod")
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "ichef-prod" in str(excinfo.value)


def test_profile_exists_but_no_password_error_offers_recovery_paths(tmp_xdg, fake_keyring, monkeypatch):
    """If profile fields exist but password missing, error should offer
    multiple re-key paths (Claude Code skill, in-band setup_via_dialog,
    and terminal set-password CLI). Name kept path-agnostic so adding
    new options later doesn't require a test rename."""
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


# ===== upgrade rescue: single non-"default" profile works end-to-end =====


def test_profile_mode_single_non_default_profile_auto_resolves(
    tmp_xdg, fake_keyring, monkeypatch
):
    """End-to-end upgrade rescue: a fresh machine has one profile named
    'ichef-prod' (not 'default') and no active-profile pointer file. The
    server must auto-pick that profile and connect — no error, no manual
    setup step required."""
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile(
        "ichef-prod",
        host="ichef-prod.example.com", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("ichef-prod", "ichef-pw")
    args = _ns()
    host, port, user, password, dbname = server.resolve_connection_params(args)
    assert (host, port, user, password, dbname) == (
        "ichef-prod.example.com", 5439, "alice", "ichef-pw", "warehouse",
    )


# ===== error message clarity when no rescue is possible =====


def test_ambiguous_multi_profile_error_lists_profiles_and_suggests_switch(
    tmp_xdg, fake_keyring, monkeypatch
):
    """Multi-profile / no 'default' / no pointer is the genuinely ambiguous
    case that needs explicit user action. The error must:
    1. Name the available profiles so the user knows what to switch TO
    2. Suggest /redshift-switch-profile (not /redshift-setup — they already
       have profiles configured; setup would just add another)
    """
    monkeypatch.delenv("REDSHIFT_COMMENT_PROFILE", raising=False)
    config.write_profile("prod", host="h1", port=5439, user="u", dbname="d")
    config.write_profile("staging", host="h2", port=5439, user="u", dbname="d")
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "prod" in msg
    assert "staging" in msg
    assert "/redshift-comment-mcp:redshift-switch-profile" in msg


def test_named_profile_typo_error_lists_existing_profiles(
    tmp_xdg, fake_keyring, monkeypatch
):
    """If the user explicitly named a profile (via env or pointer file)
    that doesn't exist, mention the existing profiles so they can spot
    the typo — not just 'run /redshift-setup'.

    Note: deliberately picked names that don't share substrings, so
    `"existing-name" in msg` can't pass on the existing error template
    (which echoes the typo).
    """
    monkeypatch.setenv("REDSHIFT_COMMENT_PROFILE", "wrong-name")
    config.write_profile("prod-warehouse", host="h", port=5439, user="u", dbname="d")
    args = _ns()
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    # The typo name must be in the error so the user sees the mismatch.
    assert "wrong-name" in msg
    # Existing profile must be named so the user can correct the typo.
    assert "prod-warehouse" in msg
