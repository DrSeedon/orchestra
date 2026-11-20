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
    sleep = "| 12 | 01→02.01 | — | **7ч10м** | x | y | z |\n| 13 | 02→03.01 | — | **50м** | x | y | z |\n"
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
