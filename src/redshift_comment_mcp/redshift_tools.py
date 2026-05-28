import functools
import logging
import re
import awswrangler as wr
from fastmcp import FastMCP
from typing import Any, Callable, Dict, Optional
from .config import ConfigurationError
from .connection import RedshiftConnectionConfig

logger = logging.getLogger(__name__)


def _not_configured_error(exc: ConfigurationError) -> Dict[str, Any]:
    """Structured response surfaced to the agent when a DB tool is invoked
    on a server without a configured profile (degraded-mode contract).

    Replaces the pre-v0.7.0 behavior of letting the ConfigurationError
    propagate up out of ``main()`` and crash the server before MCP wire even
    came up. Now the server boots regardless; each tool catches the error
    via ``@_guarded`` and returns this dict so the agent sees the setup
    pipeline in its tool-call result, not in a hard-to-reach client log.

    Schema is aligned with setup_via_dialog's error responses:
    ``exception_class`` carries the type name for agents that want to
    branch on it; ``message`` carries the raw exception text (this is
    safe here because the ConfigurationError text is server-controlled
    in resolve_connection_params — no third-party data flows into it).
    """
    return {
        "error": "not_configured",
        "exception_class": type(exc).__name__,
        "message": str(exc),
        "next_step": (
            "1) Call `get_setup_status` to see the current state (whether "
            "config.toml fields exist + whether a keychain password exists). "
            "2) Call `setup_via_dialog(host=..., user=..., dbname=...)` to "
            "bootstrap or update a profile — password collected via OS-"
            "native dialog server-side, never crosses MCP wire / chat / "
            "tool args. Alternatively, have the user run "
            "`uvx redshift-comment-mcp setup` in a terminal. After setup, "
            "retry the original tool — no MCP client restart needed "
            "(lazy resolve picks up the new profile on next call)."
        ),
    }


def _guarded(tool_fn):
    """Decorator: convert ConfigurationError into a structured tool response.

    Stack with ``@self.mcp.tool`` immediately above:

        @self.mcp.tool
        @_guarded
        def list_schemas(...): ...

    Other exceptions propagate to FastMCP for normal error handling — only
    "no profile yet" gets the in-band degraded-mode response.
    """
    @functools.wraps(tool_fn)
    def wrapper(*args, **kwargs):
        try:
            return tool_fn(*args, **kwargs)
        except ConfigurationError as e:
            return _not_configured_error(e)
    return wrapper


# ===== setup_via_dialog response builders =====
#
# Each function builds a structured response for one of the dialog-collection
# outcomes (cancelled / permission_denied / dialog_unavailable / platform_
# unsupported / empty_password). Extracted to module level so the
# setup_via_dialog tool body stays focused on orchestration; each builder
# is self-contained, has only ``profile`` + ``platform`` inputs, and is
# unit-testable independently of the larger tool flow.


def _build_dialog_cancelled_response(profile: str, **_kw) -> Dict[str, Any]:
    return {
        "status": "dialog_cancelled",
        "profile": profile,
        "message": (
            f"Password dialog was cancelled. Profile '{profile}' is "
            f"INCOMPLETE — DB tools will continue to return not_configured "
            f"until a password is set. Ask the user explicitly whether they "
            f"intended to cancel (and abandon Redshift setup) or hit Cancel "
            f"by accident; default to retrying setup_via_dialog if no clear "
            f"cancellation signal was given."
        ),
    }


def _build_permission_denied_response(profile: str, platform: str, **_kw) -> Dict[str, Any]:
    return {
        "status": "permission_denied",
        "profile": profile,
        "platform": platform,
        "message": (
            f"macOS blocked the password dialog. The app running the MCP "
            f"server (Claude Desktop / Cursor / etc.) doesn't have "
            f"`Automation > System Events` permission, so the dialog never "
            f"appeared — this is NOT a user cancellation. Profile "
            f"'{profile}' fields are saved but password is not set. Tell "
            f"the user: open System Settings → Privacy & Security → "
            f"Automation → find the app entry → enable `System Events`, "
            f"then call setup_via_dialog again. If no permission entry "
            f"exists yet, run `tccutil reset AppleEvents` from a terminal "
            f"to force a fresh permission prompt on next attempt. Fallback: "
            f"have the user pipe the password via "
            f"`redshift-comment-mcp set-password --profile {profile} "
            f"--stdin` from a terminal."
        ),
    }


def _build_dialog_unavailable_response(profile: str, platform: str, **_kw) -> Dict[str, Any]:
    return {
        "status": "dialog_unavailable",
        "profile": profile,
        "platform": platform,
        "message": (
            f"No supported dialog tool found on this host (macOS needs "
            f"`osascript`, Linux needs `zenity`). Profile fields for "
            f"'{profile}' are saved but no password is set. Tell the user "
            f"the dialog isn't available and instruct them to run this in "
            f"a terminal themselves: `redshift-comment-mcp set-password "
            f"--profile {profile} --stdin` (piping the password). DO NOT "
            f"pass the password as a tool argument or shell argument — "
            f"that leaks it to chat / process args / shell history."
        ),
    }


def _build_platform_unsupported_response(profile: str, platform: str, **_kw) -> Dict[str, Any]:
    return {
        "status": "platform_unsupported",
        "profile": profile,
        "platform": platform,
        "message": (
            f"Password dialog is not supported on platform '{platform}' "
            f"(only macOS and Linux are wired). Profile fields for "
            f"'{profile}' are saved but no password is set. Tell the user "
            f"to set the password from their terminal: "
            f"`redshift-comment-mcp set-password --profile {profile} "
            f"--stdin` (pipe the password via stdin)."
        ),
    }


def _build_empty_password_response(profile: str, **_kw) -> Dict[str, Any]:
    return {
        "status": "empty_password",
        "profile": profile,
        "message": (
            f"Password dialog returned an empty string — likely the user "
            f"clicked OK without typing, or the dialog failed to render. "
            f"Profile '{profile}' is INCOMPLETE. Ask the user to retry "
            f"and call setup_via_dialog again with the same arguments."
        ),
    }


