import os
import sys
import argparse
import logging
from typing import Optional
from .config import ConfigurationError
from .connection import create_redshift_config
from .redshift_tools import RedshiftTools, ConnectionDecision, resolve_profile_decision

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5439


def _coerce_port(raw) -> int:
    """argparse ``type=`` for ``--port`` that tolerates optional-userConfig debris.

    A Claude Code plugin ``userConfig`` is optional: a blank port field arrives
    as ``""`` and an unset field may arrive as the unsubstituted literal
    ``${user_config.port}``. Plain ``type=int`` would make argparse abort with
    ``invalid int value`` and the server would never boot. Map any
    empty / non-numeric value to ``DEFAULT_PORT`` instead of raising; pass real
    integer strings (and already-int values) through unchanged.
    """
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_PORT


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
      is ignored throughout this mode.
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

        for candidate_name in candidate_names:
            try:
                candidate = cfg.read_profile(candidate_name)
                if not candidate:
                    continue
                candidate_port = _coerce_port(candidate.get("port"))
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
                return ConnectionDecision(
                    mechanism="borrowed", host=host, port=port, user=user, dbname=dbname,
                    has_fields=True, has_password=True, password=borrowed_password,
                    profile_name=candidate_name,
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
                    return f"{name} ({target_host}:{target_port})"
                except Exception as e:  # noqa: BLE001 — see above
                    logger.debug(
                        "borrow-refusal message: could not describe profile "
                        "%r (%s)", name, type(e).__name__,
                    )
                    return f"{name} (unreadable)"

            existing_desc = ", ".join(_target_desc(name) for name in existing)
        else:
            existing_desc = "none configured"
        raise ConfigurationError(
            f"Inline mode requires a password for "
            f"host={decision.host!r} port={decision.port!r} "
            f"user={decision.user!r} dbname={decision.dbname!r}, and no stored "
            f"profile's host/port/user/dbname all match it to borrow one from.\n"
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
