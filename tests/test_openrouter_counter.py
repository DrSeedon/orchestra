"""#368 — счётчик запросов OpenRouter: локальный счёт + сверка с /activity.

Красные тесты Phase 2 (коммить ДО реализации). Красота красного:
- test_t1_*: падают с ModuleNotFoundError "app.openrouter_counter" — модуль-счётчик
  и есть отсутствующее поведение; после реализации оракул — ассерты.
- test_t2_*: аналогично для app.openrouter_activity.
- test_t3_*: AttributeError на system._get_openrouter_usage — отсутствующая ветка /api/usage.
- test_t4_*: AssertionError на анкор в usage.js — delivery-чек фронтенда.
"""

import json

import httpx
import pytest


@pytest.fixture(autouse=True)
def _init_db():
    """Прод создаёт схему на старте (app.main); тестам нужен тот же шаг."""
    from app import db

    db.init_db()
    yield


# ── helpers ──────────────────────────────────────────────────────────────

def _sse(body_chunks: str) -> bytes:
    lines = "".join(f"data: {c}\n\n" for c in body_chunks)
    return lines.encode()


def _fake_transport(calls: list[int]):
    """429 (retryable) на первый вызов, затем 200 SSE. Пишет статусы в calls."""

    def handler(request: httpx.Request) -> httpx.Response:
        n = len(calls)
        calls.append(n)
        if n == 0:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"error": {"code": 429, "message": "Rate limit exceeded"}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse([
                json.dumps({"id": "g1", "choices": [{"index": 0, "delta": {"content": "ok"}}]}),
                "[DONE]",
            ]),
        )

    return httpx.MockTransport(handler)


async def _drain(client, calls):
    from app.harness import llm as or_llm

    events = []
    async for ev in client.stream(messages=[{"role": "user", "content": "hi"}], tools=[]):
        events.append(ev)
    return events


@pytest.fixture
def fast_retry(monkeypatch):
    from app.harness import llm as or_llm

    monkeypatch.setattr(or_llm, "BACKOFF_BASE", 0.001)


# ── T1: счётчик считает каждую HTTP-попытку, включая ретраи и неудачи ────────

def test_t1_counts_every_attempt_including_retry_and_failures(fast_retry):
    from app import openrouter_counter as counter
    from app.harness import llm as or_llm

    calls: list[int] = []
    client = or_llm.OpenRouterClient(
        api_key="test-key", model="z-ai/glm-5.2:free",
        http=httpx.AsyncClient(transport=_fake_transport(calls)),
    )

    import asyncio
    asyncio.run(_drain(client, calls))

    # 429 + повторная попытка = 2 HTTP-запроса = 2 единицы квоты
    assert len(calls) == 2, f"expected 2 HTTP attempts, got {len(calls)}"
    assert counter.today_count() == 2
    breakdown = counter.status_breakdown(counter.today_utc())
    assert breakdown.get("429") == 1, f"rejected attempt must be counted: {breakdown}"
    assert breakdown.get("200") == 1, f"successful attempt must be counted: {breakdown}"
    assert counter.minute_count() == 2


def test_t1_utc_day_rollover_and_persistence(fast_retry):
    from app import openrouter_counter as counter

    # Вчерашние попытки не входят в today_count, но видны по своему дню.
    counter.record_attempt_start(ts=0.0)          # 1970-01-01 UTC
    assert counter.today_count() == 0
    assert counter.local_day_count(counter.day_of(0.0)) == 1
    assert counter.local_day_count(counter.today_utc()) == 0


def test_t1_survives_restart_rows_not_memory(fast_retry):
    """Счёт живёт в SQLite: новый 'процесс' (новый импорт-стейт) видит те же строки."""
    from app import openrouter_counter as counter

    counter.record_attempt_start()
    counter.record_attempt_start()
    before = counter.today_count()
    assert before == 2
    # Перезапуск = просто новый вызов тех же функций: источник — БД, не память.
    assert counter.today_count() == 2


# ── T2: сверка вчерашнего дня с /activity ────────────────────────────────────

def test_t2_reconcile_names_delta_and_breakdown():
    from app.openrouter_activity import reconcile

    result = reconcile(
        day="2026-08-21",
        provider_requests=92,
        local_count=85,
        local_by_status={"200": 80, "429": 5},
    )
    assert result["provider_requests"] == 92
    assert result["local_requests"] == 85
    assert result["delta"] == 7          # 92 - 85: чужой расход и/или отклонённые
    assert result["day"] == "2026-08-21"


def test_t2_reconcile_local_above_provider_is_visible_not_clamped():
    from app.openrouter_activity import reconcile

    # Локальный счёт больше провайдерского — тоже честное число, не max(0, ...)
    result = reconcile(day="2026-08-21", provider_requests=10, local_count=13,
                       local_by_status={"200": 10, "502": 3})
    assert result["delta"] == -3


def test_t2_fetch_refuses_today_without_network(monkeypatch):
    """Сегодняшняя дата запрещена провайдером — отсекаем до сети (F9 research)."""
    from app import openrouter_activity as activity

    def _boom(*a, **k):
        raise AssertionError("network call must not happen for today's date")

    monkeypatch.setattr(activity, "_http_get_json", _boom)
    import datetime as dt
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    result = activity.fetch_day_sync(today)
    assert result["available"] is False
    assert "completed" in result["reason"]


def test_t2_fetch_without_management_key_degrades(monkeypatch):
    from app import openrouter_activity as activity

    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)
    result = activity.fetch_day_sync("2026-08-21")
    assert result["available"] is False
    assert "key" in result["reason"].lower()


# ── T3: ветка openrouter в /api/usage ────────────────────────────────────────

def test_t3_usage_payload_counts_and_limits():
    from app import openrouter_counter as counter
    from app.routes import system

    row_a = counter.record_attempt_start()
    row_b = counter.record_attempt_start()
    # Статусы проставлены явно: сиды с NULL (ответ не получен) пережили бы
    # мутанта «считаем только 2xx» — а обе попытки тратят квоту.
    counter.record_attempt_status(row_a, 200)
    counter.record_attempt_status(row_b, 429)

    payload = system._get_openrouter_usage()

    assert payload["available"] is True
    assert payload["daily"]["count"] == 2
    assert payload["daily"]["limit"] == 1000
    assert payload["minute"]["count"] == 2
    assert payload["minute"]["limit"] == 20
    assert payload["source"] == "local"


def test_t3_usage_payload_never_fakes_zero_when_broken(monkeypatch):
    """Сломанный счётчик → available False, а не ноль, который читается как «свободно»."""
    from app import openrouter_counter as counter
    from app.routes import system

    monkeypatch.setattr(counter, "today_count", lambda: (_ for _ in ()).throw(RuntimeError("db broken")))

    payload = system._get_openrouter_usage()

    assert payload["available"] is False
    assert "daily" not in payload or payload["daily"] is None


# ── T4: полоса в usage.js (delivery-чек) ─────────────────────────────────────

def test_t4_usage_bar_has_openrouter_group():
    js = open("app/static/js/usage.js", encoding="utf-8").read()
    assert 'data-usage-compact-provider="openrouter"' in js, (
        "usage.js must render an OpenRouter provider group in renderUsageBar()"
    )
    # Честные состояния: нет данных — явная подпись, не ноль.
    assert "нет данных" in js, "unavailable state must be explicit"
