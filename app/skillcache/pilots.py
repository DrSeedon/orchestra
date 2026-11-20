"""Ten read-only capsule plans over host-authorized sources.

Sources are trusted adapters, never module names, endpoints or credentials from
the manifest. Materialized evidence stays in the runner's private state.
"""

from datetime import date, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from statistics import median

from .abi import Operation, Rejected, canonical, check_value, object_schema
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

MORNING_RAW = object_schema({
    "window": WINDOW,
    "unread_mail_count": NATURAL,
    "mail_subjects": array({"type": "string", "maxLength": 200}, 20),
    "sleep_minutes": OPTIONAL_NUMBER,
    "rhr_bpm": OPTIONAL_NUMBER,
    "reminders_pending": NATURAL,
    "active_courses": NATURAL,
})
MORNING_DIGEST = object_schema({
    "window": WINDOW,
    "unread_mail_count": NATURAL,
    "mail_subjects": array({"type": "string", "maxLength": 200}, 20),
    "sleep_minutes": OPTIONAL_NUMBER,
    "rhr_bpm": OPTIONAL_NUMBER,
    "reminders_pending": NATURAL,
    "active_courses": NATURAL,
    "checksum": HASH,
})

WELLNESS_REQUEST = object_schema({"window": WINDOW, "category": {"enum": ["all", "supplements", "sleep"]}})
WELLNESS_RAW = object_schema({
    "selection": WELLNESS_REQUEST,
    "updated": {"type": "string", "maxLength": 40},
    "active_courses": NATURAL,
    "low_stock_count": NATURAL,
    "low_stock_names": array({"type": "string", "maxLength": 120}, 64),
    "recent_intake_count": NATURAL,
    "sleep_nights": NATURAL,
    "median_sleep_minutes": OPTIONAL_NUMBER,
    "median_rhr_bpm": OPTIONAL_NUMBER,
})
WELLNESS_SUMMARY = object_schema({
    "selection": WELLNESS_REQUEST,
    "updated": {"type": "string", "maxLength": 40},
    "active_courses": NATURAL,
    "low_stock_count": NATURAL,
    "low_stock_names": array({"type": "string", "maxLength": 120}, 64),
    "recent_intake_count": NATURAL,
    "sleep_nights": NATURAL,
    "median_sleep_minutes": OPTIONAL_NUMBER,
    "median_rhr_bpm": OPTIONAL_NUMBER,
    "checksum": HASH,
})

EDO_REQUEST = object_schema({"scope_key": IDENT, "include_deadlines": {"type": "boolean"}})
EDO_RAW = object_schema({
    "scope_key": IDENT,
    "db_exists": {"type": "boolean"},
    "db_bytes": NATURAL,
    "platform_exists": {"type": "boolean"},
    "license_exists": {"type": "boolean"},
    "incoming_xml_count": NATURAL,
    "deadline_lines": array({"type": "string", "maxLength": 240}, 20),
})
EDO_STATUS = object_schema({
    "scope_key": IDENT,
    "db_exists": {"type": "boolean"},
    "db_bytes": NATURAL,
    "platform_exists": {"type": "boolean"},
    "license_exists": {"type": "boolean"},
    "incoming_xml_count": NATURAL,
    "deadline_lines": array({"type": "string", "maxLength": 240}, 20),
    "checksum": HASH,
})

