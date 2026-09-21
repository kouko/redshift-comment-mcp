import os
import re
import sys
import argparse
import logging
from typing import Optional
from .config import ConfigurationError
from .connection import create_redshift_config
from .redshift_tools import RedshiftTools, ConnectionDecision, resolve_profile_decision

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5439

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _render_profile_name(name: str) -> str:
    """Render a stored profile name for an operator-facing refusal message.

    A profile name is not operator-only input (W0-09 item 2): nothing
    validates it at write time, and ``setup_via_dialog``'s ``profile``
    argument is chosen by an agent whose job is reading Redshift comments it
    does not control, so a name can carry a control character the same way
    any other tool argument can. Shared by every message-building site that
    interpolates a stored name (``_target_desc`` below and the
    ambiguous-profiles join in ``resolve_connection_params``) so the two
    cannot drift apart on how they render one.

    - No control character: ``!r``, the same treatment every value beside a
      name in these messages already gets.
    - A control character present: truncate at the FIRST one and still
      render that prefix ``!r``'d, plus an explicit marker. ``!r`` alone
      escapes a control character so it can no longer split the message
      into an extra structural line, but the text placed after it is still
      fully legible in the escaped output — enough to land attacker-chosen
      content in text an agent reads. A control character is never
      legitimate in a profile name, so refusing to render past the first
      one is honest, and it keeps this message from being the thing that
      carries the payload. When the prefix is non-empty, it identifies
      which entry is the problem, and the marker says that entry itself is
      malformed — never replaced with a generic placeholder that would
      hide which one to go fix. When the control character is the name's
      FIRST character, the prefix is empty (``'' [truncated: ...]``) and
      names nothing; that entry is identified instead by the
      host/port/user/dbname printed alongside it in both message halves
      that call this function, which is enough for the operator to act on.

    Confirmed truncation points: newline, carriage return, an ANSI escape
    (``\\x1b``), NUL and DEL all fall in ``\\x00``-``\\x1f``/``\\x7f`` and
    truncate. U+2028 (LINE SEPARATOR) and U+2029 (PARAGRAPH SEPARATOR) do
    NOT truncate — they fall outside this regex — but ``repr`` escapes them
    to ``\\u2028``/``\\u2029`` in the ``!r`` output, so neither can forge an
    extra structural line either way.

    This does not validate profile names or close the gap that lets one
    reach the store with a control character in it at all — that remains
    ``config.write_profile`` / ``setup_via_dialog``, out of scope here (see
    the W0-09 report's follow-up).
    """
    match = _CONTROL_CHAR_RE.search(name)
    if match is None:
        return repr(name)
    return f"{name[:match.start()]!r} [truncated: name contains a control character]"


class _SubstitutedPort(int):
    """A port value ``_coerce_port`` could not parse from what was typed.

    Behaves as a plain ``int`` equal to ``DEFAULT_PORT`` everywhere
    ``args.port`` / ``decision.port`` is read — the server still boots on a
    typo, exactly as ``_coerce_port`` always has. ``raw_value`` carries the
    original string and the ``substituted`` flag lets
    ``resolve_connection_decision`` refuse to borrow a stored profile's
    keychain password on a port the operator did not actually name, and lets
    ``resolve_connection_params`` quote the mistyped value in its refusal
    (see W0-07).

    Only a genuine typo is wrapped here. A blank field and an unsubstituted
    ``${user_config.port}`` placeholder — the two optional-userConfig
    artefacts ``_coerce_port`` exists to tolerate — are deliberately NOT
    wrapped: an operator who left the field blank has effectively chosen
    ``DEFAULT_PORT``, so those two stay a plain ``int`` and keep borrowing
    normally, the same as a profile recorded without an explicit port.
    """

    substituted = True

    def __new__(cls, raw_value):
        obj = super().__new__(cls, DEFAULT_PORT)
        obj.raw_value = raw_value
        return obj


