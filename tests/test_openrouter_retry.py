"""#368 T5 — ретрай минутной стены OpenRouter: потолок ожидания и два вида 429.

Оракул из docs/tasks/368/plan.md (тикет T5), AC 1-5.
"""

import asyncio
import json

import httpx
import pytest

from app.harness import llm

SSE_OK = (
    b'data: {"id":"g","choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n'
    b"data: [DONE]\n\n"
)

UPSTREAM_429 = {}                                   # без X-RateLimit-*: «занято» у провайдера
PLATFORM_429 = {"x-ratelimit-limit": "20", "x-ratelimit-remaining": "0"}


@pytest.fixture
def fast_backoff(monkeypatch):
    monkeypatch.setattr(llm, "BACKOFF_BASE", 0.001)


@pytest.fixture
def captured_sleep(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


def _transport(statuses, header_sets, calls: list):
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = state["i"]
        state["i"] += 1
        calls.append(i)
        if statuses[i] == 429:
            return httpx.Response(429, headers=header_sets[i],
                                  json={"error": {"code": 429}})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=SSE_OK)

    return httpx.MockTransport(handler)


async def _run(statuses, header_sets):
    calls: list = []
    client = llm.OpenRouterClient(
        api_key="k", model="test/model:free",
        http=httpx.AsyncClient(transport=_transport(statuses, header_sets, calls)))
    kinds = []
    async for ev in client.stream(messages=[{"role": "user", "content": "hi"}], tools=[]):
        kinds.append(ev.kind)
    return kinds, calls


# AC1: экспоненда с джиттером — растёт внутри запуска, различается между запусками

@pytest.mark.asyncio
async def test_t5_delays_grow_within_run_and_differ_between_runs(captured_sleep):
    await _run([429, 429, 200], [UPSTREAM_429, UPSTREAM_429, {}])
    first = list(captured_sleep)
    assert len(first) == 2
    assert first[1] > first[0], f"delays must grow within a run: {first}"

    captured_sleep.clear()
    await _run([429, 429, 200], [UPSTREAM_429, UPSTREAM_429, {}])
    second = list(captured_sleep)
    assert second[1] > second[0]
    assert first != second, f"jitter dead: two runs identical {first}"


# AC2: Retry-After ≤ потолка соблюдается дословно, а не формулой

@pytest.mark.asyncio
async def test_t5_retry_after_honored_verbatim(fast_backoff, captured_sleep):
    await _run([429, 200], [{"retry-after": "7"}, {}])
    assert captured_sleep == [7.0]


# AC4a: платформенный 429 — потолок шире, Retry-After 45с честно отрабатывается

@pytest.mark.asyncio
async def test_t5_platform_429_waits_out_longer_retry_after(fast_backoff, captured_sleep, caplog):
    with caplog.at_level("WARNING"):
        kinds, _ = await _run([429, 200], [PLATFORM_429 | {"retry-after": "45"}, {}])
    assert kinds[-1] == "final"
    assert captured_sleep == [45.0]
    assert any("platform" in r.message for r in caplog.records), \
        "platform 429 must be visible in the log as 'platform'"


# AC3+AC4b: upstream 429 с Retry-After выше СВОЕГО (меньшего) потолка — внятный RuntimeError

@pytest.mark.asyncio
async def test_t5_upstream_retry_after_over_ceiling_raises_clear_error(fast_backoff, captured_sleep):
    with pytest.raises(RuntimeError) as exc:
        await _run([429], [UPSTREAM_429 | {"retry-after": "45"}])
    text = str(exc.value)
    assert "потолок" in text, text
    assert "45" in text and "30" in text, f"error must name both waits: {text}"
    assert captured_sleep == [], "must fail fast instead of sleeping past the ceiling"


# AC5: счётчик считает каждую попытку ретрая

@pytest.mark.asyncio
async def test_t5_counter_counts_every_retry(fast_backoff, captured_sleep):
    from app import db, openrouter_counter as counter

    db.init_db()
    kinds, calls = await _run([429, 429, 200], [UPSTREAM_429, UPSTREAM_429, {}])
    assert kinds[-1] == "final"
    assert len(calls) == 3
    assert counter.today_count() == 3
    breakdown = counter.status_breakdown(counter.today_utc())
    assert breakdown.get("429") == 2 and breakdown.get("200") == 1


@pytest.mark.asyncio
async def test_t5_does_not_sleep_after_the_last_failed_attempt(fast_backoff, captured_sleep):
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        await _run(
            [429, 429, 429],
            [UPSTREAM_429, UPSTREAM_429, UPSTREAM_429],
        )

    assert len(captured_sleep) == 2
