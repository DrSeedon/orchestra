"""Synthetic counterexamples with expected values independent of the manifest."""

from copy import deepcopy
from hashlib import sha256

from .abi import canonical
from .pilots import MANIFESTS
from .sources import Evidence


def _hash(value) -> str:
    return sha256(canonical(value).encode()).hexdigest()


class SyntheticSources(Evidence):
    def __init__(self, fixture):
        super().__init__()
        self.fixture = fixture

    def _read(self, domain, selection):
        assert selection == self.fixture["selection"]
        return self.record(domain, deepcopy(self.fixture["read"]))

    def mail(self, window, accounts):
        assert accounts == ["mailru", "gmail"]
        return self._read("mail", window)

    def direct(self, selection):
        return self._read("direct", selection)

    def sleep(self, window):
        return self._read("sleep", window)

    def cdp(self, selection):
        return self._read("cdp", selection)

    def morning(self, window):
        return self._read("morning", window)

    def wellness(self, selection):
        return self._read("wellness", selection)

    def edo(self, target):
        return self._read("edo", target)

    def youtube(self, target):
        return self._read("youtube", target)

    def vps(self, query):
        return self._read("vps", query)

    def avito(self, query):
        return self._read("avito", query)

    def origin(self, page):
        assert page == self.fixture["selection"]["page"]
        return self.fixture["origin"]