def _coerce_port(raw) -> int:
    """argparse ``type=`` for ``--port`` that tolerates optional-userConfig debris.

    A Claude Code plugin ``userConfig`` is optional: a blank port field arrives
    as ``""`` and an unset field may arrive as the unsubstituted literal
    ``${user_config.port}``. Plain ``type=int`` would make argparse abort with
    ``invalid int value`` and the server would never boot. Map either of
    those two specific artefacts to a plain ``DEFAULT_PORT`` instead of
    raising; pass real integer strings (and already-int values) through
    unchanged.

    Anything else that fails to parse (a typo such as ``"9999x"``) is
    neither artefact — the operator typed a value and got it wrong — so it
    is wrapped in ``_SubstitutedPort`` instead of a plain int: the server
    still boots with ``DEFAULT_PORT``, but the substitution is recorded so
    it does not silently match a stored profile's borrow scan (see W0-07).
    """
    if isinstance(raw, int):
        return raw
    stripped = "" if raw is None else str(raw).strip()
    if not stripped or (stripped.startswith("${user_config") and stripped.endswith("}")):
        return DEFAULT_PORT
    try:
        return int(stripped)
    except ValueError:
        return _SubstitutedPort(raw)


def _normalize_inline(value):
    """Return ``None`` for inline string args that aren't a real value.

    Treats an empty string OR an unsubstituted ``${user_config...}`` placeholder
    literal as "unset" so the inline-completeness check below falls through to
    profile mode instead of mistaking the placeholder for a real host/user/dbname.
    """
    if not value:
        return None
    stripped = str(value).strip()
    if stripped.startswith("${user_config") and stripped.endswith("}"):
        return None
    return value or None

# Subcommands handled by setup_cli.py — delegated before server arg parsing.
SETUP_SUBCOMMANDS = {
    "setup",
    "set-password",
    "test-connection",
    "list-profiles",
    "delete-profile",
    "set-fields",
}


def _resolve_inline_password(args: argparse.Namespace) -> Optional[str]:
    """Return the inline password value, or ``None`` if absent/placeholder.

    Runs ``args.password`` and the ``REDSHIFT_PASSWORD`` env var through the
    exact same ``_normalize_inline`` every other inline field (host / user /
    dbname) already gets. Without this, an unsubstituted ``${user_config...}``
    placeholder literal — or a host that substitutes env the way it
    substitutes argv — would be a truthy string: ``has_password`` would
    report ``True`` and the server would authenticate with the literal
    placeholder text instead of treating it as no password at all.

    A single function so ``resolve_inline_params`` (presence only) and
    ``resolve_connection_decision`` (the actual value) can never derive a
    different answer from each other, the same reason ``ConnectionDecision``
    replaced the old bare-tuple seam.
    """
    return _normalize_inline(getattr(args, "password", None)) or _normalize_inline(
        os.getenv("REDSHIFT_PASSWORD")
    )


def resolve_inline_params(
    args: argparse.Namespace,
) -> Optional[tuple[str, int, str, bool, str]]:
    """Detect legacy inline mode from CLI args, password presence only.

    Returns ``(host, port, user, has_password, dbname)`` when ``args.host`` /
    ``args.user`` / ``args.dbname`` all specify a real inline value (after
    the same optional-userConfig normalization ``resolve_connection_params``
    applies), else ``None``.

    ``has_password`` reflects presence of ``args.password`` or the
    ``REDSHIFT_PASSWORD`` env var, both normalized by
    ``_resolve_inline_password`` so an unsubstituted placeholder or blank
    value is "unset" rather than a truthy secret — it NEVER returns the
    secret itself. This is the detection ``resolve_connection_decision``
    below reuses so the connector and ``get_setup_status`` always agree on
    whether inline (or borrowed) mode is active, without ``get_setup_status``
    ever handling the password value itself.
    """
    host = _normalize_inline(args.host)
    user = _normalize_inline(args.user)
    dbname = _normalize_inline(args.dbname)
    if not (host and user and dbname):
        return None
    has_password = bool(_resolve_inline_password(args))
    return host, _coerce_port(args.port), user, has_password, dbname


