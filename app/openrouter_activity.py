"""#368 — сверка локального счётчика OpenRouter с провайдером (GET /api/v1/activity).

Management key даёт построчные запросы за ЗАВЕРШЁННЫЕ сутки (сегодняшнего дня
в выдаче нет — research #368 F9), по всему аккаунту. Сверка вчерашнего дня:
delta = provider - local публикуется КАК ЕСТЬ (без clamp) рядом с разбивкой
локальных попыток по статусам — так отделяются чужой расход и отклонённые
попытки от молчаливой лжи счётчика.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_ACTIVITY_URL = "https://openrouter.ai/api/v1/activity"


def _http_get_json(url: str, key: str, timeout: float = 30.0) -> tuple[int, dict]:
    resp = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    return resp.status_code, resp.json()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def reconcile(day: str, provider_requests: int, local_count: int,
              local_by_status: dict[str, int]) -> dict:
    """Чистая функция сверки. delta НЕ зажимается в >=0: локальный счёт больше
    провайдерского — тоже честный результат (например, провайдер не считает
    отклонённые попытки)."""
    return {
        "day": day,
        "provider_requests": provider_requests,
        "local_requests": local_count,
        "delta": provider_requests - local_count,
        "local_by_status": dict(local_by_status),
    }


def fetch_day_sync(day: str) -> dict:
    """Провайдерское число запросов за завершённые сутки.

    Возвращает {"available": True, "requests": n} или
    {"available": False, "reason": str}. Сегодняшняя дата и отсутствие ключа
    отсекаются ДО сети.
    """
    if day >= _today():
        return {"available": False,
                "reason": f"only completed UTC days are available ({day} is today or future)"}
    key = (os.environ.get("OPENROUTER_MANAGEMENT_KEY") or "").strip()
    if not key:
        return {"available": False, "reason": "no OPENROUTER_MANAGEMENT_KEY"}

    try:
        status, body = _http_get_json(f"{_ACTIVITY_URL}?date={day}", key)
    except Exception as e:
        logger.warning(f"OpenRouter activity fetch failed: {e}")
        return {"available": False, "reason": f"fetch failed: {e}"}
    if status != 200:
        detail = body.get("error", {}).get("message", "") if isinstance(body, dict) else str(body)[:200]
        return {"available": False, "reason": f"HTTP {status}: {detail}"}
    rows = body.get("data") or []
    return {
        "available": True,
        "day": day,
        "requests": sum(int(r.get("requests") or 0) for r in rows),
        "fetched_at": time.time(),
    }
