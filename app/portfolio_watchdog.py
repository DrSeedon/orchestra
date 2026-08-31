"""Optional goal-stall watchdog with a durable, generation-scoped outbox."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db


logger = logging.getLogger("orchestra.portfolio_watchdog")
INTERVAL_SECONDS = 300
CLAIM_LEASE_SECONDS = 300


def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        current = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _valid_owner(conn, project_id: str):
    rows = conn.execute(
        """SELECT s.* FROM portfolio_members m
           JOIN sessions s ON s.id=m.session_id
           WHERE m.project_id=? AND m.role='owner' AND m.revoked_at IS NULL
             AND s.status!='archived' AND s.role='orchestrator'
             AND TRIM(COALESCE(s.parent_id,''))=''""",
        (project_id,),
    ).fetchall()
    return rows[0] if len(rows) == 1 else None


def _has_open_wait(conn, goal_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM portfolio_waits WHERE goal_id=? AND status='open'",
        (goal_id,),
    ).fetchone() is not None


def _has_live_lease(conn, goal_id: str, now_text: str) -> bool:
    return conn.execute(
        """SELECT 1 FROM portfolio_activity_leases
           WHERE goal_id=? AND lease_expires_at>?""",
        (goal_id, now_text),
    ).fetchone() is not None


def _has_active_linked_worker(conn, project_id: str) -> bool:
    return conn.execute(
        """SELECT 1 FROM portfolio_task_links l
           JOIN tm_tasks t ON t.id=l.task_row_id
           JOIN sessions s ON s.id=t.worker_session_id
           WHERE l.project_id=? AND l.removed_at IS NULL
             AND s.status IN ('running','waiting')
           LIMIT 1""",
        (project_id,),
    ).fetchone() is not None


def _delivery_payload(
    goal, owner, delivery_id: str, claim_token: str
) -> dict[str, Any]:
    generation = int(goal["stall_generation"])
    return {
        "delivery_id": delivery_id,
        "claim_token": claim_token,
        "project_id": goal["project_id"],
        "goal_id": goal["id"],
        "stall_generation": generation,
        "target_session_id": owner["id"],
        "target_name": owner["name"],
        "target_scope": owner["scope"],
        "target_task_id": str(owner["task_id"] or ""),
        "target_generation": (
            f"session={owner['id']}|task={owner['task_id'] or ''}|"
            f"branch={owner['branch'] or ''}|"
            f"needs_switch={int(bool(owner['needs_switch']))}"
        ),
        "message": (
            f"[Project watchdog] Project {goal['project_id']} has made no progress "
            f"for at least {goal['stall_after_seconds']} seconds. Continue the goal: "
            f"{goal['objective']}"
        ),
    }


def _claim_candidates(now: datetime, *, shadow: bool) -> tuple[list[dict], dict[str, int]]:
    now_text = now.isoformat()
    lease_until = (now + timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat()
    payloads: list[dict] = []
    stats = {"candidates": 0, "suppressed": 0, "shadow": 0}
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        goals = conn.execute(
            """SELECT g.* FROM portfolio_goals g
               JOIN portfolio_projects p ON p.id=g.project_id
               WHERE g.status='active' AND g.watchdog_enabled=1
                 AND p.archived_at IS NULL
               ORDER BY g.created_at,g.id"""
        ).fetchall()
        for goal in goals:
            owner = _valid_owner(conn, goal["project_id"])
            last_progress = _utc(goal["last_progress_at"])
            stalled = (now - last_progress).total_seconds() >= int(
                goal["stall_after_seconds"]
            )
            if (
                owner is None
                or not stalled
                or _has_open_wait(conn, goal["id"])
                or _has_live_lease(conn, goal["id"], now_text)
                or _has_active_linked_worker(conn, goal["project_id"])
            ):
                stats["suppressed"] += 1
                continue
            stats["candidates"] += 1
            if shadow:
                stats["shadow"] += 1
                continue
            existing = conn.execute(
                """SELECT * FROM portfolio_watchdog_outbox
                   WHERE goal_id=? AND stall_generation=?""",
                (goal["id"], goal["stall_generation"]),
            ).fetchone()
            claim_token = str(uuid.uuid4())
            if existing is not None:
                if existing["state"] == "accepted":
                    stats["suppressed"] += 1
                    continue
                if existing["state"] == "delivering" and existing["lease_expires_at"] > now_text:
                    stats["suppressed"] += 1
                    continue
                delivery_id = existing["delivery_id"]
                changed = conn.execute(
                    """UPDATE portfolio_watchdog_outbox
                       SET state='delivering',attempts=attempts+1,
                           claimed_at=?,lease_expires_at=?,claim_token=?
                       WHERE goal_id=? AND stall_generation=?
                         AND state!='accepted'""",
                    (
                        now_text,
                        lease_until,
                        claim_token,
                        goal["id"],
                        goal["stall_generation"],
                    ),
                ).rowcount
                if changed != 1:
                    stats["suppressed"] += 1
                    continue
            else:
                delivery_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO portfolio_watchdog_outbox(
                           goal_id,stall_generation,delivery_id,claim_token,target_owner_session_id,
                           state,attempts,claimed_at,lease_expires_at)
                       VALUES(?,?,?,?,?,'delivering',1,?,?)""",
                    (
                        goal["id"],
                        goal["stall_generation"],
                        delivery_id,
                        claim_token,
                        owner["id"],
                        now_text,
                        lease_until,
                    ),
                )
            payloads.append(_delivery_payload(goal, owner, delivery_id, claim_token))
    return payloads, stats