def resolve_connection_decision(
    args: argparse.Namespace,
    profile_override: Optional[str] = None,
) -> ConnectionDecision:
    """Resolve the single connection decision both the connector
    (``resolve_connection_params`` below) and the status tool
    (``get_setup_status``, via the ``status_provider`` wired up in ``main()``)
    report from — replacing the old ``inline_status_provider`` seam that
    shared only mode detection between them, which is exactly why they could
    still disagree about everything after the mode (see W0-02).

    Three mechanisms, same priority ``resolve_connection_params`` always had:

    - **Legacy inline**: all of ``args.host`` / ``args.user`` / ``args.dbname``
      are present. Password from ``args.password`` or ``REDSHIFT_PASSWORD``
      env var. If neither supplies one, ``config.toml`` is scanned for a
      profile whose host, port, user AND dbname all equal the inline
      four-field target, and that profile's keychain password is borrowed
      (mechanism ``"borrowed"``) — the connection still targets the inline
      host/port/user/dbname; a stored profile can supply a password only,
      never a connection target, and it only ever lends to a launch naming
      the exact same four-field target it was recorded for. Profile *name*
      is ignored throughout this mode. When MORE THAN ONE stored profile
      matches the same four-field target — a shape a credential rotation
      leaves behind (the retired profile kept alongside its replacement,
      same target), among others — the scan always refuses rather than
      picking whichever name sorts first: the decision comes back plain
      password-less ``"inline"`` with ``ambiguous_profiles`` naming every
      tied candidate. The refusal fires on the tie alone — see
      ``ConnectionDecision.ambiguous_profiles`` for why the scan reads but
      never compares the tied candidates' passwords to reach it (see W0-09).
    - **Profile mode** (the default): delegated to
      ``resolve_profile_decision``, which looks up the profile name via
      ``config.resolve_active_profile(profile_override or args.profile)``
      (priority CLI flag > ``REDSHIFT_COMMENT_PROFILE`` env > active-profile
      pointer file > ``"default"``) and reads host/user/dbname from
      ``~/.config/redshift-comment-mcp/config.toml``, password from OS
      keychain. ``profile_override`` lets ``get_setup_status`` peek at a
      named profile without touching the live server's own resolution.
    """
    inline = resolve_inline_params(args)
    if inline:
        host, port, user, has_password, dbname = inline
        if has_password:
            # Re-derive the password value here: resolve_inline_params
            # deliberately returns only presence (has_password bool), never
            # the secret. Reuses _resolve_inline_password so this can never
            # disagree with the presence check above about what counts as a
            # real password (see W0-03).
            password = _resolve_inline_password(args)
            return ConnectionDecision(
                mechanism="inline", host=host, port=port, user=user, dbname=dbname,
                has_fields=True, has_password=True, password=password,
                profile_name=None,
            )

        # No inline password. Before giving up, see if config.toml holds a
        # profile that IS this exact target — host, port, user AND dbname
        # all equal the inline four-field target — and borrow its keychain
        # password. The connection always targets the inline host/port/
        # user/dbname the operator typed; a stored profile can only ever
        # contribute a password, never redirect the connection anywhere
        # else, and it only lends to a launch naming the same four-field
        # target it was recorded for — a profile recorded at a different
        # port refuses rather than lending a password to a different
        # listener on the same host. An unmatched (or password-less) store
        # falls through to the password-less "inline" decision below rather
        # than guessing.
        #
        if getattr(port, "substituted", False):
            # `port` is a `_SubstitutedPort`: _coerce_port could not parse it
            # from what the operator actually typed (a typo, not the blank
            # or ${user_config.port} placeholder artefacts it exists to
            # tolerate). Letting it participate in the scan below would
            # silently match — and lend a keychain password to — whatever
            # profile happens to be recorded at DEFAULT_PORT, the same
            # silent-substitution shape the four-field match was widened to
            # close for an explicitly mistyped port, re-entering through the
            # parser. Skip the scan; resolve_connection_params quotes the
            # raw typed value in the resulting refusal.
            logger.debug(
                "borrow scan: port %r could not be parsed from typed value "
                "%r; refusing to borrow on a substituted port",
                int(port), getattr(port, "raw_value", None),
            )
            return ConnectionDecision(
                mechanism="inline", host=host, port=port, user=user, dbname=dbname,
                has_fields=True, has_password=False, password=None,
                profile_name=None,
            )

        # The scan below is guarded: list_profiles() / read_profile() /
        # get_password() can each raise for reasons that have nothing to do
        # with whether a match exists — no keyring backend on the host
        # (NoKeyringError), a non-table entry in config.toml (AttributeError
        # off a non-dict profile), or a malformed config.toml
        # (TOMLDecodeError, raised by list_profiles() itself before any
        # profile name is even available). None of those is
        # ConfigurationError, so @_guarded would not catch them, and
        # get_setup_status (which shares this exact function as its
        # status_provider) carries no guard of its own at all — a
        # keyring-less host would otherwise crash the one tool an agent
        # uses to ask "what state am I in", in a mode that never touched
        # the keychain before. Any such failure here must fall through to
        # the existing password-less inline refusal instead of escaping as
        # an opaque crash.
        from . import config as cfg
        try:
            candidate_names = cfg.list_profiles()
        except Exception as e:  # noqa: BLE001 — see comment above
            logger.debug(
                "borrow scan: could not list profiles (%s); falling through "
                "to the password-less inline decision", type(e).__name__,
            )
            candidate_names = []

        # Collect every candidate that matches AND has a password to lend —
        # not just the first — so an ambiguous match (see below) can be
        # detected instead of silently resolved by list_profiles()'s sort
        # order.
        lenders: list[tuple[str, str]] = []
        for candidate_name in candidate_names:
            try:
                candidate = cfg.read_profile(candidate_name)
                if not candidate:
                    continue
                candidate_port = _coerce_port(candidate.get("port"))
                if getattr(candidate_port, "substituted", False):
                    # Mirrors the launch-side guard above: config.toml held a
                    # stored port `_coerce_port` could not parse (a TOML
                    # float such as `9999.0`, or a hand-edited non-numeric
                    # string) — not the blank/placeholder shapes that
                    # legitimately collapse to DEFAULT_PORT. Matching it
                    # against a launch at DEFAULT_PORT would lend this
                    # profile's password to a target it was never recorded
                    # for. A profile whose stored port is unreadable is not
                    # a profile for this target.
                    continue
                if (candidate.get("host"), candidate_port, candidate.get("user"), candidate.get("dbname")) != (
                    host, port, user, dbname,
                ):
                    continue
                borrowed_password = cfg.get_password(candidate_name)
            except Exception as e:  # noqa: BLE001 — see comment above
                logger.debug(
                    "borrow scan: skipping profile %r after %s",
                    candidate_name, type(e).__name__,
                )
                continue
            if borrowed_password:
                lenders.append((candidate_name, borrowed_password))

        if len(lenders) == 1:
            candidate_name, borrowed_password = lenders[0]
            return ConnectionDecision(
                mechanism="borrowed", host=host, port=port, user=user, dbname=dbname,
                has_fields=True, has_password=True, password=borrowed_password,
                profile_name=candidate_name,
            )

        if len(lenders) > 1:
            # More than one profile matches the whole four-field target.
            # A credential rotation leaves exactly this shape (the retired
            # profile kept alongside its replacement, same target), among
            # others. Picking the first by config.list_profiles()'s sort
            # order would silently prefer whichever name sorts first —
            # possibly a retired secret — and could burn attempts against an
            # account lockout policy. A loud refusal beats a quiet wrong
            # answer, the same principle kouko chose for the port gap above
            # (2026-09-21).
            #
            # The refusal fires on the tie alone — see
            # ConnectionDecision.ambiguous_profiles for why the scan reads
            # but never compares the tied candidates' passwords to reach it
            # (see W0-09).
            ambiguous_names = tuple(name for name, _ in lenders)
            logger.debug(
                "borrow scan: refusing to guess — %d profiles all match "
                "this target: %s",
                len(ambiguous_names), ambiguous_names,
            )
            return ConnectionDecision(
                mechanism="inline", host=host, port=port, user=user, dbname=dbname,
                has_fields=True, has_password=False, password=None,
                profile_name=None, ambiguous_profiles=ambiguous_names,
            )

        return ConnectionDecision(
            mechanism="inline", host=host, port=port, user=user, dbname=dbname,
            has_fields=True, has_password=False, password=None,
            profile_name=None,
        )

    return resolve_profile_decision(
        profile_override if profile_override is not None else args.profile
    )


