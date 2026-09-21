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


# ===== resolve_inline_params (status-side inline detection) =====
# Extracted so get_setup_status can report inline mode truthfully without
# re-resolving the password value (it only needs presence, not the secret).


def test_resolve_inline_params_complete_with_password(tmp_xdg, monkeypatch):
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h.example.com", user="alice", dbname="analytics",
               password="secret", port=5430)
    assert server.resolve_inline_params(args) == (
        "h.example.com", 5430, "alice", True, "analytics"
    )


def test_resolve_inline_params_password_presence_from_env(tmp_xdg, monkeypatch):
    monkeypatch.setenv("REDSHIFT_PASSWORD", "envsecret")
    args = _ns(host="h", user="u", dbname="d")
    assert server.resolve_inline_params(args) == ("h", 5439, "u", True, "d")


def test_resolve_inline_params_no_password_still_inline(tmp_xdg, monkeypatch):
    """Complete host/user/dbname but no password → still inline, has_password=False
    (the status tool must surface this as 'inline but needs a password')."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d")
    assert server.resolve_inline_params(args) == ("h", 5439, "u", False, "d")


def test_resolve_inline_params_partial_returns_none(tmp_xdg, monkeypatch):
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h")  # user/dbname absent → not inline
    assert server.resolve_inline_params(args) is None


def test_resolve_inline_params_placeholder_returns_none(tmp_xdg, monkeypatch):
    """Unsubstituted optional-userConfig placeholders are not a real inline config."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="${user_config.host}", user="${user_config.user}",
               dbname="${user_config.dbname}")
    assert server.resolve_inline_params(args) is None


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



# ===== W0-01 (amended by W0-05): borrow a password only from a profile
# matching the FULL four-field target =====
# Inline host/port/user/dbname supplied, no password anywhere (neither
# --password nor REDSHIFT_PASSWORD). A stored profile may lend its keychain
# password, but ONLY when its host+port+user+dbname all equal the inline
# values — it must never lend a connection-target field: an unmatched store
# (including one that differs only by port) can only refuse, never redirect
# the connection somewhere the operator did not type.


