"""Four read-only plans over host-authorized sources.

Sources are trusted adapters, never module names, endpoints or credentials from
the manifest. Materialized evidence stays in the runner's private state.
"""

from datetime import date, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from statistics import median
import re

from .abi import Operation, Rejected, canonical, check_value, fields, object_schema
from .registry import Catalog


def string(length=120):
    return {"type": "string", "minLength": 1, "maxLength": length}


def array(items, limit=2048):
    return {"type": "array", "items": items, "maxItems": limit}


DATE = {**string(10), "pattern": r"^\d{4}-\d\d-\d\d$"}
IDENT = {**string(), "pattern": r"^[a-zA-Z0-9_.:@/-]+$"}
NATURAL = {"type": "integer", "minimum": 0}
NUMBER = {"type": "number", "minimum": 0}
OPTIONAL_NUMBER = {"anyOf": [NUMBER, {"type": "null"}]}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
WINDOW = object_schema({"start": DATE, "end": DATE})
COVERAGE = object_schema({"folder": string(), "count": NATURAL})
MAIL = object_schema({
    "id": string(250), "thread_key": string(254), "received": DATE,
    "subject": {"type": "string", "maxLength": 500},
    "preview": {"type": "string", "maxLength": 1500},
})
MAIL_BATCH = object_schema({
    "window": WINDOW, "sources": array(IDENT, 2), "coverage": array(COVERAGE),
    "messages": array(MAIL),
})
MAIL_SUMMARY = object_schema({
    "id": string(250), "subject": MAIL["properties"]["subject"], "preview": MAIL["properties"]["preview"],
})
DIGEST = array(object_schema({"id": string(250), "summary": string(500)}))
DIRECT_REQUEST = object_schema({"window": WINDOW, "campaign": IDENT, "goal": IDENT,
                                "attribution": {"enum": ["FCCD", "LC", "LSCCD", "AUTO"]}, "vat": {"type": "boolean"}})
DIRECT_ROW = object_schema({"date": DATE, "spend_micros": NATURAL, "conversions": NATURAL})
DIRECT_REPORT = object_schema({
    "selection": DIRECT_REQUEST, "currency": IDENT, "timezone": IDENT,
    "rows": array(DIRECT_ROW, 93), "provider_totals": object_schema({"spend_micros": NATURAL, "conversions": NATURAL}),
})
DIRECT_RESULT = object_schema({
    "selection": DIRECT_REQUEST, "currency": IDENT, "timezone": IDENT,
    "spend_micros": NATURAL, "conversions": NATURAL, "checksum": HASH,
})
SLEEP_ROW = object_schema({"date": DATE, "sleep_minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
                           "rhr_bpm": OPTIONAL_NUMBER})
SLEEP_RESULT = object_schema({
    "window": WINDOW, "nights": NATURAL, "missing": array(DATE, 93),
    "median_sleep_minutes": OPTIONAL_NUMBER, "median_rhr_bpm": OPTIONAL_NUMBER,
    "rhr_observations": NATURAL,
})
CDP_REQUEST = object_schema({"page": IDENT,
                             "selectors": array({**string(100), "pattern": r"^#[A-Za-z_][\w-]*$"}, 12)})
CDP_RESULT = object_schema({
    "page": IDENT, "origin": string(), "status": NATURAL,
    "elements": array(object_schema({"selector": string(100), "count": NATURAL}), 12),
    "dom_nodes": NATURAL, "load_ms": NUMBER,
})


