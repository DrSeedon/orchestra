"""Offline search regressions: storage work, contracts and event-loop ownership."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def database(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "search.sqlite")
    db.init_db()
    with db._conn() as c:
        c.executemany(
            "INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES(?,?,?,?,?,?)",
            [(sid, name, scope, scope, "test", "2026-10-01") for sid, name, scope in (
                ("own", "project-orchestrator", "/synthetic/own"),
                ("foreign", "project-orchestrator", "/synthetic/foreign"),
                ("worker", "project-orchestrator-copy", "/synthetic/own"),
            )],
        )
    return db


def insert(c, rows):
    c.executemany(
        "INSERT INTO logs(id,session_id,ts,type,content,origin) VALUES(?,?,?,?,?,?)", rows,
    )


def log(index, content="audit-marker", *, sid="own", ts="2026-10-24T12:00:00Z",
        kind="text", origin="unknown"):
    return index, sid, ts, kind, content, origin


@pytest.fixture
def api(monkeypatch):
    from app import mcp_stdio
    from app.routes import sessions

    app = FastAPI()
    app.include_router(sessions.router)

    @app.get("/health")
    async def health():
        return {"alive": True}

    real_client = httpx.AsyncClient
    transport = httpx.ASGITransport(app=app)
    monkeypatch.setattr(mcp_stdio, "SCOPE", "/synthetic/own")
    monkeypatch.setattr(
        mcp_stdio.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    return app, real_client, mcp_stdio


@pytest.mark.asyncio
async def test_mcp_route_database_scope_dates_order_voice_and_limits(database, api):
    _, _, mcp = api
    with database._conn() as c:
        insert(c, [
            log(1, "[voice: synthetic.oga] транскрипт: встреча у СБЕРБАНКА",
                kind="user_message", origin="user"),
            log(2, "Сбербанк", sid="foreign"),
            log(3, "Сбербанк", sid="worker"),
            log(4, "сбербанк", ts="2026-10-25T00:30:00+02:00", origin="agent",
                kind="user_message"),
            log(5, "сбербанк", ts="2026-10-23T23:30:00-02:00", kind="tool_result"),
            log(6, "сбербанк", ts="2026-10-24T23:30:00-02:00"),
            log(7, "сбербанк", ts="2026-10-24T00:30:00+02:00"),
            log(8, "сбербанк", ts="not-a-date"),
        ])
    result = json.loads(await mcp.search_logs(
        "СБЕР", date_from="2026-10-24", date_to="2026-10-24",
        agent="project-orchestrator", limit=50, kinds="all",
    ))
    assert [r["id"] for r in result["results"]] == [5, 4, 1]
    assert [r["type"] for r in result["results"]] == ["tool", "agent message", "user message"]
    assert "транскрипт" in result["results"][-1]["snippet"]
    assert result["scanned"] == 3
    assert not result["scan_truncated"] and not result["result_limit_reached"]
    all_projects = json.loads(await mcp.search_logs("Сбер", all_projects=True,
                                                 agent="project-orchestrator"))
    assert 2 in [r["id"] for r in all_projects["results"]]
    assert 3 not in [r["id"] for r in all_projects["results"]]
    limited = json.loads(await mcp.search_logs("Сбер", limit=1))
    assert limited["results"][0]["id"] == 8  # ids, not timestamps, define recency
    assert limited["result_limit_reached"] and limited["scanned"] == 1
    empty = json.loads(await mcp.search_logs("absent", date_from="2026-10-24",
                                           date_to="2026-10-24"))
    assert empty["results"] == [] and empty["scanned"] == 3
    assert not empty["result_limit_reached"] and not empty["scan_truncated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"query": ""}, {"query": " "}, {"query": "x" * 201},
    {"scope": None}, {"all_projects": True},
    {"date_from": "2026-02-30"}, {"date_to": "2026-1-2"},
    {"date_from": "2026-10-25", "date_to": "2026-10-24"},
    {"agent": " "}, {"agent": "x" * 101},
])
async def test_invalid_route_combinations_do_not_search(monkeypatch, api, params):
    from app.routes import sessions

    def forbidden(*args, **kwargs):
        pytest.fail("invalid request reached storage")

    monkeypatch.setattr(sessions, "search_logs", forbidden)
    app, real_client, _ = api
    values = {"query": "marker", "scope": "/synthetic/own", **params}
    values = {k: v for k, v in values.items() if v is not None}
    async with real_client(transport=httpx.ASGITransport(app), base_url="http://offline") as client:
        response = await client.get("/api/logs/search", params=values)
    assert response.status_code == 400


@pytest.mark.parametrize("count", [9_999, 10_000, 10_001])
def test_candidate_boundary_and_coverage(database, count):
    with database._conn() as c:
        insert(c, (log(i, "absent" if i != 1 else "hidden-match")
                   for i in range(1, count + 1)))
    result = database.search_logs("hidden-match", scope="/synthetic/own", limit=50)
    assert result["scanned"] == min(count, 10_000)
    assert result["scan_truncated"] is (count > 10_000)
    assert [r["id"] for r in result["results"]] == ([] if count > 10_000 else [1])
    assert not result["result_limit_reached"]


@pytest.mark.asyncio
async def test_result_limit_fifty_and_scan_limit_can_both_be_reached(database, api):
    with database._conn() as c:
        insert(c, (log(i, "match" if i <= 50 else "noise") for i in range(1, 10_050)))
    # The 10,000th candidate is the first match; 49 matches remain outside coverage.
    result = database.search_logs("match", scope="/synthetic/own", limit=1)
    assert result["scanned"] == 10_000 and result["scan_truncated"]
    assert result["result_limit_reached"]
    with database._conn() as c:
        c.execute("UPDATE logs SET content='match'")
    _, _, mcp = api
    result = json.loads(await mcp.search_logs("match", limit=500))
    assert result["limit"] == 50 and len(result["results"]) == 50
    assert result["scanned"] == 50 and not result["scan_truncated"]
    result = json.loads(await mcp.search_logs("match", limit=-10))
    assert result["limit"] == 1 and len(result["results"]) == 1


@pytest.mark.parametrize("prefix,match,query", [
    ("ß" * 500, "Straße", "STRASSE"),
    ("İ" * 500, "aßb", "SS"),
    ("ß" * 500, "İ", "i\u0307"),
    ("ß" * 500, "ß", "s"),
], ids=["sharp-s-prefix", "dotted-i-prefix", "expanded-query", "partial-expansion"])
def test_casefold_expansion_keeps_original_match_in_snippet(database, prefix, match, query):
    with database._conn() as c:
        insert(c, [log(1, prefix + " " + match + " " + "z" * 500)])
    result = database.search_logs(query, scope="/synthetic/own")
    assert match in result["results"][0]["snippet"]


def instrument_payloads(database, monkeypatch, observe):
    """A transparent view counts content evaluations inside SQLite, including sort work.

    Backing storage and indexes remain real SQLite. No timing or SQL-string assertion
    is needed to detect fetching blobs that the result limit never consumes.
    """
    with database._conn() as c:
        c.execute("ALTER TABLE logs RENAME TO stored_logs")
        c.execute("""CREATE VIEW logs AS SELECT id,session_id,ts,type,origin,
                     observe_content(content) AS content FROM stored_logs""")
    connect = database._conn

    def observed_connection(*args, **kwargs):
        c = connect(*args, **kwargs)
        c.create_function("observe_content", 1, observe)
        return c

    monkeypatch.setattr(database, "_conn", observed_connection)


@pytest.mark.parametrize("dates", [
    ("2026-10-24", "2026-10-24"), ("2026-10-23", "2026-10-24"),
    (None, "2026-10-24"), ("2026-10-23", None), (None, None),
])
@pytest.mark.parametrize("size", [24, 32_768])
def test_narrow_search_loads_only_consumed_payloads(database, monkeypatch, dates, size):
    with database._conn() as c:
        # Dates alternate in id order; foreign-project blobs and name collisions
        # must not become candidates or consume the 10,000-row coverage budget.
        insert(c, (log(i, "z" * size, ts=f"2026-10-{23 + i % 2}T12:00:00Z")
                   for i in range(1, 257)))
        insert(c, (log(i, "audit-marker", ts="2026-10-24T12:00:00Z")
                   for i in range(257, 265)))
        insert(c, (log(i, "audit-marker", sid="foreign" if i % 2 else "worker")
                   for i in range(265, 1_265)))
    reads = []

    def observe(content):
        reads.append(len(content))
        return content

    instrument_payloads(database, monkeypatch, observe)
    result = database.search_logs(
        "audit-marker", scope="/synthetic/own", agent="project-orchestrator",
        date_from=dates[0], date_to=dates[1], limit=8,
    )
    assert [r["id"] for r in result["results"]] == list(range(264, 256, -1))
    assert result["scanned"] == 8
    assert reads == [len("audit-marker")] * 8
    assert not result["scan_truncated"]


def test_rare_match_still_searches_complete_payload(database):
    payload = "z" * 200_000 + " РЕДКАЯ фраза " + "z" * 200_000
    with database._conn() as c:
        insert(c, [log(1, payload), *(log(i, "noise") for i in range(2, 202))])
    result = database.search_logs("редкая ФРАЗА", scope="/synthetic/own")
    assert result["scanned"] == 201
    assert "РЕДКАЯ фраза" in result["results"][0]["snippet"]


def test_search_uses_one_snapshot_during_concurrent_scope_and_content_updates(database, monkeypatch):
    from contextlib import contextmanager

    with database._conn() as c:
        insert(c, [log(1), log(2)])
    connect = database._conn
    changed = []

    @contextmanager
    def observed():
        with connect() as c:
            class ConcurrentWriter:
                def execute(self, sql, params=()):
                    # Commit between candidate selection and the first payload read.
                    # Exceptions propagate, unlike errors inside SQLite trace callbacks.
                    if "WHERE l.id = " in sql and not changed:
                        with connect() as writer:
                            writer.execute("UPDATE sessions SET scope='/synthetic/moved' WHERE id='own'")
                            writer.execute("UPDATE logs SET content='changed'")
                            writer.execute("DELETE FROM logs WHERE id=1")
                        changed.append(True)
                    return c.execute(sql, params)

            yield ConcurrentWriter()

    monkeypatch.setattr(database, "_conn", observed)
    result = database.search_logs("audit-marker", scope="/synthetic/own")
    assert changed == [True]
    assert [r["id"] for r in result["results"]] == [2, 1]
    assert {r["project"] for r in result["results"]} == {"/synthetic/own"}
    assert database.search_logs("audit-marker", scope="/synthetic/own")["scanned"] == 0


@pytest.mark.asyncio
async def test_blocked_sqlite_search_does_not_block_other_api(database, monkeypatch, api):
    from app.routes import sessions

    app, real_client, _ = api
    entered, release = threading.Event(), threading.Event()
    original = sessions.search_logs

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(2), "test did not release blocked search"
        return original(*args, **kwargs)

    monkeypatch.setattr(sessions, "search_logs", blocked)
    async with real_client(transport=httpx.ASGITransport(app), base_url="http://offline") as client:
        search = asyncio.create_task(client.get("/api/logs/search", params={
            "query": "marker", "scope": "/synthetic/own",
        }))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            # Check while the worker is provably blocked, not merely after it returns.
            assert not search.done()
            response = await asyncio.wait_for(client.get("/health"), 1)
            assert response.json() == {"alive": True}
        finally:
            release.set()
            await asyncio.gather(search, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel,error", [(False, False), (False, True), (True, False)])
async def test_worker_connection_ownership_error_cancel_and_recovery(
    database, monkeypatch, api, cancel, error,
):
    from app.routes import sessions

    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    loop_thread = threading.get_ident()
    opened = []
    connect = database._conn

    from contextlib import contextmanager

    @contextmanager
    def observed():
        try:
            with connect() as c:
                assert threading.get_ident() != loop_thread
                opened.append((c, threading.get_ident()))
                entered.set()
                assert release.wait(2)
                if error:
                    c.execute("SELECT missing_column FROM logs")
                yield c
                assert threading.get_ident() == opened[-1][1]
        finally:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                c.execute("SELECT 1")
            closed.set()

    monkeypatch.setattr(database, "_conn", observed)
    task = asyncio.create_task(sessions.search_logs_endpoint("marker", scope="/synthetic/own"))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert not task.done()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not closed.is_set()  # caller cancellation does not close the worker's DB
        release.set()
        if error:
            with pytest.raises(sqlite3.OperationalError, match="missing_column"):
                await task
        elif not cancel:
            assert (await task).status_code == 200
        assert await asyncio.to_thread(closed.wait, 3)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert len(opened) == 1
    monkeypatch.setattr(database, "_conn", connect)
    assert (await sessions.search_logs_endpoint("marker", scope="/synthetic/own")).status_code == 200


@pytest.mark.asyncio
async def test_mcp_chain_avoids_payload_materialization_deadline(database, monkeypatch, api):
    """Independent client/server loops enforce an offline, scaled read deadline.

    A content-access gate stalls only if SQLite evaluates a ninth payload despite
    limit=8. This reproduces transport timeout causally without a 30-second sleep.
    The MCP client still sends its unchanged 30-second timeout configuration.
    """
    app, real_client, mcp = api
    with database._conn() as c:
        insert(c, (log(i, "audit-marker", ts=f"2026-10-24T{i % 24:02}:00:00Z")
                   for i in range(1, 65)))
    release = threading.Event()
    reads = []

    def observe(content):
        reads.append(content)
        if len(reads) > 8:
            assert release.wait(3), "unconsumed payload gate not released"
        return content

    instrument_payloads(database, monkeypatch, observe)
    executor = ThreadPoolExecutor(max_workers=1)

    class DeadlineTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert request.extensions["timeout"]["read"] == 30

            async def serve():
                return await httpx.ASGITransport(app).handle_async_request(request)

            future = executor.submit(asyncio.run, serve())
            try:
                return await asyncio.wait_for(asyncio.wrap_future(future), 1)
            except TimeoutError as exc:
                raise httpx.ReadTimeout("synthetic payload gate", request=request) from exc

    monkeypatch.setattr(mcp.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=DeadlineTransport(), **kwargs))
    try:
        from mcp.types import CallToolRequest, CallToolRequestParams

        handler = mcp.mcp._mcp_server.request_handlers[CallToolRequest]
        wrapped = await handler(CallToolRequest(params=CallToolRequestParams(
            name="search_logs", arguments={
                "query": "audit-marker", "date_from": "2026-10-24", "date_to": "2026-10-24",
                "agent": "project-orchestrator", "limit": 8,
            },
        )))
        envelope = wrapped.root
        assert not envelope.isError, envelope.structuredContent
        result = envelope.structuredContent["result"]
        if isinstance(result, str):
            result = json.loads(result)
        assert [r["id"] for r in result["results"]] == list(range(64, 56, -1))
        assert len(reads) == 8
    finally:
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True)