VIDEO_ID = {**string(11), "pattern": r"^[A-Za-z0-9_-]{11}$"}
YT_REQUEST = object_schema({"video_id": VIDEO_ID, "include_transcript": {"type": "boolean"}})
YT_RAW = object_schema({
    "video_id": VIDEO_ID,
    "include_transcript": {"type": "boolean"},
    "title": {"type": "string", "maxLength": 300},
    "author_name": {"type": "string", "maxLength": 200},
    "author_url": {"type": "string", "maxLength": 300},
    "has_transcript": {"type": "boolean"},
    "chapters_count": NATURAL,
    "transcript_chars": NATURAL,
    "transcript_excerpt": {"type": "string", "maxLength": 2000},
})
YT_META = object_schema({
    "video_id": VIDEO_ID,
    "include_transcript": {"type": "boolean"},
    "title": {"type": "string", "maxLength": 300},
    "author_name": {"type": "string", "maxLength": 200},
    "author_url": {"type": "string", "maxLength": 300},
    "has_transcript": {"type": "boolean"},
    "chapters_count": NATURAL,
    "transcript_chars": NATURAL,
    "transcript_excerpt": {"type": "string", "maxLength": 2000},
    "checksum": HASH,
})

VPS_REQUEST = object_schema({"units": array(IDENT, 8), "include_sessions": {"type": "boolean"}})
VPS_SERVICE_ROW = object_schema({
    "unit": IDENT,
    "active": {"type": "string", "maxLength": 40},
    "sub": {"type": "string", "maxLength": 40},
    "pid": NATURAL,
    "rss_mib": NATURAL,
    "restarts": NATURAL,
})
VPS_RAW = object_schema({
    "units": array(IDENT, 8),
    "include_sessions": {"type": "boolean"},
    "service_states": array(VPS_SERVICE_ROW, 8),
    "disk_free_mb": NATURAL,
    "running_sessions": NATURAL,
    "waiting_sessions": NATURAL,
    "idle_sessions": NATURAL,
})
VPS_REPORT = object_schema({
    "units": array(IDENT, 8),
    "service_states": array(VPS_SERVICE_ROW, 8),
    "disk_free_mb": NATURAL,
    "running_sessions": NATURAL,
    "waiting_sessions": NATURAL,
    "idle_sessions": NATURAL,
    "cut_risk": {"type": "boolean"},
    "checksum": HASH,
})

