"""Durable end-of-turn signal from a worker to its parent (V-680).

A worker turn can end without the worker having told its parent anything: an explicit
DONE never sent, a provider error, a dead listener, a restart of Orchestra. The parent
used to cover that with a self-armed `idle` watcher. Instead the platform records the
fact in the same place the turn ends and delivers it itself.

One row per (worker session, turn): `signal_key` is UNIQUE, so however many code paths
notice the same turn ending, the parent is woken for it once. The row survives restart;
a sweeper delivers pending rows with backoff until the parent accepts them. Rows that
fall due together for one parent go out as one message — a restart ends many turns at
once and each wake-up of an orchestrator is a paid turn.

Delivery is at-least-once with a probe of the parent's log for the row's ref before a
resend, so a crash between "parent accepted" and "row marked" does not repeat the message.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app import db
from app.errtext import err_text
from app.events import MessageProvenance

logger = logging.getLogger("orchestra.turn_signals")

#: Distinguishes this process's in-memory turn counters from a previous process's.
BOOT_ID = uuid.uuid4().hex

SWEEP_INTERVAL_S = 30.0
RETRY_BASE_S = 30.0
RETRY_MAX_S = 900.0
SEND_TIMEOUT_S = 120.0

_DDL = """
CREATE TABLE IF NOT EXISTS turn_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_key TEXT NOT NULL UNIQUE,
    worker_session_id TEXT NOT NULL,
    worker_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    turn_ok INTEGER NOT NULL,
    stop_reason TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','delivered','dropped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    delivered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_turn_signals_pending ON turn_signals(next_attempt_at)
    WHERE state = 'pending';