def resolve_connection_params(args: argparse.Namespace) -> tuple[str, int, str, str, str]:
    """Resolve ``(host, port, user, password, dbname)`` from parsed CLI args.

    Thin wrapper over ``resolve_connection_decision``: returns the target +
    password when one is available, else raises ``ConfigurationError``
    (subclass of ``ValueError`` for backward-compat) with a message tailored
    to the mechanism and the specific way it fell short — pointing at both
    ``/redshift-comment-mcp:redshift-setup`` (Claude Code skill) and
    ``redshift-comment-mcp setup`` (CLI, e.g. ``uvx redshift-comment-mcp
    setup``) for profile mode, or at the ``REDSHIFT_PASSWORD`` env var and
    the existing profiles available to borrow from for inline mode (never
    at ``--password`` — see W0-03: no server-authored message recommends
    that flag, though it remains a supported inline-launch argument).
    Surfaces a helpful next step regardless of whether the caller has the
    Claude Code plugin installed. Code paths that should react in-process
    (e.g. degraded-mode MCP tools returning a structured not_configured
    error) catch the specific subclass; legacy ``except ValueError`` still
    works.
    """
    decision = resolve_connection_decision(args)
    if decision.has_password:
        return decision.host, decision.port, decision.user, decision.password, decision.dbname

    from . import config as cfg

    if decision.mechanism == "inline":
        # Building this message re-touches the same store the borrow scan
        # above already guarded against (see resolve_connection_decision) —
        # a message-building failure must not replace the refusal the user
        # actually needs to see with an opaque store exception either.
        try:
            existing = cfg.list_profiles()
        except Exception as e:  # noqa: BLE001 — see resolve_connection_decision
            logger.debug(
                "borrow-refusal message: could not list profiles (%s)",
                type(e).__name__,
            )
            existing = []
        if existing:
            def _target_desc(name: str) -> str:
                try:
                    fields = cfg.read_profile(name) or {}
                    target_host = fields.get("host", "?")
                    target_port = _coerce_port(fields.get("port"))
                    target_user = fields.get("user", "?")
                    target_dbname = fields.get("dbname", "?")
                    # Same register as the typed half below (host=/port=/
                    # user=/dbname=, each !r) so the two halves of the
                    # message can be compared field by field — rendering
                    # only host:port let two profiles differing solely in
                    # dbname print as identical entries (see W0-07 defect A).
                    # The NAME goes through _render_profile_name (see W0-09
                    # item 2), not a bare !r: it is not operator-only input
                    # — setup_via_dialog's `profile` argument is an
                    # agent-chosen tool argument — and unlike every value
                    # beside it here, an unquoted name could carry a
                    # newline into this multi-line, line-structured message
                    # and forge a second "Existing profiles:" entry of its
                    # own choosing.
                    #
                    # `target_port` may be a `_SubstitutedPort`: the borrow
                    # scan (above) already skips this candidate on exactly
                    # this condition (see W0-11), but printing `!r` here
                    # would still show the substituted DEFAULT_PORT as
                    # though it were this profile's real port — making it
                    # print identically to a typed target at DEFAULT_PORT
                    # and hiding the actual reason it did not match: config
                    # .toml holds a port this server cannot read (a TOML
                    # float, or a hand-edited non-numeric string). Show the
                    # raw stored value instead, with a reason, exactly as
                    # the typed side already does for its own unparseable
                    # port (`substituted_port_note` below).
                    if getattr(target_port, "substituted", False):
                        port_desc = (
                            f"port={getattr(target_port, 'raw_value', None)!r} "
                            f"(unreadable — could not be parsed as a number)"
                        )
                    else:
                        port_desc = f"port={target_port!r}"
                    return (
                        f"{_render_profile_name(name)} (host={target_host!r} "
                        f"{port_desc} user={target_user!r} "
                        f"dbname={target_dbname!r})"
                    )
                except Exception as e:  # noqa: BLE001 — see above
                    logger.debug(
                        "borrow-refusal message: could not describe profile "
                        "%r (%s)", name, type(e).__name__,
                    )
                    return f"{_render_profile_name(name)} (unreadable)"

            existing_desc = ", ".join(_target_desc(name) for name in existing)
        else:
            existing_desc = "none configured"
        substituted_port_note = ""
        if getattr(decision.port, "substituted", False):
            substituted_port_note = (
                f" The port you typed ({getattr(decision.port, 'raw_value', decision.port)!r}) "
                f"could not be read as a number, so the server substituted "
                f"the default port {int(decision.port)} to boot — but a "
                f"substituted port never borrows a stored profile's "
                f"password. Fix the typo and relaunch."
            )
        if decision.ambiguous_profiles:
            # More than one stored profile matches the inline target — see
            # ConnectionDecision.ambiguous_profiles for why the scan reads
            # but never compares the tied candidates' passwords to reach
            # this branch (see W0-09). Name both (or all) tied candidates
            # explicitly (via _render_profile_name — see W0-09 item 2 —
            # never a bare interpolation); never their passwords.
            raise ConfigurationError(
                f"Inline mode requires a password for "
                f"host={decision.host!r} port={decision.port!r} "
                f"user={decision.user!r} dbname={decision.dbname!r}, and "
                f"{len(decision.ambiguous_profiles)} stored profiles all "
                f"match that exact target: "
                f"{', '.join(_render_profile_name(name) for name in decision.ambiguous_profiles)}. "
                f"Refusing to guess which one to borrow — picking by sort order could "
                f"silently prefer a retired credential over its "
                f"replacement, the shape a credential rotation leaves "
                f"behind.\n"
                f"Existing profiles: {existing_desc}.\n"
                f"Delete the stale profile with `redshift-comment-mcp "
                f"delete-profile --profile <name>` so only one matches "
                f"this target, or provide the REDSHIFT_PASSWORD env var "
                f"directly."
            )

        raise ConfigurationError(
            f"Inline mode requires a password for "
            f"host={decision.host!r} port={decision.port!r} "
            f"user={decision.user!r} dbname={decision.dbname!r}, and no stored "
            f"profile's host/port/user/dbname all match it to borrow one "
            f"from.{substituted_port_note}\n"
            f"Existing profiles: {existing_desc}.\n"
            f"Provide the REDSHIFT_PASSWORD env var, or configure a profile "
            f"matching this exact host/port/user/dbname via "
            f"/redshift-comment-mcp:redshift-setup."
        )

    # mechanism == "profile"
    profile_name = decision.profile_name
    if not decision.has_fields:
        # Two distinct UX cases share this raise site:
        # - No profiles at all → user needs to run /redshift-setup
        # - ≥1 profile, just not the one we resolved → user needs to
        #   switch (typo in name, or post-upgrade multi-profile with no
        #   "default" and no pointer file). List them so the user can
        #   spot the right name without re-running setup.
        #
        # Both messages use real "\n" between bullet items so they render
        # as multi-line when shown to the user. Concatenated f-strings
        # without explicit "\n" would render as a single run-on line.
        existing = cfg.list_profiles()
        if existing:
            raise ConfigurationError(
                f"Profile '{profile_name}' is not configured.\n"
                f"Existing profiles: {', '.join(existing)}.\n"
                f"To switch to an existing profile:\n"
                f"  - Claude Code: /redshift-comment-mcp:redshift-switch-profile\n"
                f"  - Terminal: pass `--profile <name>` to redshift-comment-mcp, "
                f"or set `REDSHIFT_COMMENT_PROFILE=<name>` env var\n"
                f"To add a new profile:\n"
                f"  - Claude Code: /redshift-comment-mcp:redshift-setup\n"
                f"  - In-band MCP tool: call `setup_via_dialog(host=..., "
                f"user=..., dbname=...)` — password collected via OS dialog "
                f"server-side, never crosses MCP wire / chat\n"
                f"  - Terminal: `uvx redshift-comment-mcp setup --profile <name>`\n"
                f"  - Code-agent Bash pipeline: `set-fields ... && set-password --dialog`"
            )
        raise ConfigurationError(
            f"Profile '{profile_name}' is not configured. Configure via one of:\n"
            f"  - Claude Code: /redshift-comment-mcp:redshift-setup in chat "
            f"(password collected via system dialog, never enters chat).\n"
            f"  - In-band MCP tool: call `setup_via_dialog(host=..., "
            f"user=..., dbname=...)` — runs the same dialog mechanism inside "
            f"this MCP session; password never crosses MCP wire / chat / "
            f"tool args.\n"
            f"  - Code agent (any MCP client with Bash): "
            f"`redshift-comment-mcp set-fields --profile {profile_name} "
            f"--host H --port P --user U --dbname D` then "
            f"`redshift-comment-mcp set-password --profile {profile_name} --dialog` "
            f"(the `--dialog` flag launches an OS-native password prompt; "
            f"`--stdin` is the headless fallback).\n"
            f"  - Human in terminal: `uvx redshift-comment-mcp setup "
            f"--profile {profile_name}` (full interactive Q&A).\n"
            f"Ask the user for host/user/dbname interactively; never invent "
            f"them. Never pass the password as a tool argument or shell "
            f"argument."
        )
    raise ConfigurationError(
        f"Password missing from keychain for profile '{profile_name}'. "
        f"Re-key via one of:\n"
        f"  - Claude Code: /redshift-comment-mcp:redshift-setup\n"
        f"  - In-band MCP tool: call `setup_via_dialog(host=..., "
        f"user=..., dbname=...)` with the existing or new values to "
        f"overwrite (call `get_setup_status` first if you need the "
        f"existing field values).\n"
        f"  - Terminal: `redshift-comment-mcp set-password --profile "
        f"{profile_name} --dialog` (OS dialog) or `--stdin` (headless "
        f"pipe). DO NOT use the no-flag interactive `set-password` form "
        f"from an agent — getpass reads from /dev/tty, not stdin."
    )


