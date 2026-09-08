"""SQLite storage for sessions and logs."""

from app.task_refs import task_ref as public_task_ref

import json
import logging
import math
import os
import re
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("db")


_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"

def _resolve_db_path() -> Path:
    """Путь к БД: ORCHESTRA_DB_PATH из env (если задан) или дефолт data/orchestra.db.

    Позволяет разным worktree/веткам и тестам держать свою БД, не блокируя
    друг друга через SQLite-лок при параллельной работе.
    """
    override = os.getenv("ORCHESTRA_DB_PATH", "").strip()
    if not override:
        return _DEFAULT_DB_PATH
    p = Path(override)
    return p if p.is_absolute() else (Path(__file__).parent.parent / p)


DB_PATH = _resolve_db_path()


class OwnedConnection(sqlite3.Connection):
    """The creating scope commits/rolls back and closes; borrowers use nullcontext."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _conn(path: Path | None = None) -> sqlite3.Connection:
    """Open an owned connection, closed by its context or explicitly by its caller."""
    path = DB_PATH if path is None else Path(path)
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(path), factory=OwnedConnection)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
    except BaseException:
        conn.close()
        raise
    return conn


SCHEMA_VERSION = 1



def init_db(path: Path | None = None) -> None:
    with _conn(path) as connection:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version or connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
            raise RuntimeError('database schema needs offline migration before starting Orchestra')
        schema = Path(__file__).with_name('schema.sql').read_text()
        connection.executescript('BEGIN IMMEDIATE;\n' + schema)
        connection.execute("INSERT INTO profiles(name,config_dir) VALUES('personal','')")
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany('INSERT INTO kv(key,value) VALUES(?,?)',
            [(key, now) for key in ('tool_error_collector_started_at','turn_usage_collector_started_at')])
        connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')



def kv_get(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def kv_delete(key: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM kv WHERE key=?", (key,))



def save_session(
    s: dict,
    *,
    _connection: sqlite3.Connection | None = None,
) -> None:
    # Пустой id — не «почти валидная» строка, а невидимка: все UPDATE … WHERE id=?
    # по ней меняют ноль строк молча (#54). Падать здесь, а не позже и не в другом месте.
    if not str(s.get("id") or "").strip():
        raise ValueError(
            f"session id is required and must be non-empty "
            f"(name={s.get('name')!r}, scope={s.get('scope')!r})"
        )
    s.setdefault("context_pct", 0)
    s.setdefault("context_tokens", 0)
    s.setdefault("progress_pct", 0)
    s.setdefault("progress_status", "")
    s.setdefault("backend_type", "claude")
    s.setdefault("task_id", "")
    s.setdefault("description", "")
    s.setdefault("cost_usd_cached", 0.0)
    s.setdefault("context_cost", 0.0)
    s.setdefault("total_turns", 0)
    s.setdefault("total_input_tokens", 0)
    s.setdefault("total_output_tokens", 0)
    s.setdefault("total_cache_read_tokens", 0)
    s.setdefault("total_cache_create_tokens", 0)
    s.setdefault("total_tool_calls", 0)
    s.setdefault("template_hash", "")
    s.setdefault("role", "worker")
    s.setdefault("parent_id", "")
    s.setdefault("parent_name", "")
    s.setdefault("pipeline", "")
    s.setdefault("profile", "")
    s.setdefault("disabled_tools", "[]")
    s.setdefault("mcp_servers_custom", "")
    s.setdefault("owned_dirs", "")
    s.setdefault("tg_topic", 0)
    s.setdefault("session_id_history", "[]")
    s.setdefault("effort", "")
    s.setdefault("runtime_handoff", "")
    s.setdefault("history_import_source", None)
    s.setdefault("last_summary", "")
    s.setdefault("base_branch", "")
    s.setdefault("needs_switch", 0)
    s.setdefault("prompt_overlay", None)
    connection_scope = (
        nullcontext(_connection) if _connection is not None else _conn()
    )
    with connection_scope as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt, prompt_overlay,
                status, session_id, cost_usd, worktree_path, branch, base_branch,
                needs_switch, is_orchestrator,
                color, created_at, finished_at, context_pct, context_tokens,
                progress_pct, progress_status, backend_type, task_id, description,
                cost_usd_cached, context_cost,
                total_turns, total_input_tokens, total_output_tokens,
                total_cache_read_tokens, total_cache_create_tokens, total_tool_calls,
                template_hash, role, parent_id, parent_name, mcp_servers_custom, disabled_tools, pipeline,
                profile, owned_dirs, tg_topic, session_id_history, effort, runtime_handoff,
                history_import_source, last_summary)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt, :prompt_overlay,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :base_branch,
                :needs_switch, :is_orchestrator,
                :color, :created_at, :finished_at, :context_pct, :context_tokens,
                :progress_pct, :progress_status, :backend_type, :task_id, :description,
                :cost_usd_cached, :context_cost,
                :total_turns, :total_input_tokens, :total_output_tokens,
                :total_cache_read_tokens, :total_cache_create_tokens, :total_tool_calls,
                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :disabled_tools, :pipeline,
                :profile, :owned_dirs, :tg_topic, :session_id_history, :effort,
                :runtime_handoff, :history_import_source, :last_summary)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                model=excluded.model,
                system_prompt=excluded.system_prompt,
                prompt_overlay=excluded.prompt_overlay,
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                cost_usd_cached=excluded.cost_usd_cached,
                context_cost=excluded.context_cost,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
                base_branch=excluded.base_branch,
                needs_switch=excluded.needs_switch,
                cwd=excluded.cwd,
                color=excluded.color,
                finished_at=excluded.finished_at,
                context_pct=excluded.context_pct,
                context_tokens=excluded.context_tokens,
                progress_pct=excluded.progress_pct,
                progress_status=excluded.progress_status,
                backend_type=excluded.backend_type,
                task_id=excluded.task_id,
                description=excluded.description,
                total_turns=excluded.total_turns,
                total_input_tokens=excluded.total_input_tokens,
                total_output_tokens=excluded.total_output_tokens,
                total_cache_read_tokens=excluded.total_cache_read_tokens,
                total_cache_create_tokens=excluded.total_cache_create_tokens,
                total_tool_calls=excluded.total_tool_calls,
                template_hash=excluded.template_hash,
                role=excluded.role,
                parent_id=excluded.parent_id,
                parent_name=excluded.parent_name,
                mcp_servers_custom=excluded.mcp_servers_custom,
                disabled_tools=excluded.disabled_tools,
                pipeline=excluded.pipeline,
                profile=excluded.profile,
                owned_dirs=excluded.owned_dirs,
                tg_topic=excluded.tg_topic,
                session_id_history=excluded.session_id_history,
                effort=excluded.effort,
                runtime_handoff=excluded.runtime_handoff,
                history_import_source=excluded.history_import_source,
                last_summary=excluded.last_summary
        """, s)


def publish_ready_session(s: dict, task_identity: dict | None = None) -> None:
    """Atomically replace one archived identity with a fully prepared session."""
    from contextlib import nullcontext
    from app.task_runtime import active_runtime
    runtime = active_runtime() if task_identity else None
    with runtime.operation() if runtime else nullcontext():
        with _conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM sessions WHERE id=?", (s["id"],)).fetchone():
                raise sqlite3.IntegrityError(f"session id already exists: {s['id']}")
            c.execute(
                "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
                (s["name"], s["scope"]),
            )
            save_session(s, _connection=c)
            if task_identity:
                if c.execute(
                    "SELECT 1 FROM tm_task_reservations WHERE task_id = ?",
                    (task_identity["id"],),
                ).fetchone():
                    raise ValueError(f"task #{task_identity['par_number']} is reserved")
                cur = c.execute(
                    "UPDATE tm_tasks SET worker_session_id=?, status='in_progress', "
                    "sync_revision=sync_revision+1, updated_at=? "
                    "WHERE id=? AND project_id=? AND par_number=? AND sync_revision=? "
                    "AND worker_session_id IS NULL",
                    (
                        s["id"], datetime.now(timezone.utc).isoformat(),
                        task_identity["id"], task_identity["project_id"],
                        task_identity["par_number"], task_identity["sync_revision"],
                    ),
                )
                if cur.rowcount != 1:
                    raise ValueError(
                        f"task #{task_identity['par_number']} binding compare-and-swap failed"
                    )
                published = runtime.publish(c, task_identity['id'])
                task_identity = {**task_identity, 'stable_id': published['id'],
                                 'task_snapshot_ref': f"git-task:{published['id']}@{runtime.store.head}"}
                stable_id = str(task_identity.get("stable_id") or "")
                snapshot_ref = task_identity["task_snapshot_ref"]
                task_run_receipt_open(
                    session_id=s["id"],
                    worker_name=s["name"],
                    scope=s["scope"],
                    task_id=public_task_ref(task_identity),
                    task_stable_id=stable_id,
                    task_snapshot_ref=snapshot_ref,
                    prompt_template_start=str(s.get("template_hash") or ""),
                    task_source=("canonical" if stable_id and snapshot_ref else "legacy"),
                    connection=c,
                )


def update_session_lifecycle(
    session_id: str,
    *,
    branch: str,
    base_branch: str,
    task_id: str,
    needs_switch: bool,
) -> bool:
    """Persist the Git lifecycle snapshot for loaded and detached sessions alike."""
    with _conn() as c:
        cur = c.execute(
            """UPDATE sessions
               SET branch=?, base_branch=?, task_id=?, needs_switch=?
               WHERE id=? AND status != 'archived'""",
            (branch, base_branch, task_id, int(needs_switch), session_id),
        )
        if cur.rowcount == 0:
            # Ноль строк — это не «нечего менять», это промах по идентичности (#54):
            # строка либо архивная, либо её id не совпадает ни с чем (пустой/призрак).
            logger.warning(
                "UPDATE sessions changed 0 rows: lifecycle for id=%r not persisted",
                session_id,
            )
        return cur.rowcount == 1


