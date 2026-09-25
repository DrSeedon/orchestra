"""Stall signals (V-642): the platform tells an agent about silence it cannot see itself.

Two independent detectors, neither of which touches the session it watches:
* silent turn — RUNNING, live backend, no provider event for SILENCE_SIGNAL_SECONDS;
  the parent gets one message per silence;
* delivered but not started — a message reached an idle worker, no provider event
  followed within TURN_START_GRACE_SECONDS; the delivery is marked and the sender told.
Nothing is interrupted or retried: the message only informs.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app import db
from app.errtext import err_text
from app.events import MessageProvenance

logger = logging.getLogger("orchestra.stall_signals")

SILENCE_SIGNAL_SECONDS = 20 * 60
TURN_START_GRACE_SECONDS = 60
STALLED_CODE = "TURN_NOT_STARTED"


async def _notify(session_id: str, text: str, subtype: str, ref: str) -> None:
    from app.deps import manager

    target = await manager.ensure_loaded_by_id(session_id)
    if target is None:
        return
    await manager.send(
        target.id, text,
        provenance=MessageProvenance(
            origin="platform", senders=("Orchestra",), subtype=subtype, ref=ref,
        ),
    )


def describe_event(event) -> str:
    """Last provider event as the parent should read it: a tool call names the tool."""
    if event.type == "tool_use":
        return f"tool_use {str(event.content).split(':', 1)[0].strip()}"
    return str(event.type)


async def signal_silence(s, silence: float, last_event: str, last_event_at: str) -> None:
    """One message to the owner of a worker that has produced no provider event."""
    parent_id = s.parent_id
    if not parent_id:
        return
    text = (
        f"[Orchestra] Worker {s.name} (task {s.task_id or '-'}) is RUNNING but the provider "
        f"has sent no event for {silence / 60:.0f} min. Last event: {last_event} at "
        f"{last_event_at}. A long tool call (e.g. bash) looks the same as a wedged turn; "
        "check with list_agents / message the worker. Nothing was interrupted."
    )
    try:
        await _notify(parent_id, text, "silence_signal", s.id)
    except Exception as error:
        logger.warning("[%s] silence signal failed: %s", s.name, err_text(error))


def mark_stalled(delivery_id: str, reason: str) -> dict | None:
    """Attach the stall to a SUBMITTED receipt. State stays SUBMITTED: a distinct state
    would become the target's queue head and block everything behind it."""
    error = json.dumps(
        {
            "code": STALLED_CODE, "retryable": False, "outcome_unknown": False,
            "message": f"Delivered, but no turn started: {reason}",
        },
        ensure_ascii=False,
    )
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """UPDATE message_deliveries SET error_json=?, updated_at=?
               WHERE delivery_id=? AND state='SUBMITTED' AND error_json IS NULL""",
            (error, _now(), delivery_id),
        )
        if not cursor.rowcount:
            return None
        return dict(connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone())


def _now() -> str:
    from app.message_deliveries import _now as now

    return now()


async def watch_turn_start(s, delivery_id: str, *, grace: float | None = None) -> bool:
    """After an idle-path delivery: stalled unless a provider event arrives within grace.

    Returns True when the delivery was marked stalled. `_last_msg_time` is set when the
    turn state starts, i.e. before the send; an event after `baseline` is the proof.
    """
    baseline = s._last_msg_time
    await asyncio.sleep(TURN_START_GRACE_SECONDS if grace is None else grace)
    if s._last_msg_time != baseline:
        return False
    row = mark_stalled(delivery_id, f"agent status is {s.status.value}, no provider event")
    if row is None:
        return False
    sender = row["source_session_id"]
    if sender:
        text = (
            f"[Orchestra] Your message to {row['target_name']} (delivery {delivery_id}) "
            f"was delivered, but no turn started within "
            f"{TURN_START_GRACE_SECONDS if grace is None else grace:.0f}s: "
            f"agent status is {s.status.value}. See message_delivery_status."
        )
        try:
            await _notify(sender, text, "delivery_stalled", delivery_id)
        except Exception as error:
            logger.warning("stall notice to sender failed: %s", err_text(error))
    return True