# Dispatch table for setup_via_dialog's 4 ``reason``-based failure paths
# returned by ``_collect_password_via_dialog``. The 5th case (``ok`` but
# empty password) is checked separately because it isn't keyed by reason.
_DIALOG_FAILURE_BUILDERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "cancelled": _build_dialog_cancelled_response,
    "permission_denied": _build_permission_denied_response,
    "unavailable": _build_dialog_unavailable_response,
    "unsupported": _build_platform_unsupported_response,
}

# 分頁設定
DEFAULT_MAX_ITEMS = 50  # 預設最大回傳筆數（超過時自動截斷）

# Comment 大小防護
# 經 production cluster 實測（2026-05-08, n=8534）：column comment p100=471，
# table comment p90=919 / p95=1517 / p100=3680。1000 字元截斷 9% 的 table
# 長尾，column comment 完全不受影響。單筆 getter（get_table_comment 等）不
# 套用，使用者要全文時走那條路。
MAX_COMMENT_LEN = 1000

# scale_hint 觸發門檻：list_tables 回應 total_count 超過此值時附上分頁成本提示
SCALE_HINT_THRESHOLD = 100


# ===== SQL 安全驗證 =====

# str.strip() 預設只去 ASCII whitespace；MCP 傳輸／編輯器複製常會在 SQL 前面塞
# 不可見字元（BOM / ZWSP / NBSP 等），導致 startswith('SELECT'|'WITH') 誤判。
# 把這些一併剝掉。
_TRIM_CHARS = (
    " \t\n\r\f\v"
    "﻿"  # BOM
    "​"  # ZERO WIDTH SPACE
    "‌"  # ZERO WIDTH NON-JOINER
    "‍"  # ZERO WIDTH JOINER
    "⁠"  # WORD JOINER
    " "  # NO-BREAK SPACE
)

# 禁止的 mutating / privilege / IO 命令。注意這些是「禁止關鍵字」，不是
# 「禁止語句」——任何位置出現皆拒，因此包含 multi-statement piggyback。
_FORBIDDEN_KEYWORDS = (
    'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE',
    'MERGE', 'GRANT', 'REVOKE', 'COPY', 'UNLOAD',
)
_FORBIDDEN_RE = re.compile(r'\b(' + '|'.join(_FORBIDDEN_KEYWORDS) + r')\b')


def _strip_strings_and_comments(sql: str) -> str:
    """
    把 SQL 裡的字串字面量、quoted identifier、行註解、塊註解、dollar-quote
    全部置換成等長空白，讓後續的 keyword 掃描只看到「真實的 SQL token」。
    保持長度一致是為了之後若想回報行/列號不會偏移。

    未終結的字串或註解視為語法錯誤，直接 raise — 否則攻擊者可用 unterminated
    literal 把後續惡意關鍵字偽裝成「字串內文」。
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]

        # 行註解 -- ... \n
        if c == '-' and i + 1 < n and sql[i + 1] == '-':
            while i < n and sql[i] != '\n':
                out.append(' ')
                i += 1
            continue

        # 塊註解 /* ... */（Redshift 不支援巢狀，不處理）
        if c == '/' and i + 1 < n and sql[i + 1] == '*':
            out.append('  ')
            i += 2
            while i + 1 < n and not (sql[i] == '*' and sql[i + 1] == '/'):
                out.append(' ')
                i += 1
            if i + 1 >= n:
                raise ValueError("Unterminated block comment in SQL.")
            out.append('  ')
            i += 2
            continue

        # 單引號字串 '...'，'' 為跳脫
        if c == "'":
            out.append(' ')
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append('  ')
                        i += 2
                        continue
                    out.append(' ')
                    i += 1
                    break
                out.append(' ')
                i += 1
            else:
                raise ValueError("Unterminated string literal in SQL.")
            continue

        # 雙引號 quoted identifier "..."，"" 為跳脫
        if c == '"':
            out.append(' ')
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        out.append('  ')
                        i += 2
                        continue
                    out.append(' ')
                    i += 1
                    break
                out.append(' ')
                i += 1
            else:
                raise ValueError("Unterminated quoted identifier in SQL.")
            continue

        # Dollar-quoted $$...$$（PostgreSQL 擴充，Redshift SP 內可見）
        if c == '$' and i + 1 < n and sql[i + 1] == '$':
            out.append('  ')
            i += 2
            while i + 1 < n and not (sql[i] == '$' and sql[i + 1] == '$'):
                out.append(' ')
                i += 1
            if i + 1 >= n:
                raise ValueError("Unterminated dollar-quoted string in SQL.")
            out.append('  ')
            i += 2
            continue

        out.append(c)
        i += 1

    return ''.join(out)


def validate_read_only_sql(sql_statement: str) -> None:
    """
    驗證 sql_statement 為 read-only（SELECT / WITH 開頭，且不含禁用關鍵字）。
    不通過則 raise ValueError。

    防護重點：
    1. 剝除 BOM / ZWSP / NBSP 等不可見字元，避免 startswith 誤判
    2. 字串字面量、quoted identifier、行/塊/$$ 註解內的內容不參與關鍵字判定
       （消除 `WHERE col = 'INSERT'` / `-- DROP TABLE old` 之類誤殺）
    3. 禁用關鍵字以 `\\b` word boundary 比對，且套用在「sanitized 後」的 SQL 上
       （未終結的字串/註解會被 reject，不會被當成擋牆繞過）
    """
    raw = sql_statement.strip(_TRIM_CHARS) if sql_statement else ""
    if not raw:
        raise ValueError("Empty query.")

    head = raw.upper()
    if not (head.startswith('SELECT') or head.startswith('WITH')):
        raise ValueError("Only SELECT and WITH queries are allowed.")

    sanitized = _strip_strings_and_comments(raw).upper()

    m = _FORBIDDEN_RE.search(sanitized)
    if m:
        raise ValueError(f"{m.group(1)} statements are not allowed.")


def paginate_results(items: list, limit: Optional[int], offset: int, default_max: int) -> Dict[str, Any]:
    """
    處理分頁邏輯。
    - 如果有指定 limit，使用指定的 limit
    - 如果沒有指定 limit 且資料超過 default_max，自動截斷並提示
    """
    total_count = len(items)

    # 套用 offset
    if offset > 0:
        items = items[offset:]

    # 決定實際的 limit
    if limit is not None:
        # 使用者指定了 limit
        actual_limit = limit
        truncated = len(items) > limit
        items = items[:limit]
        auto_truncated = False
    elif len(items) > default_max:
        # 超過預設最大值，自動截斷
        actual_limit = default_max
        truncated = True
        items = items[:default_max]
        auto_truncated = True
    else:
        # 資料量在範圍內，全部回傳
        actual_limit = None
        truncated = False
        auto_truncated = False

    return {
        "items": items,
        "total_count": total_count,
        "returned_count": len(items),
        "offset": offset,
        "limit": actual_limit,
        "has_more": truncated,
        "auto_truncated": auto_truncated
    }


def apply_comment_cap(items: list, key: str, max_len: int = MAX_COMMENT_LEN) -> int:
    """In-place truncate the comment field at ``key`` for each item in ``items``;
    returns the count of items that were truncated.

    Items whose comment is shorter than or equal to ``max_len`` are left
    untouched. Truncated comments get an ellipsis appended so the caller
    can detect truncation visually as well as via the returned count.
    """
    count = 0
    for item in items:
        original = item.get(key)
        if isinstance(original, str) and len(original) > max_len:
            item[key] = original[:max_len] + "…"
            count += 1
    return count


def build_scale_hint(total_count: int, page_size: int = DEFAULT_MAX_ITEMS) -> Optional[str]:
    """Return a one-line scale hint when total_count would force painful
    pagination, or None when the result is small enough to enumerate fully.

    The threshold (SCALE_HINT_THRESHOLD) is intentionally above one page
    so the hint only fires when full enumeration genuinely costs ≥3 round
    trips. Message includes the actual page count so the LLM can weigh
    cost objectively rather than relying on a magic threshold.
    """
    if total_count <= SCALE_HINT_THRESHOLD:
        return None
    pages = (total_count + page_size - 1) // page_size
    return (
        f"This schema has {total_count} tables. "
        f"Full enumeration would need {pages} paginated tool calls. "
        f"Consider search_tables(keywords) for goal-oriented queries."
    )


def calculate_hit_count(name: str, comment: str, keywords: list) -> int:
    """
    計算關鍵字在 name 和 comment 中的命中次數。
    每個關鍵字最多計為 1 次（不論出現幾次）。
    """
    hit_count = 0
    search_text = f"{name.lower()} {comment.lower()}"
    for kw in keywords:
        if kw.lower() in search_text:
            hit_count += 1
    return hit_count


# --- Redshift Tools Implementation ---
class RedshiftTools:
    """
    Provides a set of tools for interacting with Redshift databases to support guided data exploration.
    Uses a connect/disconnect pattern for each operation to ensure maximum robustness.
    """
    def __init__(self, config_provider: Callable[[], RedshiftConnectionConfig]):
        """Construct a tool provider with a *lazy* connection-config resolver.

        ``config_provider`` is called on every DB tool invocation (via the
        ``config`` property below). It re-reads config.toml + keychain each
        time, so a profile newly written by ``setup_via_dialog`` /
        ``setup`` CLI is picked up on the next tool call without restarting
        the MCP client. If the provider raises ``ConfigurationError``, the
        ``@_guarded`` decorator on each tool turns it into a structured
        ``{"error": "not_configured", ...}`` response — the server itself
        never crashes for missing-profile.
        """
        self._config_provider = config_provider
        self.mcp = FastMCP(
            name="Redshift Comment MCP",
            instructions="""
