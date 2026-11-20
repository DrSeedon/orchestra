"""Host-owned source connectors. Request values never select credentials or URLs."""

import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email import policy
from email.parser import BytesParser
import imaplib
import io
from pathlib import Path
import re
import ssl
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .abi import AccessRevoked, Rejected, RetryableRead
from .pilots import dates


LIMIT = 2048
_CDP_SLOT = threading.BoundedSemaphore()


class Evidence:
    """Verification accepts only a materialization made by this run's sources."""

    def __init__(self):
        self.records = set()

    def record(self, domain, value):
        from .registry import digest

        self.records.add((domain, digest(value)))
        return value

    def attest(self, domain, value):
        from .registry import digest

        if (domain, digest(value)) not in self.records:
            raise Rejected("unattested evidence")


class LiveSources(Evidence):
    def __init__(self, config, environ):
        super().__init__()
        self.config = config
        self.environ = environ
        self.deadline = time.monotonic() + 48

    def _check_budget(self):
        if time.monotonic() >= self.deadline:
            raise Rejected("source time budget exceeded")

    def _token(self, name):
        key = self.config.get(name, "")
        token = self.environ.get(key)
        if not token:
            raise AccessRevoked
        return token

    def mail(self, window, accounts):
        messages, coverage = self._imap(window)
        gmail, gmail_coverage = self._gmail(window)
        if len(messages) + len(gmail) > LIMIT:
            raise Rejected("mail window exceeds limit")
        return self.record("mail", {"window": window, "sources": accounts,
                                    "messages": messages + gmail, "coverage": coverage + gmail_coverage})

    def _imap(self, window):
        username = self.config.get("mailru_user")
        if not username:
            raise AccessRevoked
        password = self._token("mailru_password_env")
        lower, upper = (date.fromisoformat(window[k]) for k in ("start", "end"))
        messages = []
        coverage = []
        with imaplib.IMAP4_SSL("imap.mail.ru", ssl_context=ssl.create_default_context(), timeout=8) as mail:
            mail.login(username, password)
            status, folders = mail.list()
            if status != "OK" or not folders or len(folders) > 64:
                raise Rejected("failed to list mail folders")
            for entry in folders:
                match = re.fullmatch(rb'\(([^)]*)\) (?:"([^"]+)"|NIL) ("(?:[^"\\]|\\.)*"|[^ "]+)', entry)
                if match is None:
                    raise Rejected("unsupported mail folder listing")
                flags, delimiter, wire_folder = match.groups()
                name = wire_folder.strip(b'"')
                if not (name.upper() == b"INBOX" or delimiter and name.upper().startswith(b"INBOX" + delimiter)):
                    continue
                if b"\\noselect" in flags.lower():
                    continue
                folder = "mailru/" + name.decode("ascii")
                self._check_budget()
                if mail.select(wire_folder, readonly=True)[0] != "OK":
                    raise Rejected("mail folder unavailable")
                # IMAP date predicates use the server's calendar date. Widen before UTC filtering.
                since = (lower - timedelta(days=1)).strftime("%d-%b-%Y")
                before = (upper + timedelta(days=2)).strftime("%d-%b-%Y")
                status, uids = mail.uid("SEARCH", None, "SINCE", since, "BEFORE", before, "UNSEEN")
                if status != "OK":
                    raise Rejected("mail folder search failed")
                found = (uids[0] or b"").split()
                if len(messages) + len(found) > LIMIT:
                    raise Rejected("mail window exceeds limit")
                start = len(messages)
                for uid in found:
                    self._check_budget()
                    status, values = mail.uid("FETCH", uid, "(INTERNALDATE BODY.PEEK[]<0.16384>)")
                    blobs = [item for item in values if isinstance(item, tuple)]
                    if status != "OK" or len(blobs) != 1:
                        raise Rejected("mail message unavailable")
                    meta, payload = blobs[0]
                    stamp = re.search(rb'INTERNALDATE "([^"]+)"', meta)
                    if stamp is None:
                        raise Rejected("mail date unavailable")
                    received = datetime.strptime(stamp[1].decode(), "%d-%b-%Y %H:%M:%S %z").astimezone(timezone.utc).date()
                    if not lower <= received <= upper:
                        continue
                    parsed = BytesParser(policy=policy.default).parsebytes(payload)
                    part = parsed.get_body(preferencelist=("plain", "html"))
                    preview = part.get_content() if part is not None else ""
                    mid = f"{folder}/{uid.decode('ascii')}"
                    messages.append({
                        "id": mid, "thread_key": str(parsed.get("Message-ID") or mid)[:254],
                        "received": received.isoformat(), "subject": str(parsed.get("Subject") or "")[:500],
                        "preview": preview[:1500],
                    })
                coverage.append({"folder": folder, "count": len(messages) - start})
        return messages, coverage

    def _gmail(self, window):
        token = self._token("gmail_access_token_env")
        base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        lower, upper = (date.fromisoformat(window[k]) for k in ("start", "end"))
        epoch = lambda day: int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        query = f"is:unread after:{epoch(lower) - 1} before:{epoch(upper + timedelta(days=1))}"
        messages = []
        seen = set()
        cursor = None
        with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=8, trust_env=False) as client:
            for _ in range(32):
                self._check_budget()
                params = {"q": query, "maxResults": 100}
                if cursor:
                    params["pageToken"] = cursor
                response = _json_response(client.get(base, params=params))
                rows = response.get("messages", [])
                if len(messages) + len(rows) > LIMIT:
                    raise Rejected("mail window exceeds limit")
                for item in rows:
                    self._check_budget()
                    mid = item["id"]
                    if not re.fullmatch(r"[0-9a-f]+", mid) or mid in seen:
                        raise Rejected("invalid or duplicate Gmail id")
                    seen.add(mid)
                    message = _json_response(client.get(base + "/" + mid, params={
                        "format": "full",
                        "fields": "id,internalDate,snippet,payload(headers)",
                    }))
                    if message["id"] != mid:
                        raise Rejected("Gmail message identity changed")
                    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
                    received = datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc).date()
                    if not lower <= received <= upper:
                        raise Rejected("Gmail message outside window")
                    messages.append({
                        "id": "gmail/" + mid, "thread_key": str(headers.get("message-id") or "gmail/" + mid)[:254],
                        "received": received.isoformat(), "subject": str(headers.get("subject", ""))[:500],
                        "preview": str(message.get("snippet", ""))[:1500],
                    })
                next_cursor = response.get("nextPageToken")
                if not next_cursor:
                    return messages, [{"folder": "gmail/unread", "count": len(messages)}]
                if next_cursor == cursor:
                    break
                cursor = next_cursor
        raise Rejected("Gmail pagination incomplete")

    def direct(self, selection):
        campaign = selection["campaign"]
        goal = selection["goal"]
        config = self.config.get("direct", {})
        if (campaign not in config.get("campaigns", ()) or goal not in config.get("goals", ())
                or selection["attribution"] not in config.get("attributions", ())
                or not campaign.isascii() or not campaign.isdecimal() or not goal.isascii() or not goal.isdecimal()):
            raise AccessRevoked
        token = self._token("direct_access_token_env")
        details = self._report(selection, token, ["CampaignId", "Date", "Cost", "Conversions"])
        independent = self._report(selection, token, ["CampaignId", "Cost", "Conversions"])
        days = dates(selection["window"])
        rows = {day: {"date": day, "spend_micros": 0, "conversions": 0} for day in days}
        seen = set()
        for row in details:
            day = row["Date"]
            if day not in rows or day in seen:
                raise Rejected("overlapping or out of scope Direct report rows")
            seen.add(day)
            rows[day].update(_amounts(row))
        if len(independent) > 1:
            raise Rejected("unexpected report total rows")
        totals = _amounts(independent[0]) if independent else {"spend_micros": 0, "conversions": 0}
        return self.record("direct", {
            "selection": selection, "currency": config["currency"], "timezone": config["timezone"],
            "rows": list(rows.values()), "provider_totals": totals,
        })

    def _report(self, selection, token, columns):
        self._check_budget()
        request = {
            "SelectionCriteria": {"DateFrom": selection["window"]["start"], "DateTo": selection["window"]["end"],
                                  "Filter": [{"Field": "CampaignId", "Operator": "EQUALS", "Values": [selection["campaign"]]}]},
            "ReportName": "skillcache-" + uuid4().hex, "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE", "Format": "TSV",
            "IncludeVAT": "YES" if selection["vat"] else "NO",
            "Goals": [selection["goal"]], "AttributionModels": [selection["attribution"]], "FieldNames": columns,
        }
        headers = {"Authorization": f"Bearer {token}", "processingMode": "online", "returnMoneyInMicros": "true",
                   "skipReportHeader": "true", "skipReportSummary": "true", "Accept-Language": "en"}
        endpoint = "https://api.direct.yandex.com/json/v5/reports"
        with httpx.Client(timeout=12, trust_env=False) as client:
            with client.stream("POST", endpoint, headers=headers, json={"params": request}) as response:
                if response.status_code in (401, 403):
                    raise AccessRevoked
                if response.status_code in (201, 202, 429, 500, 502, 503, 504):
                    raise RetryableRead
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 256 * 1024:
                        raise Rejected("oversized Direct report")
        table = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), delimiter="\t")
        goal_column = "Conversions_" + selection["goal"] + "_" + selection["attribution"]
        expected = [goal_column if col == "Conversions" else col for col in columns]
        if table.fieldnames != expected:
            raise Rejected("unexpected attribution columns")
        rows = []
        for row in table:
            if row.get("CampaignId") != selection["campaign"] or None in row or any(value is None for value in row.values()):
                raise Rejected("unexpected report campaign or row shape")
            row["Conversions"] = row.pop(goal_column)
            rows.append(row)
        return rows

    def sleep(self, window):
        root = self.config.get("wellness_root")
        if not root:
            raise AccessRevoked
        root = Path(root)
        days = set(dates(window))
        records = []
        for month in sorted({day[:7] for day in days}):
            activity_path = root / "activity-log" / (month + "-activity.md")
            activity = {}
            for row in _table_rows(activity_path):
                if row[0] in days and row[4].isdigit():
                    activity[row[0]] = int(row[4])
            path = root / "sleep-log" / (month + "-sleep.md")
            for row in _table_rows(path):
                if not row[0].isdigit():
                    continue
                wake = re.search(r"→(\d\d)\.(\d\d)$", row[1])
                duration = re.fullmatch(r"\*\*(?:(\d+)ч)?(\d+)м\*\*", row[3].replace(" ", ""))
                if not wake or not duration:
                    raise Rejected("unsupported Xiaomi sleep row")
                day = f"{month[:4]}-{wake[2]}-{wake[1]}"
                if day in days:
                    records.append({"date": day, "sleep_minutes": int(duration[1] or 0) * 60 + int(duration[2]),
                                    "rhr_bpm": activity.get(day)})
        return self.record("sleep", records)

    def _page(self, name):
        url = self.config.get("cdp_pages", {}).get(name)
        if not url:
            raise AccessRevoked
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise AccessRevoked
        return url, f"{parsed.scheme}://{parsed.netloc}"

    def origin(self, page):
        return self._page(page)[1]

    def cdp(self, selection):
        from playwright.sync_api import sync_playwright

        url, expected = self._page(selection["page"])

        def restrict(route):
            target = urlsplit(route.request.url)
            allowed = f"{target.scheme}://{target.netloc}" == expected
            if not allowed or route.request.method not in {"GET", "HEAD"}:
                route.abort()
                return
            response = route.fetch(max_redirects=0, timeout=8000)
            if 300 <= response.status < 400:
                route.abort()
                return
            route.fulfill(response=response)

        if not _CDP_SLOT.acquire(blocking=False):
            raise Rejected("headless source busy")
        try:
            return self._snapshot(sync_playwright, url, restrict, selection)
        finally:
            _CDP_SLOT.release()

    def _snapshot(self, sync_playwright, url, restrict, selection):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, timeout=8000)
            try:
                context = browser.new_context(service_workers="block")
                context.route("**/*", restrict)
                context.route_web_socket("**/*", lambda websocket: websocket.close())
                # No caller-supplied JavaScript. Selectors use a restricted ID grammar.
                page = context.new_page()
                session = context.new_cdp_session(page)
                session.send("Performance.enable")
                response = page.goto(url, wait_until="domcontentloaded", timeout=8000)
                if response is None:
                    raise Rejected("page yielded no response")
                metrics = session.send("Performance.getMetrics")["metrics"]
                counters = session.send("Memory.getDOMCounters")
                perf = {item["name"]: item["value"] for item in metrics}
                elapsed = max(0, (perf.get("DomContentLoaded", 0) - perf.get("NavigationStart", 0)) * 1000)
                result = {
                    "page": selection["page"], "origin": page.evaluate("location.origin"), "status": response.status,
                    "elements": [{"selector": selector, "count": page.locator(selector).count()}
                                 for selector in selection["selectors"]],
                    "dom_nodes": counters["nodes"], "load_ms": elapsed,
                }
                return self.record("cdp", result)
            finally:
                browser.close()


def _json_response(response):
    if response.status_code in (401, 403):
        raise AccessRevoked
    response.raise_for_status()
    if len(response.content) > 256 * 1024:
        raise Rejected("oversized source response")
    return response.json()


def _amounts(row):
    spend = Decimal(row["Cost"])
    conversions = Decimal(row["Conversions"])
    if any(x < 0 or x != x.to_integral_value() for x in (spend, conversions)):
        raise Rejected("invalid report units")
    return {"spend_micros": int(spend), "conversions": int(conversions)}


def _table_rows(path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("| "):
                row = [value.strip() for value in line.strip().strip("|").split("|")]
                if len(row) >= 6:
                    yield row

