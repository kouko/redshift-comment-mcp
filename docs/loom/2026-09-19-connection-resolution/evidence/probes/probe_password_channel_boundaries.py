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
    messages the server actually emits — five distinct raise sites — and
    checks each rendered string, so a message that recommends the flag through
    an f-string built at runtime is caught too.

    The fifth site is W0-08's: the inline branch grew a second, separate
    ``raise`` for the ambiguous-lender case, with its own text rather than a
    clause added to the existing one. A new raise site is a new chance to
    re-suggest the flag, and it is the one site whose text is *about* which
    stored password to use, so it is added here rather than left to the
    source grep.
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
    # inline, no password, two stored profiles tie on the whole target (W0-08)
    for tied, tied_secret in (("tie-a", "tied-a-secret"), ("tie-b", "tied-b-secret")):
        config.write_profile(
            tied, host="h.example.com", port=5439, user="u", dbname="d",
        )
        config.set_password(tied, tied_secret)
    _capture(ns(host="h.example.com", user="u", dbname="d"))

    assert len(messages) == 5
    for message in messages:
        assert "--password" not in message, (
            f"a server-authored refusal still recommends the argv flag: {message!r}"
        )
        for leaked in ("not-lendable", "tied-a-secret", "tied-b-secret"):
            assert leaked not in message, (
                f"a refusal leaked a stored password: {message!r}"
            )
    assert "tie-a" in messages[-1] and "tie-b" in messages[-1], (
        f"the fifth capture is not the ambiguity refusal, so this probe stopped "
        f"covering that raise site: {messages[-1]!r}"
    )
    assert any("REDSHIFT_PASSWORD" in message for message in messages), (
        "the inline refusals must still name the env-var channel that replaced "
        "the flag (W0-03 boundary: env-var guidance survives)"
    )


def test_wiretext_everypublishedsurface_omitsthepasswordflag():
    """Acceptance 5 on the whole wire, not on the one surface each guard checks.

    W0-08 split the A5 regression guard in two: an AST scan over server.py
    and redshift_tools.py source that exempts a ``--password`` written inside
    double backticks unless it sits in an ``@self.mcp.tool`` docstring, and a
    runtime companion that reads every registered tool's published
    ``description``. The AST half names its own blind spot (a tool registered
    through some other decorator shape) and points at the runtime half as
    the one to trust.

    The runtime half does close that specific hole — a tool registered via an
    aliased decorator still appears in ``list_tools``, so its description is
    still read. But it reads descriptions and nothing else, while the source
    half's exemption is keyed on formatting and applies anywhere outside a
    tool docstring. Between them sits the surface with the widest reach of
    all: the FastMCP ``instructions`` handshake, a plain string literal (not
    a docstring, not a description) that every MCP client receives before it
    calls anything. A double-backticked ``--password`` recommendation written
    there is exempted by one guard and unread by the other.

    So this walks what the wire actually carries — the handshake string, and
    every registered tool's name, description and input schema — and takes no
    view on how any of it was spelled in the source.
    """
    import asyncio

    from _probe_support import server_instructions, tools_for

    surfaces = {"instructions": server_instructions()}

    tools = tools_for(ns())
    lister = getattr(tools.mcp, "list_tools", None) or tools.mcp._list_tools
    for tool in asyncio.run(lister()):
        surfaces[f"{tool.name}.description"] = tool.description or ""
        schema = getattr(tool, "parameters", None) or getattr(
            tool, "inputSchema", None
        )
        if schema is not None:
            surfaces[f"{tool.name}.input_schema"] = json.dumps(schema)

    assert "instructions" in surfaces and surfaces["instructions"].strip()
    assert any(key.endswith(".description") for key in surfaces), (
        "no tool descriptions were read, so this probe would pass vacuously"
    )

    offending = {
        name: text for name, text in surfaces.items() if "--password" in text
    }
    assert offending == {}, (
        f"agent-visible text recommends the argv password flag on "
        f"{sorted(offending)}. Every string here is published to an MCP "
        f"client verbatim, and the A5 guards in tests/ read only tool "
        f"descriptions (runtime half) or exempt a double-backticked "
        f"reference outside a tool docstring (source half), so neither "
        f"covers all of it: {offending!r}"
    )
