"""#368 — локальный счётчик HTTP-попыток к OpenRouter (квота free-моделей).

Единица счёта — одна HTTP-попытка POST /chat/completions, включая ретраи и
неудачные ответы: провайдер тратит квоту на попытку, а не на успех (research #368).
Персистентность — SQLite (app.db), переживает рестарт процесса. Все функции
тотальны: сбой учёта НИКОГДА не роняет вызывающий стрим, но гасит healthy().
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone

from app.db import _conn

logger = logging.getLogger(__name__)

_PRUNE_EVERY = 100          # записей между чистками строк старше 31 дня
_RETAIN_SECONDS = 31 * 86400

_insert_count = 0
_last_error: str = ""


def _fail(exc: Exception) -> None:
    global _last_error
    _last_error = f"{type(exc).__name__}: {exc}"
    logger.warning(f"openrouter counter failed: {_last_error}")


def _ok() -> None:
    """Успешная операция снимает флаг сбоя: транзиентная ошибка БД (например,
    таблица ещё не создана в чужом тесте) не должна портить healthy() навсегда."""
    global _last_error
    _last_error = ""


def today_utc() -> str:
    return day_of(time.time())


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def record_attempt_start(ts: float | None = None) -> int | None:
    """Одна HTTP-попытка начата. Возвращает id строки (или None при сбое учёта)."""
    global _insert_count
    try:
        ts = time.time() if ts is None else ts
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO openrouter_attempts (ts, day, status) VALUES (?, ?, NULL)",
                (ts, day_of(ts)),
            )
            _insert_count += 1
            if _insert_count % _PRUNE_EVERY == 0:
                c.execute("DELETE FROM openrouter_attempts WHERE ts < ?",
                          (time.time() - _RETAIN_SECONDS,))
            _ok()
            return int(cur.lastrowid)
    except (sqlite3.Error, OSError) as e:
        _fail(e)
        return None


def record_attempt_status(attempt_id: int | None, status: int | None) -> None:
    if attempt_id is None:
        return
    try:
        with _conn() as c:
            c.execute("UPDATE openrouter_attempts SET status = ? WHERE id = ?",
                      (status, attempt_id))
            _ok()
    except (sqlite3.Error, OSError) as e:
        _fail(e)


def today_count() -> int:
    return local_day_count(today_utc())


def local_day_count(day: str) -> int:
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM openrouter_attempts WHERE day = ?", (day,)
            ).fetchone()
            _ok()
            return int(row["n"])
    except (sqlite3.Error, OSError) as e:
        _fail(e)
        return -1


def minute_count(window_sec: int = 60) -> int:
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM openrouter_attempts WHERE ts >= ?",
                (time.time() - window_sec,),
            ).fetchone()
            _ok()
            return int(row["n"])
    except (sqlite3.Error, OSError) as e:
        _fail(e)
        return -1


def status_breakdown(day: str) -> dict[str, int]:
    """{'200': n, '429': n, 'none': n} — 'none' = ответ не получен (транспортная ошибка)."""
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) AS n FROM openrouter_attempts "
                "WHERE day = ? GROUP BY status", (day,)
            ).fetchall()
            _ok()
            return {
                (str(r["status"]) if r["status"] is not None else "none"): int(r["n"])
                for r in rows
            }
    except (sqlite3.Error, OSError) as e:
        _fail(e)
        return {}


def healthy() -> bool:
    return _last_error == ""


def mark_unhealthy(reason: str) -> None:
    """Внешний хук (llm.py) глушит исключение, но обязан погасить healthy()."""
    global _last_error
    _last_error = reason or "unhealthy"