def main():
    """主程式進入點。

    兩種模式：
    1. ``redshift-comment-mcp <subcommand>`` → 委派給 ``setup_cli.main``
       （setup / set-password / test-connection / list-profiles /
       delete-profile / set-fields）
    2. ``redshift-comment-mcp [args]`` → 啟動 MCP 伺服器。Profile 解析
       優先級：``--profile`` flag > ``REDSHIFT_COMMENT_PROFILE`` env var
       > ``~/.config/redshift-comment-mcp/active-profile`` 檔 > ``"default"``。
       若使用者提供完整 inline 連線參數 (``--host`` / ``--user`` /
       ``--dbname`` 皆有)，則略過 profile 走 v0.1 inline 模式。
    """
    # Subcommand routing: first positional arg is one of the setup subcommands.
    if len(sys.argv) >= 2 and sys.argv[1] in SETUP_SUBCOMMANDS:
        from . import setup_cli
        sys.exit(setup_cli.main(sys.argv[1:]))

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    parser = argparse.ArgumentParser(description="Redshift MCP Server")
    parser.add_argument(
        "--profile",
        help=(
            "Override the resolved profile name. "
            "Default resolution: REDSHIFT_COMMENT_PROFILE env var > "
            "active-profile file > 'default'."
        ),
    )
    parser.add_argument("--host", help="Redshift 主機位址 (legacy inline 模式)")
    parser.add_argument(
        "--port",
        type=_coerce_port,
        default=DEFAULT_PORT,
        help="Redshift 連接埠 (空字串 / 未替換的 userConfig 佔位符 → 預設 5439)",
    )
    parser.add_argument("--user", help="Redshift 使用者名稱 (legacy inline 模式)")
    parser.add_argument(
        "--password",
        required=False,
        help="Redshift 密碼 (legacy inline 模式；或 REDSHIFT_PASSWORD env var)",
    )
    parser.add_argument("--dbname", help="Redshift 資料庫名稱 (legacy inline 模式)")
    args = parser.parse_args()

    # Degraded-mode startup contract (since v0.7.0):
    #   The server boots and enters the MCP stdio loop EVEN if no profile is
    #   configured. Profile resolution is deferred to each MCP tool call via
    #   the lazy provider below. A tool whose call raises ConfigurationError
    #   returns a structured `not_configured` error to the agent instead of
    #   crashing the server. The new `setup_via_dialog` MCP tool lets an
    #   agent provision a profile in-band — fields via args, password via OS
    #   dialog server-side; the password never crosses the MCP wire.
    #
    #   Re-resolution happens per call (no cache), so newly-written profiles
    #   become live without restarting the MCP client.
    def lazy_config_provider():
        """Resolve connection params + build a RedshiftConnectionConfig.

        Called on every MCP tool invocation that needs a DB connection.
        Re-reads config.toml + keychain each time, so updates from
        `setup_via_dialog` / `setup` / `set-password` take effect immediately.
        """
        host, port, user, password, dbname = resolve_connection_params(args)
        return create_redshift_config(
            host=host, port=port, user=user, password=password, dbname=dbname,
        )

    logger.info("MCP 伺服器啟動中（degraded-mode 啟動 — profile 在第一次 tool 呼叫時 lazy resolve）")
    # Re-evaluated per get_setup_status call (not cached) so a REDSHIFT_PASSWORD
    # env change (or a newly written profile) is reflected, mirroring
    # lazy_config_provider's re-resolution. resolve_connection_decision is the
    # exact function lazy_config_provider's resolve_connection_params calls
    # internally — one decision, read by both, never two that could drift
    # apart (see W0-02).
    redshift_tools = RedshiftTools(
        lazy_config_provider,
        status_provider=lambda profile: resolve_connection_decision(args, profile),
    )
    mcp_server = redshift_tools.get_server()

    try:
        mcp_server.run()  # FastMCP defaults to STDIO transport
    except KeyboardInterrupt:
        logger.info("收到中止信號，正在關閉伺服器...")
    except Exception as e:
        logger.error(f"伺服器運行時發生錯誤: {e}", exc_info=True)
    finally:
        logger.info("MCP 伺服器已關閉。")


if __name__ == "__main__":
    main()
