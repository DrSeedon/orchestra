"""Visible quota holds for child reports; delivery state stays with its owner (V-1028)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from app import db
from app.events import InjectedMessage, MessageProvenance

logger = logging.getLogger(__name__)
HINT = "Move the parent to hubsol, or hubsonnet/hubopus with model_reason."
_inflight: set[str] = set()
_recovery_task: asyncio.Task | None = None
_rescan_requested = False


def _ensure_schema(connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS report_hold_notices (
        report_key TEXT PRIMARY KEY,
        worker_session_id TEXT NOT NULL,
        parent_session_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        notified_at TEXT
    )""")


def _parent(worker: dict) -> dict | None:
    if worker.get("parent_id"):
        return db.get_session(worker["parent_id"])
    if worker.get("parent_name"):
        return db.get_session_by_name(worker["parent_name"], worker["scope"])
    return None


def held_reports() -> list[dict]:
    """Project canonical queues, including rows parked by an earlier process."""
    from app import message_deliveries, turn_signals

    turn_signals.ensure_schema()
    with db._conn() as connection:
        signals = connection.execute(
            "SELECT id, worker_session_id, last_error FROM turn_signals "
            "WHERE state='pending' AND last_error LIKE 'QuotaGateError:%'"
        ).fetchall()
        messages = connection.execute(
            "SELECT delivery_id, source_session_id, target_session_id, error_json, state "
            "FROM message_deliveries WHERE state IN ('WAITING_QUOTA','QUEUED')"
        ).fetchall()
    reports = []
    for row in signals:
        worker = db.get_session(row["worker_session_id"])
        parent = _parent(worker) if worker else None
        if parent:
            reports.append(dict(report_key=f"turn_signal:{row['id']}",
                                worker=worker, parent=parent, reason=row["last_error"]))
    heads = {}
    for row in messages:
        worker = db.get_session(row["source_session_id"]) if row["source_session_id"] else None
        parent = _parent(worker) if worker else None
        if parent and parent["id"] == row["target_session_id"]:
            blocker = row
            if row["state"] != "WAITING_QUOTA":
                target_id = row["target_session_id"]
                if target_id not in heads:
                    heads[target_id] = message_deliveries._next_target_delivery(target_id)
                blocker = heads[target_id]
                if blocker is None or blocker["state"] != "WAITING_QUOTA":
                    continue
            try:
                error = json.loads(blocker["error_json"]) if blocker["error_json"] else {}
            except (TypeError, ValueError):
                error = {}
            if not isinstance(error, dict):
                error = {}
            reports.append(dict(report_key=f"message_delivery:{row['delivery_id']}",
                                worker=worker, parent=parent,
                                reason=error.get("message") or "Quota gate is closed"))
    return reports


def status_map() -> dict[str, dict]:
    """No cached status: released, cancelled and delivered reports disappear immediately."""
    result = {}
    for report in held_reports():
        worker_id = report["worker"]["id"]
        status = result.setdefault(worker_id, {
            "count": 0, "parent_name": report["parent"]["name"],
            "reason": report["reason"], "hint": HINT,
        })
        status["count"] += 1
    return result


async def recover(manager=None) -> None:
    """Observe all held reports and deliver one durable diagnostic per report upstream.

    This carries no report body. The original agent delivery retains its quota gate.
    Stable event ids and the parent's journal reconcile a crash after acceptance.
    """
    if manager is None:
        from app.deps import manager

    try:
        reports = held_reports()
    except Exception:
        logger.exception("report quota-hold recovery scan failed")
        return
    for report in reports:
        key = report["report_key"]
        if key in _inflight:
            continue
        _inflight.add(key)
        try:
            worker, parent = report["worker"], report["parent"]
            with db._conn() as connection:
                _ensure_schema(connection)
                connection.execute(
                    "INSERT OR IGNORE INTO report_hold_notices "
                    "(report_key, worker_session_id, parent_session_id, reason) VALUES (?, ?, ?, ?)",
                    (key, worker["id"], parent["id"], report["reason"]),
                )
                notice = connection.execute(
                    "SELECT * FROM report_hold_notices WHERE report_key=?", (key,),
                ).fetchone()
                logged = connection.execute(
                    "SELECT 1 FROM logs WHERE session_id=? AND event_id=?",
                    (worker["id"], f"report-held:{key}"),
                ).fetchone()
            text = (
                f"Report held by quota gate: {worker['name']} → {parent['name']}; "
                f"{key}. {report['reason']} {HINT}"
            )
            provenance = MessageProvenance(
                origin="platform", senders=("Orchestra",), subtype="report_quota_hold", ref=key,
            )
            if not logged:
                db.add_log(worker["id"], datetime.now(timezone.utc), "status", text,
                           event_id=f"report-held:{key}", provenance=provenance)
            if notice["notified_at"]:
                continue
            upstream = _parent(parent)
            if upstream is None or upstream["id"] in {worker["id"], parent["id"]}:
                continue
            event_id = f"report-hold-notice:{key}"
            with db._conn() as connection:
                accepted = connection.execute(
                    "SELECT 1 FROM logs WHERE session_id=? AND event_id=?",
                    (upstream["id"], event_id),
                ).fetchone()
            if not accepted:
                async def send_notice():
                    loaded = await manager.ensure_loaded_by_id(upstream["id"])
                    if loaded is None:
                        raise LookupError(f"upstream session unavailable: {upstream['id']}")
                    await manager.send(
                        upstream["id"], InjectedMessage(text, provenance, event_id),
                        provenance=provenance,
                    )

                await asyncio.wait_for(send_notice(), timeout=10.0)
            with db._conn() as connection:
                connection.execute(
                    "UPDATE report_hold_notices SET notified_at=? WHERE report_key=?",
                    (datetime.now(timezone.utc).isoformat(), key),
                )
        except Exception:
            logger.exception("report quota-hold notice remains pending: %s", key)
        finally:
            _inflight.discard(key)


def ensure_runner(manager=None) -> asyncio.Task:
    """Best-effort notification must never delay receipt acceptance or quota release."""
    global _recovery_task, _rescan_requested
    if _recovery_task is not None and not _recovery_task.done():
        _rescan_requested = True
        return _recovery_task
    _rescan_requested = False
    task = asyncio.create_task(recover(manager))
    _recovery_task = task

    def completed(done):
        global _rescan_requested
        if done.cancelled():
            return
        try:
            done.result()
        except Exception:
            logger.exception("report quota-hold recovery failed")
        if _recovery_task is done and _rescan_requested:
            _rescan_requested = False
            ensure_runner(manager)

    task.add_done_callback(completed)
    return task
