"""Доставки, отбитые гейтом квот, ждут его снятия внутри платформы (V-678).

Раньше отказ гейта возвращался отправителю, и оркестратор ставил себе bg-таймер
«повтори через N часов»: платный ход на каждое пробуждение, часто впустую, а отложенное
сообщение легко забыть. Теперь отбитое гейтом сообщение (и первое задание нового воркера)
принимается как обычная durable-доставка в состоянии `WAITING_QUOTA`.

Владельцы: хранение и порядок — `message_deliveries` / `initial_deliveries` (их таблицы,
`accept_seq`, идемпотентность по `delivery_id`); решение «гейт пропускает» — `quota_gate`;
этот модуль — только ПЕРЕХОД `WAITING_QUOTA → QUEUED`, когда гейт открылся. Дальше доставку
ведёт прежний runner. Новой таблицы и нового долгоживущего состояния в памяти нет, поэтому
рестарт ничего не теряет: после старта цикл просто находит те же строки.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from app import db
from app.errtext import err_text

logger = logging.getLogger("orchestra.quota_queue")

SWEEP_INTERVAL_SECONDS = 60.0
# ETA пересчитывается при каждом проходе, но строка перезаписывается, только если оценка
# сдвинулась заметно: иначе минутный цикл писал бы в БД впустую.
ETA_REWRITE_THRESHOLD_SECONDS = 600.0
WAITING_STATE = "WAITING_QUOTA"
RELEASED_CODE = "QUOTA_WAIT_RELEASED"

_release_lock = asyncio.Lock()


def _decision_eta(decision) -> float | None:
    seconds = getattr(decision, "release_in_seconds", None)
    if isinstance(seconds, (int, float)):
        return time.time() + float(seconds)
    return None


def wait_error(decision, *, now: float | None = None) -> dict:
    """Что хранится в `error_json` ждущей доставки: причина и ориентир по времени."""
    moment = time.time() if now is None else now
    return {
        "code": "WAITING_QUOTA",
        "message": (
            f"{decision.provider_label} quota gate is closed ({decision.reason}); "
            "the delivery is durably queued and goes out by itself when the gate opens."
        ),
        "retryable": False,
        "outcome_unknown": False,
        "details": {
            "provider": decision.provider,
            "provider_label": decision.provider_label,
            "utilization": decision.utilization,
            "reason": decision.reason,
            "release_status": decision.release_status,
            "release_in_seconds": decision.release_in_seconds,
            "reset_at": decision.reset_at,
            "eta_at": _decision_eta(decision),
            "parked_at": moment,
        },
    }


def released_error() -> dict:
    """Метка «эту доставку уже держали за гейтом»: по ней отправителю сообщат об отказе."""
    return {
        "code": RELEASED_CODE,
        "message": "The quota gate opened; the delivery was released from the wait.",
        "retryable": False,
        "outcome_unknown": False,
    }


def was_parked(error_json: str | None) -> bool:
    if not error_json:
        return False
    try:
        code = json.loads(error_json).get("code")
    except (ValueError, AttributeError):
        return False
    return code in {"WAITING_QUOTA", RELEASED_CODE}


def _eta_text(details: dict) -> str:
    eta_at = details.get("eta_at")
    if isinstance(eta_at, (int, float)):
        remaining = max(0.0, float(eta_at) - time.time())
        stamp = datetime.fromtimestamp(float(eta_at), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        hours, rest = divmod(int(remaining), 3600)
        return f"about {hours}h {rest // 60:02d}m from now (~{stamp}), an estimate"
    if details.get("reset_at"):
        return f"no later than the window reset at {details['reset_at']}"
    return "time unknown — the gate is re-checked every minute"


def quota_wait_action(row) -> dict:
    """`next_action` для ждущей доставки; общий для прямых и первых заданий."""
    try:
        error = json.loads(row["error_json"]) if row["error_json"] else {}
    except ValueError:
        error = {}
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    return {
        "code": "WAITING_QUOTA",
        "retryable": False,
        "eta_at": details.get("eta_at"),
        "message": (
            "Accepted and durably queued: the quota gate is closed, so this delivery "
            f"goes out automatically when it opens — {_eta_text(details)}. Do NOT resend "
            "and do NOT set a retry timer; a restart does not lose it. Order to the same "
            "target is preserved; the owner's gate override releases it at once."
        ),
    }


def _model_of(session_id: str) -> str:
    row = db.get_session(session_id)
    return str(row["model"]) if row and row.get("model") else ""


async def _admission_allows(model: str):
    """(разрешено, решение). Нет модели/сбой оценки → пропускаем: runner отвергнет сам."""
    if not model:
        return True, None
    from app.quota_gate import get_worker_admission

    try:
        decision = await get_worker_admission(model)
    except Exception as error:
        logger.warning("quota release: admission check failed for %s: %s", model, err_text(error))
        return True, None
    return decision.state != "blocked", decision


def _waiting_rows(table: str, session_column: str) -> list[dict]:
    with db._conn() as connection:
        rows = connection.execute(
            f"SELECT delivery_id, {session_column} AS session_id, error_json "
            f"FROM {table} WHERE state='WAITING_QUOTA' ORDER BY created_at",
        ).fetchall()
    return [dict(row) for row in rows]


def waiting_scopes() -> set[str]:
    """Scopes with a durable owner/agent delivery still held by the quota gate."""
    with db._conn() as connection:
        rows = connection.execute(
            """SELECT target_scope AS scope FROM message_deliveries
                 WHERE state='WAITING_QUOTA'
               UNION
               SELECT scope FROM initial_deliveries
                 WHERE state='WAITING_QUOTA'""",
        ).fetchall()
    return {str(row["scope"]) for row in rows if row["scope"]}


def _refresh_eta(table: str, delivery_id: str, error_json: str | None, decision) -> None:
    """Подправить ориентир, если он заметно уплыл: отправитель читает его из receipt."""
    try:
        old = json.loads(error_json)["details"]["eta_at"] if error_json else None
    except (ValueError, KeyError, TypeError):
        old = None
    fresh = _decision_eta(decision)
    if fresh is None or (
        isinstance(old, (int, float)) and abs(fresh - old) < ETA_REWRITE_THRESHOLD_SECONDS
    ):
        return
    with db._conn() as connection:
        connection.execute(
            f"UPDATE {table} SET error_json=? WHERE delivery_id=? AND state='WAITING_QUOTA'",
            (json.dumps(wait_error(decision), ensure_ascii=False), delivery_id),
        )


def _release_rows(table: str, ids: list[str]) -> int:
    marker = json.dumps(released_error(), ensure_ascii=False)
    released = 0
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for delivery_id in ids:
            released += connection.execute(
                f"UPDATE {table} SET state='QUEUED', error_json=?, updated_at=? "
                "WHERE delivery_id=? AND state='WAITING_QUOTA'",
                (marker, datetime.now(timezone.utc).isoformat(), delivery_id),
            ).rowcount
    return released


def _has_open_initial(session_id: str) -> bool:
    """Первое задание воркера ещё не ушло: прямое сообщение не должно его обогнать."""
    with db._conn() as connection:
        return connection.execute(
            "SELECT 1 FROM initial_deliveries WHERE session_id=? "
            "AND state IN ('WAITING_QUOTA','QUEUED','PREPARING','DISPATCHING') LIMIT 1",
            (session_id,),
        ).fetchone() is not None


async def release_waiting() -> int:
    """Один проход: всё, что гейт теперь пропускает, возвращается в обычную очередь.

    Вызывается циклом раз в минуту и немедленно — при снятии гейта владельцем. Идемпотентен
    и безопасен при параллельном вызове: переход — условный `UPDATE ... WHERE state=`.
    """
    from app import deps, initial_deliveries, initial_delivery_events, message_deliveries

    released = 0
    async with _release_lock:
        verdicts: dict[str, tuple[bool, object]] = {}

        async def verdict(model: str):
            if model not in verdicts:
                verdicts[model] = await _admission_allows(model)
            return verdicts[model]

        # Первые задания — раньше прямых: у свежего воркера они идут первыми по смыслу.
        initial_ids: list[str] = []
        for row in await asyncio.to_thread(_waiting_rows, "initial_deliveries", "session_id"):
            allowed, decision = await verdict(_model_of(row["session_id"]))
            if allowed:
                initial_ids.append(row["delivery_id"])
            elif decision is not None:
                _refresh_eta("initial_deliveries", row["delivery_id"], row["error_json"], decision)
        if initial_ids:
            released += _release_rows("initial_deliveries", initial_ids)
            for delivery_id in initial_ids:
                initial_deliveries.ensure_delivery_runner(delivery_id)

        message_ids: dict[str, list[str]] = {}
        for row in await asyncio.to_thread(
            _waiting_rows, "message_deliveries", "target_session_id",
        ):
            session_id = row["session_id"]
            if _has_open_initial(session_id):
                continue
            allowed, decision = await verdict(_model_of(session_id))
            if allowed:
                message_ids.setdefault(session_id, []).append(row["delivery_id"])
            elif decision is not None:
                _refresh_eta("message_deliveries", row["delivery_id"], row["error_json"], decision)
        for session_id, ids in message_ids.items():
            released += _release_rows("message_deliveries", ids)
            message_deliveries.ensure_target_runner(session_id)
    try:
        initial_delivery_events.ensure_runner(deps.manager)
    except Exception as error:
        logger.warning("initial delivery event recovery failed: %s", err_text(error))
    if released:
        logger.info("quota gate open: released %d waiting deliveries", released)
    return released


async def quota_release_loop() -> None:
    while True:
        try:
            await release_waiting()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("quota release sweep failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