def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
    """Move an orchestrator's session to a new scope in one transaction.

    Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
    bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
    session_id (Claude resume token) is left intact — context survives.

    Rejected if another session with the same name already lives in new_scope
    (UNIQUE(name, scope)). A task-associated session also rejects a target task-project
    collision; without a task association, tm_projects/test_lock migration is skipped
    on UNIQUE collision and the explicit session move still succeeds.
    """
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT name, task_id FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            return {"error": f"session not found: {session_id}"}
        name = row["name"]
        clash = c.execute(
            "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
            (name, new_scope, session_id),
        ).fetchone()
        if clash:
            return {"error": f"session '{name}' already exists in scope '{new_scope}'"}

        source_project = c.execute(
            "SELECT id FROM tm_projects WHERE scope=?", (old_scope,)
        ).fetchone()
        target_project = c.execute(
            "SELECT id FROM tm_projects WHERE scope=?", (new_scope,)
        ).fetchone()
        if (
            row["task_id"]
            and target_project
            and (not source_project or source_project["id"] != target_project["id"])
        ):
            return {
                "error": (
                    f"cannot change scope with task #{row['task_id']}: target scope "
                    f"belongs to task project '{target_project['id']}'"
                )
            }

        cur = c.execute(
            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
            (new_scope, new_cwd, session_id, old_scope),
        )
        if cur.rowcount == 0:
            return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}

        tm_migrated = False
        if not target_project:
            cur = c.execute("UPDATE tm_projects SET scope=? WHERE scope=?", (new_scope, old_scope))
            tm_migrated = cur.rowcount > 0

        c.execute(
            "UPDATE bg_jobs SET target_scope=? WHERE target_scope=? AND status IN ('active','triggering')",
            (new_scope, old_scope),
        )

        lock_target_taken = c.execute("SELECT 1 FROM test_lock WHERE scope=?", (new_scope,)).fetchone()
        if not lock_target_taken:
            c.execute("UPDATE test_lock SET scope=? WHERE scope=?", (new_scope, old_scope))

        return {"ok": True, "scope": new_scope, "cwd": new_cwd, "tm_project_migrated": tm_migrated}


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_by_name(name: str, scope: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE name = ? AND scope = ? AND status != 'archived'",
            (name, scope),
        ).fetchone()
        return dict(row) if row else None


# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──

def list_profiles() -> list[dict]:
    """Все профили, отсортированы по имени: ``[{"name":..., "config_dir":...}]``."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name, config_dir FROM profiles ORDER BY name"
        ).fetchall()
        return [{"name": r["name"], "config_dir": r["config_dir"]} for r in rows]


def get_profile(name: str) -> dict | None:
    """Один профиль по имени или ``None``, если не найден."""
    with _conn() as c:
        row = c.execute(
            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        return {"name": row["name"], "config_dir": row["config_dir"]} if row else None


def upsert_profile(name: str, config_dir: str) -> None:
    """Создать профиль или обновить его ``config_dir`` (по конфликту имени)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET config_dir = excluded.config_dir",
            (name, config_dir),
        )


def delete_profile(name: str) -> None:
    """Удалить профиль. Сид-профиль ``personal`` удалять запрещено."""
    if name == "personal":
        raise ValueError("Профиль 'personal' является сид-профилем и не может быть удалён")
    with _conn() as c:
        c.execute("DELETE FROM profiles WHERE name = ?", (name,))


def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
    with _conn() as c:
        archived_filter = "" if include_archived else " AND status != 'archived'"
        if scope:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE scope = ?{archived_filter} ORDER BY created_at DESC", (scope,)
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE 1=1{archived_filter} ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_last_turn_map() -> dict[str, str]:
    """{session_id: last 'turn ended' log ts} for cache-timer display. One query."""
    with _conn() as c:
        rows = c.execute(
            "SELECT session_id, MAX(ts) AS last_ts FROM logs "
            "WHERE type='status' AND content LIKE 'turn ended%' "
            "GROUP BY session_id"
        ).fetchall()
        return {r["session_id"]: r["last_ts"] for r in rows}


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_archived_session(name: str, scope: str) -> None:
    """Free the UNIQUE(name, scope) slot held by an archived row before re-spawn.

    get_session_by_name filters archived out, so the archived row is invisible to
    callers — this deletes it explicitly (name+scope scoped, never name-only).
    """
    with _conn() as c:
        c.execute(
            "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
            (name, scope),
        )


def archive_session(session_id: str) -> None:
    from app import tm

    from app import tm
    with tm.active_runtime().operation():
        with _conn() as c:
            cur = c.execute(
                "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), session_id),
            )
            # Одна транзакция с архивацией: между «воркера больше нет» и «его задача
            # пересчитана» не должно существовать окна, в котором задача числится за мёртвым.
            tm.release_session_task_binding(c, session_id)
            if cur.rowcount == 0:
                logger.warning(
                    "UPDATE sessions changed 0 rows: session id=%r not archived", session_id,
                )


def add_log(
    session_id: str,
    ts: datetime,
    type: str,
    content: str,
    event_id: str = "",
    *,
    provenance=None,
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    tool_is_error: bool | None = None,
) -> int:
    """ИНВАРИАНТ: строки logs неизменяемы — только этот INSERT и оптовый DELETE по
    возрасту в cleanup_old_logs. Ни одного UPDATE. На этом стоит зеркало журнала в
    браузере (#8): сохранённая строка не может стать неверной, только исчезнуть.
    Появится первый UPDATE logs (например, редактирование сообщения) — зеркало начнёт
    врать МОЛЧА; чинить придётся get_logs_sync и клиентское хранилище вместе.

    Здесь же — ЕДИНСТВЕННЫЙ шов маскирования для БД (#224): строки неизменяемы, значит
    замаскировать значение позже уже нельзя. Второй шов, живой SSE, идёт мимо этой функции
    и закрыт в live_broker.publish.
    """
    from app.events import MessageProvenance

    if type == "user_message" and provenance is None:
        raise ValueError("user_message provenance is required")
    if provenance is not None and not isinstance(provenance, MessageProvenance):
        raise TypeError("provenance must be MessageProvenance")
    if provenance is None:
        origin, origin_detail = "unknown", '{"senders":["unknown"]}'
    else:
        origin, origin_detail = provenance.to_storage()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO logs (
                   session_id, ts, type, content, event_id,
                   tool_use_id, tool_name, tool_is_error, origin, origin_detail
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, ts.isoformat(), type, content, event_id,
                tool_use_id, tool_name,
                None if tool_is_error is None else int(tool_is_error),
                origin, origin_detail,
            ),
        )
        return cur.lastrowid


def dashboard_voice_enqueue(
    voice_id: str,
    session_id: str,
    session_name: str,
    scope: str,
    path: str,
    content_type: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO dashboard_voice_transcriptions
               (voice_id, session_id, session_name, scope, path, content_type,
                state, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', '', ?, ?)""",
            (voice_id, session_id, session_name, scope, path, content_type, now, now),
        )


def dashboard_voice_pending() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM dashboard_voice_transcriptions
               WHERE state IN ('QUEUED', 'RUNNING') ORDER BY created_at"""
        ).fetchall()
        return [dict(row) for row in rows]


def dashboard_voice_mark_running(voice_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE dashboard_voice_transcriptions SET state='RUNNING', updated_at=? WHERE voice_id=?",
            (now, voice_id),
        )


def dashboard_voice_mark_sent(voice_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE dashboard_voice_transcriptions SET state='SENT', updated_at=? WHERE voice_id=?",
            (now, voice_id),
        )


def dashboard_voice_mark_failed(voice_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """UPDATE dashboard_voice_transcriptions
               SET state='FAILED', error=?, updated_at=? WHERE voice_id=?""",
            (error, now, voice_id),
        )


def get_recent_chat_logs(session_id: str) -> list[dict]:
    """Read a bounded chat window and any tool call paired across its boundary."""
    from app.chat_history import MAX_MESSAGES

    columns = "id,ts,type,substr(content,1,8000) AS content,length(content) AS content_length,tool_use_id,origin"
    with _conn() as connection:
        connection.execute("BEGIN")
        rows = [dict(row) for row in connection.execute(
            f"SELECT {columns} FROM logs WHERE session_id=? "
            "AND type IN ('user_message','text','tool','tool_result') "
            "AND NOT (type='user_message' AND origin='platform') "
            "ORDER BY id DESC LIMIT ?", (session_id, MAX_MESSAGES),
        )]
        present = {row['tool_use_id'] for row in rows if row['type'] == 'tool'}
        missing = {row['tool_use_id'] for row in rows
                   if row['type'] == 'tool_result' and row['tool_use_id']} - present
        if missing:
            placeholders = ','.join('?' for _ in missing)
            calls = connection.execute(
                f"SELECT {columns} FROM logs WHERE id IN ("
                "SELECT MAX(id) FROM logs WHERE session_id=? AND type='tool' "
                f"AND tool_use_id IN ({placeholders}) AND id<? GROUP BY tool_use_id)",
                (session_id, *sorted(missing), min(row['id'] for row in rows)),
            ).fetchall()
            rows.extend(dict(call) for call in calls)
    return sorted(rows, key=lambda row: row['id'])


def get_history_logs(session_id: str, conn=None) -> tuple[int, list[dict]]:
    """Return one immutable log boundary without the dashboard's 5k row cap."""
    c = conn or _conn()
    try:
        max_id = int(c.execute(
            "SELECT COALESCE(MAX(id), 0) FROM logs WHERE session_id = :session_id",
            {"session_id": session_id},
        ).fetchone()[0])
        rows = c.execute(
            """SELECT * FROM logs
               WHERE session_id = :session_id AND id <= :max_id
               ORDER BY id ASC""",
            {"session_id": session_id, "max_id": max_id},
        ).fetchall()
        return max_id, [_decode_log_provenance(dict(row)) for row in rows]
    finally:
        if conn is None:
            c.close()


_HANDOFF_COLUMNS = (
    "handoff_id", "session_id", "idempotency_key", "status",
    "source_runtime", "source_model", "source_session_id",
    "target_runtime", "target_model", "snapshot_log_id",
    "snapshot_sha256", "packet_json", "packet_sha256", "preferred_mode",
    "confirmed_attempt_no", "failure_code", "created_at", "updated_at",
    "confirmed_at",
)


def _insert_runtime_handoff(c: sqlite3.Connection, record: dict) -> dict:
    existing = c.execute(
        "SELECT * FROM runtime_handoffs WHERE session_id=? AND idempotency_key=?",
        (record["session_id"], record["idempotency_key"]),
    ).fetchone()
    if existing:
        return dict(existing)
    columns = [column for column in _HANDOFF_COLUMNS if column in record]
    placeholders = ", ".join("?" for _ in columns)
    c.execute(
        f"INSERT INTO runtime_handoffs ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        tuple(record[column] for column in columns),
    )
    return dict(c.execute(
        "SELECT * FROM runtime_handoffs WHERE handoff_id=?",
        (record["handoff_id"],),
    ).fetchone())


def create_runtime_handoff(record: dict) -> dict:
    """Insert an idempotent handoff operation without duplicating its packet."""
    with _conn() as c:
        return _insert_runtime_handoff(c, record)


def prepare_runtime_handoff_snapshot(
    session_id: str,
    idempotency_key: str,
    builder,
) -> tuple[dict | None, object | None]:
    """Freeze logs and create the prepared row under one SQLite write lock.

    ``builder`` receives the current session row, snapshot id, and rows. It returns
    ``(record, side_result)``; ``record=None`` is an ineligible preparation and does
    not create a live operation.
    """
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            "SELECT * FROM runtime_handoffs WHERE session_id=? AND idempotency_key=?",
            (session_id, idempotency_key),
        ).fetchone()
        if existing:
            return dict(existing), None
        session = c.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not session:
            raise RuntimeError("runtime handoff source session not found")
        snapshot_id, rows = get_history_logs(session_id, conn=c)
        record, side_result = builder(dict(session), snapshot_id, rows)
        if record is None:
            return None, side_result
        return _insert_runtime_handoff(c, record), side_result