Redshift database exploration tools where COMMENTS are the source of
truth for schema / table / column meaning — names are unreliable and
may conflict with comments. Always retrieve comments before drafting
SQL; trust the comment over the name when they disagree.

PAGINATION: list_*, search_*, and get_all_column_comments cap at 50
items per response. Check `has_more`; if true, refetch with `offset`
until exhausted before drawing conclusions.

COMMENT TRUNCATION: Multi-item responses cap each comment at 1000
chars. Look for `comment_truncated_count` in the response; if present,
some comments were cut. Call get_table_comment / get_column_comment
on the specific item for full text. Single-item getters never truncate.

SCALE GUIDANCE: list_tables emits `scale_hint` when total_count > 100.
For schemas at that size, paginating list_tables to completion is
expensive — prefer search_tables(keywords) for goal-oriented queries.

OPTIMIZATION: list_* tools accept include_comments / include_parent_comments
flags to fold get_*_comment calls into the same response.

SEARCH KEYWORDS: search_schemas / search_tables / search_columns take
space-separated keywords (OR logic). Pick keywords in the user's
conversation language — comments usually match.

SEARCH SCOPE:
- search_tables(keywords, schema_name=None) — pass schema_name for
  one schema (faster, narrower); omit it for cluster-wide search.
- search_columns(keywords, schema_name, table_name=None) — pass
  table_name for one-table drill-down; omit it for schema-wide
  cross-table search (returns table_name on each row, the natural
  primitive for FK / JOIN-key reconnaissance).

For ad-hoc exploration, prefer list_* / search_* tools over execute_sql
against information_schema — they include comments directly.

EXECUTE_SQL TRANSPARENCY: When you call execute_sql, the response
includes `_executed_sql` (the SQL that ran) and `_user_facing_message`
(a display directive). You MUST surface `_executed_sql` verbatim to
the user — in a code block, before or alongside the result. Do not
paraphrase, summarize, or hide the query. Users need direct visibility
into what runs against their database. The metadata tools (list_* /
search_* / get_*) use fixed catalog templates and do not carry these
fields; their semantic API is the contract.

SETUP RECOVERY (degraded-mode contract, since v0.7.0): The server can
boot without a configured profile. Two entry points:

  - PROACTIVE: call `get_setup_status` at session start to check whether
    a profile is configured. Safe to call any time, returns
    non-secrets only. If `configured=false`, follow `next_step`.
  - REACTIVE: any DB tool returns `{"error": "not_configured", ...}` —
    read the `next_step` field and follow it.