AVITO_REQUEST = object_schema({"batch": IDENT, "status_filter": {"enum": ["all", "published", "draft"]}})
AVITO_RAW = object_schema({
    "batch": IDENT,
    "status_filter": {"enum": ["all", "published", "draft"]},
    "total_items": NATURAL,
    "matched_items": NATURAL,
    "published_count": NATURAL,
    "draft_count": NATURAL,
    "total_price_rub": NATURAL,
    "missing_photo_count": NATURAL,
})
AVITO_STATS = object_schema({
    "batch": IDENT,
    "status_filter": {"enum": ["all", "published", "draft"]},
    "total_items": NATURAL,
    "matched_items": NATURAL,
    "published_count": NATURAL,
    "draft_count": NATURAL,
    "total_price_rub": NATURAL,
    "missing_photo_count": NATURAL,
    "checksum": HASH,
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


def _checksum(value) -> str:
    return sha256(canonical(value).encode()).hexdigest()


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
    source.attest("mail", batch)
    if batch["window"] != inputs["window"] or set(batch["sources"]) != set(inputs["sources"]):
        raise Rejected("mail batch window or sources mismatch")
    if not all(c["count"] >= 0 for c in batch["coverage"]):
        raise Rejected("invalid coverage count")
    if inputs["evidence"] != _normalized(batch):
        raise Rejected("normalized evidence drifted")
    ids = {row["id"] for row in batch["messages"]}
    if any(not item["summary"] or item["id"] not in ids for item in inputs["digest"]):
        raise Rejected("digest cites unknown message or empty summary")
    return {}


def _direct_fetch(inputs, source):
    dates(inputs["selection"]["window"])
    return {"report": source.direct(inputs["selection"])}


def _direct_totals(report):
    days = dates(report["selection"]["window"])
    by_day = {r["date"]: r for r in report["rows"]}
    if set(by_day) != set(days):
        raise Rejected("direct daily rows incomplete")
    spend = sum(r["spend_micros"] for r in report["rows"])
    conv = sum(r["conversions"] for r in report["rows"])
    prov = report["provider_totals"]
    if (spend, conv) != (prov["spend_micros"], prov["conversions"]):
        raise Rejected("direct daily sum disagrees with provider totals")
    payload = {
        "selection": report["selection"], "currency": report["currency"], "timezone": report["timezone"],
        "spend_micros": spend, "conversions": conv,
    }
    return {**payload, "checksum": _checksum(payload)}


def _direct_reconcile(inputs, source):
    return {"totals": _direct_totals(inputs["report"])}


def _direct_verify(inputs, source):
    source.attest("direct", inputs["report"])
    if inputs["report"]["selection"] != inputs["selection"] or inputs["totals"] != _direct_totals(inputs["report"]):
        raise Rejected("direct verification failed")
    return {}


def _sleep_summary(window, records):
    expected = dates(window)
    selected = [r for r in records if r["date"] in expected]
    found = {r["date"] for r in selected}
    heart = [r["rhr_bpm"] for r in selected if r["rhr_bpm"] is not None]
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


def _morning_collect(inputs, source):
    dates(inputs["window"])
    return {"raw": source.morning(inputs["window"])}


def _morning_norm_payload(raw):
    return {**raw, "checksum": _checksum(raw)}


def _morning_normalize(inputs, source):
    return {"digest": _morning_norm_payload(inputs["raw"])}


def _morning_verify(inputs, source):
    raw = inputs["raw"]
    source.attest("morning", raw)
    if raw["window"] != inputs["window"] or inputs["digest"] != _morning_norm_payload(raw):
        raise Rejected("morning digest verification failed")
    return {}


def _wellness_collect(inputs, source):
    dates(inputs["selection"]["window"])
    return {"raw": source.wellness(inputs["selection"])}


def _wellness_payload(raw):
    return {**raw, "checksum": _checksum(raw)}


def _wellness_summarize(inputs, source):
    return {"summary": _wellness_payload(inputs["raw"])}


def _wellness_verify(inputs, source):
    raw = inputs["raw"]
    source.attest("wellness", raw)
    if raw["selection"] != inputs["selection"] or inputs["summary"] != _wellness_payload(raw):
        raise Rejected("wellness summary verification failed")
    return {}


def _edo_collect(inputs, source):
    return {"raw": source.edo(inputs["target"])}


def _edo_payload(raw):
    return {**raw, "checksum": _checksum(raw)}


def _edo_normalize(inputs, source):
    return {"status": _edo_payload(inputs["raw"])}


def _edo_verify(inputs, source):
    raw = inputs["raw"]
    source.attest("edo", raw)
    if raw["scope_key"] != inputs["target"]["scope_key"] or inputs["status"] != _edo_payload(raw):
        raise Rejected("edo status verification failed")
    return {}


def _youtube_fetch(inputs, source):
    return {"raw": source.youtube(inputs["target"])}


def _youtube_payload(raw):
    return {**raw, "checksum": _checksum(raw)}


def _youtube_normalize(inputs, source):
    return {"metadata": _youtube_payload(inputs["raw"])}


def _youtube_verify(inputs, source):
    raw, target = inputs["raw"], inputs["target"]
    source.attest("youtube", raw)
    if (raw["video_id"] != target["video_id"]
            or bool(raw["include_transcript"]) != bool(target["include_transcript"])
            or inputs["metadata"] != _youtube_payload(raw)):
        raise Rejected("youtube metadata verification failed")
    return {}


def _vps_collect(inputs, source):
    return {"raw": source.vps(inputs["query"])}


def _vps_payload(raw):
    payload = {
        "units": raw["units"],
        "service_states": raw["service_states"],
        "disk_free_mb": raw["disk_free_mb"],
        "running_sessions": raw["running_sessions"],
        "waiting_sessions": raw["waiting_sessions"],
        "idle_sessions": raw["idle_sessions"],
        "cut_risk": raw["running_sessions"] > 0,
    }
    return {**payload, "checksum": _checksum(raw)}


def _vps_summarize(inputs, source):
    return {"report": _vps_payload(inputs["raw"])}


def _vps_verify(inputs, source):
    raw, query = inputs["raw"], inputs["query"]
    source.attest("vps", raw)
    if (raw["units"] != query["units"]
            or [row["unit"] for row in raw["service_states"]] != query["units"]
            or inputs["report"] != _vps_payload(raw)):
        raise Rejected("vps preflight verification failed")
    return {}


def _avito_collect(inputs, source):
    return {"raw": source.avito(inputs["query"])}


def _avito_payload(raw):
    return {**raw, "checksum": _checksum(raw)}


def _avito_summarize(inputs, source):
    return {"stats": _avito_payload(inputs["raw"])}


def _avito_verify(inputs, source):
    raw, query = inputs["raw"], inputs["query"]
    source.attest("avito", raw)
    if (raw["batch"] != query["batch"] or raw["status_filter"] != query["status_filter"]
            or inputs["stats"] != _avito_payload(raw)):
        raise Rejected("avito stats verification failed")
    return {}


TYPES = {
    "window": WINDOW, "mail_sources": array(IDENT, 2), "mail_batch": MAIL_BATCH,
    "mail_evidence": array(MAIL_SUMMARY), "mail_digest": DIGEST,
    "direct_selection": DIRECT_REQUEST, "direct_report": DIRECT_REPORT, "direct_totals": DIRECT_RESULT,
    "sleep_records": array(SLEEP_ROW, 93), "sleep_summary": SLEEP_RESULT,
    "cdp_selection": CDP_REQUEST, "cdp_snapshot": CDP_RESULT,
    "morning_raw": MORNING_RAW, "morning_digest": MORNING_DIGEST,
    "wellness_selection": WELLNESS_REQUEST, "wellness_raw": WELLNESS_RAW, "wellness_summary": WELLNESS_SUMMARY,
    "edo_target": EDO_REQUEST, "edo_raw": EDO_RAW, "edo_status": EDO_STATUS,
    "yt_target": YT_REQUEST, "yt_raw": YT_RAW, "yt_metadata": YT_META,
    "vps_query": VPS_REQUEST, "vps_raw": VPS_RAW, "vps_report": VPS_REPORT,
    "avito_query": AVITO_REQUEST, "avito_raw": AVITO_RAW, "avito_stats": AVITO_STATS,
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
    "morning.collect@1": Operation({"window": "window"}, {"raw": "morning_raw"}, _morning_collect),
    "morning.normalize@1": Operation({"raw": "morning_raw"}, {"digest": "morning_digest"}, _morning_normalize),
    "morning.verify_digest@1": Operation(
        {"window": "window", "raw": "morning_raw", "digest": "morning_digest"}, {}, _morning_verify, verify=True),
    "wellness.collect@1": Operation({"selection": "wellness_selection"}, {"raw": "wellness_raw"}, _wellness_collect),
    "wellness.summarize@1": Operation({"raw": "wellness_raw"}, {"summary": "wellness_summary"}, _wellness_summarize),
    "wellness.verify@1": Operation(
        {"selection": "wellness_selection", "raw": "wellness_raw", "summary": "wellness_summary"},
        {}, _wellness_verify, verify=True),
    "edo.collect_status@1": Operation({"target": "edo_target"}, {"raw": "edo_raw"}, _edo_collect),
    "edo.normalize_status@1": Operation({"raw": "edo_raw"}, {"status": "edo_status"}, _edo_normalize),
    "edo.verify_status@1": Operation(
        {"target": "edo_target", "raw": "edo_raw", "status": "edo_status"}, {}, _edo_verify, verify=True),
    "youtube.fetch_meta@1": Operation({"target": "yt_target"}, {"raw": "yt_raw"}, _youtube_fetch),
    "youtube.normalize_meta@1": Operation({"raw": "yt_raw"}, {"metadata": "yt_metadata"}, _youtube_normalize),
    "youtube.verify_meta@1": Operation(
        {"target": "yt_target", "raw": "yt_raw", "metadata": "yt_metadata"}, {}, _youtube_verify, verify=True),
    "vps.collect_health@1": Operation({"query": "vps_query"}, {"raw": "vps_raw"}, _vps_collect),
    "vps.summarize_health@1": Operation({"raw": "vps_raw"}, {"report": "vps_report"}, _vps_summarize),
    "vps.verify_health@1": Operation(
        {"query": "vps_query", "raw": "vps_raw", "report": "vps_report"}, {}, _vps_verify, verify=True),
    "avito.collect_stats@1": Operation({"query": "avito_query"}, {"raw": "avito_raw"}, _avito_collect),
    "avito.summarize_stats@1": Operation({"raw": "avito_raw"}, {"stats": "avito_stats"}, _avito_summarize),
    "avito.verify_stats@1": Operation(
        {"query": "avito_query", "raw": "avito_raw", "stats": "avito_stats"}, {}, _avito_verify, verify=True),
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
    "xiaomi-sleep": _manifest(
        "xiaomi-sleep", "sleep_window", "Summarize synchronized Xiaomi sleep records",
        [("window", "window", "request")], [_program("aggregate", "sleep.aggregate_window@1")],
        _program("verify", "sleep.verify_window@1"), ["summary"]),
    "browser-control": _manifest(
        "browser-control", "inspect_page", "Read the structure of an authorized headless page",
        [("selection", "cdp_selection", "request")], [_program("snapshot", "cdp.snapshot_page@1")],
        _program("verify", "cdp.verify_origin@1"), ["snapshot"]),
    "morning-digest": _manifest(
        "morning-digest", "morning_collect", "Collect read-only mail, sleep, wellness and reminders for morning digest",
        [("window", "window", "request")],
        [_program("collect", "morning.collect@1"), _program("normalize", "morning.normalize@1")],
        _program("verify", "morning.verify_digest@1"), ["digest"]),
    "wellness-dashboard": _manifest(
        "wellness-dashboard", "wellness_summary", "Collect read-only supplement courses, low stock, sleep and heart rate trends",
        [("selection", "wellness_selection", "request")],
        [_program("collect", "wellness.collect@1"), _program("summarize", "wellness.summarize@1")],
        _program("verify", "wellness.verify@1"), ["summary"]),
    "edo-1c-status": _manifest(
        "edo-1c-status", "edo_readonly_status", "Read only status check of accounting database, certificate license and deadlines",
        [("target", "edo_target", "request")],
        [_program("collect", "edo.collect_status@1"), _program("normalize", "edo.normalize_status@1")],
        _program("verify", "edo.verify_status@1"), ["status"]),
    "youtube-reader": _manifest(
        "youtube-reader", "youtube_metadata", "Deterministically extract YouTube oEmbed metadata and cached transcript excerpts",
        [("target", "yt_target", "request")],
        [_program("fetch", "youtube.fetch_meta@1"), _program("normalize", "youtube.normalize_meta@1")],
        _program("verify", "youtube.verify_meta@1"), ["metadata"]),
    "vps-health-preflight": _manifest(
        "vps-health-preflight", "vps_preflight", "Read-only VPS preflight: services, RSS, disk, sessions and cut risk",
        [("query", "vps_query", "request")],
        [_program("collect", "vps.collect_health@1"), _program("summarize", "vps.summarize_health@1")],
        _program("verify", "vps.verify_health@1"), ["report"]),
    "avito-stats": _manifest(
        "avito-stats", "avito_inventory", "Read-only Avito listing inventory, publication counts and price totals",
        [("query", "avito_query", "request")],
        [_program("collect", "avito.collect_stats@1"), _program("summarize", "avito.summarize_stats@1")],
        _program("verify", "avito.verify_stats@1"), ["stats"]),
}


def catalog(skills, schemas=None):
    return Catalog(TYPES, OPERATIONS, skills, schemas or {})
