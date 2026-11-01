"""Exact-session searches must not traverse unrelated project/agent log history."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import threading

import httpx
import pytest

from tests.test_log_search_v1078 import api, database, insert, log


DATES = [
    ("2026-10-25", None),  # Reported lower-only request; no date_to default.
    (None, "2026-10-25"),
    ("2026-10-24", "2026-10-26"),
    (None, None),
]


def populate(database, foreign=0):
    with database._conn() as c:
        insert(c, (log(i, "14:30", ts="2026-10-25T14:30:00Z") for i in range(1, 9)))
        insert(c, (log(i, "14:30", sid="foreign" if i % 2 else "worker",
                       ts="2026-10-25T14:30:00Z") for i in range(9, 9 + foreign)))


def count_work(database, monkeypatch, on_progress=None):
    """Count real SQLite VM work, including cursor read-ahead and all SQL phases."""
    connect = database._conn
    work = [0]

    @contextmanager
    def observed():
        with connect() as c:
            def progress():
                work[0] += 100
                if on_progress:
                    on_progress(work[0])
                return 0

            c.set_progress_handler(progress, 100)
            yield c

    monkeypatch.setattr(database, "_conn", observed)
    return work


@pytest.mark.parametrize("dates", DATES)
@pytest.mark.parametrize("analyzed", [False, True])
@pytest.mark.parametrize("query", ["14:30", "absent"])
def test_exact_session_work_is_independent_of_unrelated_logs(database, monkeypatch, dates,
                                                             analyzed, query):
    populate(database)
    work = count_work(database, monkeypatch)

    def search():
        work[0] = 0
        result = database.search_logs(query, scope="/synthetic/own", agent="project-orchestrator",
                                      date_from=dates[0], date_to=dates[1], limit=8)
        return result, work[0]

    small, small_work = search()
    with database._conn() as c:
        insert(c, (log(i, "14:30", sid="foreign" if i % 2 else "worker",
                       ts="2026-10-25T14:30:00Z") for i in range(9, 16_393)))
        if analyzed:
            c.execute("ANALYZE")
    large, large_work = search()
    assert large == small
    assert large["scanned"] == 8
    assert [r["id"] for r in large["results"]] == (list(range(8, 0, -1)) if query == "14:30" else [])
    # A generous deterministic instruction budget, not a wall-clock performance SLA.
    # A few session/index lookups are allowed; thousands of foreign rows are not.
    assert large_work <= small_work + 1_000
    assert large_work < 2_000


@pytest.mark.parametrize("agent", ["missing", "PROJECT-ORCHESTRATOR"])
@pytest.mark.parametrize("analyzed", [False, True])
def test_missing_exact_agent_avoids_global_log_walk(database, monkeypatch, agent, analyzed):
    populate(database, foreign=8_192)
    if analyzed:
        with database._conn() as c:
            c.execute("ANALYZE")
    work = count_work(database, monkeypatch)
    result = database.search_logs("14:30", scope="/synthetic/own", agent=agent,
                                  date_from="2026-10-25", limit=8)
    assert result["results"] == [] and result["scanned"] == 0
    assert not result["scan_truncated"] and not result["result_limit_reached"]
    assert work[0] < 2_000


def test_single_day_keeps_selective_day_lookup_with_large_old_session_history(database, monkeypatch):
    populate(database)
    with database._conn() as c:
        insert(c, (log(i, "14:30", ts="2020-01-01T14:30:00Z") for i in range(9, 16_393)))
    work = count_work(database, monkeypatch)
    result = database.search_logs("14:30", scope="/synthetic/own", agent="project-orchestrator",
                                  date_from="2026-10-25", date_to="2026-10-25", limit=8)
    assert [r["id"] for r in result["results"]] == list(range(8, 0, -1))
    assert result["scanned"] == 8 and not result["scan_truncated"]
    assert work[0] < 2_000


def test_exact_session_utc_dates_full_unicode_content_and_broad_controls(database):
    with database._conn() as c:
        insert(c, [
            log(1, "ß" * 20_000 + " редкая Straße İ " + "z" * 20_000,
                ts="2026-10-25T00:30:00+02:00"),  # prior UTC day
            log(2, "ß" * 20_000 + " редкая Straße İ " + "z" * 20_000,
                ts="2026-10-24T23:30:00-02:00"),  # lower UTC day
            log(3, "редкая Straße İ", ts="invalid"),
            log(4, "редкая Straße İ", ts="2026-10-26T14:30:00Z"),
            log(5, "редкая Straße İ", sid="foreign", ts="2026-10-25T14:30:00Z"),
            log(6, "редкая Straße İ", sid="worker", ts="2026-10-25T14:30:00Z"),
        ])
    for query in ("РЕДКАЯ", "STRASSE", "i\u0307"):
        result = database.search_logs(query, scope="/synthetic/own", agent="project-orchestrator",
                                      date_from="2026-10-25", limit=8)
        assert [r["id"] for r in result["results"]] == [4, 2]
        assert result["scanned"] == 2
        assert "редкая Straße İ" in result["results"][1]["snippet"]
    # No exact-session assumption may escape into explicit all_projects or scope-only search.
    broad = database.search_logs("STRASSE", scope=None, agent="project-orchestrator",
                                 date_from="2026-10-25")
    assert [r["id"] for r in broad["results"]] == [5, 4, 2]
    scoped = database.search_logs("STRASSE", scope="/synthetic/own", date_from="2026-10-25")
    assert [r["id"] for r in scoped["results"]] == [6, 4, 2]
    upper = database.search_logs("STRASSE", scope="/synthetic/own", agent="project-orchestrator",
                                 date_to="2026-10-24")
    assert [r["id"] for r in upper["results"]] == [1]
    day = database.search_logs("STRASSE", scope="/synthetic/own", agent="project-orchestrator",
                               date_from="2026-10-25", date_to="2026-10-25")
    assert [r["id"] for r in day["results"]] == [2]
    foreign = database.search_logs("STRASSE", scope="/synthetic/foreign", agent="project-orchestrator",
                                   date_from="2026-10-25")
    assert [r["id"] for r in foreign["results"]] == [5]


def test_exact_session_dates_filter_before_candidate_cap_and_do_not_follow_id_time(database):
    populate(database)
    with database._conn() as c:
        # Newest IDs have older timestamps: stopping at the first old timestamp,
        # or capping the session before filtering its dates, would hide all matches.
        insert(c, (log(i, "14:30", ts="2026-10-24T14:30:00Z") for i in range(9, 10_020)))
    result = database.search_logs("14:30", scope="/synthetic/own", agent="project-orchestrator",
                                  date_from="2026-10-25", limit=8)
    assert [r["id"] for r in result["results"]] == list(range(8, 0, -1))
    assert result["scanned"] == 8 and not result["scan_truncated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("requested,expected", [(-1, 1), (500, 50)])
async def test_exact_session_mcp_clamps_result_limits(database, api, requested, expected):
    with database._conn() as c:
        insert(c, (log(i, "14:30", ts="2026-10-25T14:30:00Z") for i in range(1, 61)))
    _, _, mcp = api
    result = json.loads(await mcp.search_logs("14:30", agent="project-orchestrator",
                                            date_from="2026-10-25", limit=requested))
    assert [r["id"] for r in result["results"]] == list(range(60, 60 - expected, -1))
    assert result["limit"] == expected and result["scanned"] == expected
    assert result["result_limit_reached"] and not result["scan_truncated"]


@pytest.mark.parametrize("count", [9_999, 10_000, 10_001])
def test_exact_session_candidate_cap_keeps_rare_matches_and_coverage(database, count):
    with database._conn() as c:
        insert(c, (log(i, "needle" if i == 1 else "noise", ts="2026-10-25T14:30:00Z")
                   for i in range(1, count + 1)))
        insert(c, (log(i, "needle", sid="foreign", ts="2026-10-25T14:30:00Z")
                   for i in range(count + 1, count + 101)))
    result = database.search_logs("needle", scope="/synthetic/own", agent="project-orchestrator",
                                  date_from="2026-10-25", limit=8)
    assert [r["id"] for r in result["results"]] == ([] if count > 10_000 else [1])
    assert result["scanned"] == min(count, 10_000)
    assert result["scan_truncated"] is (count > 10_000)
    assert not result["result_limit_reached"]


def test_exact_session_snapshot_survives_rename_move_update_and_delete(database, monkeypatch):
    populate(database)
    connect = database._conn
    changed = []

    @contextmanager
    def observed():
        with connect() as c:
            class ConcurrentWriter:
                def execute(self, sql, params=()):
                    if "WHERE l.id = " in sql and not changed:
                        with connect() as writer:
                            writer.execute("UPDATE sessions SET name='moved',scope='/synthetic/moved' WHERE id='own'")
                            writer.execute("UPDATE logs SET content='changed' WHERE session_id='own'")
                            writer.execute("DELETE FROM logs WHERE id=1")
                        changed.append(True)
                    return c.execute(sql, params)

            yield ConcurrentWriter()

    monkeypatch.setattr(database, "_conn", observed)
    result = database.search_logs("14:30", scope="/synthetic/own", agent="project-orchestrator",
                                  date_from="2026-10-25", limit=8)
    assert changed == [True]
    assert [r["id"] for r in result["results"]] == list(range(8, 0, -1))
    assert {r["project"] for r in result["results"]} == {"/synthetic/own"}
    assert database.search_logs("14:30", scope="/synthetic/own", agent="project-orchestrator",
                                date_from="2026-10-25")["scanned"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("force_timeout", [False, True])
async def test_lower_date_mcp_work_deadline_and_transport_recovery(database, monkeypatch, api,
                                                                 force_timeout):
    """Scale a deterministic excess-SQL-work stall, with a real ReadTimeout control.

    This is an injected deadline, not a reproduction of the private 30-second incident.
    No production timeout or payload truncation is changed; the VM-work oracle above
    independently detects the defect even without this transport deadline.
    """
    app, real_client, mcp = api
    populate(database, foreign=16_384)
    release = threading.Event()
    gated = threading.Event()

    def gate(work):
        if work > 2_000:
            gated.set()
            assert release.wait(5)

    work = count_work(database, monkeypatch, gate)
    executor = ThreadPoolExecutor(max_workers=1)

    class DeadlineTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert request.extensions["timeout"]["read"] == 30
            assert "date_to" not in request.url.params
            assert request.url.params["query"] == "14:30"
            assert request.url.params["date_from"] == "2026-10-25"
            assert request.url.params["agent"] == "project-orchestrator"
            if force_timeout:
                raise httpx.ReadTimeout("synthetic transport control", request=request)

            async def serve():
                return await httpx.ASGITransport(app).handle_async_request(request)

            future = executor.submit(asyncio.run, serve())
            try:
                return await asyncio.wait_for(asyncio.wrap_future(future), 1)
            except TimeoutError as exc:
                raise httpx.ReadTimeout("synthetic SQL-work gate", request=request) from exc

    monkeypatch.setattr(mcp.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=DeadlineTransport(), **kwargs))
    from mcp.types import CallToolRequest, CallToolRequestParams

    async def invoke():
        handler = mcp.mcp._mcp_server.request_handlers[CallToolRequest]
        wrapped = await handler(CallToolRequest(params=CallToolRequestParams(
            name="search_logs", arguments={"query": "14:30", "date_from": "2026-10-25",
                                           "agent": "project-orchestrator", "limit": 8},
        )))
        return wrapped.root

    try:
        envelope = await invoke()
        if force_timeout:
            assert envelope.isError
            error = envelope.structuredContent["error"]
            assert error["code"] == "transport_timeout"
            assert error["details"]["exception_type"] == "ReadTimeout"
            assert error["retryable"] and not error["outcome_unknown"]
            force_timeout = False
            envelope = await invoke()
        assert not envelope.isError, envelope.structuredContent
        result = envelope.structuredContent["result"]
        if isinstance(result, str):
            result = json.loads(result)
        assert [r["id"] for r in result["results"]] == list(range(8, 0, -1))
        assert result["scanned"] == 8 and result["result_limit_reached"]
        assert not gated.is_set()
        assert work[0] < 2_000
    finally:
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True)
