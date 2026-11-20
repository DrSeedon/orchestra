"""Synthetic counterexamples with expected values independent of the manifest."""

from copy import deepcopy

from .pilots import MANIFESTS
from .sources import Evidence


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
        elif skill == "wellness-dashboard":
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
        else:
            raise KeyError(skill)
        name = next(name for name, binding in MANIFESTS[skill]["bindings"].items() if binding["from"] == "request")
        probes.append({
            "selection": selection, "read": values, "expected": expected, "workspace": workspace,
            "bindings": {name: selection}, "answer": answer,
            "origin": values["origin"] if skill == "browser-control" else None,
        })
    return probes

