"""#197 — статика едет сжатой, а потоки не буферизуются.

Горб первой загрузки — это статика: 814 КБ против 68 КБ у всех API вместе. Она
отдавалась без сжатия, и на канале юзера (~30 КБ/с, ~17% потерянных коннектов) это
и есть «загрузился в начале долго».

Опасность сжатия ровно одна и она не про размер: gzip копит буфер, и поток, который
обязан приходить ПО МЕРЕ ПОЯВЛЕНИЯ, приезжает пачкой в конце. Поэтому наличие
заголовка тут проверяется мимоходом, а настоящий оракул — инкрементальность SSE.
"""

import asyncio
import contextlib
import json
import time
from unittest import mock

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route


def _app_like_production() -> Starlette:
    """Стенд повторяет ПОРЯДОК и параметры прода, а не воображаемую конфигурацию.

    Проверять сжатие на настоящем `app.main` нельзя дёшево: он поднимает lifespan с
    воркерами, мостом и туннелями. Здесь важна ровно одна вещь — как ведёт себя
    GZipMiddleware с теми же аргументами на тех же трёх видах ответа.
    """

    async def static_like(request):
        # Крупный сжимаемый ответ — это app.js (434 КБ реального JS).
        return PlainTextResponse(
            "function orchestraDashboard() { return 42; }\n" * 4000,
            media_type="application/javascript",
        )

    async def sse(request):
        async def gen():
            for i in range(3):
                yield f"data: {json.dumps({'i': i})}\n\n".encode()
                await asyncio.sleep(0.15)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def markdown_stream(request):
        # GET /api/report_bug: StreamingResponse, но конечный и НЕ event-stream.
        async def gen():
            for i in range(200):
                yield f"# report {i}\n".encode()

        return StreamingResponse(gen(), media_type="text/markdown")

    app = Starlette(routes=[
        Route("/static/js/app.js", static_like),
        Route("/api/sessions/x/stream", sse),
        Route("/api/report_bug", markdown_stream),
    ])
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    return app


@pytest.mark.asyncio
async def test_static_is_gzipped_and_shrinks_over_the_wire():
    transport = httpx.ASGITransport(app=_app_like_production())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        plain = await client.get(
            "/static/js/app.js", headers={"accept-encoding": "identity"}
        )
        gz = await client.get(
            "/static/js/app.js", headers={"accept-encoding": "gzip"}
        )

    assert plain.status_code == 200 and gz.status_code == 200
    assert gz.headers.get("content-encoding") == "gzip"
    wire_plain = len(plain.content)
    # httpx распаковывает прозрачно — вес ПО ПРОВОДУ берём из content-length ответа.
    wire_gz = int(gz.headers["content-length"])
    assert wire_gz < wire_plain / 2, f"сжатие не дало выигрыша: {wire_plain} -> {wire_gz}"
    # Тело обязано совпасть: сжатие меняет вес, а не содержимое.
    assert gz.text == plain.text


@contextlib.contextmanager
def _live_server(app):
    """Настоящий сокет, а не ASGITransport.

    ASGITransport собирает тело целиком, прежде чем отдать его клиенту, — на нём
    `aiter_bytes` даёт ОДИН кусок и при исправном коде тоже. Такая проверка мерила бы
    транспорт вместо сжатия и краснела бы всегда. Инкрементальность видна только через
    сокет.
    """
    import threading

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if server.started and server.servers and server.servers[0].sockets:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("uvicorn не поднялся за 15 с")
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def _stream_arrivals(base_url: str, path: str) -> tuple[list[float], dict]:
    """Моменты прихода непустых кусков и заголовки ответа."""
    arrivals: list[float] = []
    with httpx.Client(base_url=base_url, timeout=30) as client:
        with client.stream(
            "GET", path, headers={"accept-encoding": "gzip"}
        ) as response:
            assert response.status_code == 200
            start = time.monotonic()
            for chunk in response.iter_bytes():
                if chunk.strip():
                    arrivals.append(time.monotonic() - start)
            headers = dict(response.headers)
    return arrivals, headers


