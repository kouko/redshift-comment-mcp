"""Adversarial probes: the new KeychainDeleteError as an escape route.

Change: 2026-09-18-config-store-integrity
Anchor: src/redshift_comment_mcp/config.py :: KeychainDeleteError, delete_profile
        src/redshift_comment_mcp/setup_cli.py :: cmd_delete_profile

``delete_profile`` changed from "returns bool" to "returns bool or raises". A
new exception on a function that already had callers is two questions: does
every caller handle it, and does the exception — or the cause chained behind
it — carry anything it should not. The ``except Exception`` around the keychain
call is deliberately broad, so the third question is what it now catches that
it was never meant to.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _probe_support import install_fake_keychain, isolate_config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[5]
SERVICE = "redshift-comment-mcp"
SECRET = "hunter2-correct-horse-battery-staple"


@pytest.fixture
def store(tmp_path, monkeypatch):
    config_file = isolate_config(monkeypatch, tmp_path)
    keychain = install_fake_keychain(monkeypatch)
    from redshift_comment_mcp import config as cfg

    return config_file, cfg, keychain


def _seed(cfg, name="prod"):
    cfg.write_profile(name, host="h.example.com", port=5439, user="u", dbname="d")
    cfg.set_password(name, SECRET)


# ----- who calls it -----


def _delete_profile_call_sites(tree: ast.AST) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "delete_profile"
    ]


def _handlers_covering(tree: ast.AST, call: ast.Call) -> list[str]:
    """Names of the exception types whose ``try`` lexically encloses ``call``."""
    covering: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        body_lines = {
            n.lineno for stmt in node.body for n in ast.walk(stmt)
            if hasattr(n, "lineno")
        }
        if call.lineno not in body_lines:
            continue
        for handler in node.handlers:
            if handler.type is None:
                covering.append("bare except")
            else:
                covering.append(ast.unparse(handler.type))
    return covering


def test_deleteprofile_everyshippedcallsite_handlesthekeychaindeleteerror():
    """Scan every shipped module for a delete_profile call left unguarded.

    A raise added to an existing function is only safe if the callers moved
    with it. This walks the real source rather than trusting a grep, so a call
    site added later is caught too.
    """
    unguarded: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for call in _delete_profile_call_sites(tree):
            handlers = _handlers_covering(tree, call)
            if not any("KeychainDeleteError" in h or h == "bare except"
                       for h in handlers):
                rel = path.relative_to(REPO_ROOT)
                unguarded.append(f"{rel}:{call.lineno} (handlers: {handlers or 'none'})")

    assert not unguarded, (
        "these call sites invoke config.delete_profile without handling the "
        f"KeychainDeleteError it can now raise: {unguarded}"
    )


def test_deleteprofile_thekeychainerrorpath_isreachablefromthecli(store, monkeypatch):
    """End to end: a locked keychain reaches the CLI as exit 2, not a traceback."""
    _config_file, cfg, _keychain = store
    _seed(cfg)

    import keyring

    class _Locked(Exception):
        pass

    monkeypatch.setattr(
        keyring, "delete_password",
        lambda service, user: (_ for _ in ()).throw(_Locked("keychain is locked")),
    )

    from redshift_comment_mcp import setup_cli
    import argparse

    monkeypatch.setattr("builtins.input", lambda *_a: "y")
    args = argparse.Namespace(profile="prod", yes=True)
    code = setup_cli.cmd_delete_profile(args)

    assert code == 2, f"the locked-keychain path exited {code}, expected 2"
    assert cfg.read_profile("prod") is not None, "the failed delete removed the fields"


# ----- what the error carries -----


def test_keychaindeleteerror_backendechoingasecret_keepsitoutofeveryusersurface(
    store, monkeypatch, capsys
):
    """A backend whose exception text quotes a secret: where can it reach?

    RECONCILED with the finding it pins (was
    ``…_keepsitoutofthetraceback``). That assertion demanded the secret be
    absent from ``traceback.format_exc()``, which is unreachable at the same
    time as the sibling case's ``__cause__ is boom``: ``__cause__`` is always
    rendered, so the only way to strip it is to mutate the backend exception's
    ``args`` before re-raising — throwing away the real diagnostic for every
    user on every keychain failure, to defend against a payload no backend
    has. ``keyring.delete_password(service, username)`` is never handed a
    password. My own finding said so and recorded ``fix: None required``; the
    assertion, not the finding, was wrong.

    What is pinned instead is every surface a user or a log actually sees:
    nothing the backend said is copied into the new exception's own message or
    args, and nothing reaches stderr through the CLI. The chain is asserted
    positively, as the deliberate design it is — which is also what makes the
    remaining exposure visible rather than quietly dropped: a caller that
    renders the full chain renders whatever the backend put in it.
    """
    _config_file, cfg, _keychain = store
    _seed(cfg)

    import keyring

    class _ChattyBackend(Exception):
        pass

    chatty_text = f"SecKeychainItemDelete failed for prod: {SECRET}"

    def chatty(service, user):
        raise _ChattyBackend(chatty_text)

    monkeypatch.setattr(keyring, "delete_password", chatty)

    with pytest.raises(cfg.KeychainDeleteError) as caught:
        cfg.delete_profile("prod")

    own_message = str(caught.value)
    own_args = repr(caught.value.args)

    assert SECRET not in own_message, "KeychainDeleteError's message quotes the secret"
    assert SECRET not in own_args, "KeychainDeleteError's args quote the secret"
    assert chatty_text not in own_message, (
        "the backend's own text was copied verbatim into KeychainDeleteError's "
        "message, so whatever a backend puts in it travels wherever the new "
        "error is printed — including the CLI, which prints str(e)"
    )
    assert type(caught.value.__cause__).__name__ == "_ChattyBackend", (
        "the backend exception is no longer the chained cause — deliberate "
        "design (config.py raises `from e`) and the only record of what "
        "really failed"
    )

    # The one rendering a user is ever shown: the CLI's own handler.
    import argparse

    from redshift_comment_mcp import setup_cli

    monkeypatch.setattr("builtins.input", lambda *_a: "y")
    code = setup_cli.cmd_delete_profile(argparse.Namespace(profile="prod"))
    printed = capsys.readouterr()

    assert code == 2
    assert SECRET not in printed.err and SECRET not in printed.out, (
        "the CLI's delete-profile output carries the secret the backend put in "
        "its exception text"
    )
    assert "_ChattyBackend" in printed.err, (
        "the CLI names no cause at all, so a user cannot tell a locked "
        "keychain from a broken backend"
    )


def test_deleteprofile_backendraisingaprogrammingerror_stillnamesthecause(
    store, monkeypatch
):
    """The broad ``except Exception`` catches things that are not a locked keychain.

    A ``TypeError`` from a backend whose signature moved, an ``AttributeError``
    from a half-initialised backend — all of them become the same
    ``KeychainDeleteError`` whose text ends "unlock the keychain and delete it
    again", which is not the fix for either. Breadth is the deliberate choice
    here, so what has to hold instead is that the user can still tell what
    actually happened: the cause's class name is in the message, and the store
    is untouched whatever was raised.
    """
    _config_file, cfg, keychain = store
    _seed(cfg)

    import keyring

    for boom in (TypeError("delete_password() takes 3 positional arguments"),
                 AttributeError("'NoneType' object has no attribute 'delete'"),
                 RuntimeError("D-Bus session bus is not available")):
        monkeypatch.setattr(
            keyring, "delete_password",
            lambda service, user, _e=boom: (_ for _ in ()).throw(_e),
        )
        with pytest.raises(cfg.KeychainDeleteError) as caught:
            cfg.delete_profile("prod")

        message = str(caught.value)
        assert type(boom).__name__ in message, (
            f"a {type(boom).__name__} was reported as a keychain failure with "
            f"no trace of what it really was: {message!r}"
        )
        assert caught.value.__cause__ is boom, "the original cause was dropped"
        assert cfg.read_profile("prod") is not None, "the store was modified anyway"
        assert (SERVICE, "prod") in keychain, "the password was removed anyway"


def test_deleteprofile_keychainraisingkeyboardinterrupt_leavesthestoreintact(
    store, monkeypatch
):
    """Ctrl-C at the OS unlock prompt is a BaseException, not an Exception.

    The broad ``except Exception`` deliberately does not catch it, so the
    interrupt propagates raw. The property that has to hold is the one the
    docstring claims for the ordering: nothing in the store was touched yet.
    """
    _config_file, cfg, keychain = store
    _seed(cfg)

    import keyring

    monkeypatch.setattr(
        keyring, "delete_password",
        lambda service, user: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        cfg.delete_profile("prod")

    assert cfg.read_profile("prod") is not None, "the fields went with the interrupt"
    assert (SERVICE, "prod") in keychain, "the password went with the interrupt"


def test_deleteprofile_keychainreturningsuccessforthewrongprofile_deletesonlywhatwasasked(
    store, monkeypatch
):
    """Absence is checked before the keychain, so a typo never reaches it.

    Ordering point 2 of the docstring. The abuse is the name that looks like a
    profile but is not one — a trailing newline, a path traversal, the empty
    string — each of which must be answered False without a keychain call.
    """
    _config_file, cfg, keychain = store
    _seed(cfg, "prod")

    import keyring

    touched: list[str] = []
    real_delete = keyring.delete_password

    def recording(service, user):
        touched.append(user)
        return real_delete(service, user)

    monkeypatch.setattr(keyring, "delete_password", recording)

    for hostile in ["", "prod\n", " prod", "PROD", "../prod", "prod\x00",
                    "profile.prod", "p" * 4096]:
        assert cfg.delete_profile(hostile) is False, (
            f"delete_profile({hostile!r}) reported a deletion for a name that "
            f"is not a configured profile"
        )

    assert touched == [], (
        f"the keychain was called for names that are not profiles: {touched}. "
        f"Each call is a potential OS unlock prompt for a profile that does "
        f"not exist"
    )
    assert cfg.read_profile("prod") is not None
    assert (SERVICE, "prod") in keychain
