"""Probe: the edges of the password channel W0-03 narrowed.

Acceptance 4 says an unsubstituted configuration placeholder must be treated
as no password rather than as a password. ``_normalize_inline`` implements
that as: strip, then ``startswith("${user_config")`` and ``endswith("}")``.
That is a narrow shape, and the whole point of the acceptance line is that a
truthy-but-meaningless string must not be authenticated with. So the probes
here walk the edge of that shape, and the edge of the standing constraint that
the value must not reach argv.

Two behaviours are characterised rather than asserted-against, because the
intent puts them out of scope explicitly: the whitespace-only password, and
how a placeholder that is not exactly this shape is classified. Recording
them keeps the boundary visible to whoever picks up the filed follow-ups.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _probe_support import isolate_store, ns  # noqa: E402

from redshift_comment_mcp import config, server  # noqa: E402

# probes/ -> evidence/ -> <change-id>/ -> loom/ -> docs/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[5]

SECRET = "pr0be-B0RR0WED-s3cret"


def _store_with_matching_profile(tmp_path, monkeypatch):
    isolate_store(monkeypatch, tmp_path)
    config.write_profile(
        "prod", host="redshift.internal", port=5439, user="alice", dbname="warehouse",
    )
    config.set_password("prod", SECRET)


def test_password_unsubstitutedplaceholder_fallsthroughtoborrow(tmp_path, monkeypatch):
    """The two W0 tasks must compose: a placeholder is absence, so borrow.

    This is the exact field configuration the 2026-09-17 incident produced —
    host/user/dbname filled, password field left blank so the host passes the
    literal placeholder through — and it must now resolve, not authenticate
    with the placeholder text.
    """
    _store_with_matching_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("REDSHIFT_PASSWORD", "${user_config.password}")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    decision = server.resolve_connection_decision(args)

    assert decision.mechanism == "borrowed"
    assert decision.password == SECRET, (
        "the unsubstituted placeholder was authenticated with instead of being "
        "treated as absence"
    )


def test_password_emptyenvvar_fallsthroughtoborrow(tmp_path, monkeypatch):
    """An empty ``REDSHIFT_PASSWORD`` is absence, not a zero-length password."""
    _store_with_matching_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("REDSHIFT_PASSWORD", "")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    assert server.resolve_connection_decision(args).password == SECRET


def test_password_paddedplaceholder_fallsthroughtoborrow(tmp_path, monkeypatch):
    """Boundary: a placeholder a host wrapped in whitespace is still absence."""
    _store_with_matching_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("REDSHIFT_PASSWORD", "  ${user_config.password}\n")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    assert server.resolve_connection_decision(args).password == SECRET


def test_password_offshapeplaceholder_ischaracterised(tmp_path, monkeypatch):
    """Characterisation: what the placeholder test does NOT classify as absence.

    ``startswith("${user_config")`` is case-sensitive and ``endswith("}")``
    requires the literal to be the whole value. So an uppercased placeholder,
    or one with trailing text, is treated as a real password and would be sent
    to Redshift verbatim. Neither shape is one Claude Code emits — the
    substitution tokens in ``.claude-plugin/plugin.json`` are lowercase and
    whole-value — so this is recorded as the boundary of the guard rather than
    asserted against it. A different host with a different token casing would
    move it from boundary to defect.
    """
    _store_with_matching_profile(tmp_path, monkeypatch)
    args = ns(host="redshift.internal", user="alice", dbname="warehouse")

    tokens = [token for token in json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text()
    )["mcpServers"]["redshift-comment"]["args"] if "user_config" in token]
    assert tokens, "the manifest no longer substitutes any ${user_config.*} token"
    assert all(token == token.lower() for token in tokens), (
        f"the manifest now emits a non-lowercase substitution token, which the "
        f"case-sensitive placeholder guard would not catch: {tokens!r}"
    )

    monkeypatch.setenv("REDSHIFT_PASSWORD", "${USER_CONFIG.password}")
    assert server.resolve_connection_decision(args).password == "${USER_CONFIG.password}"

    monkeypatch.setenv("REDSHIFT_PASSWORD", "${user_config.password} ")
    assert server.resolve_connection_decision(args).password == SECRET


def test_password_whitespaceonly_ischaracterised(tmp_path, monkeypatch):
    """Characterisation of the gate the intent files as out of scope.

    "The blank-password gate — ``if not password`` accepts whitespace-only
    values." A single space is truthy, so it beats the borrow and is sent as
    the password. Recorded so the follow-up has an executable starting point;
    not asserted against, because closing it here would be scope this change
    declined.
    """
    _store_with_matching_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("REDSHIFT_PASSWORD", " ")

    args = ns(host="redshift.internal", user="alice", dbname="warehouse")
    decision = server.resolve_connection_decision(args)

    assert decision.mechanism == "inline"
    assert decision.password == " ", (
        "behaviour changed — the whitespace-only gate may now be closed; if so "
        "this characterisation should become an assertion"
    )


def test_argv_borrowedlaunch_carriesnopassword(tmp_path, monkeypatch):
    """The standing constraint, on the channel the intent names first.

    Two halves: the launch this server is actually running under must not have
    the borrowed secret anywhere in ``sys.argv``, and the manifest that builds
    a real launch must not put the password on the command line at all — it
    goes through ``env``.
    """
    _store_with_matching_profile(tmp_path, monkeypatch)
    args = ns(host="redshift.internal", user="alice", dbname="warehouse")

    decision = server.resolve_connection_decision(args)
    assert decision.password == SECRET, "probe setup failed: nothing was borrowed"
    assert not any(SECRET in argument for argument in sys.argv)

    manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    launch = manifest["mcpServers"]["redshift-comment"]
    assert "--password" not in launch["args"], (
        f"the manifest puts the password on argv: {launch['args']!r}"
    )
    assert not any("password" in argument.lower() for argument in launch["args"]), (
        f"the manifest's argv mentions the password field: {launch['args']!r}"
    )
    assert launch["env"]["REDSHIFT_PASSWORD"] == "${user_config.password}"


def test_messages_everyserverauthoredrefusal_omitsthepasswordflag(tmp_path, monkeypatch):
    """Acceptance 5, from the attacker's side: every refusal path, not one.

    The implementer's pin greps the module source. This one walks the refusal
    messages the server actually emits — four distinct raise sites — and
    checks each rendered string, so a message that recommends the flag through
    an f-string built at runtime is caught too.
    """
    isolate_store(monkeypatch, tmp_path)
    messages = []

    def _capture(args):
        try:
            server.resolve_connection_params(args)
        except Exception as exc:
            messages.append(str(exc))
        else:
            raise AssertionError(f"expected a refusal for {args!r}")

    # inline, no password, empty store
    _capture(ns(host="h.example.com", user="u", dbname="d"))
    # inline, no password, a store that cannot lend
    config.write_profile("other", host="o.example.com", port=5439, user="u", dbname="d")
    config.set_password("other", "not-lendable")
    _capture(ns(host="h.example.com", user="u", dbname="d"))
    # profile mode, resolved profile absent while other profiles exist
    _capture(ns(profile="typo"))
    # profile mode, fields present but no keychain entry
    config.write_profile("lonely", host="l.example.com", port=5439, user="u", dbname="d")
    _capture(ns(profile="lonely"))

    assert len(messages) == 4
    for message in messages:
        assert "--password" not in message, (
            f"a server-authored refusal still recommends the argv flag: {message!r}"
        )
        assert "not-lendable" not in message, (
            f"a refusal leaked a stored password: {message!r}"
        )
    assert any("REDSHIFT_PASSWORD" in message for message in messages), (
        "the inline refusals must still name the env-var channel that replaced "
        "the flag (W0-03 boundary: env-var guidance survives)"
    )
