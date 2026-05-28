"""Tests for ``setup_cli.main()`` argparse-routed subcommand entry points.

The skills (``/redshift-setup`` Step 3 / 5, ``/redshift-switch-profile``
Step 6) call these subcommands via ``uv run --project … redshift-comment-mcp
<subcommand>`` and branch on exit codes (0 / 1 / 2). This file pins down
those exit codes plus the stderr / stdout contracts the skills rely on.

Subcommands covered:
  - set-fields       (non-interactive, used by /redshift-setup Step 3)
  - test-connection  (used by /redshift-setup Step 5 + /redshift-switch-profile Step 6)
  - list-profiles    (used by /redshift-switch-profile Step 2)
  - delete-profile   (interactive confirm)
  - set-password     (interactive getpass)

The interactive ``setup`` subcommand isn't tested here — it's an
end-to-end Q&A flow that the skill replaces with chat-driven prompts.
"""
from __future__ import annotations

import sys
import types

import pytest

from redshift_comment_mcp import config, setup_cli


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


# ===== set-fields =====


def test_set_fields_writes_profile(tmp_xdg, fake_keyring):
    rc = setup_cli.main([
        "set-fields", "--profile", "default",
        "--host", "h.example.com", "--port", "5439",
        "--user", "alice", "--dbname", "analytics",
    ])
    assert rc == 0
    assert config.read_profile("default") == {
        "host": "h.example.com", "port": 5439,
        "user": "alice", "dbname": "analytics",
    }


def test_set_fields_default_port_when_omitted(tmp_xdg, fake_keyring):
    rc = setup_cli.main([
        "set-fields", "--profile", "default",
        "--host", "h", "--user", "u", "--dbname", "d",
    ])
    assert rc == 0
    assert config.read_profile("default")["port"] == 5439


def test_set_fields_overwrites_existing(tmp_xdg, fake_keyring):
    config.write_profile("default", host="old", port=5439, user="u", dbname="d")
    rc = setup_cli.main([
        "set-fields", "--profile", "default",
        "--host", "new.example.com", "--user", "u", "--dbname", "d",
    ])
    assert rc == 0
    assert config.read_profile("default")["host"] == "new.example.com"


def test_set_fields_missing_required_flag_exits(tmp_xdg, fake_keyring):
    """argparse exits with SystemExit(2) on missing required arg."""
    with pytest.raises(SystemExit):
        setup_cli.main([
            "set-fields", "--profile", "default",
            # --host missing
            "--user", "u", "--dbname", "d",
        ])


# ===== test-connection =====