def test_four_field_match_borrows_and_uses_inline_values(tmp_xdg, fake_keyring, monkeypatch):
    """A stored profile whose host, port, user AND dbname all equal the
    inline values lends its keychain password. Connection uses the INLINE
    values (proven by exercising the code path that reads them from the
    inline variables, not from the matched profile dict — a bug that
    accidentally returned the profile's own field values would still pass
    here since match requires the fields to be equal, but would fail
    test_port_mismatch_refuses_and_names_both_ports below)."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "default", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("default", "borrowed-pw")
    args = _ns(host="h.example.com", user="u", dbname="d")
    assert server.resolve_connection_params(args) == (
        "h.example.com", 5439, "u", "borrowed-pw", "d"
    )


def test_port_mismatch_refuses_and_names_both_ports(tmp_xdg, fake_keyring, monkeypatch):
    """A profile whose host/user/dbname all match the inline target but
    whose PORT differs must NOT lend its password — a password provisioned
    for host:5439 must never be sent to host:9999. Refuse, and name both
    ports in the message so the operator can see the only difference at a
    glance (Acceptance 2: 'each existing profile's target')."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "default", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("default", "borrowed-pw")
    args = _ns(host="h.example.com", port=9999, user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "9999" in msg
    assert "5439" in msg


def test_password_present_still_wins(tmp_xdg, fake_keyring, monkeypatch):
    """An inline password that IS supplied is used as-is; the profile store
    is never consulted, even when a matching profile with a different
    password exists."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "default", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("default", "profile-pw")
    args = _ns(host="h.example.com", user="u", dbname="d", password="inline-pw")
    assert server.resolve_connection_params(args) == (
        "h.example.com", 5439, "u", "inline-pw", "d"
    )


def test_mismatched_profile_raises_naming_both_hosts(tmp_xdg, fake_keyring, monkeypatch):
    """A profile exists but its target does not match the inline values →
    refuse rather than borrow across a mismatch. The message must name both
    the inline target's host and each existing profile's target — host AND
    port (Acceptance 2) — so the user can see why nothing matched, including
    the case where a port is the only difference."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "prod", host="prod.example.com", port=6543, user="alice", dbname="warehouse",
    )
    config.set_password("prod", "prod-pw")
    args = _ns(host="inline.example.com", user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "inline.example.com" in msg
    assert "prod.example.com" in msg
    assert "6543" in msg


def test_no_profiles_at_all_raises(tmp_xdg, fake_keyring, monkeypatch):
    """Boundary: no stored profiles exist at all, so there is nothing to
    borrow from → refuse. The message must still name the inline target."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="inline.example.com", user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "inline.example.com" in str(excinfo.value)


# ===== W0-08 item 3: an ambiguous lender must refuse, not pick by sort
# order =====
# A credential rotation leaves exactly two profiles recorded for the same
# four-field target with different passwords (the retired one and its
# replacement). probe_borrow_scope.py::test_borrow_ambiguousprofiles_reportslender
# pinned the pre-existing behaviour — the scan takes whichever name
# config.list_profiles() (sorted) yields first — as merely survivable. kouko
# closed it on 2026-09-21: a loud refusal beats a quiet wrong answer, the
# same principle chosen for the port gap above.


def test_ambiguous_profiles_refuse_to_borrow(tmp_xdg, fake_keyring, monkeypatch):
    """Two stored profiles match the inline four-field target with
    different passwords. Neither may be picked silently — the decision
    must come back password-less rather than "borrowed" from whichever
    name happens to sort first."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "prod", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("prod", "retired-secret")
    config.write_profile(
        "prod-rotated", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("prod-rotated", "live-secret")

    args = _ns(host="h.example.com", user="u", dbname="d")
    decision = server.resolve_connection_decision(args)

    assert decision.mechanism == "inline"
    assert decision.has_password is False
    assert decision.password is None


def test_ambiguous_profiles_error_names_both_candidates(tmp_xdg, fake_keyring, monkeypatch):
    """The refusal message must name both tied profiles (Acceptance 2's
    'each existing profile's target'), and must never leak either
    password."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "prod", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("prod", "retired-secret")
    config.write_profile(
        "prod-rotated", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("prod-rotated", "live-secret")

    args = _ns(host="h.example.com", user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "prod" in msg
    assert "prod-rotated" in msg
    assert "retired-secret" not in msg
    assert "live-secret" not in msg


def test_single_matching_profile_still_borrows_despite_ambiguity_check(tmp_xdg, fake_keyring, monkeypatch):
    """Boundary: exactly one profile matching the target must keep lending
    its password exactly as before — the ambiguity check must fire only
    when there is genuinely more than one candidate."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "prod", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("prod", "only-secret")

    args = _ns(host="h.example.com", user="u", dbname="d")
    decision = server.resolve_connection_decision(args)

    assert decision.mechanism == "borrowed"
    assert decision.password == "only-secret"
    assert decision.profile_name == "prod"


# ===== W0-05 defect 3: the borrow scan must not make a keychain-free path
# depend on the keychain (or on a clean config.toml) =====
# The scan calls cfg.list_profiles() / cfg.read_profile() / cfg.get_password()
# with no exception handling; only ConfigurationError is caught by
# @_guarded, so anything else (NoKeyringError, AttributeError from a
# non-table config.toml entry, TOMLDecodeError from a malformed file) used
# to escape as an opaque crash instead of falling through to the existing
# password-less inline refusal — in a mode (inline launch, no password) that
# never touched the keychain before this change existed.


def _corrupt_store_no_keyring_backend(monkeypatch):
    from keyring.errors import NoKeyringError
    config.write_profile(
        "default", host="h.example.com", port=5439, user="u", dbname="d",
    )

    def _raise(profile):
        raise NoKeyringError("no keyring backend available")

    monkeypatch.setattr(config, "get_password", _raise)


def _corrupt_store_non_table_entry(monkeypatch):
    # A stray non-table value under [profile] (e.g. `profile.bad = "oops"`
    # instead of `[profile.bad]`) makes read_profile return something that
    # isn't a dict, so `.get("host")` on it raises AttributeError.
    monkeypatch.setattr(config, "list_profiles", lambda: ["bad"])
    monkeypatch.setattr(config, "read_profile", lambda name: "not-a-table")


def _corrupt_store_malformed_toml(monkeypatch):
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("this is not [valid toml")


_CORRUPT_STORE_SETUPS = {
    "no_keyring_backend": (_corrupt_store_no_keyring_backend, "NoKeyringError"),
    "non_table_entry": (_corrupt_store_non_table_entry, "AttributeError"),
    "malformed_toml": (_corrupt_store_malformed_toml, "TOMLDecodeError"),
}


@pytest.mark.parametrize(
    "corrupt_store", list(_CORRUPT_STORE_SETUPS), ids=list(_CORRUPT_STORE_SETUPS)
)
def test_borrow_scan_store_failure_falls_through_to_inline_refusal(
    tmp_xdg, monkeypatch, caplog, corrupt_store
):
    """Boundary (Acceptance 3 / defect 3): whatever the borrow scan hits
    while consulting the store, an inline launch with no password ends up
    at the same password-less inline refusal it always would have — never
    an escaped store exception — and the exception type (never any value)
    is logged at debug level."""
    import logging as _logging

    caplog.set_level(_logging.DEBUG, logger="redshift_comment_mcp.server")
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    setup_fn, expected_exception_name = _CORRUPT_STORE_SETUPS[corrupt_store]
    setup_fn(monkeypatch)

    args = _ns(host="h.example.com", user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "h.example.com" in str(excinfo.value)
    assert expected_exception_name in caplog.text


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


# ===== W0-03 / A4: the password channel gets the same normalization every
# other inline field gets =====
# `_normalize_inline` already maps "" and an unsubstituted `${user_config...}`
# literal to "unset" for host/user/dbname. The password value skipped that
# normalization entirely (both `args.password` and `REDSHIFT_PASSWORD`), so
# a host that ever substitutes env the way it substitutes argv would hand a
# truthy placeholder string to `has_password` and to the actual connection
# attempt. The password must go through the exact same normalization.


def test_resolve_inline_params_password_placeholder_is_no_password(tmp_xdg, monkeypatch):
    """A4 positive: an unsubstituted userConfig placeholder in --password is
    'unset', not a real password — has_password must be False."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d", password="${user_config.password}")
    assert server.resolve_inline_params(args) == ("h", 5439, "u", False, "d")


def test_resolve_inline_params_password_env_placeholder_is_no_password(tmp_xdg, monkeypatch):
    """A4 positive, env-var channel: the same unsubstituted-placeholder
    literal arriving via REDSHIFT_PASSWORD (not just --password) must also
    be treated as no password."""
    monkeypatch.setenv("REDSHIFT_PASSWORD", "${user_config.password}")
    args = _ns(host="h", user="u", dbname="d")
    assert server.resolve_inline_params(args) == ("h", 5439, "u", False, "d")


def test_resolve_inline_params_blank_password_is_no_password(tmp_xdg, monkeypatch):
    """A4 positive, blank string (the other half of `_normalize_inline`'s
    contract): an empty --password must be no password, not a truthy ''."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d", password="")
    assert server.resolve_inline_params(args) == ("h", 5439, "u", False, "d")


def test_resolve_inline_params_real_password_unaffected(tmp_xdg, monkeypatch):
    """A4 negative: a genuine password value must pass through the new
    normalization completely unchanged — has_password True, and (checked
    below via resolve_connection_params) the exact string is used to
    connect, not a mangled or re-derived one."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d", password="realsecret")
    assert server.resolve_inline_params(args) == ("h", 5439, "u", True, "d")


def test_inline_password_real_value_unaffected_by_normalization(tmp_xdg, fake_keyring, monkeypatch):
    """A4 negative, end-to-end: resolve_connection_params must still return
    the real password verbatim once it goes through the shared normalization
    helper — the fix must not alter or truncate an actual secret."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d", password="realsecret")
    assert server.resolve_connection_params(args) == ("h", 5439, "u", "realsecret", "d")


def test_inline_placeholder_password_falls_through_to_borrow(tmp_xdg, fake_keyring, monkeypatch):
    """A4 end-to-end with W0-01/W0-05: an unsubstituted placeholder
    --password must not block the borrow path — with a profile matching the
    full inline four-field target, the connection borrows its keychain
    password exactly as if no --password had been supplied at all, instead
    of authenticating with the literal placeholder string and failing
    confusingly.

    The stored profile's port matches the inline default (5439) — this test
    is about the placeholder-password normalization, not port matching; see
    test_port_mismatch_refuses_and_names_both_ports for that."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "default", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("default", "borrowed-pw")
    args = _ns(host="h.example.com", user="u", dbname="d", password="${user_config.password}")
    assert server.resolve_connection_params(args) == (
        "h.example.com", 5439, "u", "borrowed-pw", "d"
    )


def test_inline_placeholder_password_with_no_matching_profile_raises(tmp_xdg, fake_keyring, monkeypatch):
    """A4 boundary: a placeholder password with nothing to borrow from must
    raise the same as a genuinely absent password, not authenticate with the
    placeholder literal."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="inline.example.com", user="u", dbname="d", password="${user_config.password}")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "inline.example.com" in str(excinfo.value)


# ===== W0-03 / A5: no message recommends passing the password as argv =====
# `--password` stays a supported flag (README documents inline launch args
# as a public integration path for other MCP clients) — only messages that
# *recommend* it as a way to supply a password are in scope. A prohibition
# ("Never pass the password as a tool argument or shell argument") and the
# argparse --help text for the flag's own existence are not recommendations
# and must survive untouched.


def test_missing_password_error_does_not_recommend_password_flag(tmp_xdg, fake_keyring, monkeypatch):
    """A5 positive: the inline missing-password error must no longer tell
    the reader to pass --password — the one path that puts the secret into
    argv, shell history and (for an agent) the session transcript."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "--password" not in str(excinfo.value)


def test_missing_password_error_still_mentions_env_var(tmp_xdg, fake_keyring, monkeypatch):
    """A5 boundary: the safe channel's guidance must survive — removing the
    --password recommendation must not also remove the REDSHIFT_PASSWORD
    env var guidance."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    args = _ns(host="h", user="u", dbname="d")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "REDSHIFT_PASSWORD" in str(excinfo.value)


def _get_tool_fn(tools, name):
    """Pull a registered tool's callable, surviving FastMCP API churn.

    Duplicated from tests/test_tools.py rather than imported, to keep this
    file's only cross-module dependency the one declared at the top
    (``redshift_comment_mcp.server`` / ``config``) — see that file's own
    copy for the FastMCP 2.x/3.x compatibility note this exists for.
    """
    import asyncio
    lister = getattr(tools.mcp, 'list_tools', None) or tools.mcp._list_tools
    for t in asyncio.run(lister()):
        if t.name == name:
            return t.fn
    raise KeyError(f"tool {name!r} not registered")


def test_get_setup_status_inline_next_step_does_not_recommend_password_flag():
    """A5 positive, the second site the intent doc flags: get_setup_status's
    next_step for inline-mode-missing-password must not recommend
    --password either. This reader is an agent with shell access — the one
    most likely to act on the recommendation literally."""
    from redshift_comment_mcp.redshift_tools import RedshiftTools, ConnectionDecision
    from redshift_comment_mcp.config import ConfigurationError

    def provider():
        raise ConfigurationError("doesn't matter — get_setup_status doesn't touch the provider")

    tools = RedshiftTools(
        provider,
        status_provider=lambda profile: ConnectionDecision(
            mechanism="inline",
            host="h.example.com", port=5439, user="alice", dbname="analytics",
            has_fields=True, has_password=False, password=None,
            profile_name=None,
        ),
    )
    get_setup_status = _get_tool_fn(tools, "get_setup_status")

    result = get_setup_status()
    assert "--password" not in result["next_step"]
    assert "REDSHIFT_PASSWORD" in result["next_step"]


def _mcp_tool_docstring_line_ranges(source: str) -> list[tuple[int, int]]:
    """Line ranges (1-indexed, inclusive) of every ``@self.mcp.tool``-decorated
    function's own docstring in ``source``.

    FastMCP publishes a tool's docstring verbatim as that tool's
    ``description`` in the MCP ``tools/list`` response — the exact text every
    connected client receives, agent or human. A reference formatted as
    internal documentation (double-backtick-quoted) inside one of these
    docstrings is not internal at all once it ships this way; it reaches the
    wire regardless of how it is spelled.

    Known blind spot, spelled out rather than left implicit: this recognizes
    only the literal decorator shape ``@self.mcp.tool`` (optionally stacked
    with another decorator such as ``@_guarded``). A tool registered any
    other way — e.g. ``mcp.tool()(fn)`` called programmatically, a decorator
    aliased to a different name, or a docstring assembled by string
    concatenation instead of a literal triple-quoted constant — would not be
    found here and would fall through to the looser backtick-reference
    exemption below, silently. The companion runtime test,
    ``TestNoToolDescriptionRecommendsThePasswordFlag`` in test_tools.py,
    checks the ACTUAL published ``t.description`` of every registered tool
    at runtime and has no such blind spot; it is the one to trust if the two
    ever disagree.
    """
    import ast

    tree = ast.parse(source)
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_mcp_tool = False
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Attribute) and dec.attr == "tool"
                and isinstance(dec.value, ast.Attribute) and dec.value.attr == "mcp"
                and isinstance(dec.value.value, ast.Name) and dec.value.value.id == "self"
            ):
                is_mcp_tool = True
                break
        if not is_mcp_tool:
            continue
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            doc_node = node.body[0]
            ranges.append((doc_node.lineno, doc_node.end_lineno))
    return ranges