def cases(skill):
    is_mail = skill == "kesha-mail"
    workspace = {"sources": ["mailru", "gmail"]} if is_mail else {}
    probes = []
    for variant in (0, 1):
        day = ["2025-01-01", "2025-02-02"][variant]
        window = {"start": day, "end": day}
        selection = window
        answer = {}
        if is_mail:
            box = ["mailru/INBOX/Test", "mailru/INBOX/Changed"][variant]
            mid = ["synthetic-a", "synthetic-b"][variant]
            values = {"window": window, "sources": workspace["sources"],
                      "coverage": [{"folder": "mailru/INBOX", "count": 0},
                                   {"folder": box, "count": 1}, {"folder": "gmail/unread", "count": 0}],
                      "messages": [{"id": mid, "thread_key": mid, "received": day,
                                    "subject": "Synthetic subject", "preview": "<b>Synthetic content</b>"}]}
            expected = {"digest": [{"id": mid, "summary": "Fixture digest"}]}
            answer = {"prioritize": expected}
        elif skill == "direct-reports":
            selection = {"window": window, "campaign": ["11", "22"][variant],
                         "goal": ["55", "66"][variant], "attribution": ["LSCCD", "AUTO"][variant],
                         "vat": bool(variant)}
            totals = {"spend_micros": [1000, 2200][variant], "conversions": [1, 9][variant]}
            expected = {"totals": {"selection": selection, "currency": "RUB", "timezone": "Europe/Moscow", **totals}}
            values = {"selection": selection, "currency": "RUB", "timezone": "Europe/Moscow",
                      "provider_totals": totals, "rows": [{"date": day, **totals}]}
        elif skill == "xiaomi-sleep":
            minutes, heart = [(420, 55), (480, None)][variant]
            values = [{"date": day, "sleep_minutes": minutes, "rhr_bpm": heart}]
            if variant:
                window = {"start": day, "end": "2025-02-03"}
                selection = window
            expected = {"summary": {"window": window, "nights": 1, "missing": ["2025-02-03"] if variant else [],
                                    "median_sleep_minutes": minutes, "median_rhr_bpm": heart,
                                    "rhr_observations": 0 if variant else 1}}
        elif skill == "browser-control":
            selection = {"page": ["sample-a", "sample-b"][variant], "selectors": ["#content"]}
            values = {"page": selection["page"], "origin": ["https://a.example", "https://b.example"][variant],
                      "status": 200, "elements": [{"selector": "#content", "count": 1}],
                      "dom_nodes": [10, 20][variant], "load_ms": [100, 110][variant]}
            expected = {"snapshot": values}
        elif skill == "morning-digest":
            values = {
                "window": window,
                "unread_mail_count": [2, 5][variant],
                "mail_subjects": [["Order A"], ["Invoice B", "Alert C"]][variant],
                "sleep_minutes": [430, 470][variant],
                "rhr_bpm": [58, 62][variant],
                "reminders_pending": [1, 3][variant],
                "active_courses": [3, 4][variant],
            }
            expected = {"digest": {**values, "checksum": _hash(values)}}
        elif skill == "wellness-dashboard":
            selection = {"window": window, "category": ["all", "supplements"][variant]}
            values = {
                "selection": selection,
                "updated": ["2025-01-01", "2025-02-02"][variant],
                "active_courses": [4, 2][variant],
                "low_stock_count": [1, 2][variant],
                "low_stock_names": [["magnesium"], ["omega3", "vitd"]][variant],
                "recent_intake_count": [5, 8][variant],
                "sleep_nights": [1, 2][variant],
                "median_sleep_minutes": [425, 465][variant],
                "median_rhr_bpm": [56, 60][variant],
            }
            expected = {"summary": {**values, "checksum": _hash(values)}}
        elif skill == "edo-1c-status":
            selection = {"scope_key": ["seedon-edo", "seedon-acc"][variant], "include_deadlines": bool(variant)}
            values = {
                "scope_key": selection["scope_key"],
                "db_exists": True,
                "db_bytes": [1048576, 2097152][variant],
                "platform_exists": True,
                "license_exists": bool(variant),
                "incoming_xml_count": [0, 3][variant],
                "deadline_lines": [[], ["25.02: УСН/персданные"]][variant],
            }
            expected = {"status": {**values, "checksum": _hash(values)}}
        elif skill == "youtube-reader":
            selection = {"video_id": ["dQw4w9WgXcQ", "M7lc1UVf-VE"][variant], "include_transcript": bool(variant)}
            values = {
                "video_id": selection["video_id"],
                "include_transcript": selection["include_transcript"],
                "title": ["Sample Video A", "Sample Video B"][variant],
                "author_name": ["Author A", "Author B"][variant],
                "author_url": ["https://www.youtube.com/@a", "https://www.youtube.com/@b"][variant],
                "has_transcript": bool(variant),
                "chapters_count": [0, 4][variant],
                "transcript_chars": [0, 42][variant],
                "transcript_excerpt": ["", "First cached chapter line for sample B."][variant],
            }
            expected = {"metadata": {**values, "checksum": _hash(values)}}
        elif skill == "vps-health-preflight":
            selection = {"units": [["orchestra.service"], ["orchestra.service", "kesha-bot-vps.service"]][variant],
                         "include_sessions": bool(variant)}
            states = [[{"unit": "orchestra.service", "active": "active", "sub": "running", "pid": 100, "rss_mib": 256, "restarts": 0}],
                      [{"unit": "orchestra.service", "active": "active", "sub": "running", "pid": 101, "rss_mib": 300, "restarts": 0},
                       {"unit": "kesha-bot-vps.service", "active": "active", "sub": "running", "pid": 102, "rss_mib": 120, "restarts": 0}]][variant]
            values = {
                "units": selection["units"],
                "include_sessions": selection["include_sessions"],
                "service_states": states,
                "disk_free_mb": [50000, 48000][variant],
                "running_sessions": [0, 1][variant],
                "waiting_sessions": [2, 3][variant],
                "idle_sessions": [10, 12][variant],
            }
            expected = {"report": {
                "units": values["units"],
                "service_states": values["service_states"],
                "disk_free_mb": values["disk_free_mb"],
                "running_sessions": values["running_sessions"],
                "waiting_sessions": values["waiting_sessions"],
                "idle_sessions": values["idle_sessions"],
                "cut_risk": values["running_sessions"] > 0,
                "checksum": _hash(values),
            }}
        elif skill == "avito-stats":
            selection = {"batch": ["batch-aug", "batch-oct"][variant], "status_filter": ["all", "draft"][variant]}
            values = {
                "batch": selection["batch"],
                "status_filter": selection["status_filter"],
                "total_items": [11, 13][variant],
                "matched_items": [11, 9][variant],
                "published_count": [11, 4][variant],
                "draft_count": [0, 9][variant],
                "total_price_rub": [35000, 62000][variant],
                "missing_photo_count": [0, 2][variant],
            }
            expected = {"stats": {**values, "checksum": _hash(values)}}
        else:
            raise KeyError(skill)
        name = next(name for name, binding in MANIFESTS[skill]["bindings"].items() if binding["from"] == "request")
        probes.append({
            "selection": selection, "read": values, "expected": expected, "workspace": workspace,
            "bindings": {name: selection}, "answer": answer,
            "origin": values["origin"] if skill == "browser-control" else None,
        })
    return probes