Either way, the bootstrap flow is:

  1. Ask the user for host / port / user / dbname conversationally
     (these are NOT secrets; OK to discuss in chat).
  2. Call `setup_via_dialog` with those args. It writes config.toml
     fields, launches an OS-native password dialog server-side
     (macOS osascript / Linux zenity), and **tests the connection
     against Redshift** before declaring success. The password value
     never crosses the MCP wire.
  3. Interpret the response status:
     - `configured` (with `tested: true`) — retry the original DB
       tool, lazy resolution picks up the new profile without restart.
     - `configured_but_connection_failed` — fields/password were
       saved but Redshift connect failed. Read `connection_error`
       (likely host typo / VPN not connected / wrong password /
       paused cluster), ask the user to verify, then call
       setup_via_dialog again with corrections (overwrites).
     - `dialog_cancelled` / `empty_password` — profile incomplete;
       ask the user whether they meant to cancel; usually retry.
     - `permission_denied` (macOS only) — Apple Events blocked. The
       dialog never appeared; the MCP-client app lacks Automation >
       System Events permission. Do NOT retry blindly — tell the user
       to enable it (System Settings → Privacy & Security → Automation)
       OR fall back to `set-password --stdin` from a terminal.
     - `dialog_unavailable` / `platform_unsupported` (no GUI tool) —
       the dialog path is unusable on this host; tell the user to
       run `redshift-comment-mcp set-password --profile X --stdin`
       from a terminal. DO NOT pass the password as a tool argument.

