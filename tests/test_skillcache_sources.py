"""Exercise live adapter code paths without external services or real profiles."""

import json

import httpx
import pytest

from app.skillcache.abi import Rejected
from app.skillcache.pilots import _direct_reconcile, _direct_verify
from app.skillcache.sources import LiveSources


WINDOW = {"start": "2025-01-02", "end": "2025-01-03"}


def fake_http(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(
        "app.skillcache.sources.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_gmail_paginates_and_uses_only_read_requests(monkeypatch):
    pages = []

    def response(request):
        assert request.method == "GET"
        assert request.url.host == "gmail.googleapis.com"
        if request.url.path.endswith("/messages"):
            cursor = request.url.params.get("pageToken")
            pages.append(cursor)
            data = {"messages": [{"id": "aa" if cursor is None else "bb"}]}
            if cursor is None:
                data["nextPageToken"] = "next"
            assert "is:unread after:" in request.url.params["q"]
        else:
            mid = request.url.path.rsplit("/", 1)[1]
            assert "body" not in request.url.params["fields"]
            data = {"id": mid, "internalDate": "1735776000000", "snippet": "fixture"}
        return httpx.Response(200, json=data)

    fake_http(monkeypatch, response)
    src = LiveSources({"gmail_access_token_env": "FAKE_GMAIL"}, {"FAKE_GMAIL": "synthetic"})
    messages, coverage = src._gmail(WINDOW)
    assert pages == [None, "next"]
    assert [row["id"] for row in messages] == ["gmail/aa", "gmail/bb"]
    assert coverage == [{"folder": "gmail/unread", "count": 2}]


def test_imap_checks_nested_inbox_and_uses_readonly_peek(monkeypatch):
    calls = []

    class IMAP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, *args):
            return "OK", []

        def list(self):
            return "OK", [b'(\\HasChildren) "/" "INBOX"', b'() "/" "INBOX/Deals"', b'() "/" "Sent"']

        def select(self, folder, *, readonly):
            assert readonly
            calls.append(folder)
            return "OK", []

        def uid(self, command, *args):
            if command == "SEARCH":
                assert args[-1] == "UNSEEN"
                return "OK", [b"1" if calls[-1] == b'"INBOX/Deals"' else b""]
            assert command == "FETCH" and "BODY.PEEK" in args[-1]
            return "OK", [(b'1 (INTERNALDATE "02-Jan-2025 12:00:00 +0000"',
                            b"Subject: Fixture\r\n\r\nA message")]

    monkeypatch.setattr("app.skillcache.sources.imaplib.IMAP4_SSL", IMAP)
    config = {"mailru_user": "synthetic", "mailru_password_env": "FAKE_MAIL"}
    src = LiveSources(config, {"FAKE_MAIL": "synthetic"})
    messages, coverage = src._imap(WINDOW)
    assert calls == [b'"INBOX"', b'"INBOX/Deals"']
    assert messages[0]["preview"] == "A message"
    assert coverage == [{"folder": "mailru/INBOX", "count": 0}, {"folder": "mailru/INBOX/Deals", "count": 1}]


def test_direct_requests_daily_and_independent_totals(monkeypatch):
    calls = []
    selection = {"window": WINDOW, "campaign": "42", "goal": "10", "attribution": "LC", "vat": True}

    def response(request):
        assert request.url.path == "/json/v5/reports"
        params = json.loads(request.content)["params"]
        assert params["IncludeVAT"] == "YES"
        assert params["Goals"] == ["10"] and params["AttributionModels"] == ["LC"]
        assert params["SelectionCriteria"] == {
            "DateFrom": "2025-01-02", "DateTo": "2025-01-03",
            "Filter": [{"Field": "CampaignId", "Operator": "EQUALS", "Values": ["42"]}],
        }
        calls.append(params["FieldNames"])
        data = ("CampaignId\tDate\tCost\tConversions_10_LC\n42\t2025-01-02\t123\t2\n"
                if "Date" in calls[-1] else "CampaignId\tCost\tConversions_10_LC\n42\t123\t2\n")
        return httpx.Response(200, text=data)

    fake_http(monkeypatch, response)
    direct = {"campaigns": ["42"], "goals": ["10"], "attributions": ["LC"],
              "currency": "RUB", "timezone": "Europe/Moscow"}
    src = LiveSources({"direct": direct, "direct_access_token_env": "FAKE_DIRECT"}, {"FAKE_DIRECT": "synthetic"})
    report = src.direct(selection)
    assert len(calls) == 2
    assert report["rows"][-1] == {"date": "2025-01-03", "spend_micros": 0, "conversions": 0}
    totals = _direct_reconcile({"report": report}, src)["totals"]
    assert _direct_verify({"report": report, "totals": totals, "selection": selection}, src) == {}
    with pytest.raises(Rejected):
        _direct_verify({"report": report, "totals": {**totals, "spend_micros": 0}, "selection": selection}, src)


def test_sleep_reads_synced_files_without_writes(tmp_path):
    logs = tmp_path / "sleep-log"
    logs.mkdir()
    activity = tmp_path / "activity-log"
    activity.mkdir()
    sleep_path = logs / "2025-01-sleep.md"
    rhr_path = activity / "2025-01-activity.md"
    sleep = (
        "| 11 | 31.12→01.01 | — | — | — | — | — |\n"
        "| 12 | 01→02.01 | — | **7ч10м** ✅ | x | y | z |\n"
        "| 13 | 02→03.01 | — | ~50м | x | y | z |\n"
    )
    rhr = "| 2025-01-02 | 1 | x | 10 | 59 | — |\n"
    sleep_path.write_text(sleep)
    rhr_path.write_text(rhr)
    src = LiveSources({"wellness_root": str(tmp_path)}, {})
    assert src.sleep(WINDOW) == [
        {"date": "2025-01-02", "sleep_minutes": 430, "rhr_bpm": 59},
        {"date": "2025-01-03", "sleep_minutes": 50, "rhr_bpm": None},
    ]
    assert sleep_path.read_text() == sleep and rhr_path.read_text() == rhr



def test_cdp_reads_authorized_headless_page_without_following_redirects(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace as Obj

    calls = []
    source = LiveSources({"cdp_pages": {"dashboard": "https://preview.example/"}}, {})

    class Route:
        def __init__(self, url="https://preview.example/", method="GET", status=200):
            self.request = Obj(url=url, method=method)
            self.status = status

        def fetch(self, *, max_redirects, timeout):
            assert max_redirects == 0
            return Obj(status=self.status)

        def abort(self):
            calls.append("aborted")

        def fulfill(self, *, response):
            calls.append(response.status)

    class Context:
        def route(self, pattern, guard):
            for route in (Route(status=302), Route(url="https://elsewhere.example/"),
                          Route(method="POST"), Route()):
                guard(route)

        def route_web_socket(self, pattern, guard):
            guard(Obj(close=lambda: calls.append("closed-websocket")))

        def new_page(self):
            return Obj(goto=lambda *_, **__: Obj(status=200),
                       evaluate=lambda expression: "https://preview.example",
                       locator=lambda selector: Obj(count=lambda: 1))

        def new_cdp_session(self, page):
            return Obj(send=lambda method: {
                "Performance.enable": {},
                "Performance.getMetrics": {"metrics": [
                    {"name": "NavigationStart", "value": 1},
                    {"name": "DomContentLoaded", "value": 1.5},
                ]},
                "Memory.getDOMCounters": {"nodes": 20},
            }[method])

    def launch(*, headless, timeout):
        assert headless
        return Obj(new_context=lambda *, service_workers: Context(), close=lambda: calls.append("closed"))

    monkeypatch.setattr("playwright.sync_api.sync_playwright",
                        lambda: nullcontext(Obj(chromium=Obj(launch=launch))))
    result = source.cdp({"page": "dashboard", "selectors": ["#status"]})
    assert calls == ["aborted", "aborted", "aborted", 200, "closed-websocket", "closed"]
    assert result["elements"] == [{"selector": "#status", "count": 1}]
    assert result["dom_nodes"] == 20 and result["load_ms"] == 500


def test_wave17_six_new_live_sources_read_only_and_masked(tmp_path, monkeypatch):
    import json
    import sqlite3
    from types import SimpleNamespace
    import httpx
    from app.skillcache.sources import LiveSources
    from app.skillcache.abi import AccessRevoked
    from app.skillcache.pilots import (
        _avito_summarize, _avito_verify,
        _edo_normalize, _edo_verify,
        _morning_normalize, _morning_verify,
        _vps_summarize, _vps_verify,
        _wellness_summarize, _wellness_verify,
        _youtube_normalize, _youtube_verify,
    )

    # Setup fixtures on tmp_path
    sleep_dir = tmp_path / "sleep-log"
    act_dir = tmp_path / "activity-log"
    sleep_dir.mkdir()
    act_dir.mkdir()
    (sleep_dir / "2025-01-sleep.md").write_text("| 1 | 01→02.01 | — | **7ч30м** | x | y | z |\n")
    (act_dir / "2025-01-activity.md").write_text("| 2025-01-02 | 1 | 2 | 3 | 58 | 6 |\n")

    dash_json = tmp_path / "wellness_data.json"
    dash_json.write_text(json.dumps({
        "updated": "2025-01-02",
        "courses": {"c1": {"active": True}, "c2": {"active": False}},
        "inventory": {"mag": {"name": "Magnesium", "stock": 3, "threshold": 5}},
        "log": [{"id": 1}, {"id": 2}],
    }))

    rem_db = tmp_path / "reminders.db"
    with sqlite3.connect(rem_db) as conn:
        conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, status TEXT)")
        conn.execute("INSERT INTO reminders VALUES (1, 'pending'), (2, 'done')")

    edo_db = tmp_path / "edo-db"
    edo_db.mkdir()
    (edo_db / "1Cv8.1CD").write_bytes(b"edo-data")
    edo_inbox = tmp_path / "edo-inbox"
    edo_inbox.mkdir()
    (edo_inbox / "doc1.xml").write_text("<xml/>")
    acc_guide = tmp_path / "ACCOUNTING.md"
    acc_guide.write_text("Срок сдачи РСВ до 25 числа\nsk-proj-secret1234567890abcdef token\n")

    yt_cache = tmp_path / "yt-cache"
    yt_cache.mkdir()
    (yt_cache / "dQw4w9WgXcQ.json").write_text(json.dumps({
        "title": "Video Title", "author_name": "Channel",
        "author_url": "https://youtube.com/@c", "transcript": "Hello chapter", "chapters_count": 2,
    }))

    orch_db = tmp_path / "orchestra.db"
    with sqlite3.connect(orch_db) as conn:
        conn.execute("CREATE TABLE sessions (name TEXT, status TEXT)")
        conn.execute("INSERT INTO sessions VALUES ('w1', 'running'), ('w2', 'idle')")

    avito_json = tmp_path / "listings.json"
    avito_json.write_text(json.dumps({
        "items": [
            {"batch": "b1", "status": "published", "price_rub": 1500, "photos": 3},
            {"batch": "b1", "status": "draft", "price_rub": 2500, "photos": 0},
        ]
    }))

    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0,
        stdout="ActiveState=active\nSubState=running\nMainPID=1234\nMemoryCurrent=104857600\nNRestarts=0\n",
    ))

    src = LiveSources({
        "wellness_root": str(tmp_path),
        "wellness_dashboard_path": str(dash_json),
        "reminders_db_path": str(rem_db),
        "edo_db_dir": str(edo_db),
        "edo_platform_path": str(edo_db / "1Cv8.1CD"),
        "edo_license_path": str(edo_db / "missing.lic"),
        "edo_inbox_dir": str(edo_inbox),
        "accounting_guide_path": str(acc_guide),
        "youtube_cache_dir": str(yt_cache),
        "vps_allowed_units": ["orchestra.service"],
        "vps_stat_path": str(tmp_path),
        "orchestra_db_path": str(orch_db),
        "avito_listings_path": str(avito_json),
    }, {})

    win = {"start": "2025-01-02", "end": "2025-01-02"}
    m_raw = src.morning(win)
    m_dig = _morning_normalize({"raw": m_raw}, src)["digest"]
    assert m_dig["reminders_pending"] == 1 and m_dig["active_courses"] == 1
    assert _morning_verify({"window": win, "raw": m_raw, "digest": m_dig}, src) == {}

    wsel = {"window": win, "category": "all"}
    w_raw = src.wellness(wsel)
    w_sum = _wellness_summarize({"raw": w_raw}, src)["summary"]
    assert w_sum["low_stock_names"] == ["Magnesium"] and w_sum["sleep_nights"] == 1
    assert _wellness_verify({"selection": wsel, "raw": w_raw, "summary": w_sum}, src) == {}

    etgt = {"scope_key": "seedon", "include_deadlines": True}
    e_raw = src.edo(etgt)
    e_st = _edo_normalize({"raw": e_raw}, src)["status"]
    assert e_st["incoming_xml_count"] == 1 and e_st["db_bytes"] == 8
    assert _edo_verify({"target": etgt, "raw": e_raw, "status": e_st}, src) == {}

    ytgt = {"video_id": "dQw4w9WgXcQ", "include_transcript": True}
    y_raw = src.youtube(ytgt)
    y_meta = _youtube_normalize({"raw": y_raw}, src)["metadata"]
    assert y_meta["title"] == "Video Title" and y_meta["chapters_count"] == 2
    assert _youtube_verify({"target": ytgt, "raw": y_raw, "metadata": y_meta}, src) == {}

    vq = {"units": ["orchestra.service"], "include_sessions": True}
    v_raw = src.vps(vq)
    v_rep = _vps_summarize({"raw": v_raw}, src)["report"]
    assert v_rep["cut_risk"] is True and v_rep["service_states"][0]["rss_mib"] == 100
    assert _vps_verify({"query": vq, "raw": v_raw, "report": v_rep}, src) == {}
    with pytest.raises(AccessRevoked):
        src.vps({"units": ["ssh.service"], "include_sessions": False})

    aq = {"batch": "b1", "status_filter": "draft"}
    a_raw = src.avito(aq)
    a_st = _avito_summarize({"raw": a_raw}, src)["stats"]
    assert a_st["matched_items"] == 1 and a_st["missing_photo_count"] == 1
    assert _avito_verify({"query": aq, "raw": a_raw, "stats": a_st}, src) == {}