def get_runtime_handoff(handoff_id: str) -> dict | None:
    with _conn() as c:
        try:
            row = c.execute(
                "SELECT * FROM runtime_handoffs WHERE handoff_id=?", (handoff_id,)
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            return None
        return dict(row) if row else None


def list_runtime_handoff_attempts(handoff_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM runtime_handoff_attempts WHERE handoff_id=? "
            "ORDER BY attempt_no",
            (handoff_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_latest_runtime_handoffs() -> list[dict]:
    """Return the one unfinished operation that can affect each session owner."""
    with _conn() as c:
        try:
            rows = c.execute(
                """SELECT h.*
                   FROM runtime_handoffs AS h
                   JOIN (
                       SELECT session_id, MAX(rowid) AS newest_rowid
                       FROM runtime_handoffs
                       WHERE status IN (
                           'prepared', 'target_staged', 'ingress_validated',
                           'capability_validated', 'source_released',
                           'recovery_required'
                       )
                       GROUP BY session_id
                   ) AS latest ON latest.newest_rowid = h.rowid
                   ORDER BY h.rowid"""
            ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            return []
        return [dict(row) for row in rows]


def get_latest_runtime_handoff_for_session(session_id: str) -> dict | None:
    """Return the unfinished operation that owns a session's recovery gate."""
    with _conn() as c:
        try:
            row = c.execute(
                """SELECT * FROM runtime_handoffs
                   WHERE session_id=? AND status IN (
                       'prepared', 'target_staged', 'ingress_validated',
                       'capability_validated', 'source_released',
                       'recovery_required'
                   )
                   ORDER BY rowid DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            return None
        return dict(row) if row else None


def get_confirmed_runtime_handoff_attempt(
    session_id: str,
    target_session_id: str | None,
) -> dict | None:
    """Locate the provider-owned target store for the current confirmed owner."""
    if not target_session_id:
        return None
    with _conn() as c:
        row = c.execute(
            """SELECT a.*, h.target_runtime, h.target_model
               FROM runtime_handoffs AS h
               JOIN runtime_handoff_attempts AS a
                 ON a.handoff_id=h.handoff_id
                AND a.attempt_no=h.confirmed_attempt_no
               WHERE h.session_id=? AND h.status='confirmed'
                 AND a.status='confirmed' AND a.target_session_id=?
               ORDER BY h.rowid DESC LIMIT 1""",
            (session_id, target_session_id),
        ).fetchone()
        return dict(row) if row else None


def retire_runtime_handoff(
    handoff_id: str,
    *,
    status: str,
    failure_code: str,
) -> None:
    """Atomically terminate an operation and retire every allocated target owner."""
    if status not in {"failed", "recovery_required"}:
        raise ValueError("runtime handoff retirement status must be terminal")
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        changed = c.execute(
            """UPDATE runtime_handoffs
               SET status=?, failure_code=?, updated_at=?
               WHERE handoff_id=?""",
            (status, failure_code, now, handoff_id),
        )
        if changed.rowcount != 1:
            raise RuntimeError("runtime handoff not found")
        c.execute(
            """UPDATE runtime_handoff_attempts
               SET status=CASE WHEN status='confirmed' THEN status ELSE 'retired' END,
                   error_code=COALESCE(error_code, ?),
                   retired_at=COALESCE(retired_at, ?), updated_at=?
               WHERE handoff_id=?""",
            (failure_code, now, now, handoff_id),
        )


def allocate_runtime_handoff_attempt(
    handoff_id: str,
    *,
    mode: str,
    candidate_sha256: str,
    cleanup_locator: str,
) -> dict:
    """Persist the cleanup owner before an external target can be created."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) FROM runtime_handoff_attempts "
            "WHERE handoff_id=?",
            (handoff_id,),
        ).fetchone()
        attempt_no = int(row[0]) + 1
        if attempt_no > 2:
            raise RuntimeError("runtime handoff fallback exhausted")
        c.execute(
            """INSERT INTO runtime_handoff_attempts
               (handoff_id, attempt_no, mode, status, cleanup_locator,
                candidate_sha256, created_at, updated_at)
               VALUES (?, ?, ?, 'allocated', ?, ?, ?, ?)""",
            (
                handoff_id, attempt_no, mode, cleanup_locator,
                candidate_sha256, now, now,
            ),
        )
        return dict(c.execute(
            "SELECT * FROM runtime_handoff_attempts "
            "WHERE handoff_id=? AND attempt_no=?",
            (handoff_id, attempt_no),
        ).fetchone())


def update_runtime_handoff_attempt(
    handoff_id: str,
    attempt_no: int,
    *,
    status: str,
    target_session_id: str | None = None,
    preflight_json: str | None = None,
    ingress_json: str | None = None,
    capability_json: str | None = None,
    error_code: str | None = None,
    retired_at: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute(
            """UPDATE runtime_handoff_attempts SET
                   status=?, target_session_id=COALESCE(?, target_session_id),
                   preflight_json=COALESCE(?, preflight_json),
                   ingress_json=COALESCE(?, ingress_json),
                   capability_json=COALESCE(?, capability_json),
                   error_code=COALESCE(?, error_code),
                   retired_at=COALESCE(?, retired_at), updated_at=?
               WHERE handoff_id=? AND attempt_no=?""",
            (
                status, target_session_id, preflight_json, ingress_json,
                capability_json, error_code, retired_at, now,
                handoff_id, attempt_no,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("runtime handoff attempt not found")


def update_runtime_handoff_status(
    handoff_id: str, status: str, *, failure_code: str | None = None
) -> None:
    with _conn() as c:
        cur = c.execute(
            "UPDATE runtime_handoffs SET status=?, failure_code=?, updated_at=? "
            "WHERE handoff_id=?",
            (
                status, failure_code, datetime.now(timezone.utc).isoformat(),
                handoff_id,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError("runtime handoff not found")


def confirm_runtime_handoff(
    *,
    handoff_id: str,
    attempt_no: int,
    expected_source: dict,
    target_session_id: str,
) -> None:
    """Commit target ownership and the operation ledger in one transaction."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        handoff = c.execute(
            "SELECT * FROM runtime_handoffs WHERE handoff_id=?", (handoff_id,)
        ).fetchone()
        if not handoff:
            raise RuntimeError("runtime handoff not found")
        session = c.execute(
            "SELECT model, session_id, backend_type FROM sessions WHERE id=?",
            (handoff["session_id"],),
        ).fetchone()
        actual_source = {
            "runtime": session["backend_type"],
            "model": session["model"],
            "session_id": session["session_id"],
        } if session else None
        if actual_source != expected_source:
            raise RuntimeError("runtime handoff source changed before confirmation")
        if handoff["status"] != "source_released":
            raise RuntimeError("runtime handoff source was not released")
        attempt = c.execute(
            "SELECT * FROM runtime_handoff_attempts "
            "WHERE handoff_id=? AND attempt_no=?",
            (handoff_id, attempt_no),
        ).fetchone()
        if not attempt or attempt["status"] != "capability_validated":
            raise RuntimeError("runtime handoff attempt was not capability validated")
        expected_candidate_sha256 = handoff["packet_sha256"]
        if attempt["mode"] in {"packet_delta", "fallback_packet"}:
            # The delivered candidate is a projection of the ledger packet, so its hash
            # is recomputed here rather than read from the attempt it must verify. The
            # projection is unconditional in `_stage_runtime_handoff_target`, so it must
            # be unconditional here too: a ledger packet the staging step still projects
            # but this one skips would fail confirmation after the source was released.
            from app.runtime_history import (
                build_runtime_delivery_packet,
                build_runtime_packet_fallback,
            )

            packet = build_runtime_delivery_packet(json.loads(handoff["packet_json"]))
            if attempt["mode"] == "fallback_packet":
                packet = build_runtime_packet_fallback(packet)
            expected_candidate_sha256 = packet["integrity"]["canonical_sha256"]
        if attempt["candidate_sha256"] != expected_candidate_sha256:
            raise RuntimeError("runtime handoff attempt hash mismatch")
        if not target_session_id or attempt["target_session_id"] != target_session_id:
            raise RuntimeError("runtime handoff target session mismatch")
        c.execute(
            "UPDATE sessions SET model=?, session_id=?, backend_type=?, "
            "runtime_handoff='', history_import_source=NULL WHERE id=?",
            (
                handoff["target_model"], target_session_id,
                handoff["target_runtime"], handoff["session_id"],
            ),
        )
        c.execute(
            "UPDATE runtime_handoffs SET status='confirmed', "
            "confirmed_attempt_no=?, confirmed_at=?, updated_at=? "
            "WHERE handoff_id=?",
            (attempt_no, now, now, handoff_id),
        )
        c.execute(
            "UPDATE runtime_handoff_attempts SET status='confirmed', updated_at=? "
            "WHERE handoff_id=? AND attempt_no=?",
            (now, handoff_id, attempt_no),
        )


# Sub-agent telemetry columns that upsert may set. Text cols use NULLIF-COALESCE
# (empty from a progress event must NOT wipe a value set by start/end). Numeric
# cols take the incoming value when > 0 (TaskUsage is cumulative → latest wins,
# never summed — session total already counts subagents, see backend_claude).
_SA_TEXT = ("sdk_session_id", "tool_use_id", "description", "task_type",
            "status", "last_tool_name", "output_file", "summary", "raw_json", "ended_at")
_SA_NUM = ("total_tokens", "tool_uses", "duration_ms")


def subagent_upsert(session_id: str, task_id: str, **fields) -> None:
    """Insert or update one sub-agent row (keyed by session_id+task_id).

    start creates the row; progress/end update only the fields they carry.
    Empty text / zero numbers never overwrite an existing value.
    Explicit starts keep the earliest known lifecycle timestamp.
    """
    started_at = fields.get("started_at") or datetime.now(timezone.utc).isoformat()
    cols = ["session_id", "task_id", "started_at"]
    vals = [session_id, task_id, started_at]
    updates = [
        "started_at=CASE WHEN julianday(excluded.started_at) < "
        "julianday(subagents.started_at) THEN excluded.started_at "
        "ELSE subagents.started_at END"
    ]
    for k in _SA_TEXT:
        if k in fields and fields[k] is not None:
            cols.append(k); vals.append(fields[k])
            updates.append(f"{k}=COALESCE(NULLIF(excluded.{k}, ''), subagents.{k})")
    for k in _SA_NUM:
        if k in fields and fields[k]:
            cols.append(k); vals.append(int(fields[k]))
            updates.append(f"{k}=MAX(excluded.{k}, subagents.{k})")
    if fields.get("ended_at") and not fields.get("duration_ms"):
        # local_bash notifications carry no TaskUsage. Preserve SDK duration
        # when present; otherwise derive wall time from the persisted lifecycle.
        updates.append(
            "duration_ms=CASE WHEN subagents.duration_ms > 0 "
            "THEN subagents.duration_ms ELSE MAX(0, CAST("
            "(julianday(excluded.ended_at) - julianday(subagents.started_at)) "
            "* 86400000 AS INTEGER)) END"
        )
    placeholders = ", ".join("?" for _ in cols)
    set_clause = ", ".join(updates) if updates else "task_id=task_id"
    with _conn() as c:
        c.execute(
            f"INSERT INTO subagents ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(session_id, task_id) DO UPDATE SET {set_clause}",
            vals,
        )


def get_subagents(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM subagents WHERE session_id = ? ORDER BY started_at ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_subagent(session_id: str, task_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subagents WHERE session_id = ? AND task_id = ?",
            (session_id, task_id),
        ).fetchone()
        return dict(row) if row else None


def _decode_log_provenance(row: dict) -> dict:
    from app.events import MessageProvenance

    if not isinstance(row.get("origin"), str) or not row["origin"]:
        raise ValueError("stored log provenance origin is missing")
    if "origin_detail" not in row:
        raise ValueError("stored log provenance detail is missing")
    provenance = MessageProvenance.from_storage(
        row["origin"], row["origin_detail"],
    )
    return {
        **row,
        "origin": provenance.origin,
        "origin_detail": provenance.detail(),
    }


def get_logs(session_id: str, after_id: int = 0, limit: int = 5000, conn=None) -> list[dict]:
    c = conn or _conn()
    try:
        if after_id > 0:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (session_id, after_id, limit),
            ).fetchall()
            return [_decode_log_provenance(dict(r)) for r in rows]
        else:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [_decode_log_provenance(dict(r)) for r in reversed(rows)]
    finally:
        if conn is None:
            c.close()


def get_log(log_id: int) -> dict | None:
    """Одна строка журнала целиком, без потолка — за ней приходят по кнопке «загрузить
    целиком», когда обрезанного текста не хватило (#74)."""
    with _conn() as c:
        row = c.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
        return _decode_log_provenance(dict(row)) if row else None


def get_logs_before(session_id: str, before_id: int, limit: int = 500, max_bytes: int = 0,
                    cap: int = 0) -> list[dict]:
    """Страница истории НАЗАД от before_id.

    ``max_bytes > 0`` — потолок на суммарный content ответа (#72). Считать порцию строками
    недостаточно: 25 строк в разных чатах дают от 5.2 до 46.6 КБ gzip, а канал юзера рвёт
    крупные ответы. Первая строка отдаётся всегда, даже если одна перебирает бюджет: иначе
    жирная строка даёт пустой ответ, и клиентский добор зациклится, ни разу не сдвинувшись.

    ``cap > 0`` — потолок на ОДНУ строку, тот же механизм, что у зеркала (#74). Без него
    бюджет выше бессилен против одиночного base64-блоба: у seo-cro такая строка едет одна
    на 507 КБ. Обрезанная строка помечается ``trunc`` и в чате получает видимый маркер.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM logs WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (session_id, before_id, limit),
        ).fetchall()
        out, used = [], 0
        for r in rows:
            # Сперва потолок, потом бюджет: бюджет обязан считать то, что реально поедет,
            # иначе жирная строка съедает его целиком, будучи обрезанной до килобайта.
            decoded = _decode_log_provenance(dict(r))
            d = _cap_content(decoded, cap) if cap else decoded
            size = len((d.get("content") or "").encode())
            if max_bytes and out and used + size > max_bytes:
                break
            out.append(d)
            used += size
        return list(reversed(out))


_SYNC_COLS = (
    "id, session_id, ts, type, content, event_id, "
    "tool_use_id, tool_name, tool_is_error, origin, origin_detail"
)


def _project_image_generation_result(row: dict, cap: int) -> dict | None:
    """Return the useful, bounded part of a persisted ImageGeneration result.

    The PNG already lives at ``saved_path``. Shipping its multi-megabyte base64 field in
    dashboard history both blows the row cap and cuts off the path/prompt stored after it.
    """
    if row.get("type") != "tool_result" or row.get("tool_name") != "ImageGeneration":
        return None
    source = row.get("content") or ""
    try:
        data = json.loads(source)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not any(
        key in data for key in ("saved_path", "revised_prompt", "status")
    ):
        return None

    projected = {
        "status": str(data.get("status") or ""),
        "saved_path": str(data.get("saved_path") or ""),
        "revised_prompt": str(data.get("revised_prompt") or ""),
    }
    encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    if cap and len(encoded.encode()) > cap:
        # Keep valid JSON and the path even when an abnormal revised prompt alone exceeds
        # the row cap. The ordinary byte-prefix truncation would make JSON unparsable again.
        prompt = projected["revised_prompt"].encode()
        projected["revised_prompt"] = ""
        base_size = len(json.dumps(
            projected, ensure_ascii=False, separators=(",", ":"),
        ).encode())
        available = max(0, cap - base_size)
        projected["revised_prompt"] = prompt[:available].decode(errors="ignore")
        encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    if cap and len(encoded.encode()) > cap:
        return None

    row["content"] = encoded
    row["projection"] = "image_generation"
    row["source_bytes"] = len(source.encode())
    row.pop("trunc", None)
    return row


def _cap_content(row: dict, cap: int) -> dict:
    """Обрезать content до cap БАЙТ (не символов) и пометить обрезку.

    Байты, а не символы: бюджет клиентского зеркала считается в байтах, а кириллица
    в UTF-8 даёт 2 байта на символ — по символам потолок уехал бы вдвое. Срез может
    разрубить символ пополам, поэтому errors="ignore".
    """
    projected = _project_image_generation_result(row, cap)
    if projected is not None:
        return projected
    raw = (row.get("content") or "").encode()
    if len(raw) <= cap:
        return row
    row["content"] = raw[:cap].decode(errors="ignore")
    row["trunc"] = len(raw)  # исходная длина в байтах — её показывает кнопка «загрузить целиком»
    return row


def get_logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384) -> dict:
    """Журнал всех сессий всех проектов одним ответом — для зеркала в браузере.

    after_id == 0 — холодный старт: последние ``tail`` строк на каждую сессию.
    ``tail == 0`` — только карта сессий и отметка, без единой строки журнала: зеркало
    наполняется тем, что юзер реально открыл (#72). Раньше клиент просил tail=20 на все
    сессии и получал 145 КБ по проводу ради строк, из которых рисовалось ~5%.
    after_id > 0  — инкремент: всё, что появилось после этой отметки.

    ``live_sessions`` — полный список сессий БЕЗ фильтров, по ``{id, name, scope}``.
    Логи висят на sessions(id) с ON DELETE CASCADE (и foreign_keys=ON), поэтому
    удалённая сессия уносит свой журнал, и клиент обязан это повторить. Отсюда же
    требование к вызывающему: пустой список означает сбой, а не «сессий нет» — по нему
    нельзя вычищать зеркало.

    Имя и scope нужны не для красоты: после F5 браузер знает, какого агента показывать,
    но не знает его session_id, а логи ключуются именно по нему. Сохранённая карта
    имя+scope → id даёт показать историю до первого сетевого ответа.
    """
    with _conn() as c:
        max_log_id = c.execute("SELECT COALESCE(MAX(id), 0) FROM logs").fetchone()[0]
        live = [{"id": r["id"], "name": r["name"], "scope": r["scope"]}
                for r in c.execute("SELECT id, name, scope FROM sessions")]
        if after_id > 0:
            rows = c.execute(
                f"SELECT {_SYNC_COLS} FROM logs WHERE id > ? ORDER BY id ASC",
                (after_id,),
            ).fetchall()
        else:
            rows = c.execute(
                f"""WITH ranked AS (
                        SELECT {_SYNC_COLS},
                               ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY id DESC) rn
                        FROM logs
                    )
                    SELECT {_SYNC_COLS} FROM ranked WHERE rn <= ? ORDER BY id ASC""",
                (tail,),
            ).fetchall()
        return {
            "max_log_id": max_log_id,
            "live_sessions": live,
            "logs": [
                _cap_content(_decode_log_provenance(dict(r)), cap) for r in rows
            ],
        }


def get_stats(scope: str | None = None) -> dict:
    with _conn() as c:
        where = "WHERE scope = ?" if scope else ""
        params = (scope,) if scope else ()
        total = c.execute(f"SELECT COUNT(*) FROM sessions {where}", params).fetchone()[0]
        active = c.execute(
            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
            "status IN ('running', 'starting')",
            params,
        ).fetchone()[0]
        archived = c.execute(
            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
            "status = 'archived'",
            params,
        ).fetchone()[0]
        cost = c.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) FROM sessions {where}", params
        ).fetchone()[0]
        logs_where = (
            f"WHERE session_id IN (SELECT id FROM sessions {where})"
            if where else ""
        )
        total_logs = c.execute(
            f"SELECT COUNT(*) FROM logs {logs_where}", params
        ).fetchone()[0]
        agg = c.execute(
            f"""SELECT COALESCE(SUM(total_turns), 0),
                       COALESCE(SUM(total_input_tokens), 0),
                       COALESCE(SUM(total_output_tokens), 0),
                       COALESCE(SUM(total_tool_calls), 0)
                FROM sessions {where}""",
            params,
        ).fetchone()
        return {
            "total_sessions": total,
            "active": active,
            "archived": archived,
            "total_cost_usd": round(cost, 4),
            "total_logs": total_logs,
            "total_turns": agg[0],
            "total_input_tokens": agg[1],
            "total_output_tokens": agg[2],
            "total_tool_calls": agg[3],
        }


def cleanup_old_logs(days: int = 7) -> int:
    """REMOVED by owner decision — agent history is research data, never delete it.

    Kept as a loud tombstone: this function used to drop `logs` older than 7 days on a
    6-hour timer, which silently destroyed every diary older than a week while `sessions`
    rows survived since May. Any caller is a bug.
    """
    raise RuntimeError(
        "cleanup_old_logs is disabled: agent logs must never be deleted. "
        "If disk pressure is real, export to files first and ask the owner."
    )


# ── Review receipts ──

_REVIEW_RECEIPT_COLUMNS = (
    "receipt_id", "schema_version", "runtime", "reviewer_model", "model_source",
    "session_id", "worker_name", "scope", "task_id", "task_source", "artifact_path",
    "mode", "round", "job_id", "usage_event_id", "requested_at", "completed_at",
    "status", "return_code", "failure_code", "artifact_exists", "artifact_bytes",
    "artifact_sha256", "verdict_present", "verdict_value", "jsonl_response_present",
    "recovery_source",
    "notification_event_id", "subject_kind", "target_sha", "worker_head",
    "requested_by_session_id", "requested_by_worker",
    "policy_ref", "task_stable_id", "task_snapshot_ref",
    "prompt_template_start", "prompt_template_end", "terminal_operation_id",
)
_REVIEW_RECEIPT_SOURCES = frozenset({"direct", "derived", "unknown"})



def task_run_receipt_open(
    *,
    session_id: str,
    worker_name: str,
    scope: str,
    task_id: str,
    task_stable_id: str = "",
    task_snapshot_ref: str = "",
    prompt_template_start: str = "",
    task_source: str = "",
    requested_at: str = "",
    connection: sqlite3.Connection | None = None,
) -> dict:
    """Open one task assignment receipt; identical live replay returns the row."""
    session_id = str(session_id or "").strip()
    worker_name = str(worker_name or "").strip()
    scope = str(scope or "").rstrip("/")
    task_id = str(task_id or "").strip()
    task_stable_id = str(task_stable_id or "").strip()
    task_snapshot_ref = str(task_snapshot_ref or "").strip()
    prompt_template_start = str(prompt_template_start or "").strip()
    task_source = str(task_source or "").strip() or (
        "canonical" if task_stable_id and task_snapshot_ref else "legacy"
    )
    if not session_id or not worker_name or not scope or not task_id:
        raise ValueError("task run requires session, worker, scope, and task id")
    expected = {
        "session_id": session_id,
        "worker_name": worker_name,
        "scope": scope,
        "task_id": task_id,
        "task_source": task_source,
        "task_stable_id": task_stable_id,
        "task_snapshot_ref": task_snapshot_ref,
        "prompt_template_start": prompt_template_start,
    }
    owner = nullcontext(connection) if connection is not None else _conn()
    with owner as c:
        if connection is None:
            c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
            "AND session_id=? AND status='requested' ORDER BY requested_at DESC",
            (session_id,),
        ).fetchall()
        if len(existing) > 1:
            raise ValueError(f"session '{session_id}' has multiple open task runs")
        if existing:
            saved = dict(existing[0])
            if any(str(saved[key] or "") != value for key, value in expected.items()):
                raise ValueError("open task run conflicts with current assignment provenance")
            return saved
        from app.work_review import ASSIGNMENT_VERSION

        values = {key: None for key in _REVIEW_RECEIPT_COLUMNS}
        values.update({
            "receipt_id": f"task-run:{uuid4()}",
            "schema_version": ASSIGNMENT_VERSION,
            "runtime": "",
            "reviewer_model": "",
            "model_source": "unknown",
            **expected,
            "artifact_path": "",
            "mode": "task_run",
            "round": None,
            "job_id": "",
            "usage_event_id": "",
            "requested_at": requested_at or datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "status": "requested",
            "return_code": None,
            "failure_code": "",
            "artifact_exists": None,
            "artifact_bytes": None,
            "artifact_sha256": "",
            "verdict_present": None,
            "verdict_value": "",
            "jsonl_response_present": None,
            "recovery_source": "",
            "notification_event_id": "",
            "subject_kind": "task_run",
            "target_sha": "",
            "worker_head": "",
            "requested_by_session_id": "",
            "requested_by_worker": "",
            "policy_ref": "",
            "prompt_template_end": "",
            "terminal_operation_id": "",
        })
        columns = ", ".join(_REVIEW_RECEIPT_COLUMNS)
        placeholders = ", ".join("?" for _ in _REVIEW_RECEIPT_COLUMNS)
        try:
            c.execute(
                f"INSERT INTO review_receipts ({columns}) VALUES ({placeholders})",
                tuple(values[key] for key in _REVIEW_RECEIPT_COLUMNS),
            )
        except sqlite3.IntegrityError as error:
            replay = c.execute(
                "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
                "AND session_id=? AND status='requested'",
                (session_id,),
            ).fetchone()
            if replay is None:
                raise ValueError("task run conflicts with another open assignment") from error
            saved = dict(replay)
            if any(str(saved[key] or "") != value for key, value in expected.items()):
                raise ValueError("open task run conflicts with current assignment provenance") from error
            return saved
        return dict(c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?",
            (values["receipt_id"],),
        ).fetchone())


def task_run_receipt_finish(
    *,
    session_id: str,
    task_id: str,
    status: str,
    prompt_template_end: str,
    terminal_operation_id: str = "",
    failure_code: str = "",
    connection: sqlite3.Connection | None = None,
) -> dict:
    """Finish the single open task run; identical terminal replay is safe."""
    if status not in {"completed", "interrupted"}:
        raise ValueError("task run terminal status must be completed or interrupted")
    terminal_operation_id = str(terminal_operation_id or "")
    prompt_template_end = str(prompt_template_end or "")
    failure_code = str(failure_code or "")
    owner = nullcontext(connection) if connection is not None else _conn()
    with owner as c:
        if connection is None:
            c.execute("BEGIN IMMEDIATE")
        if terminal_operation_id:
            replay = c.execute(
                "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
                "AND session_id=? AND task_id=? AND terminal_operation_id=?",
                (session_id, str(task_id), terminal_operation_id),
            ).fetchone()
            if replay is not None:
                saved = dict(replay)
                if (
                    saved["status"] == status
                    and str(saved["prompt_template_end"] or "") == prompt_template_end
                    and str(saved["failure_code"] or "") == failure_code
                ):
                    return saved
                raise ValueError("task run operation already has a different outcome")
        rows = c.execute(
            "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
            "AND session_id=? AND task_id=? AND status='requested'",
            (session_id, str(task_id)),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("multiple open task runs match one assignment")
        if not rows:
            prior = c.execute(
                "SELECT * FROM review_receipts WHERE subject_kind='task_run' "
                "AND session_id=? AND task_id=? ORDER BY requested_at DESC LIMIT 1",
                (session_id, str(task_id)),
            ).fetchone()
            if prior is None:
                raise LookupError("open task run not found")
            saved = dict(prior)
            if (
                saved["status"] == status
                and str(saved["prompt_template_end"] or "") == prompt_template_end
                and str(saved["terminal_operation_id"] or "") == terminal_operation_id
                and str(saved["failure_code"] or "") == failure_code
            ):
                return saved
            raise ValueError("task run already has a different terminal outcome")
        receipt_id = rows[0]["receipt_id"]
        c.execute(
            "UPDATE review_receipts SET status=?,completed_at=?,failure_code=?,"
            "prompt_template_end=?,terminal_operation_id=? "
            "WHERE receipt_id=? AND status='requested'",
            (
                status,
                datetime.now(timezone.utc).isoformat(),
                failure_code,
                prompt_template_end,
                terminal_operation_id,
                receipt_id,
            ),
        )
        return dict(c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,),
        ).fetchone())



def _require_bound_task_run_for_review(
    connection: sqlite3.Connection,
    receipt: dict,
) -> None:
    if receipt.get("subject_kind") != "implementation" or not receipt.get("task_id"):
        return
    bound = connection.execute(
        "SELECT 1 FROM sessions s JOIN tm_projects p "
        "ON RTRIM(p.scope,'/')=RTRIM(s.scope,'/') "
        "JOIN tm_tasks t ON t.project_id=p.id "
        "AND (CASE WHEN t.ref_prefix='' THEN '' ELSE t.ref_prefix || '-' END || CAST(t.par_number AS TEXT))=s.task_id "
        "WHERE s.id=? AND s.status!='archived' AND s.task_id=? "
        "AND t.status='in_progress' AND t.worker_session_id=s.id",
        (receipt["session_id"], str(receipt["task_id"])),
    ).fetchone()
    if bound is None:
        return
    runs = connection.execute(
        "SELECT receipt_id FROM review_receipts WHERE subject_kind='task_run' "
        "AND session_id=? AND task_id=? AND status='requested'",
        (receipt["session_id"], str(receipt["task_id"])),
    ).fetchall()
    if len(runs) != 1:
        raise ValueError(
            "implementation review requires exactly one open task-run receipt"
        )


def review_receipt_create(receipt: dict) -> bool:
    """Insert one immutable review start receipt; duplicate ids are replay-safe."""
    if not isinstance(receipt, dict):
        raise TypeError("review receipt must be a dict")
    missing = [
        key for key in (
            "receipt_id", "runtime", "reviewer_model", "model_source", "session_id",
            "worker_name", "scope", "task_id", "task_source", "artifact_path", "mode",
            "job_id", "usage_event_id", "status",
        ) if key not in receipt
    ]
    if missing:
        raise ValueError("review receipt missing fields: " + ", ".join(missing))
    if receipt["model_source"] not in _REVIEW_RECEIPT_SOURCES:
        raise ValueError("invalid review receipt model_source")
    values = {key: receipt.get(key) for key in _REVIEW_RECEIPT_COLUMNS}
    values["schema_version"] = int(values["schema_version"] or 1)
    values["round"] = None if values["round"] is None else int(values["round"])
    values["status"] = values["status"] or "requested"
    values["requested_at"] = values["requested_at"] or datetime.now(timezone.utc).isoformat()
    values["failure_code"] = values["failure_code"] or ""
    values["artifact_sha256"] = values["artifact_sha256"] or ""
    values["verdict_value"] = values["verdict_value"] or ""
    values["recovery_source"] = values["recovery_source"] or ""
    values["notification_event_id"] = values["notification_event_id"] or ""
    values["subject_kind"] = values["subject_kind"] or "unknown"
    values["target_sha"] = values["target_sha"] or ""
    values["worker_head"] = values["worker_head"] or ""
    values["requested_by_session_id"] = values["requested_by_session_id"] or ""
    values["requested_by_worker"] = values["requested_by_worker"] or ""
    values["policy_ref"] = values["policy_ref"] or ""
    values["task_stable_id"] = values["task_stable_id"] or ""
    values["task_snapshot_ref"] = values["task_snapshot_ref"] or ""
    values["prompt_template_start"] = values["prompt_template_start"] or ""
    values["prompt_template_end"] = values["prompt_template_end"] or ""
    values["terminal_operation_id"] = values["terminal_operation_id"] or ""
    placeholders = ", ".join("?" for _ in _REVIEW_RECEIPT_COLUMNS)
    columns = ", ".join(_REVIEW_RECEIPT_COLUMNS)
    with _conn() as c:
        cursor = c.execute(
            f"INSERT INTO review_receipts ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT(receipt_id) DO NOTHING",
            tuple(values[key] for key in _REVIEW_RECEIPT_COLUMNS),
        )
        if cursor.rowcount == 0:
            existing = c.execute(
                "SELECT * FROM review_receipts WHERE receipt_id=?",
                (values["receipt_id"],),
            ).fetchone()
            if existing is None or any(
                existing[key] != values[key] for key in _REVIEW_RECEIPT_COLUMNS
            ):
                raise ValueError("review receipt id conflicts with existing provenance")
        return cursor.rowcount == 1


def review_receipt_get(receipt_id: str) -> dict | None:
    if not receipt_id:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?", (receipt_id,)
        ).fetchone()
    return dict(row) if row else None




def review_receipt_reserve(receipt: dict) -> dict:
    """Allocate the next artifact round and insert its start receipt atomically."""
    if not isinstance(receipt, dict):
        raise TypeError("review receipt must be a dict")
    artifact_path = str(receipt.get("artifact_path") or "")
    if not artifact_path:
        raise ValueError("review receipt artifact_path is required")
    values = dict(receipt)
    values["round"] = None
    values.setdefault("schema_version", 1)
    values.setdefault("requested_at", datetime.now(timezone.utc).isoformat())
    values.setdefault("status", "requested")
    values.setdefault("failure_code", "")
    values.setdefault("artifact_sha256", "")
    values.setdefault("verdict_value", "")
    values.setdefault("recovery_source", "")
    values.setdefault("notification_event_id", "")
    values.setdefault("subject_kind", "unknown")
    values.setdefault("target_sha", "")
    values.setdefault("worker_head", "")
    values.setdefault("requested_by_session_id", "")
    values.setdefault("requested_by_worker", "")
    values.setdefault("policy_ref", "")
    values.setdefault("task_stable_id", "")
    values.setdefault("task_snapshot_ref", "")
    values.setdefault("prompt_template_start", "")
    values.setdefault("prompt_template_end", "")
    values.setdefault("terminal_operation_id", "")
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        _require_bound_task_run_for_review(c, values)
        from app.work_review import reserve_budget
        reserve_budget(c, values)
        row = c.execute(
            "SELECT COALESCE(MAX(round), 0) FROM review_receipts WHERE artifact_path=?",
            (artifact_path,),
        ).fetchone()
        values["round"] = int(row[0] or 0) + 1
        placeholders = ", ".join("?" for _ in _REVIEW_RECEIPT_COLUMNS)
        columns = ", ".join(_REVIEW_RECEIPT_COLUMNS)
        c.execute(
            f"INSERT INTO review_receipts ({columns}) VALUES ({placeholders})",
            tuple(values.get(key) for key in _REVIEW_RECEIPT_COLUMNS),
        )
        saved = c.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?",
            (values["receipt_id"],),
        ).fetchone()
    return dict(saved)


def review_receipt_finish(receipt_id: str, updates: dict) -> bool:
    """Record terminal execution facts without allowing start provenance to drift."""
    allowed = {
        "job_id", "completed_at", "status", "return_code", "failure_code",
        "artifact_exists", "artifact_bytes", "artifact_sha256", "verdict_present",
        "verdict_value", "jsonl_response_present", "recovery_source",
        "notification_event_id",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError("review receipt terminal fields not allowed: " + ", ".join(sorted(unknown)))
    if updates.get("status") not in {None, "requested", "completed", "failed", "timed_out", "interrupted"}:
        raise ValueError("invalid review receipt status")
    if not updates:
        return False
    assignments = ", ".join(f"{key}=?" for key in updates)
    with _conn() as c:
        cursor = c.execute(
            f"UPDATE review_receipts SET {assignments} WHERE receipt_id=?",
            tuple(updates[key] for key in updates) + (receipt_id,),
        )
        return cursor.rowcount == 1




# ── Background Jobs ──

def bg_save_job(job: dict) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO bg_jobs (id, type, config, message, target_session_id,
                target_name, target_scope, created_by_name, status, expires_at,
                trigger_at, created_at, last_output)
            VALUES (:id, :type, :config, :message, :target_session_id,
                :target_name, :target_scope, :created_by_name, :status, :expires_at,
                :trigger_at, :created_at, :last_output)
        """, job)


def bg_replace_job(job: dict, replace_key: str) -> list[str]:
    """Atomically cancel an earlier keyed job and insert its replacement."""
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT id FROM bg_jobs "
            "WHERE status IN ('active','triggering') "
            "AND json_extract(config, '$.replace_key')=?",
            (replace_key,),
        ).fetchall()
        replaced_ids = [row["id"] for row in rows]
        if replaced_ids:
            placeholders = ",".join("?" for _ in replaced_ids)
            c.execute(
                f"UPDATE bg_jobs SET status='cancelled' "
                f"WHERE id IN ({placeholders})",
                replaced_ids,
            )
        c.execute("""
            INSERT INTO bg_jobs (id, type, config, message, target_session_id,
                target_name, target_scope, created_by_name, status, expires_at,
                trigger_at, created_at, last_output)
            VALUES (:id, :type, :config, :message, :target_session_id,
                :target_name, :target_scope, :created_by_name, :status, :expires_at,
                :trigger_at, :created_at, :last_output)
        """, job)
        c.execute("COMMIT")
        return replaced_ids


def bg_cron_should_fire(job_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM bg_jobs WHERE id=? AND status='active' AND expires_at >= ?",
            (job_id, now),
        ).fetchone()
        return row is not None


def bg_cron_record_fire(job_id: str) -> None:
    # IMMEDIATE lock: prevents two scheduler ticks from recording the same fire
    # (cron jobs can fire again while the previous trigger is still being processed)
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT config, status FROM bg_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "active":
            c.execute("ROLLBACK")
            return
        try:
            cfg = json.loads(row["config"])
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        cfg["last_fired_at"] = now_iso
        cfg["fire_count"] = cfg.get("fire_count", 0) + 1
        c.execute(
            "UPDATE bg_jobs SET config=?, last_output=? WHERE id=? AND status='active'",
            (json.dumps(cfg), f"fired #{cfg['fire_count']} at {now_iso}", job_id),
        )
        c.execute("COMMIT")


def bg_claim_trigger(job_id: str) -> bool:
    # Atomic CAS: only one concurrent checker can move job to 'triggering' —
    # multiple scheduler ticks could race here without this guard
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='triggering', triggered_at=? WHERE id=? AND status='active'",
            (datetime.now(timezone.utc).isoformat(), job_id),
        )
        return cur.rowcount > 0


def bg_get_job(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM bg_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def bg_finish_trigger(job_id: str, last_output: str = "") -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='triggered', last_output=? WHERE id=?",
            (last_output[-3000:], job_id),
        )


def bg_fail_job(job_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='failed', error=? WHERE id=? AND status IN ('active','triggering')",
            (error[:1000], job_id),
        )


def bg_fail_job_if_active(job_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='failed', error=? WHERE id=? AND status='active'",
            (error[:1000], job_id),
        )


def bg_cancel_job(job_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='cancelled' WHERE id=? AND status='active'",
            (job_id,),
        )
        return cur.rowcount > 0


def bg_expire_job(job_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='expired' WHERE id=? AND status='active'",
            (job_id,),
        )
        return cur.rowcount > 0


def bg_update_output(job_id: str, output: str) -> None:
    with _conn() as c:
        c.execute("UPDATE bg_jobs SET last_output=? WHERE id=?", (output[-3000:], job_id))


def bg_update_config(job_id: str, config: dict, output: str = "") -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET config=?, last_output=? "
            "WHERE id=? AND status='triggering'",
            (json.dumps(config), output[-3000:], job_id),
        )
        return cur.rowcount > 0


def bg_get_jobs(scope: str | None = None, session_id: str | None = None,
                active_only: bool = False) -> list[dict]:
    with _conn() as c:
        clauses, params = [], []
        if scope:
            clauses.append("target_scope = ?")
            params.append(scope)
        if session_id:
            clauses.append("target_session_id = ?")
            params.append(session_id)
        if active_only:
            clauses.append("status IN ('active','triggering')")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = c.execute(
            f"SELECT * FROM bg_jobs {where} ORDER BY created_at DESC LIMIT 50", params
        ).fetchall()
        return [dict(r) for r in rows]


def bg_cancel_by_session(session_id: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='cancelled' WHERE target_session_id=? AND status='active'",
            (session_id,),
        )
        return cur.rowcount


def bg_get_active_all() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM bg_jobs WHERE status IN ('active','triggering')"
        ).fetchall()
        return [dict(r) for r in rows]


def bg_expire_overdue() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='active' AND expires_at < ?", (now,)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE bg_jobs SET status='expired' WHERE id IN ({placeholders})", ids)
        stale = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' AND triggered_at < ?",
            ((datetime.now(timezone.utc).replace(second=0, microsecond=0)).isoformat(),),
        ).fetchall()
        return ids + [r["id"] for r in stale]


def bg_reset_stale_triggering() -> list[str]:
    """Зовётся только при старте, где ЛЮБОЙ 'triggering' — сирота: процесс, забравший
    его через bg_claim_trigger, мёртв. Порог по возрасту оставлял джоб, чей триггер
    убит рестартом секунды назад, в 'triggering' навсегда: никто больше этот статус
    не трогает, а слот scope он занимать продолжает.
    """
    with _conn() as c:
        rows = c.execute("SELECT id FROM bg_jobs WHERE status='triggering'").fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})", ids)
        return ids


def bg_reset_wake_triggering() -> list[str]:
    """Wake batches are safe to replay because each target turn is revalidated."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' "
            "AND json_extract(config, '$.action')='wake_subscription_limited'"
        ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(
                f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})",
                ids,
            )
        return ids


def bg_count_active(scope: str) -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM bg_jobs WHERE target_scope=? AND status IN ('active','triggering')",
            (scope,),
        ).fetchone()[0]


def bg_cleanup_old(max_age_hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM bg_jobs WHERE status IN ('triggered','expired','cancelled','failed') AND created_at < ?",
            (cutoff,),
        )
        return cur.rowcount


def tool_error_add(
    session_name: str,
    scope: str,
    tool_name: str,
    error_text: str,
    *,
    runtime: str = "unknown",
    tool_use_id: str = "",
) -> bool:
    """Atomically record one bounded tool failure; return false on replay."""
    with _conn() as c:
        cursor = c.execute(
            """INSERT OR IGNORE INTO tool_errors
               (session_name, scope, tool_name, error_text, runtime, tool_use_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_name,
                scope,
                tool_name or "unknown",
                str(error_text or "")[:4000],
                runtime or "unknown",
                tool_use_id or "",
            ),
        )
        return cursor.rowcount == 1