Never invent host/user/dbname values. Never pass the password as a
tool argument or shell argument — the system dialog or stdin pipe are
the only chat-leak-free paths.
"""
        )
        self._setup_tools()

    @property
    def config(self) -> RedshiftConnectionConfig:
        """Lazy-resolved current connection config.

        Each access invokes ``self._config_provider()``, which re-runs
        ``resolve_connection_params`` against current CLI args + on-disk
        state (config.toml + active-profile pointer file + keychain).
        Raises ``ConfigurationError`` when no profile is configured —
        caught by ``@_guarded`` on each tool so the server returns a
        structured response instead of crashing.
        """
        return self._config_provider()

    def _setup_tools(self):
        """設定所有 MCP 工具"""

        # ========== 列表工具 ==========

        @self.mcp.tool
        @_guarded
        def list_schemas(limit: Optional[int] = None, offset: int = 0, include_comments: bool = True) -> Dict[str, Any]:
            """List schema names. include_comments defaults to True (cheap — schema count is small)."""
            if include_comments:
                sql = """
                SELECT n.nspname AS schema_name, d.description AS schema_comment
                FROM pg_namespace n
                LEFT JOIN pg_description d ON n.oid = d.objoid
                WHERE n.nspowner > 1 AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                ORDER BY n.nspname;
                """
                with self.config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql, con=conn)
                    schemas = [{
                        "name": r['schema_name'],
                        "comment": r['schema_comment'] if r['schema_comment'] else "(No comment available)"
                    } for r in df.to_dict(orient='records')]
            else:
                sql = """
                SELECT n.nspname AS schema_name
                FROM pg_namespace n
                WHERE n.nspowner > 1 AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                ORDER BY n.nspname;
                """
                with self.config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql, con=conn)
                    schemas = df['schema_name'].tolist()

            # 分頁處理
            page = paginate_results(schemas, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "schemas": page["items"],
                "warning": "Schema names may be misleading. Use get_schema_comment for each schema before selection."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        @self.mcp.tool
        @_guarded
        def list_tables(schema_name: str, limit: Optional[int] = None, offset: int = 0, include_comments: bool = False, include_parent_comments: bool = True) -> Dict[str, Any]:
            """List tables in a schema. Pass include_comments=True to include table comments inline; include_parent_comments (default True) also returns the parent schema's comment."""
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            # 取得 schema comment (only if include_parent_comments=True)
            schema_comment = None
            if include_parent_comments:
                schema_sql = """
                SELECT d.description AS schema_comment
                FROM pg_namespace n
                LEFT JOIN pg_description d ON n.oid = d.objoid
                WHERE n.nspname = %s;
                """

            with self.config.get_connection() as conn:
                # 取得 schema comment
                if include_parent_comments:
                    schema_df = wr.redshift.read_sql_query(schema_sql, con=conn, params=[schema_name])
                    schema_comment = "(No comment available)"
                    if not schema_df.empty and schema_df['schema_comment'].iloc[0]:
                        schema_comment = schema_df['schema_comment'].iloc[0]

                # 取得 tables
                if include_comments:
                    tables_sql = """
                    SELECT
                        t.table_name,
                        t.table_type,
                        d.description AS table_comment
                    FROM information_schema.tables t
                    LEFT JOIN pg_class c ON c.relname = t.table_name
                    LEFT JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
                    LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
                    WHERE t.table_schema = %s
                    ORDER BY t.table_name;
                    """
                    df = wr.redshift.read_sql_query(tables_sql, con=conn, params=[schema_name])
                    records = df.to_dict(orient='records')
                    tables = [{
                        "name": r['table_name'],
                        "type": r['table_type'],
                        "comment": r['table_comment'] if r['table_comment'] else "(No comment available)"
                    } for r in records]
                else:
                    tables_sql = """
                    SELECT t.table_name, t.table_type
                    FROM information_schema.tables t
                    WHERE t.table_schema = %s
                    ORDER BY t.table_name;
                    """
                    df = wr.redshift.read_sql_query(tables_sql, con=conn, params=[schema_name])
                    records = df.to_dict(orient='records')
                    tables = [{"name": r['table_name'], "type": r['table_type']} for r in records]

            # 分頁處理
            page = paginate_results(tables, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（多筆回應防護；只對實際回傳的項目套用）
            truncated_count = 0
            if include_comments:
                truncated_count = apply_comment_cap(page["items"], "comment")

            result = {
                "schema_name": schema_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "tables": page["items"],
                "warning": "Table names may be misleading. Use get_table_comment for each table before selection."
            }

            if include_parent_comments:
                result["schema_comment"] = schema_comment

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} table comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_table_comment(schema, table) for full text."
                )

            scale_hint = build_scale_hint(page["total_count"])
            if scale_hint:
                result["scale_hint"] = scale_hint

            return result

        @self.mcp.tool
        @_guarded
        def list_columns(schema_name: str, table_name: str, limit: Optional[int] = None, offset: int = 0, include_comments: bool = False, include_parent_comments: bool = True) -> Dict[str, Any]:
            """List columns (name, type, nullable) in a table. Pass include_comments=True to include column comments inline; include_parent_comments (default True) also returns the parent table's comment."""
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            # 取得 table comment (only if include_parent_comments=True)
            table_comment = None
            if include_parent_comments:
                table_sql = """
                SELECT d.description AS table_comment
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
                WHERE n.nspname = %s AND c.relname = %s;
                """

            with self.config.get_connection() as conn:
                # 取得 table comment
                if include_parent_comments:
                    table_df = wr.redshift.read_sql_query(table_sql, con=conn, params=[schema_name, table_name])
                    table_comment = "(No comment available)"
                    if not table_df.empty and table_df['table_comment'].iloc[0]:
                        table_comment = table_df['table_comment'].iloc[0]

                # 取得 columns
                if include_comments:
                    columns_sql = """
                    SELECT
                        c.column_name,
                        c.data_type,
                        c.is_nullable,
                        d.description AS column_comment
                    FROM information_schema.columns c
                    LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
                    LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
                    LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
                    WHERE c.table_schema = %s AND c.table_name = %s
                    ORDER BY c.ordinal_position;
                    """
                    df = wr.redshift.read_sql_query(columns_sql, con=conn, params=[schema_name, table_name])
                    records = df.to_dict(orient='records')
                    columns = [{
                        "name": r['column_name'],
                        "type": r['data_type'],
                        "nullable": r['is_nullable'],
                        "comment": r['column_comment'] if r['column_comment'] else "(No comment available)"
                    } for r in records]
                else:
                    columns_sql = """
                    SELECT c.column_name, c.data_type, c.is_nullable
                    FROM information_schema.columns c
                    WHERE c.table_schema = %s AND c.table_name = %s
                    ORDER BY c.ordinal_position;
                    """
                    df = wr.redshift.read_sql_query(columns_sql, con=conn, params=[schema_name, table_name])
                    records = df.to_dict(orient='records')
                    columns = [{"name": r['column_name'], "type": r['data_type'], "nullable": r['is_nullable']} for r in records]

            # 分頁處理
            page = paginate_results(columns, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（多筆回應防護；只對實際回傳的項目套用）
            truncated_count = 0
            if include_comments:
                truncated_count = apply_comment_cap(page["items"], "comment")

            result = {
                "schema_name": schema_name,
                "table_name": table_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"],
                "warning": "Column names may be misleading. Use get_all_column_comments before writing SQL."
            }

            if include_parent_comments:
                result["table_comment"] = table_comment

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} column comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_column_comment(schema, table, col) for full text."
                )

            return result

        # ========== 搜尋工具 ==========

        @self.mcp.tool
        @_guarded
        def search_schemas(keywords: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Search schemas by keywords (space-separated, OR logic) over schema name and comment."""
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            base_sql = """
            SELECT
                n.nspname AS schema_name,
                COALESCE(d.description, '') AS schema_comment
            FROM pg_namespace n
            LEFT JOIN pg_description d ON n.oid = d.objoid
            WHERE n.nspowner > 1
              AND n.nspname NOT LIKE 'pg_%%'
              AND n.nspname <> 'information_schema'
            """

            # 加入關鍵字搜尋條件（OR 邏輯）
            params = []
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(n.nspname ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            base_sql += " ORDER BY n.nspname;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                schemas = []
                for r in records:
                    name = r['schema_name']
                    comment = r['schema_comment'] if r['schema_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    schemas.append({
                        "name": name,
                        "comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, name ASC 排序
            schemas.sort(key=lambda x: (-x["hit_count"], x["name"]))

            # 分頁處理
            page = paginate_results(schemas, limit, offset, DEFAULT_MAX_ITEMS)

            result = {
                "keywords": keyword_list,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "schemas": page["items"],
                "warning": "Schema names may be misleading. Use get_schema_comment to verify the schema's purpose."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            return result

        @self.mcp.tool
        @_guarded
        def search_tables(keywords: str, schema_name: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Search tables by keywords (space-separated, OR logic) over table name and comment.

            Pass schema_name to scope to one schema (faster, narrower). Omit it to
            search across all user schemas in the cluster (broader, slightly slower).
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # schema_name 是可選的，但若提供必須是合法 identifier
            if schema_name is not None and not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            base_sql = """
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                CASE c.relkind WHEN 'r' THEN 'BASE TABLE' WHEN 'v' THEN 'VIEW' END AS table_type,
                COALESCE(d.description, '') AS table_comment
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE c.relkind IN ('r', 'v')
              AND n.nspowner > 1
              AND n.nspname NOT LIKE 'pg_%%'
              AND n.nspname <> 'information_schema'
            """

            params: list = []
            if schema_name is not None:
                base_sql += " AND n.nspname = %s"
                params.append(schema_name)

            # 加入關鍵字搜尋條件（OR 邏輯）
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(c.relname ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            base_sql += " ORDER BY n.nspname, c.relname;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                tables = []
                for r in records:
                    name = r['table_name']
                    comment = r['table_comment'] if r['table_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    tables.append({
                        "schema_name": r['schema_name'],
                        "table_name": name,
                        "table_type": r['table_type'],
                        "table_comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, table_name ASC 排序
            tables.sort(key=lambda x: (-x["hit_count"], x["table_name"]))

            # 分頁處理
            page = paginate_results(tables, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（search 永遠帶 comment，無 include_comments flag）
            truncated_count = apply_comment_cap(page["items"], "table_comment")

            result = {
                "keywords": keyword_list,
                "schema_filter": schema_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "tables": page["items"],
                "warning": "Table names may be misleading. Use get_table_comment for each table before selection."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} table comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_table_comment(schema, table) for full text."
                )

            return result

        @self.mcp.tool
        @_guarded
        def search_columns(keywords: str, schema_name: str, table_name: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Search columns by keywords (space-separated, OR logic) over column name and comment.

            schema_name is required. Pass table_name to scope to one table (cheap;
            use this for routine drill-down). Omit table_name to search every table
            in the schema (schema-wide; the natural primitive for cross-table FK /
            JOIN-key reconnaissance, returns table_name on each row).
            """
            # 解析關鍵字
            keyword_list = [k.strip() for k in keywords.split() if k.strip()]
            if not keyword_list:
                raise ValueError("At least one keyword is required.")

            # schema 必填且需是合法 identifier
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")
            # table_name 可選；若提供必須是合法 identifier
            if table_name is not None and not table_name.isidentifier():
                raise ValueError("Invalid table name.")

            # 建構 SQL - 使用參數化查詢防止 SQL injection
            # schema-wide 模式回傳 table_name；single-table 模式為了向後相容也帶上
            base_sql = """
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                COALESCE(d.description, '') AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
            LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s
            """

            params: list = [schema_name]
            if table_name is not None:
                base_sql += " AND c.table_name = %s"
                params.append(table_name)

            # 加入關鍵字搜尋條件（OR 邏輯）
            keyword_conditions = []
            for kw in keyword_list:
                keyword_conditions.append("(c.column_name ILIKE %s OR COALESCE(d.description, '') ILIKE %s)")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")

            base_sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            # schema-wide 模式按 table 名分組，再依 ordinal 排
            base_sql += " ORDER BY c.table_name, c.ordinal_position;"

            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(base_sql, con=conn, params=params)
                records = df.to_dict(orient='records')
                columns = []
                for r in records:
                    name = r['column_name']
                    comment = r['column_comment'] if r['column_comment'] else "(No comment available)"
                    hit_count = calculate_hit_count(name, comment, keyword_list)
                    columns.append({
                        "table_name": r['table_name'],
                        "column_name": name,
                        "data_type": r['data_type'],
                        "is_nullable": r['is_nullable'],
                        "column_comment": comment,
                        "hit_count": hit_count
                    })

            # 依 hit_count DESC, table_name ASC, column_name ASC 排序
            columns.sort(key=lambda x: (-x["hit_count"], x["table_name"], x["column_name"]))

            # 分頁處理
            page = paginate_results(columns, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（search 永遠帶 comment，無 include_comments flag）
            truncated_count = apply_comment_cap(page["items"], "column_comment")

            result = {
                "keywords": keyword_list,
                "schema_name": schema_name,
                "table_name": table_name,
                "scope": "single_table" if table_name is not None else "schema_wide",
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"],
                "warning": "Column names may be misleading. Use get_column_comment for each column before using in SQL."
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} column comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_column_comment(schema, table, col) for full text."
                )

            return result

        # ========== 註解查詢工具 ==========

        @self.mcp.tool
        @_guarded
        def get_schema_comment(schema_name: str) -> Dict[str, Any]:
            """Get the authoritative comment for a schema — defines its true business purpose; trust it over the schema name."""
            if not schema_name or not schema_name.isidentifier():
                raise ValueError("Invalid schema name.")

            sql = """
            SELECT d.description AS schema_comment
            FROM pg_namespace n
            LEFT JOIN pg_description d ON n.oid = d.objoid
            WHERE n.nspname = %s;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name])
                if df.empty:
                    raise ValueError(f"Schema '{schema_name}' not found.")
                comment = df['schema_comment'].iloc[0]
                comment = comment if comment else "(No comment available)"

            return {
                "schema_name": schema_name,
                "comment": comment
            }

        @self.mcp.tool
        @_guarded
        def get_table_comment(schema_name: str, table_name: str) -> Dict[str, Any]:
            """Get the authoritative comment for a table — defines what data it actually contains; trust it over the table name."""
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT d.description AS table_comment
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
            WHERE n.nspname = %s AND c.relname = %s;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name])
                if df.empty:
                    raise ValueError(f"Table '{schema_name}.{table_name}' not found.")
                comment = df['table_comment'].iloc[0]
                comment = comment if comment else "(No comment available)"

            return {
                "schema_name": schema_name,
                "table_name": table_name,
                "comment": comment
            }

        @self.mcp.tool
        @_guarded
        def get_column_comment(schema_name: str, table_name: str, column_name: str) -> Dict[str, Any]:
            """Get the authoritative comment for a column — defines its business meaning and calculation logic; trust it over the column name."""
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT c.data_type, d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
            LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s AND c.table_name = %s AND c.column_name = %s;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name, column_name])
                if df.empty:
                    raise ValueError(f"Column '{schema_name}.{table_name}.{column_name}' not found.")
                data_type = df['data_type'].iloc[0]
                comment = df['column_comment'].iloc[0]
                comment = comment if comment else "(No comment available)"

            return {
                "schema_name": schema_name,
                "table_name": table_name,
                "column_name": column_name,
                "data_type": data_type,
                "comment": comment
            }

        @self.mcp.tool
        @_guarded
        def get_all_column_comments(schema_name: str, table_name: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Get authoritative comments for ALL columns in a table at once. Each comment overrides the column name."""
            if not schema_name.isidentifier() or not table_name.isidentifier():
                raise ValueError("Invalid schema or table name.")

            sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                d.description AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_namespace n ON n.nspname = c.table_schema
            LEFT JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_description d ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = %s AND c.table_name = %s
            ORDER BY c.ordinal_position;
            """
            with self.config.get_connection() as conn:
                df = wr.redshift.read_sql_query(sql, con=conn, params=[schema_name, table_name])
                df['column_comment'] = df['column_comment'].fillna('(No comment available)')
                records = df.to_dict(orient='records')

            # 分頁處理
            page = paginate_results(records, limit, offset, DEFAULT_MAX_ITEMS)

            # Comment 字元截斷（多筆回應防護）
            truncated_count = apply_comment_cap(page["items"], "column_comment")

            result = {
                "schema_name": schema_name,
                "table_name": table_name,
                "total_count": page["total_count"],
                "returned_count": page["returned_count"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "columns": page["items"]
            }

            if page["auto_truncated"]:
                result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

            if truncated_count > 0:
                result["comment_truncated_count"] = truncated_count
                result["comment_truncated_hint"] = (
                    f"{truncated_count} of {page['returned_count']} column comments were truncated "
                    f"at {MAX_COMMENT_LEN} chars. Use get_column_comment(schema, table, col) for full text."
                )

            return result

        # ========== SQL 執行工具 ==========

        @self.mcp.tool
        @_guarded
        def execute_sql(sql_statement: str, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
            """Execute a read-only SQL query (SELECT/WITH only). Result rows are paginated via limit/offset."""
            validate_read_only_sql(sql_statement)

            # Hoist config access out of the try/except below so ConfigurationError
            # (raised by the lazy provider when no profile is set) propagates up to
            # @_guarded instead of getting rewrapped as a generic SQL error.
            config = self.config

            try:
                with config.get_connection() as conn:
                    df = wr.redshift.read_sql_query(sql_statement, con=conn)
                    records = df.to_dict(orient='records')
                    columns = list(df.columns)

                # 分頁處理
                page = paginate_results(records, limit, offset, DEFAULT_MAX_ITEMS)

                result = {
                    "total_count": page["total_count"],
                    "returned_count": page["returned_count"],
                    "offset": page["offset"],
                    "has_more": page["has_more"],
                    "columns": columns,
                    "data": page["items"],
                    "_executed_sql": [sql_statement],
                    "_user_facing_message": (
                        "Show the user the SQL from _executed_sql verbatim "
                        "(in a code block) before presenting these results. "
                        "Do not paraphrase or omit it — users need direct "
                        "visibility into what runs against their database."
                    ),
                }

                if page["auto_truncated"]:
                    result["pagination_hint"] = f"Results auto-truncated to {DEFAULT_MAX_ITEMS}. Use limit/offset to retrieve more."

                return result
            except Exception as e:
                logger.error(f"SQL execution failed: {sql_statement}", exc_info=True)
                raise ValueError(f"SQL execution error. Please check your syntax. Original error: {e}")

        # ========== Setup tool (control plane — works WITHOUT a configured profile) ==========
        #
        # `setup_via_dialog` and `get_setup_status` below INTENTIONALLY skip
        # the `@_guarded` decorator that wraps every DB tool above. The
        # decorator converts `ConfigurationError` → not_configured response,
        # but these two tools must be USABLE when no profile is configured
        # yet — that's literally their job. Wrapping them in @_guarded would
        # make them refuse to run in the very state where they're needed.
        # Adding the decorator here is a regression that the existing
        # behavioral tests (test_setup_via_dialog_works_without_configured_
        # profile, test_get_setup_status_works_in_degraded_mode) catch.
        #
        # Forward look: the MCP 2026-07-28 RC introduces `Elicitation` —
        # a primitive for servers to request direct user input via the
        # client's native UI. Once GA'd (and FastMCP exposes it), the
        # subprocess+osascript dialog hack here becomes obsolete: server
        # can request a password through the protocol and the client
        # presents a native secure input widget. Until then, this is the
        # chat-leak-free path that works with current MCP spec.

        @self.mcp.tool
        def setup_via_dialog(
            host: str,
            user: str,
            dbname: str,
            profile: str = "default",
            port: int = 5439,
        ) -> Dict[str, Any]:
            """Bootstrap (or update) a Redshift connection profile from inside an MCP session.

            Use when DB tools (list_schemas etc.) return ``{"error": "not_configured"}``,
            or to add a new profile / re-key an existing one. Ask the user for
            host / port / user / dbname conversationally — these are not secret —
            then call this tool. The password is collected via an OS-native
            dialog (macOS osascript / Linux zenity) launched server-side; it
            **never crosses the MCP wire, never appears in chat or tool args**.

            Outcomes (return shape):
              - ``{"status": "configured", ...}`` — profile written, password in
                keychain. Lazy resolve picks it up on next DB tool call; no
                restart needed.
              - ``{"status": "dialog_cancelled" | "dialog_unavailable" |
                   "platform_unsupported" | "empty_password", ...}`` — profile
                fields saved but no password set; the message field tells the
                agent / user what to do next (often: run
                ``redshift-comment-mcp set-password --profile X --stdin`` from
                a terminal).

            For headless environments without a GUI, prefer the CLI pair
            ``set-fields`` + ``set-password --stdin`` instead.
            """
            import sys as _sys
            from . import config as cfg
            from .setup_cli import _collect_password_via_dialog

            if not all([host, user, dbname]):
                return {
                    "error": "missing_field",
                    "message": "host, user, and dbname are all required.",
                }

            try:
                cfg.write_profile(profile, host=host, port=port, user=user, dbname=dbname)
            except Exception as e:
                # Per CWE-209 / OWASP Error Handling Cheat Sheet: log the
                # full exception server-side, but return only the exception
                # CLASS to the client. The class name is diagnostic-useful
                # (PermissionError vs OSError vs ...) without including any
                # exception args, which could in theory carry sensitive
                # info (file paths, environment values, etc.).
                logger.error(f"setup_via_dialog: write_profile failed: {e}", exc_info=True)
                return {
                    "error": "write_profile_failed",
                    "exception_class": type(e).__name__,
                    "message": (
                        f"Failed to write profile fields to config.toml "
                        f"(exception class: {type(e).__name__}). The "
                        f"underlying error was logged server-side with "
                        f"full detail; it is not included in this response "
                        f"to avoid leaking sensitive context through the "
                        f"MCP wire. Most likely causes: config directory "
                        f"not writable, disk full, or filesystem error."
                    ),
                }

            password, reason = _collect_password_via_dialog(profile)

            # 4 reason-keyed failure paths dispatch to module-level builders
            # (see _DIALOG_FAILURE_BUILDERS). The 5th case ("ok" reason but
            # empty password — user clicked OK without typing) is checked
            # separately because it's keyed by password emptiness, not reason.
            if reason in _DIALOG_FAILURE_BUILDERS:
                return _DIALOG_FAILURE_BUILDERS[reason](
                    profile=profile, platform=_sys.platform,
                )
            if not password:
                return _build_empty_password_response(profile=profile)

            try:
                cfg.set_password(profile, password)
            except Exception as e:
                # Same CWE-209 discipline as write_profile_failed above: log
                # full exception server-side, return only the exception
                # class name + a sanitized message. Keychain backends are
                # third-party (macOS Security framework, gnome-keyring,
                # KWallet, etc.) and their exception args' contents are
                # outside our control — assume they may carry context we
                # don't want crossing the MCP wire.
                logger.error(f"setup_via_dialog: set_password failed: {e}", exc_info=True)
                # Surface specific keyring exceptions when recognisable
                # (per Snyk guidance: catch keyring.errors.PasswordSetError
                # / KeyringLocked separately for more actionable diagnosis).
                exc_class = type(e).__name__
                hint = {
                    "PasswordSetError": "Keychain rejected the write (locked, missing entitlement, or backend refused).",
                    "KeyringLocked": "OS keychain is currently locked; unlock it and retry.",
                    "InitError": "Keyring backend failed to initialize on this host.",
                    "NoKeyringError": "No keyring backend is available on this host.",
                }.get(exc_class, "Underlying keychain write failed.")
                return {
                    "error": "keychain_write_failed",
                    "exception_class": exc_class,
                    "message": (
                        f"{hint} Profile '{profile}' fields were saved to "
                        f"config.toml but the password was NOT stored. The "
                        f"underlying error was logged server-side with full "
                        f"detail; it is not included here per chat-leak "
                        f"hygiene. Have the user pipe the password via "
                        f"`redshift-comment-mcp set-password --profile "
                        f"{profile} --stdin` from a terminal as a fallback."
                    ),
                }

            # Verify the freshly-written profile actually connects to Redshift
            # before declaring success. Catches typos / VPN-not-connected /
            # firewall / wrong password / paused-cluster early so the agent
            # doesn't claim "configured" then immediately fail on the next
            # DB tool call.
            from .setup_cli import _test_redshift_connection
            ok, conn_err = _test_redshift_connection(host, port, user, password, dbname)

            if not ok:
                return {
                    "status": "configured_but_connection_failed",
                    "profile": profile,
                    "host": host,
                    "port": port,
                    "user": user,
                    "dbname": dbname,
                    "tested": False,
                    "connection_error": conn_err,
                    "message": (
                        f"Profile '{profile}' fields and password were "
                        f"saved, but the test connection to Redshift "
                        f"FAILED. The most likely causes: wrong host (typo "
                        f"or VPN not connected), wrong port, wrong "
                        f"user/password, firewall block, or the cluster "
                        f"is paused. Verify the values with the user and "
                        f"call setup_via_dialog again with corrections "
                        f"(it will overwrite). Connection error attached "
                        f"in `connection_error` field."
                    ),
                }

            return {
                "status": "configured",
                "profile": profile,
                "host": host,
                "port": port,
                "user": user,
                "dbname": dbname,
                "tested": True,
                "message": (
                    f"Profile '{profile}' configured AND test connection "
                    f"succeeded. Fields written to ~/.config/redshift-"
                    f"comment-mcp/config.toml, password stored in OS "
                    f"keychain, SELECT 1 against Redshift returned OK. "
                    f"Retry any DB tool now — lazy resolution will pick "
                    f"up the new profile on next call without restarting "
                    f"the MCP client."
                ),
            }

        @self.mcp.tool
        def get_setup_status(profile: str = "default") -> Dict[str, Any]:
            """Read-only check of whether a profile is configured. Safe to
            call at any time including the very start of a session — does
            not touch Redshift, does not return any secrets.

            Use at session start to decide proactively whether to call
            ``setup_via_dialog`` (before triggering any DB tool's
            not_configured error path), or to verify a setup_via_dialog
            call succeeded from a fresh angle.

            Returns:
              - ``profile`` — the queried profile name
              - ``configured`` — bool, equivalent to has_fields && has_password
              - ``has_fields`` — whether config.toml has this profile's
                non-secret fields (host / port / user / dbname)
              - ``has_password`` — whether the OS keychain has a password
                for this profile (NEVER returns the password itself)
              - ``host`` / ``port`` / ``user`` / ``dbname`` — present only
                when has_fields=True (these are non-secret)
              - ``next_step`` — present only when configured=False;
                actionable hint pointing at setup_via_dialog
            """
            from . import config as cfg

            profile_data = cfg.read_profile(profile)
            has_fields = profile_data is not None
            has_password = cfg.get_password(profile) is not None

            result: Dict[str, Any] = {
                "profile": profile,
                "configured": has_fields and has_password,
                "has_fields": has_fields,
                "has_password": has_password,
            }

            if has_fields:
                # Non-secret — safe to expose. Lets the agent show the user
                # what's currently set up vs. what they're about to overwrite.
                result["host"] = profile_data["host"]
                result["port"] = profile_data["port"]
                result["user"] = profile_data["user"]
                result["dbname"] = profile_data["dbname"]

            if not result["configured"]:
                if not has_fields:
                    result["next_step"] = (
                        f"Profile '{profile}' has no config.toml entry. "
                        f"Call setup_via_dialog(host=..., user=..., "
                        f"dbname=...) to provision it. Ask the user for "
                        f"host/user/dbname conversationally — these are "
                        f"not secrets."
                    )
                else:
                    result["next_step"] = (
                        f"Profile '{profile}' has fields but no password "
                        f"in keychain. Call setup_via_dialog with the "
                        f"existing values (or different ones to overwrite) "
                        f"— the dialog will collect a password and store it."
                    )

            return result

    def get_server(self):
        """取得配置好的 MCP 伺服器"""
        return self.mcp