def test_no_stray_password_flag_recommendation_in_source():
    """A5 regression guard: scan server.py's and redshift_tools.py's own
    source text for the literal substring '--password' and confirm every
    remaining occurrence is one that genuinely cannot reach an MCP client:

      1. the argparse flag's own declaration (`"--password",` inside
         `add_argument(...)`) — CLI-only, never published over MCP; or
      2. an RST-style code reference inside a docstring, spelled
         `` ``--password`` `` (double-backtick-quoted) — BUT only when that
         docstring belongs to a function that is NOT registered as an MCP
         tool (see `_mcp_tool_docstring_line_ranges`). A dataclass docstring,
         a plain internal function's docstring, or a module docstring never
         reaches a client; a `@self.mcp.tool`-decorated function's docstring
         always does, regardless of backtick formatting.

    The previous version of this test exempted shape 2 everywhere, on the
    premise that a docstring reference is "internal architecture
    documentation, not an instruction to the reader." That premise is false
    for any docstring FastMCP ships over the wire — a blind run measured
    agent-visible `--password` mentions going from one at base to two at
    HEAD, both inside `get_setup_status`'s own docstring, exactly the shape
    this test used to wave through. Do not re-widen the exemption back to
    "any docstring" without re-reading that finding.

    Every other occurrence is imperative guidance text (e.g. "Provide
    --password ..." / "... or pass --password ..."), which is exactly what
    this task removes. Grepping the message strings rather than asserting
    on today's known call sites makes this durable: a future edit that
    reintroduces the recommendation anywhere in either module fails this
    test.

    A literal prohibition such as "Never pass the password as a tool
    argument or shell argument" or "DO NOT pass the password as a tool
    argument" never contains the substring '--password' at all (it says
    "tool argument" / "shell argument", not the flag spelling), so it can
    never collide with either allowed shape above and needs no special
    casing here.
    """
    import re
    from redshift_comment_mcp import server as server_module
    from redshift_comment_mcp import redshift_tools as redshift_tools_module

    argparse_decl_re = re.compile(r'^\s*"--password",\s*$')
    docstring_ref_re = re.compile(r'``[^`]*--password[^`]*``')

    for module in (server_module, redshift_tools_module):
        with open(module.__file__, encoding="utf-8") as f:
            source = f.read()
        lines = source.splitlines(keepends=True)
        tool_doc_ranges = _mcp_tool_docstring_line_ranges(source)

        def _in_wire_published_docstring(lineno: int) -> bool:
            return any(start <= lineno <= end for start, end in tool_doc_ranges)

        for lineno, line in enumerate(lines, start=1):
            if "--password" not in line:
                continue
            assert not _in_wire_published_docstring(lineno), (
                f"{module.__file__}:{lineno} mentions --password inside an "
                f"@self.mcp.tool docstring. FastMCP publishes this text "
                f"verbatim to every MCP client in tools/list, so even a "
                f"double-backtick-quoted reference reaches the wire — "
                f"remove it, keeping any REDSHIFT_PASSWORD guidance:\n"
                f"{line!r}"
            )
            allowed = bool(argparse_decl_re.match(line)) or bool(docstring_ref_re.search(line))
            assert allowed, (
                f"{module.__file__}:{lineno} recommends the --password flag "
                f"as a way to supply a password — remove the recommendation, "
                f"keeping any REDSHIFT_PASSWORD env var guidance:\n{line!r}"
            )