def turn_usage_add(
    *,
    event_id: str,
    session_id: str,
    scope: str = "",
    task_id: str = "",
    runtime: str,
    model: str,
    ok: bool,
    stop_reason: str,
    cost_usd: float | None,
    cost_unaccounted: bool = False,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_create_tokens: int,
    quota_five_hour_pct: float | None = None,
    quota_seven_day_pct: float | None = None,
    quota_primary_pct: float | None = None,
    quota_sampled_at: str | None = None,
    ts: str | None = None,
) -> bool:
    """Persist one provider-identified terminal turn; return false on replay."""
    if not event_id:
        return False
    quota_pcts = (
        quota_five_hour_pct,
        quota_seven_day_pct,
        quota_primary_pct,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 100
        for value in quota_pcts
        if value is not None
    ):
        raise ValueError("quota percentages must be finite numbers from 0 to 100")
    if any(value is not None for value in quota_pcts) and not quota_sampled_at:
        raise ValueError("quota_sampled_at is required with quota percentages")
    if all(value is None for value in quota_pcts):
        quota_sampled_at = None
    observed_at = ts or datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cursor = c.execute(
            """INSERT OR IGNORE INTO turn_usage
               (event_id, ts, session_id, scope, task_id,
                runtime, model, ok, stop_reason,
                cost_usd, cost_unaccounted, input_tokens, output_tokens,
                cache_read_tokens, cache_create_tokens,
                quota_five_hour_pct, quota_seven_day_pct,
                quota_primary_pct, quota_sampled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                observed_at,
                session_id,
                scope,
                task_id,
                runtime,
                model,
                int(bool(ok)),
                stop_reason,
                None if cost_unaccounted else max(0.0, float(cost_usd or 0)),
                int(bool(cost_unaccounted)),
                max(0, int(input_tokens or 0)),
                max(0, int(output_tokens or 0)),
                max(0, int(cache_read_tokens or 0)),
                max(0, int(cache_create_tokens or 0)),
                quota_five_hour_pct,
                quota_seven_day_pct,
                quota_primary_pct,
                quota_sampled_at,
            ),
        )
        return cursor.rowcount == 1


# ── Usage Snapshots ──

def voice_cost_add(session_name: str, scope: str, duration_sec: float,
                   cost_usd: float, file_id: str, model: str = "nova-3") -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO voice_costs
               (ts, session_name, scope, duration_sec, cost_usd, model, file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), session_name, scope,
             duration_sec, cost_usd, model, file_id),
        )


def voice_cost_total_usd() -> float:
    with _conn() as c:
        return float(c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM voice_costs"
        ).fetchone()[0])


def usage_save_snapshot(five_hour_pct: float | None, seven_day_pct: float | None,
                        five_hour_resets_at: str, seven_day_resets_at: str,
                        total_cost_usd: float, active_agents: int,
                        providers: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             five_hour_pct, seven_day_pct,
             five_hour_resets_at or "", seven_day_resets_at or "",
             total_cost_usd, active_agents,
             json.dumps(providers or {}, ensure_ascii=False)),
        )


def usage_exchange_rate(hours: int = 72, min_five_hour_pct: float = 30.0) -> dict | None:
    """Сколько п.п. недельного окна съедает 1 п.п. пятичасового — по своей же истории (#162)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, five_hour_pct, seven_day_pct, five_hour_resets_at, seven_day_resets_at"
            " FROM usage_snapshots WHERE ts > ? ORDER BY ts ASC", (cutoff,)
        ).fetchall()
    clean = []
    for row in rows:
        if row["five_hour_pct"] is None or row["seven_day_pct"] is None:
            continue
        if (row["five_hour_pct"] == 0 and row["seven_day_pct"] == 0
                and not (row["five_hour_resets_at"] or "")
                and not (row["seven_day_resets_at"] or "")):
            continue
        clean.append((datetime.fromisoformat(row["ts"]),
                      float(row["five_hour_pct"]), float(row["seven_day_pct"])))
    five = seven = 0.0
    for (t1, a5, a7), (t2, b5, b7) in zip(clean, clean[1:]):
        if (t2 - t1).total_seconds() > 1800:
            continue
        five += max(0.0, b5 - a5)
        seven += max(0.0, b7 - a7)
    if five < min_five_hour_pct or seven <= 0:
        return None
    return {"rate": seven / five, "five_hour_pct_sum": five,
            "seven_day_pct_sum": seven, "window_hours": hours}


def _usage_providers_from_row(row: dict) -> dict:
    providers = json.loads(row.pop("provider_usage", "{}") or "{}")
    if providers:
        return providers
    windows = []
    # NULL в колонке = источник молчал (#150). Окно без числа — не точка данных:
    # отдать его с `utilization: None` значило бы переложить ноль на потребителя.
    fh_pct, sd_pct = row.get("five_hour_pct"), row.get("seven_day_pct")
    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct):
        windows.append({
            "id": "five_hour", "label": "5h",
            "utilization": fh_pct,
            "window_minutes": 300,
            "resets_at": row.get("five_hour_resets_at") or None,
        })
    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct):
        windows.append({
            "id": "seven_day", "label": "7d",
            "utilization": sd_pct,
            "window_minutes": 10080,
            "resets_at": row.get("seven_day_resets_at") or None,
        })
    return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}