"""

_inflight: set[int] = set()
_sweeper: asyncio.Task | None = None


def ensure_schema() -> None:
    with db._conn() as connection:
        connection.executescript(_DDL)


def make_key(session, worker_name: str) -> str:
    """Identity of the turn that just ended, stable across code paths, unique across boots."""
    if session is not None:
        return f"{session.id}:{BOOT_ID}:{getattr(session, '_turn_gen', 0)}"
    return f"{worker_name}:{BOOT_ID}:notrack:{time.time_ns()}"


def record(
    *, key: str, worker_session_id: str, worker_name: str, scope: str,
    turn_ok: bool, stop_reason: str, summary: str,
) -> int | None:
    """Persist the fact. Returns the row id, or None when this turn is already recorded."""
    ensure_schema()
    with db._conn() as connection:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO turn_signals
               (signal_key, worker_session_id, worker_name, scope, turn_ok,
                stop_reason, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, worker_session_id, worker_name, scope, int(bool(turn_ok)),
             stop_reason or "", summary or "", time.time()),
        )
        return int(cursor.lastrowid) if cursor.rowcount else None


def _backoff(attempts: int) -> float:
    return min(RETRY_BASE_S * (2 ** max(0, attempts - 1)), RETRY_MAX_S)


def _due(only_ids: list[int] | None) -> list[dict]:
    ensure_schema()
    with db._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM turn_signals WHERE state='pending' AND next_attempt_at<=? "
            "ORDER BY id", (time.time(),),
        ).fetchall()
    result = [dict(row) for row in rows if row["id"] not in _inflight]
    if only_ids is not None:
        result = [row for row in result if row["id"] in only_ids]
    return result


def _finish(ids: list[int], state: str, error: str = "") -> None:
    marks = ",".join("?" for _ in ids)
    with db._conn() as connection:
        connection.execute(
            f"UPDATE turn_signals SET state=?, last_error=?, delivered_at=? WHERE id IN ({marks})",
            (state, error, time.time(), *ids),
        )


def _retry_later(ids: list[int], error: str) -> None:
    with db._conn() as connection:
        for signal_id in ids:
            attempts = connection.execute(
                "SELECT attempts FROM turn_signals WHERE id=?", (signal_id,),
            ).fetchone()["attempts"] + 1
            connection.execute(
                "UPDATE turn_signals SET attempts=?, last_error=?, next_attempt_at=? WHERE id=?",
                (attempts, error, time.time() + _backoff(attempts), signal_id),
            )


async def _resolve_parent(manager, row: dict):
    worker = db.get_session(row["worker_session_id"]) or {}
    parent = None
    if worker.get("parent_id"):
        parent = await manager.ensure_loaded_by_id(worker["parent_id"])
    elif worker.get("parent_name"):
        parent = await manager.ensure_loaded(worker["parent_name"], row["scope"])
    else:
        try:
            name = manager._find_orchestrator_name(row["scope"])
        except ValueError:
            name = None
        if name:
            parent = await manager.ensure_loaded(name, row["scope"])
    return parent


def _compose(manager, row: dict) -> str:
    sr = f" (stop_reason={row['stop_reason']})" if row["stop_reason"] else ""
    outcome = (
        "Finished without explicit report" if row["turn_ok"]
        else "Turn failed before an explicit report"
    )
    context = manager._context_warning(row["worker_name"])
    return (
        f"[from:{row['worker_name']}] [auto-report]{sr} {outcome}. "
        f"Last output:\n{row['summary'] or '(no output)'}{context}"
    )


def _ref(ids: list[int]) -> str:
    return "turn_signal" + "".join(f"[{i}]" for i in ids)


def _already_in_parent_log(parent_id: str, signal_id: int) -> bool:
    with db._conn() as connection:
        return connection.execute(
            "SELECT 1 FROM logs WHERE session_id=? AND type='user_message' "
            "AND origin_detail LIKE '%turn_signal%' AND origin_detail LIKE ? LIMIT 1",
            (parent_id, f"%[{signal_id}]%"),
        ).fetchone() is not None


async def deliver_due(manager, only_ids: list[int] | None = None) -> int:
    """Send every due pending signal; one message per parent. Returns rows delivered."""
    rows = _due(only_ids)
    if not rows:
        return 0
    claimed = {row["id"] for row in rows}
    _inflight.update(claimed)
    delivered = 0
    try:
        groups: dict[str, tuple[object, list[dict]]] = {}
        for row in rows:
            try:
                parent = await _resolve_parent(manager, row)
            except Exception as error:
                _retry_later([row["id"]], f"parent lookup failed: {err_text(error)}")
                continue
            if parent is None:
                _finish([row["id"]], "dropped", "no parent session to notify")
                logger.warning("turn signal %s for %s dropped: no parent", row["id"], row["worker_name"])
                continue
            groups.setdefault(parent.id, (parent, []))[1].append(row)
        for parent, group in groups.values():
            ids = [row["id"] for row in group]
            fresh = [row for row in group if not _already_in_parent_log(parent.id, row["id"])]
            stale = [row["id"] for row in group if row not in fresh]
            if stale:
                _finish(stale, "delivered", "found in parent log")
            if not fresh:
                continue
            fresh_ids = [row["id"] for row in fresh]
            try:
                await asyncio.wait_for(
                    manager.send(
                        parent.id,
                        "\n\n".join(_compose(manager, row) for row in fresh),
                        provenance=MessageProvenance(
                            origin="agent",
                            senders=tuple(dict.fromkeys(row["worker_name"] for row in fresh)),
                            subtype="auto_report", ref=_ref(fresh_ids),
                        ),
                    ),
                    timeout=SEND_TIMEOUT_S,
                )
            except Exception as error:
                detail = f"{type(error).__name__}: {err_text(error)}"
                logger.warning("turn signal %s not delivered to %s: %s", fresh_ids, parent.name, detail)
                _retry_later(fresh_ids, detail)
                continue
            _finish(fresh_ids, "delivered")
            delivered += len(fresh_ids)
            logger.info("turn signal %s delivered to %s", fresh_ids, parent.name)
    finally:
        _inflight.difference_update(claimed)
    return delivered


def _turn_started_at(session_id: str) -> str:
    with db._conn() as connection:
        row = connection.execute(
            "SELECT MAX(ts) AS ts FROM logs WHERE session_id=? AND type='user_message'",
            (session_id,),
        ).fetchone()
    return (row["ts"] if row else None) or ""


def _reported_to_parent_since(worker: dict, since: str) -> bool:
    parent_id = worker.get("parent_id") or ""
    if not parent_id and worker.get("parent_name"):
        parent = db.get_session_by_name(worker["parent_name"], worker["scope"])
        parent_id = parent["id"] if parent else ""
    if not parent_id or not since:
        return False
    with db._conn() as connection:
        return connection.execute(
            "SELECT 1 FROM logs WHERE session_id=? AND type='user_message' AND origin='agent' "
            "AND ts>=? AND origin_detail LIKE ? AND origin_detail NOT LIKE '%auto_report%' LIMIT 1",
            (parent_id, since, f'%"senders":["{worker["name"]}"]%'),
        ).fetchone() is not None


def record_interrupted_by_restart(rows: list[dict]) -> int:
    """Called once per boot with sessions that were mid-turn when the process went away.

    The turn is already dead and the worker will resume with a restart notice; the parent
    still has to hear that the turn ended, unless the worker had reported during it.
    """
    from app import fan_barrier

    recorded = 0
    for worker in rows:
        if worker.get("is_orchestrator") or worker.get("role") == "orchestrator":
            continue
        if not (worker.get("parent_id") or worker.get("parent_name")):
            continue
        if fan_barrier.should_buffer(worker["name"]):
            continue
        if _reported_to_parent_since(worker, _turn_started_at(worker["id"])):
            continue
        if record(
            key=f"{worker['id']}:{BOOT_ID}:restart",
            worker_session_id=worker["id"], worker_name=worker["name"],
            scope=worker["scope"], turn_ok=False, stop_reason="interrupted_by_orchestra_restart",
            summary="The turn was cut off by an Orchestra restart; the worker resumes "
                    "from its saved conversation.",
        ):
            recorded += 1
    return recorded


async def _sweep_forever(manager) -> None:
    while True:
        try:
            await deliver_due(manager)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("turn signal sweep failed: %s: %s", type(error).__name__, error)
        await asyncio.sleep(SWEEP_INTERVAL_S)


def start_sweeper(manager) -> asyncio.Task:
    global _sweeper
    if _sweeper is None or _sweeper.done():
        _sweeper = asyncio.create_task(_sweep_forever(manager))
    return _sweeper


def sweeper_task() -> asyncio.Task | None:
    return _sweeper if _sweeper is not None and not _sweeper.done() else None

