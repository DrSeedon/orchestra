"""#V-592 — перегрузка провайдера приходит чанком внутри уже открытого потока.

Ответ 200 OK, затем `data: {"error": {...}}` с текстом вроде «Upstream error from Nvidia:
Service temporarily overloaded». За вечер 17.09 это убило 13 ходов бесплатных воркеров
целиком. Повтор безопасен ровно до первого отданного события: дальше текст и вызовы
инструментов уже уехали в ход и продублировались бы.
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


def _sse_error(message: str, code=None) -> bytes:
    err = {"message": message}
    if code is not None:
        err["code"] = code
    return b"data: " + json.dumps({"error": err}).encode() + b"\n\n"


def _sse_text_then_error(text: str, message: str) -> bytes:
    return (
        b'data: ' + json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]}).encode() + b"\n\n"
        + _sse_error(message)
    )


@pytest.fixture
def no_sleep(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(d):
        delays.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


async def _run(bodies: list[bytes]):
    """Каждый элемент bodies — тело ОДНОЙ попытки. Возвращает (kinds, число попыток)."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[min(state["i"], len(bodies) - 1)]
        state["i"] += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = llm.OpenRouterClient(
        api_key="k", model="test/model:free",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    kinds = []
    async for ev in client.stream(messages=[{"role": "user", "content": "hi"}], tools=[]):
        kinds.append(ev.kind)
    return kinds, state["i"]


@pytest.mark.asyncio
async def test_transient_stream_error_is_retried(no_sleep):
    """Перегрузка апстрима до первого события → повтор, ход выживает."""
    kinds, attempts = await _run([
        _sse_error("Upstream error from Nvidia: Service temporarily overloaded"),
        SSE_OK,
    ])
    assert attempts == 2, "перегрузку апстрима обязаны повторить"
    assert kinds[-1] == "final"
    assert len(no_sleep) == 1 and no_sleep[0] > 0, "повтор без паузы бьёт в ту же стену"


@pytest.mark.asyncio
async def test_idle_timeout_is_retried(no_sleep):
    kinds, attempts = await _run([
        _sse_error("Upstream idle timeout exceeded"),
        SSE_OK,
    ])
    assert attempts == 2
    assert kinds[-1] == "final"


@pytest.mark.asyncio
async def test_non_transient_stream_error_is_not_retried(no_sleep):
    """Нет кредитов / нет модели повтором не лечатся: попытка и суточный лимит впустую."""
    with pytest.raises(RuntimeError) as exc:
        await _run([_sse_error("Insufficient credits", code=402), SSE_OK])
    assert "Insufficient credits" in str(exc.value)
    assert no_sleep == []


@pytest.mark.asyncio
async def test_stream_error_after_first_event_is_not_retried(no_sleep):
    """Побочные действия не дублируются: часть хода уже отдана — повтор запрещён."""
    with pytest.raises(RuntimeError):
        await _run([
            _sse_text_then_error("частичный ответ", "Service temporarily overloaded"),
            SSE_OK,
        ])
    assert no_sleep == [], "повтор после отданного события удвоил бы текст и вызовы инструментов"


@pytest.mark.asyncio
async def test_attempts_are_bounded(no_sleep):
    """Три неудачные попытки — честная ошибка хода, а не бесконечный цикл."""
    body = _sse_error("Service temporarily overloaded")
    with pytest.raises(RuntimeError) as exc:
        await _run([body, body, body, body])
    assert "overloaded" in str(exc.value)
    assert len(no_sleep) == llm.MAX_RETRIES - 1