def usage_history_oldest_ts() -> str:
    """Время самого первого снимка — по нему фронт понимает, есть ли что грузить дальше."""
    with _conn() as c:
        row = c.execute("SELECT ts FROM usage_snapshots ORDER BY id ASC LIMIT 1").fetchone()
        return row["ts"] if row else ""


def usage_history_ts_before(ts: str) -> str:
    """Ближайший снимок старше ts. Окно навигации привязано к данным, а не к календарю."""
    with _conn() as c:
        row = c.execute(
            "SELECT ts FROM usage_snapshots WHERE ts < ? ORDER BY ts DESC LIMIT 1", (ts,)
        ).fetchone()
        return row["ts"] if row else ""


def usage_get_history(hours: int = 24, step_minutes: int = 5, until: str = "") -> list[dict]:
    # until — правая граница окна, исключительно: фронт передаёт время самой старой
    # уже загруженной точки, и следующий кусок обязан к ней примыкать, а не дублировать её.
    end = datetime.fromisoformat(until) if until else datetime.now(timezone.utc)
    cutoff = (end - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM usage_snapshots WHERE ts > ? AND ts < ? ORDER BY ts ASC",
            (cutoff, end.isoformat()),
        ).fetchall()
        raw = []
        for db_row in rows:
            row = dict(db_row)
            row["providers"] = _usage_providers_from_row(row)
            raw.append(row)
    if not raw:
        return []
    step = timedelta(minutes=step_minutes)
    # Дольше двух шагов тянуть последнее значение нельзя: снимки регулярно
    # прерываются на часы (ночь, рестарт), и forward-fill рисовал ровную линию
    # там, где данных не было вовсе. Точку не выдаём — на графике будет разрыв.
    stale_limit = step * 2
    start = datetime.fromisoformat(raw[0]["ts"]).replace(tzinfo=timezone.utc)
    grid: list[dict] = []
    ri = 0
    t = start
    prev = raw[0]
    prev_ts = start
    while t < end:
        # Step-forward interpolation: for each grid point, use the last known
        # snapshot at or before that time — matches "last-value" chart semantics
        while ri < len(raw) - 1:
            next_ts = datetime.fromisoformat(raw[ri + 1]["ts"]).replace(tzinfo=timezone.utc)
            if next_ts > t:
                break
            ri += 1
            prev = raw[ri]
            prev_ts = next_ts
        if t - prev_ts <= stale_limit:
            grid.append({**prev, "ts": t.isoformat()})
        t += step
    if not grid or grid[-1].get("id") != raw[-1].get("id"):
        grid.append(raw[-1])
    return grid


