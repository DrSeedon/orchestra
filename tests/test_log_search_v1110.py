"""V-1110: conversation-only default scan, `kinds`, regex alternatives, bounded matching."""
import threading

import pytest

from tests.test_log_search_v1078 import api, database, insert, log  # noqa: F401


def ids(result):
    return [r["id"] for r in result["results"]]


def test_default_skips_tool_result_and_kinds_finds_it(database):
    with database._conn() as c:
        insert(c, [
            log(1, "needle in chat", kind="user_message", origin="user"),
            log(2, "needle in tool output", kind="tool_result"),
            log(3, "needle from agent", kind="user_message", origin="agent"),
        ])
    assert ids(database.search_logs("needle", scope="/synthetic/own")) == [3, 1]
    only_tool = database.search_logs("needle", scope="/synthetic/own", kinds="tool_result")
    assert ids(only_tool) == [2]
    assert ids(database.search_logs("needle", scope="/synthetic/own", kinds="all")) == [3, 2, 1]
    with pytest.raises(ValueError):
        database.search_logs("needle", scope="/synthetic/own", kinds="bogus")


def test_kinds_filter_widens_scan_window(database, monkeypatch):
    monkeypatch.setattr(database, "LOG_SEARCH_SCAN_LIMIT", 50)
    with database._conn() as c:
        insert(c, [log(1, "old needle", kind="user_message", origin="user")])
        insert(c, (log(i, "noise", kind="tool_result") for i in range(2, 200)))
    result = database.search_logs("needle", scope="/synthetic/own")
    assert ids(result) == [1] and not result["scan_truncated"]
    assert database.search_logs("needle", scope="/synthetic/own", kinds="all")["scan_truncated"]


def test_regex_alternatives_and_bad_pattern(database):
    with database._conn() as c:
        insert(c, [
            log(1, "платье фиолетовое"), log(2, "платье СИРЕНЕВОЕ"), log(3, "платье красное"),
            log(4, "literal a[b here"), log(5, "x" * 10),
        ])
    both = database.search_logs("фиолетов|сиренев", scope="/synthetic/own")
    assert ids(both) == [2, 1]
    assert both["results"][0]["snippet"].startswith("платье СИРЕНЕВОЕ")
    # unbalanced pattern: no exception, matched as plain text
    assert ids(database.search_logs("a[b", scope="/synthetic/own")) == [4]
    assert ids(database.search_logs("(unclosed", scope="/synthetic/own")) == []


def test_catastrophic_pattern_and_huge_row_do_not_hang(database):
    done = {}
    huge = "a" * 4_000_000 + "!"
    with database._conn() as c:
        insert(c, [log(1, huge), log(2, "zz tail marker")])

    def run():
        done["nested"] = database.search_logs("(a+)+$", scope="/synthetic/own")
        done["tail"] = database.search_logs("mark.r", scope="/synthetic/own")
        done["past_cap"] = database.search_logs("!+$", scope="/synthetic/own")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(20)
    assert not t.is_alive(), "search hung"
    assert ids(done["tail"]) == [2]
    # regex matching does not look beyond LOG_SEARCH_TEXT_CAP
    assert ids(done["past_cap"]) == []


@pytest.mark.asyncio
async def test_http_kinds_param_and_validation(database, api):
    import httpx
    app, real_client, _ = api
    with database._conn() as c:
        insert(c, [log(1, "needle tool", kind="tool_result")])
    async with real_client(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        base = {"query": "needle", "scope": "/synthetic/own"}
        assert (await client.get("/api/logs/search", params=base)).json()["results"] == []
        got = await client.get("/api/logs/search", params={**base, "kinds": "tool_result"})
        assert [r["id"] for r in got.json()["results"]] == [1]
        bad = await client.get("/api/logs/search", params={**base, "kinds": "nope"})
        assert bad.status_code == 400