def test_sse_arrives_incrementally_and_is_not_compressed():
    """Настоящий оракул: события разнесены во времени, а не приезжают пачкой в конце.

    Контрольное плечо обязательно и оно РАЗРЕШАЮЩЕЕ наоборот: тот же поток, но с
    принудительным сжатием (исключения сняты), обязан схлопнуться. Без него «события
    разнесены» одинаково верно и при работающем освобождении SSE, и при стенде,
    который в принципе не умеет показать буферизацию.
    """
    with _live_server(_app_like_production()) as base_url:
        arrivals, headers = _stream_arrivals(base_url, "/api/sessions/x/stream")

    assert len(arrivals) >= 3, f"поток отдал меньше событий, чем прислал: {arrivals}"
    assert "content-encoding" not in headers, (
        f"SSE не должен сжиматься вовсе: {headers.get('content-encoding')}"
    )
    spread = arrivals[-1] - arrivals[0]
    assert spread > 0.15, (
        f"события приехали пачкой (разброс {spread:.3f} с) — поток забуферизован: {arrivals}"
    )


def test_control_arm_forced_compression_does_collapse_the_stream():
    """Контроль стенда: со сжатием того же потока разброс схлопывается.

    Это доказывает, что предыдущий тест ФИЗИЧЕСКИ СПОСОБЕН покраснеть. Без такого
    плеча зелёный там ничего не значит — он одинаков и при исправном освобождении
    SSE, и при стенде, который буферизацию не показывает в принципе.
    """
    app = _app_like_production()
    # Сжимаем ВСЁ, включая event-stream: снимаем ровно то освобождение, на котором
    # держится боевая конфигурация.
    app.user_middleware.clear()
    app.middleware_stack = None
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=9)
    with mock.patch(
        "starlette.middleware.gzip.DEFAULT_EXCLUDED_CONTENT_TYPES", ()
    ):
        with _live_server(app) as base_url:
            arrivals, headers = _stream_arrivals(base_url, "/api/sessions/x/stream")

    assert arrivals, "контрольное плечо не получило ни одного куска — стенд сломан"
    spread = arrivals[-1] - arrivals[0]
    assert headers.get("content-encoding") == "gzip", (
        f"контроль обязан был сжать поток, иначе он ничего не контролирует: {headers}"
    )
    assert spread < 0.15, (
        f"сжатый поток обязан схлопнуться, иначе оракул выше не умеет краснеть: "
        f"разброс {spread:.3f} с, {arrivals}"
    )


@pytest.mark.asyncio
async def test_markdown_stream_survives_compression_whole():
    """GET /api/report_bug сжимать можно, но тело обязано доехать целиком."""
    transport = httpx.ASGITransport(app=_app_like_production())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get(
            "/api/report_bug", headers={"accept-encoding": "gzip"}
        )

    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    expected = "".join(f"# report {i}\n" for i in range(200))
    assert response.text == expected, "сжатый поток доехал не целиком"


def test_production_app_registers_gzip_middleware():
    """Стенд выше проверяет ПОВЕДЕНИЕ; эта строка — что прод вообще его включил.

    Читаем зарегистрированный стек, а не текст файла: строка в исходнике может быть
    закомментирована или стоять в мёртвой ветке, а стек — это то, что исполняется.
    """
    from app.main import app

    stack = [m.cls.__name__ for m in app.user_middleware]
    assert "GZipMiddleware" in stack, f"gzip не подключён: {stack}"
    # `user_middleware` хранится ВНЕШНИЙ-ПЕРВЫМ: add_middleware делает insert(0), поэтому
    # последний добавленный стоит в начале списка и обрабатывает запрос раньше всех.
    # Проверено прогоном: ['GZipMiddleware', 'AuthMiddleware', 'RequestCensusMiddleware']
    # при порядке добавления Census -> Auth -> GZip.
    assert stack[0] == "GZipMiddleware", (
        f"gzip обязан быть самым внешним, иначе он придерживает http.response.start и "
        f"счётчик потоков в RequestCensusMiddleware узнаёт о потоке с опозданием: {stack}"
    )


def test_gzip_excludes_event_stream_by_default():
    """Освобождение SSE держится на константе Starlette — зафиксируем её явно.

    Обновление Starlette, где `text/event-stream` пропал бы из списка, сломало бы
    живые потоки молча. Пусть ломается тест, а не дашборд.
    """
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

    assert "text/event-stream" in DEFAULT_EXCLUDED_CONTENT_TYPES