def test_test_connection_profile_not_configured_returns_2(tmp_xdg, fake_keyring, capsys):
    rc = setup_cli.main(["test-connection", "--profile", "missing"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing" in err
    assert "not configured" in err


def test_test_connection_no_password_in_keychain_returns_2(tmp_xdg, fake_keyring, capsys):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    # No password in keychain
    rc = setup_cli.main(["test-connection", "--profile", "default"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "set-password" in err, (
        "Error message should hint at the set-password remediation"
    )


def test_test_connection_success_returns_0(tmp_xdg, fake_keyring, monkeypatch, capsys):
    """Mock redshift_connector to return a connected cursor; expect rc=0."""
    config.write_profile("default", host="h", port=5439, user="alice", dbname="analytics")
    config.set_password("default", "secret")

    class FakeCursor:
        def execute(self, *a, **kw):
            pass

        def fetchone(self):
            return ("analytics", "alice")

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    fake_module = types.SimpleNamespace(connect=lambda **kw: FakeConn())
    monkeypatch.setitem(sys.modules, "redshift_connector", fake_module)

    rc = setup_cli.main(["test-connection", "--profile", "default"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "✓ Connected" in out
    assert "database=analytics" in out
    assert "user=alice" in out


def test_test_connection_failure_returns_1(tmp_xdg, fake_keyring, monkeypatch, capsys):
    """When redshift_connector raises, expect rc=1 and stderr describing failure."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    config.set_password("default", "secret")

    def fake_connect(**kw):
        raise RuntimeError("network unreachable")

    fake_module = types.SimpleNamespace(connect=fake_connect)
    monkeypatch.setitem(sys.modules, "redshift_connector", fake_module)

    rc = setup_cli.main(["test-connection", "--profile", "default"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Connection failed" in err
    assert "network unreachable" in err


# ===== list-profiles =====


def test_list_profiles_empty_prints_helpful_hint(tmp_xdg, fake_keyring, capsys):
    rc = setup_cli.main(["list-profiles"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no profiles configured" in out
    assert "redshift-comment-mcp setup" in out


def test_list_profiles_shows_one_profile(tmp_xdg, fake_keyring, capsys):
    config.write_profile("default", host="h.example.com", port=5439, user="u", dbname="d")
    config.set_password("default", "secret")
    rc = setup_cli.main(["list-profiles"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "default" in out
    assert "u@h.example.com:5439/d" in out
    assert "✓" in out  # password OK marker


def test_list_profiles_marks_missing_password(tmp_xdg, fake_keyring, capsys):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    # No password
    rc = setup_cli.main(["list-profiles"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no password" in out


def test_list_profiles_sorted_order(tmp_xdg, fake_keyring, capsys):
    config.write_profile("zeta", host="h", port=5439, user="u", dbname="d")
    config.write_profile("alpha", host="h", port=5439, user="u", dbname="d")
    config.write_profile("middle", host="h", port=5439, user="u", dbname="d")
    rc = setup_cli.main(["list-profiles"])
    assert rc == 0
    out = capsys.readouterr().out
    # Names must appear in sorted order.
    assert out.find("alpha") < out.find("middle") < out.find("zeta")


# ===== delete-profile =====


def test_delete_profile_confirm_yes_deletes(tmp_xdg, fake_keyring, monkeypatch, capsys):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    config.set_password("default", "secret")
    monkeypatch.setattr("builtins.input", lambda _: "y")

    rc = setup_cli.main(["delete-profile", "--profile", "default"])
    assert rc == 0
    assert config.read_profile("default") is None
    assert config.get_password("default") is None
    assert "Deleted profile" in capsys.readouterr().out


def test_delete_profile_confirm_no_aborts(tmp_xdg, fake_keyring, monkeypatch, capsys):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("builtins.input", lambda _: "n")

    rc = setup_cli.main(["delete-profile", "--profile", "default"])
    assert rc == 0
    # Profile still there.
    assert config.read_profile("default") is not None
    assert "Aborted" in capsys.readouterr().out


def test_delete_profile_missing_returns_1(tmp_xdg, fake_keyring, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "y")

    rc = setup_cli.main(["delete-profile", "--profile", "nope"])
    assert rc == 1
    assert "did not exist" in capsys.readouterr().err


# ===== set-password =====


def test_set_password_profile_not_configured_returns_2(tmp_xdg, fake_keyring, capsys):
    rc = setup_cli.main(["set-password", "--profile", "missing"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing" in err
    assert "setup" in err


def test_set_password_happy_path_updates_keychain(tmp_xdg, fake_keyring, monkeypatch, capsys):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("getpass.getpass", lambda *_: "newsecret")

    rc = setup_cli.main(["set-password", "--profile", "default"])
    assert rc == 0
    assert config.get_password("default") == "newsecret"
    assert "Updated password" in capsys.readouterr().out


def test_set_password_empty_returns_2(tmp_xdg, fake_keyring, monkeypatch, capsys):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("getpass.getpass", lambda *_: "")

    rc = setup_cli.main(["set-password", "--profile", "default"])
    assert rc == 2
    assert "cannot be empty" in capsys.readouterr().err


# ===== set-password --stdin =====


def test_set_password_stdin_reads_one_line_updates_keychain(
    tmp_xdg, fake_keyring, monkeypatch, capsys
):
    """Caller pipes password via stdin → keychain. No interactive prompt."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("piped-secret\n"))

    rc = setup_cli.main(["set-password", "--profile", "default", "--stdin"])
    assert rc == 0
    assert config.get_password("default") == "piped-secret"
    assert "Updated password" in capsys.readouterr().out


def test_set_password_stdin_empty_returns_2(tmp_xdg, fake_keyring, monkeypatch, capsys):
    """Empty stdin must error so an agent doesn't silently store an empty password."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    rc = setup_cli.main(["set-password", "--profile", "default", "--stdin"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--stdin" in err and "empty" in err


# ===== set-password --dialog =====


def _mock_subprocess_run(returncode: int, stdout: str = "", stderr: str = "", raise_=None):
    """Build a subprocess.run replacement that returns a fake CompletedProcess
    (or raises) so dialog paths can be exercised without launching osascript /
    zenity in tests. ``stderr`` is needed to drive macOS permission-denied
    detection (which reads osascript's stderr for the -1743 code)."""
    def _run(*_args, **_kwargs):
        if raise_ is not None:
            raise raise_
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


def test_set_password_dialog_macos_happy_path(tmp_xdg, fake_keyring, monkeypatch, capsys):
    """macOS osascript dialog returns the typed password on stdout (captured
    by subprocess.run); CLI writes it to keychain without echoing."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(returncode=0, stdout="dialog-secret\n"),
    )

    rc = setup_cli.main(["set-password", "--profile", "default", "--dialog"])
    assert rc == 0
    assert config.get_password("default") == "dialog-secret"
    out = capsys.readouterr().out
    assert "Updated password" in out
    assert "dialog-secret" not in out  # password must never reach stdout


def test_set_password_dialog_linux_zenity_happy_path(
    tmp_xdg, fake_keyring, monkeypatch, capsys
):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(returncode=0, stdout="zenity-secret\n"),
    )

    rc = setup_cli.main(["set-password", "--profile", "default", "--dialog"])
    assert rc == 0
    assert config.get_password("default") == "zenity-secret"


def test_set_password_dialog_cancelled_returns_2(
    tmp_xdg, fake_keyring, monkeypatch, capsys
):
    """User clicks Cancel → dialog returncode != 0 → CLI exits 2, no write."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(returncode=1, stdout=""),
    )

    rc = setup_cli.main(["set-password", "--profile", "default", "--dialog"])
    assert rc == 2
    assert config.get_password("default") is None
    assert "cancelled" in capsys.readouterr().err.lower()


def test_set_password_dialog_tool_unavailable_returns_2(
    tmp_xdg, fake_keyring, monkeypatch, capsys
):
    """osascript / zenity not installed → CLI exits 2 with a clear fallback hint."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(returncode=0, raise_=FileNotFoundError("osascript")),
    )

    rc = setup_cli.main(["set-password", "--profile", "default", "--dialog"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--stdin" in err  # fallback hint
    assert "osascript" in err or "zenity" in err


def test_set_password_dialog_unsupported_platform_returns_2(
    tmp_xdg, fake_keyring, monkeypatch, capsys
):
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("sys.platform", "win32")

    rc = setup_cli.main(["set-password", "--profile", "default", "--dialog"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "win32" in err
    assert "--stdin" in err  # fallback hint


def test_set_password_stdin_and_dialog_are_mutually_exclusive(
    tmp_xdg, fake_keyring, capsys
):
    """argparse mutually_exclusive_group: --stdin and --dialog can't co-occur."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    with pytest.raises(SystemExit) as excinfo:
        setup_cli.main(["set-password", "--profile", "default", "--stdin", "--dialog"])
    assert excinfo.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


# ===== macOS Apple-Events permission denial detection =====
#
# osascript returns exit code != 0 for both user-cancel AND
# Automation-permission-denied (-1743). Pre-v0.7.0-polish these were
# conflated as "cancelled". The helper now reads stderr to distinguish them
# so the agent can give the user actionable advice (System Settings →
# Privacy & Security → Automation) instead of just "you cancelled".


@pytest.mark.parametrize("stderr_text", [
    "execution error: System Events got an error: ... (-1743)",
    "Not authorized to send Apple events to System Events. (-1743)",
    "execution error: redshift-comment-mcp is not allowed to send Apple events.",
])
def test_collect_password_via_dialog_detects_permission_denied(stderr_text, monkeypatch):
    """The helper must classify osascript's -1743 / 'not allowed to send
    Apple events' stderr as `permission_denied`, NOT `cancelled`. Both
    numeric code and English text variants exist depending on macOS
    version; parametrize over the realistic stderr shapes."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(returncode=1, stdout="", stderr=stderr_text),
    )

    pw, reason = setup_cli._collect_password_via_dialog("default")

    assert pw is None
    assert reason == "permission_denied", (
        f"stderr={stderr_text!r} should have been classified as "
        f"permission_denied (got {reason!r})"
    )


def test_collect_password_via_dialog_distinguishes_cancel_from_permission(monkeypatch):
    """Plain user-cancel still returns `cancelled` — the stderr lacks the
    -1743 / Apple-events tell so the permission heuristic doesn't fire."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(
            returncode=1, stdout="",
            stderr="execution error: User canceled. (-128)",
        ),
    )

    pw, reason = setup_cli._collect_password_via_dialog("default")

    assert pw is None
    assert reason == "cancelled"


def test_set_password_dialog_permission_denied_returns_2_with_tcc_hint(
    tmp_xdg, fake_keyring, monkeypatch, capsys
):
    """CLI level: `set-password --dialog` surfaces the permission_denied
    case with an actionable hint (System Settings + tccutil reset) so a
    terminal user can fix the underlying permission without guessing."""
    config.write_profile("default", host="h", port=5439, user="u", dbname="d")
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "redshift_comment_mcp.setup_cli.subprocess.run",
        _mock_subprocess_run(
            returncode=1, stdout="",
            stderr="execution error: ... (-1743)",
        ),
    )

    rc = setup_cli.main(["set-password", "--profile", "default", "--dialog"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "blocked" in err.lower() or "permission" in err.lower(), (
        f"err should call out the permission block; got: {err!r}"
    )
    # Concrete next-step hints
    assert "System Settings" in err or "Privacy" in err
    assert "tccutil reset AppleEvents" in err or "Automation" in err
    # Don't conflate with cancellation
    assert "cancelled" not in err.lower()