def dates(window):
    start = date.fromisoformat(window["start"])
    end = date.fromisoformat(window["end"])
    days = (end - start).days
    if not 0 <= days <= 92:
        raise Rejected("invalid date window")
    return [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden = tag

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _mail_collect(inputs, source):
    window, accounts = inputs["window"], inputs["sources"]
    dates(window)
    if set(accounts) != {"mailru", "gmail"} or len(accounts) != 2:
        raise Rejected("both mail providers are required")
    return {"batch": source.mail(window, accounts)}


def _normalized(batch):
    unique = {}
    for item in batch["messages"]:
        parser = _PlainText()
        parser.feed(item["preview"])
        unique.setdefault(item["thread_key"], {
            "id": item["id"], "subject": item["subject"],
            "preview": " ".join(" ".join(parser.parts).split()),
        })
    return list(unique.values())


def _mail_normalize(inputs, source):
    return {"evidence": _normalized(inputs["batch"])}


def _mail_verify(inputs, source):
    batch = inputs["batch"]
    covered = {item["folder"]: item["count"] for item in batch["coverage"]}
    ids = {item["id"] for item in batch["messages"]}
    expected_days = dates(inputs["window"])
    digest_ids = [item["id"] for item in inputs["digest"]]
    observed = {entry["id"] for entry in _normalized(batch)}
    if (batch["window"] != inputs["window"] or batch["sources"] != inputs["sources"]
            or len(covered) != len(batch["coverage"]) or not {"mailru/INBOX", "gmail/unread"} <= covered.keys()
            or sum(covered.values()) != len(batch["messages"]) or len(ids) != len(batch["messages"])
            or any(item["received"] not in expected_days for item in batch["messages"])
            or inputs["evidence"] != _normalized(batch)
            or not set(digest_ids) <= observed or len(digest_ids) != len(set(digest_ids))):
        raise Rejected("mail coverage or references failed")
    source.attest("mail", batch)
    return {}


def _direct_fetch(inputs, source):
    dates(inputs["selection"]["window"])
    return {"report": source.direct(inputs["selection"])}


def _direct_reconcile(inputs, source):
    report = inputs["report"]
    return {"totals": {
        "selection": report["selection"], "currency": report["currency"], "timezone": report["timezone"],
        "spend_micros": sum(r["spend_micros"] for r in report["rows"]),
        "conversions": sum(r["conversions"] for r in report["rows"]),
        "checksum": sha256(canonical(report).encode()).hexdigest(),
    }}


def _direct_verify(inputs, source):
    report, totals = inputs["report"], inputs["totals"]
    covered = [row["date"] for row in report["rows"]]
    if (report["selection"] != inputs["selection"] or sorted(covered) != dates(inputs["selection"]["window"])
            or totals != _direct_reconcile({"report": report}, source)["totals"]
            or any(totals[key] != value for key, value in report["provider_totals"].items())):
        raise Rejected("report scope, coverage or totals failed")
    source.attest("direct", report)
    return {}


def _sleep_summary(window, records):
    expected = dates(window)
    selected = [row for row in records if row["date"] in expected]
    found = {row["date"] for row in selected}
    if len(found) != len(selected):
        raise Rejected("duplicate nights")
    heart = [row["rhr_bpm"] for row in selected if row["rhr_bpm"] is not None]
    return {"window": window, "nights": len(selected), "missing": sorted(set(expected) - found),
            "median_sleep_minutes": median([r["sleep_minutes"] for r in selected]) if selected else None,
            "median_rhr_bpm": median(heart) if heart else None, "rhr_observations": len(heart)}


def _sleep_aggregate(inputs, source):
    window = inputs["window"]
    dates(window)
    records = source.sleep(window)
    check_value(array(SLEEP_ROW, 93), records)
    return {"records": records, "summary": _sleep_summary(window, records)}


def _sleep_verify(inputs, source):
    source.attest("sleep", inputs["records"])
    if (any(row["date"] not in dates(inputs["window"]) for row in inputs["records"])
            or inputs["summary"] != _sleep_summary(inputs["window"], inputs["records"])):
        raise Rejected("night coverage or units failed")
    return {}


def _cdp_snapshot(inputs, source):
    return {"snapshot": source.cdp(inputs["selection"])}


def _cdp_verify(inputs, source):
    selection, snapshot = inputs["selection"], inputs["snapshot"]
    source.attest("cdp", snapshot)
    if (snapshot["page"] != selection["page"] or snapshot["origin"] != source.origin(selection["page"])
            or not 200 <= snapshot["status"] < 300
            or snapshot["dom_nodes"] < 1
            or [item["selector"] for item in snapshot["elements"]] != selection["selectors"]
            or any(item["count"] != 1 for item in snapshot["elements"])):
        raise Rejected("unexpected origin, status or structure")
    return {}


TYPES = {
    "window": WINDOW, "mail_sources": array(IDENT, 2), "mail_batch": MAIL_BATCH,
    "mail_evidence": array(MAIL_SUMMARY), "mail_digest": DIGEST,
    "direct_selection": DIRECT_REQUEST, "direct_report": DIRECT_REPORT, "direct_totals": DIRECT_RESULT,
    "sleep_records": array(SLEEP_ROW, 93), "sleep_summary": SLEEP_RESULT,
    "cdp_selection": CDP_REQUEST, "cdp_snapshot": CDP_RESULT,
}

OPERATIONS = {
    "mail.collect@1": Operation({"window": "window", "sources": "mail_sources"}, {"batch": "mail_batch"}, _mail_collect),
    "mail.normalize@1": Operation({"batch": "mail_batch"}, {"evidence": "mail_evidence"}, _mail_normalize),
    "mail.verify_digest@1": Operation(
        {"batch": "mail_batch", "digest": "mail_digest", "window": "window", "sources": "mail_sources",
         "evidence": "mail_evidence"}, {}, _mail_verify, verify=True),
    "direct.fetch_report@1": Operation({"selection": "direct_selection"}, {"report": "direct_report"}, _direct_fetch),
    "direct.reconcile@1": Operation({"report": "direct_report"}, {"totals": "direct_totals"}, _direct_reconcile),
    "direct.verify_totals@1": Operation(
        {"selection": "direct_selection", "report": "direct_report", "totals": "direct_totals"},
        {}, _direct_verify, verify=True),
    "sleep.aggregate_window@1": Operation(
        {"window": "window"}, {"records": "sleep_records", "summary": "sleep_summary"}, _sleep_aggregate),
    "sleep.verify_window@1": Operation(
        {"window": "window", "records": "sleep_records", "summary": "sleep_summary"}, {}, _sleep_verify, verify=True),
    "cdp.snapshot_page@1": Operation({"selection": "cdp_selection"}, {"snapshot": "cdp_snapshot"}, _cdp_snapshot),
    "cdp.verify_origin@1": Operation(
        {"selection": "cdp_selection", "snapshot": "cdp_snapshot"}, {}, _cdp_verify, verify=True),
}


def _program(sid, operation):
    op = OPERATIONS[operation]
    return {"id": sid, "kind": "program", "op": operation,
            "in": {name: name for name in op.inputs}, "out": {name: name for name in op.outputs}}


def _manifest(skill, intent, description, initial, steps, verification, returns):
    bindings = {key: {"type": kind, "from": origin} for key, kind, origin in initial}
    for step in steps:
        spec = OPERATIONS[step["op"]].outputs if step["kind"] == "program" else {"digest": "mail_digest"}
        bindings.update({name: {"type": kind, "from": step["id"]} for name, kind in spec.items()})
    return {"version": 1, "skill": skill, "intent": intent, "description": description, "effect": "read",
            "bindings": bindings, "steps": steps, "verification": [verification], "return": returns}


MANIFESTS = {
    "kesha-mail": _manifest(
        "kesha-mail", "inbox_digest", "Prepare a read only inbox digest",
        [("window", "window", "request"), ("sources", "mail_sources", "authorized_workspace")],
        [_program("collect", "mail.collect@1"), _program("normalize", "mail.normalize@1"),
         {"id": "prioritize", "kind": "llm_step", "instruction": "Summarize actionable messages and cite each message identifier",
          "in": {"evidence": "evidence"}, "out": {"digest": "digest"}}],
        _program("coverage", "mail.verify_digest@1"), ["digest"]),
    "direct-reports": _manifest(
        "direct-reports", "reconcile_report", "Reconcile a campaign report",
        [("selection", "direct_selection", "request")],
        [_program("fetch", "direct.fetch_report@1"), _program("reconcile", "direct.reconcile@1")],
        _program("verify", "direct.verify_totals@1"), ["totals"]),
    "wellness-dashboard": _manifest(
        "wellness-dashboard", "sleep_window", "Summarize synchronized sleep records",
        [("window", "window", "request")], [_program("aggregate", "sleep.aggregate_window@1")],
        _program("verify", "sleep.verify_window@1"), ["summary"]),
    "browser-control": _manifest(
        "browser-control", "inspect_page", "Read the structure of an authorized headless page",
        [("selection", "cdp_selection", "request")], [_program("snapshot", "cdp.snapshot_page@1")],
        _program("verify", "cdp.verify_origin@1"), ["snapshot"]),
}


def catalog(skills, schemas=None):
    return Catalog(TYPES, OPERATIONS, skills, schemas or {})