# ── Test Lock ──

def _same_lock_holder(row, holder: str, holder_session_id: str) -> bool:
    """Тот же держатель?

    По НЕИЗМЕНЯЕМОМУ id, когда он известен обеим сторонам: имя агента меняется
    `rename_worker` и может быть занято другим агентом — тогда сравнение по строке либо
    не даёт снять свой лок, либо даёт снять ЧУЖОЙ. Строка от старого сервера id не имеет,
    и для неё остаётся сравнение по имени — иначе живой лок стал бы неснимаемым в окне
    между мержем и рестартом.
    """
    stored_id = row["holder_session_id"] if "holder_session_id" in row.keys() else ""
    if stored_id and holder_session_id:
        return stored_id == holder_session_id
    return row["holder"] == holder


def acquire_test_lock(scope: str, holder: str, reason: str = "",
                      holder_session_id: str = "") -> tuple[bool, str | None]:
    """Захватить глобальный тест-лок для scope.

    Возвращает (ok, current_holder):
    - (True, None)   — лок свободен, захвачен
    - (True, holder) — лок уже за этим же держателем (идемпотентно), reason обновлён
    - (False, name)  — занят другим, name = текущий держатель
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        if row is not None:
            if _same_lock_holder(row, holder, holder_session_id):
                # Имя держателя могло смениться с момента захвата — показываем текущее.
                c.execute(
                    "UPDATE test_lock SET holder = ?, holder_session_id = ?, reason = ?, "
                    "acquired_at = ? WHERE scope = ?",
                    (holder, holder_session_id or row["holder_session_id"], reason, now, scope),
                )
                return True, holder
            return False, row["holder"]
        c.execute(
            "INSERT INTO test_lock (scope, holder, holder_session_id, reason, acquired_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (scope, holder, holder_session_id, reason, now),
        )
        return True, None


def release_test_lock(scope: str, holder: str, holder_session_id: str = "") -> bool:
    """Освободить лок. True — освобождён (был за этим держателем); False — не держатель."""
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        if row is None or not _same_lock_holder(row, holder, holder_session_id):
            return False
        cur = c.execute("DELETE FROM test_lock WHERE scope = ?", (scope,))
        return cur.rowcount > 0


def get_test_lock(scope: str) -> dict | None:
    """Текущий держатель лока для scope или None."""
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        return dict(row) if row else None


def find_merge_proof(scope: str, branch: str) -> dict | None:
    """Доказательство, что ветка УЖЕ слита в базу (#61).

    После сквош-мержа git этого доказать не может: предок не сохраняется, а сравнение
    деревьев (`branch_content_status`) даёт «конфликт», как только база правит те же
    строки. Единственный надёжный источник — наша собственная запись об операции.

    Возвращает {"heads": [...], "operation_id": ...} с головами, на которых мерж
    состоялся: принятой при приёме операции и фактически слитой (они расходятся, когда
    воркер дописал коммит во время ожидания хода — BENIGN_ADVANCE из #17).
    """
    scope = (scope or "").rstrip("/")
    with _conn() as c:
        row = c.execute(
            """SELECT operation_id, accepted_worker_head, result_json
                 FROM merge_operations
                WHERE scope = ? AND accepted_worker_branch = ?
                  AND state = 'SUCCEEDED' AND commit_point = 'REACHED'
                ORDER BY rowid DESC LIMIT 1""",
            (scope, branch),
        ).fetchone()
    if not row:
        return None
    heads = {row["accepted_worker_head"]}
    try:
        merged = (json.loads(row["result_json"]).get("git") or {}).get("worker_head")
    except (ValueError, TypeError, AttributeError):
        merged = None
    if merged:
        heads.add(merged)
    return {"operation_id": row["operation_id"], "heads": sorted(h for h in heads if h)}


# Потолок фактов на сессию. Цифра НЕ измерена: недоставки редки по построению, мерить
# было бы не на чем. Переполнение не отбрасывается молча — оно сворачивается в видимую
# строку, поэтому реальный масштаб станет виден на первом же инциденте (#50).
FACTS_PER_SESSION = 20


def enqueue_fact(session_id: str, dedupe_key: str, text: str) -> bool:
    """Поставить в очередь ФАКТ недоставки для сессии. Повтор того же события — не дубль.

    Очередь durable намеренно: недоставка и рестарт — один и тот же сценарий, и очередь
    в памяти (`_pending_messages`, P1 из #35) терялась бы ровно тогда, когда нужна.
    """
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO undelivered_facts (session_id, dedupe_key, text, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id, dedupe_key) DO NOTHING""",
            (session_id, dedupe_key, text, datetime.now(timezone.utc).isoformat()),
        )
        return cur.rowcount == 1


def peek_facts(session_id: str, limit: int = FACTS_PER_SESSION) -> dict:
    """Факты для показа агенту: последние `limit` плюс число свёрнутых старых.

    Ключи возвращаются ВСЕ, включая свёрнутые: их существование агенту сообщено, значит
    гасить надо и их — иначе счётчик «и ещё N» рос бы вечно.
    """
    with _conn() as c:
        rows = c.execute(
            """SELECT dedupe_key, text, created_at FROM undelivered_facts
                WHERE session_id = ? ORDER BY id""",
            (session_id,),
        ).fetchall()
    if not rows:
        return {"facts": [], "collapsed": 0, "keys": []}
    shown = rows[-limit:] if limit > 0 else []
    return {
        "facts": [{"text": r["text"], "created_at": r["created_at"]} for r in shown],
        "collapsed": len(rows) - len(shown),
        "keys": [r["dedupe_key"] for r in rows],
    }


def ack_facts(session_id: str, keys: list[str]) -> int:
    """Погасить факты, которые ДОШЛИ. Зовётся только после возврата из backend.send."""
    if not keys:
        return 0
    with _conn() as c:
        cur = c.execute(
            f"DELETE FROM undelivered_facts WHERE session_id = ? AND dedupe_key IN "
            f"({','.join('?' * len(keys))})",
            (session_id, *keys),
        )
        return cur.rowcount


def clear_consumed_handover(session_id: str) -> None:
    """Do not replay a previous supervisor's buffered bytes on a later crash."""
    with _conn() as c:
        c.execute("UPDATE sessions SET active_turn_id = '', leftover = '' WHERE id = ?",
                  (session_id,))


def save_backend_identity(session_id: str, cli_pid: int, cli_started_at: int) -> None:
    """Persist process identity without overwriting a graceful handover's buffered turn."""
    with _conn() as c:
        updated = c.execute(
            "UPDATE sessions SET cli_pid = ?, cli_started_at = ? WHERE id = ?",
            (int(cli_pid or 0), int(cli_started_at or 0), session_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError(f"cannot publish CLI identity: session {session_id} is missing")



def save_handover_state(session_id: str, active_turn_id: str, leftover: str,
                        cli_pid: int = 0, cli_started_at: int = 0) -> None:
    """Persist what an adopted turn needs to be picked up by the next generation (#230 T4).

    `leftover` is the bytes already consumed out of the kernel pipe into our userspace buffer:
    everything still IN the pipe survives the restart by itself (measured — research F3), these
    do not, so they travel through the DB or they are lost.
    """
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET active_turn_id = ?, leftover = ?, cli_pid = ?, "
            "cli_started_at = ? WHERE id = ?",
            (active_turn_id or "", leftover or "", int(cli_pid or 0),
             int(cli_started_at or 0), session_id),
        )