async def _deliver_to_owner(payload: dict[str, Any]) -> str:
    from app.message_deliveries import accept_message_delivery

    resource, status_code = await accept_message_delivery(
        delivery_id=payload["delivery_id"],
        source_principal="portfolio-watchdog",
        source_name="portfolio-watchdog",
        source_scope=payload["target_scope"],
        target_session_id=payload["target_session_id"],
        target_name=payload["target_name"],
        target_scope=payload["target_scope"],
        target_task_id=payload["target_task_id"],
        target_generation=payload["target_generation"],
        message=payload["message"],
        rendered_message=payload["message"],
        message_kind="portfolio_watchdog",
        wake=True,
    )
    if status_code != 202 or not isinstance(resource, dict):
        raise RuntimeError(f"watchdog delivery was not accepted: {status_code} {resource}")
    return str(resource.get("delivery_id") or payload["delivery_id"])


async def evaluate_once(
    *,
    now: datetime | str | None = None,
    deliver: Callable[[dict[str, Any]], Awaitable[Any] | Any] | None = None,
    shadow: bool = False,
) -> dict[str, int]:
    current = _utc(now)
    payloads, stats = _claim_candidates(current, shadow=shadow)
    delivered = 0
    failed = 0
    callback = deliver or _deliver_to_owner
    for payload in payloads:
        try:
            result = callback(payload)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            failed += 1
            with db._conn() as conn:
                conn.execute(
                    """UPDATE portfolio_watchdog_outbox
                       SET state='retryable',lease_expires_at=?
                       WHERE goal_id=? AND stall_generation=? AND delivery_id=?
                         AND claim_token=? AND state='delivering'""",
                    (
                        current.isoformat(),
                        payload["goal_id"],
                        payload["stall_generation"],
                        payload["delivery_id"],
                        payload["claim_token"],
                    ),
                )
            logger.warning(
                "portfolio watchdog delivery failed: project=%s generation=%s error=%s",
                payload["project_id"],
                payload["stall_generation"],
                exc,
            )
        else:
            delivered += 1
            with db._conn() as conn:
                conn.execute(
                    """UPDATE portfolio_watchdog_outbox
                       SET state='accepted',accepted_at=?,lease_expires_at=?
                       WHERE goal_id=? AND stall_generation=? AND delivery_id=?
                         AND claim_token=? AND state='delivering'""",
                    (
                        current.isoformat(),
                        current.isoformat(),
                        payload["goal_id"],
                        payload["stall_generation"],
                        payload["delivery_id"],
                        payload["claim_token"],
                    ),
                )
    return {
        **stats,
        "claimed": len(payloads),
        "delivered": delivered,
        "failed": failed,
    }


def shadow_mode() -> bool:
    return os.getenv("PORTFOLIO_WATCHDOG_SHADOW", "1").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


async def run_loop() -> None:
    while True:
        try:
            result = await evaluate_once(shadow=shadow_mode())
            if result["candidates"]:
                logger.info("portfolio watchdog evaluation: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("portfolio watchdog evaluation failed")
        await asyncio.sleep(INTERVAL_SECONDS)


def ensure_task(app) -> asyncio.Task:
    current = getattr(app.state, "portfolio_watchdog_task", None)
    if current is not None and not current.done():
        return current
    task = asyncio.create_task(run_loop(), name="portfolio-watchdog")
    app.state.portfolio_watchdog_task = task
    return task