# ===== W0-07 defect A: the refusal must name each existing profile's WHOLE
# target, not just host:port =====
# Two profiles on the same host/port/user but different dbname must render
# as two distinguishable entries, or the operator cannot tell which one to
# point /redshift-setup at.


def test_refusal_two_profiles_differing_only_in_dbname_render_distinctly(
    tmp_xdg, fake_keyring, monkeypatch
):
    """A2 boundary: rendering only host:port collapses two profiles that
    share a host/port/user but differ in dbname into two identical-looking
    entries. The refusal must name user and dbname too, so the field that
    actually made each profile miss the inline target is visible."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    for name, dbname in (("prod", "warehouse"), ("prod_analytics", "analytics")):
        config.write_profile(
            name, host="redshift.internal", port=5439, user="alice", dbname=dbname,
        )
        config.set_password(name, f"{name}-secret")

    args = _ns(host="redshift.internal", port=5439, user="alice", dbname="reporting")
    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    msg = str(excinfo.value)
    assert "warehouse" in msg, f"prod's dbname is missing from the refusal: {msg!r}"
    assert "analytics" in msg, f"prod_analytics's dbname is missing from the refusal: {msg!r}"


# ===== W0-07 defect B: a mistyped port must not silently borrow =====
# `_coerce_port` tolerates two specific optional-userConfig artefacts (blank,
# unsubstituted placeholder) by collapsing them to DEFAULT_PORT so the server
# still boots. A genuine typo is neither artefact and must not collapse into
# a value that then matches — and borrows from — a stored profile the
# operator never named.


def test_borrow_mistyped_port_refuses_to_borrow(tmp_xdg, fake_keyring, monkeypatch):
    """A1 negative: a port argparse could not parse from what the operator
    actually typed (a typo, e.g. "9999x") must not borrow a stored
    profile's keychain password just because it collapsed to the same
    default port that profile happens to be recorded at. The refusal must
    also quote the raw typed value so the operator can see the typo."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "prod", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("prod", "provisioned-for-5439")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=server._coerce_port, default=server.DEFAULT_PORT)
    port = parser.parse_args(["--port", "9999x"]).port
    assert port == 5439  # still boots — the typo collapses to the default

    args = _ns(host="h.example.com", user="u", dbname="d", port=port)
    decision = server.resolve_connection_decision(args)
    assert decision.password != "provisioned-for-5439", (
        f"a keychain password provisioned for h.example.com:5439 was lent to "
        f"a launch whose port the server could not parse (mechanism="
        f"{decision.mechanism!r}, borrowed_from={decision.profile_name!r})"
    )
    assert decision.mechanism == "inline"

    with pytest.raises(ValueError) as excinfo:
        server.resolve_connection_params(args)
    assert "9999x" in str(excinfo.value), (
        "the refusal must quote the raw typed port value so the operator "
        f"can see the typo: {excinfo.value!r}"
    )


def test_borrow_blank_and_placeholder_port_still_borrow(tmp_xdg, fake_keyring, monkeypatch):
    """A1 boundary: blank and unsubstituted-`${user_config.port}` are the
    two artefacts `_coerce_port` exists to tolerate, not typos. They must
    keep collapsing to the documented default port and still borrow
    normally — exactly like a profile recorded without an explicit port —
    or an ordinary optional-userConfig launch would start refusing."""
    monkeypatch.delenv("REDSHIFT_PASSWORD", raising=False)
    config.write_profile(
        "default", host="h.example.com", port=5439, user="u", dbname="d",
    )
    config.set_password("default", "borrowed-pw")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=server._coerce_port, default=server.DEFAULT_PORT)

    for raw in ("", "${user_config.port}"):
        port = parser.parse_args(["--port", raw]).port
        args = _ns(host="h.example.com", user="u", dbname="d", port=port)
        assert server.resolve_connection_params(args) == (
            "h.example.com", 5439, "u", "borrowed-pw", "d"
        ), f"raw port {raw!r} must still borrow normally"
