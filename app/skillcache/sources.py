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
import json
import os
import sqlite3
import subprocess

from .pilots import _sleep_summary, dates


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


    def _load_wellness_data(self):
        api_url = self.config.get("wellness_api_url")
        if api_url:
            parsed = urlsplit(api_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
                raise AccessRevoked
            with httpx.Client(timeout=4, trust_env=False) as client:
                return _json_response(client.get(api_url))
        dash_path = self.config.get("wellness_dashboard_path")
        if not dash_path:
            return {}
        fp = Path(dash_path)
        if not fp.is_file():
            return {}
        return json.loads(fp.read_text(encoding="utf-8"))

    def morning(self, window):
        dates(window)
        unread_count = 0
        subjects = []
        if self.config.get("mailru_user") and self.config.get("gmail_access_token_env"):
            try:
                batch = self.mail(window, ["mailru", "gmail"])
                unread_count = len(batch["messages"])
                subjects = [str(m.get("subject") or "")[:200] for m in batch["messages"][:20]]
            except AccessRevoked:
                pass
        sleep_min = None
        rhr_bpm = None
        if self.config.get("wellness_root"):
            recs = self.sleep(window)
            if recs:
                latest = sorted(recs, key=lambda r: r["date"])[-1]
                sleep_min = latest.get("sleep_minutes")
                rhr_bpm = latest.get("rhr_bpm")
        rem_pending = 0
        rem_db = self.config.get("reminders_db_path")
        if rem_db and Path(rem_db).is_file():
            with sqlite3.connect(f"file:{rem_db}?mode=ro", uri=True, timeout=1.0) as conn:
                tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'").fetchone()
                if tbl:
                    cols = {r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()}
                    if "status" in cols:
                        rem_pending = int(conn.execute("SELECT COUNT(*) FROM reminders WHERE status IN ('pending','active','scheduled')").fetchone()[0])
                    else:
                        rem_pending = int(conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0])
        wdata = self._load_wellness_data()
        courses = wdata.get("courses") or {}
        active_courses = len([c for c in (courses.values() if isinstance(courses, dict) else courses) if isinstance(c, dict) and c.get("active", True)]) if courses else 0
        return self.record("morning", {
            "window": window,
            "unread_mail_count": unread_count,
            "mail_subjects": subjects,
            "sleep_minutes": sleep_min,
            "rhr_bpm": rhr_bpm,
            "reminders_pending": rem_pending,
            "active_courses": active_courses,
        })

    def wellness(self, selection):
        window = selection["window"]
        category = selection["category"]
        dates(window)
        data = self._load_wellness_data()
        if not data and not self.config.get("wellness_root"):
            raise AccessRevoked
        courses = data.get("courses") or {}
        active_courses = len([c for c in (courses.values() if isinstance(courses, dict) else courses) if isinstance(c, dict) and c.get("active", True)]) if courses else 0
        inv = data.get("inventory") or {}
        inv_items = inv.values() if isinstance(inv, dict) else inv
        low_names = []
        for item in inv_items:
            if not isinstance(item, dict):
                continue
            amt = item.get("stock", item.get("amount", 999))
            thr = item.get("threshold", item.get("min", 5))
            if isinstance(amt, (int, float)) and isinstance(thr, (int, float)) and amt <= thr:
                low_names.append(str(item.get("name") or item.get("id") or "item")[:120])
        low_names = sorted(low_names)[:64]
        logs = data.get("log") or []
        sleep_sum = {"nights": 0, "median_sleep_minutes": None, "median_rhr_bpm": None}
        if self.config.get("wellness_root"):
            recs = self.sleep(window)
            sleep_sum = _sleep_summary(window, recs)
        return self.record("wellness", {
            "selection": selection,
            "updated": str(data.get("updated") or "")[:40],
            "active_courses": active_courses if category in ("all", "supplements") else 0,
            "low_stock_count": len(low_names) if category in ("all", "supplements") else 0,
            "low_stock_names": low_names if category in ("all", "supplements") else [],
            "recent_intake_count": len(logs) if category in ("all", "supplements") else 0,
            "sleep_nights": sleep_sum["nights"] if category in ("all", "sleep") else 0,
            "median_sleep_minutes": sleep_sum["median_sleep_minutes"] if category in ("all", "sleep") else None,
            "median_rhr_bpm": sleep_sum["median_rhr_bpm"] if category in ("all", "sleep") else None,
        })

    def edo(self, target):
        db_dir = self.config.get("edo_db_dir")
        if not db_dir:
            raise AccessRevoked
        db_path = Path(db_dir)
        db_exists = db_path.exists()
        db_bytes = 0
        if db_exists:
            if db_path.is_file():
                db_bytes = db_path.stat().st_size
            else:
                for p in db_path.rglob("*"):
                    if p.is_file():
                        db_bytes += p.stat().st_size
        plat = Path(self.config.get("edo_platform_path", "")) if self.config.get("edo_platform_path") else None
        lic = Path(self.config.get("edo_license_path", "")) if self.config.get("edo_license_path") else None
        inbox = Path(self.config.get("edo_inbox_dir", "")) if self.config.get("edo_inbox_dir") else None
        xml_count = len(list(inbox.glob("*.xml"))) if inbox and inbox.is_dir() else 0
        deadlines = []
        if target.get("include_deadlines") and self.config.get("accounting_guide_path"):
            gp = Path(self.config["accounting_guide_path"])
            if gp.is_file():
                for line in gp.read_text(encoding="utf-8", errors="replace").splitlines():
                    low = line.lower()
                    if any(k in low for k in ("срок", "дедлайн", "до 25", "до 28", "ефс", "рсв", "усн")):
                        clean = _redact_line(line.strip())[:240]
                        if clean:
                            deadlines.append(clean)
                        if len(deadlines) >= 20:
                            break
        return self.record("edo", {
            "scope_key": target["scope_key"],
            "db_exists": db_exists,
            "db_bytes": int(db_bytes),
            "platform_exists": bool(plat and plat.exists()),
            "license_exists": bool(lic and lic.exists()),
            "incoming_xml_count": int(xml_count),
            "deadline_lines": deadlines,
        })

    def youtube(self, target):
        vid = target["video_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            raise Rejected("invalid YouTube video_id")
        include_tr = bool(target.get("include_transcript", False))
        cache_dir = self.config.get("youtube_cache_dir")
        cached = {}
        if cache_dir:
            cf = Path(cache_dir) / f"{vid}.json"
            if cf.is_file():
                cached = json.loads(cf.read_text(encoding="utf-8"))
        if cached:
            title = str(cached.get("title") or "")[:300]
            author_name = str(cached.get("author_name") or "")[:200]
            author_url = str(cached.get("author_url") or "")[:300]
            transcript = str(cached.get("transcript") or "")
            chapters = int(cached.get("chapters_count") or 0)
        else:
            proxy = self.config.get("youtube_proxy_url")
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
            with httpx.Client(timeout=8, trust_env=False, proxy=proxy or None, follow_redirects=False) as client:
                data = _json_response(client.get(url, headers={"User-Agent": "Mozilla/5.0"}))
            title = str(data.get("title") or "")[:300]
            author_name = str(data.get("author_name") or "")[:200]
            author_url = str(data.get("author_url") or "")[:300]
            transcript = ""
            chapters = 0
        has_tr = bool(transcript)
        excerpt = transcript[:2000] if include_tr else ""
        return self.record("youtube", {
            "video_id": vid,
            "include_transcript": include_tr,
            "title": title,
            "author_name": author_name,
            "author_url": author_url,
            "has_transcript": has_tr,
            "chapters_count": chapters,
            "transcript_chars": len(transcript),
            "transcript_excerpt": excerpt,
        })

    def vps(self, query):
        allowed = set(self.config.get("vps_allowed_units", (
            "orchestra.service", "kesha-bot-vps.service", "telegram-bot-api.service",
        )))
        units = list(query["units"])
        if any(u not in allowed for u in units):
            raise AccessRevoked
        states = []
        for unit in units:
            self._check_budget()
            proc = subprocess.run(
                ["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "MemoryCurrent", "-p", "NRestarts"],
                capture_output=True, text=True, timeout=4, check=False,
            )
            props = {}
            for line in proc.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
            mem_raw = props.get("MemoryCurrent", "")
            rss_mib = int(int(mem_raw) / (1024 * 1024)) if mem_raw.isdigit() else 0
            pid_raw = props.get("MainPID", "0")
            rst_raw = props.get("NRestarts", "0")
            states.append({
                "unit": unit,
                "active": _redact_line(props.get("ActiveState", "unknown"))[:40],
                "sub": _redact_line(props.get("SubState", "unknown"))[:40],
                "pid": int(pid_raw) if pid_raw.isdigit() else 0,
                "rss_mib": max(0, rss_mib),
                "restarts": int(rst_raw) if rst_raw.isdigit() else 0,
            })
        stat_root = self.config.get("vps_stat_path", "/")
        sv = os.statvfs(stat_root)
        disk_free_mb = int((sv.f_bavail * sv.f_frsize) / (1024 * 1024))
        running = waiting = idle = 0
        db_path = self.config.get("orchestra_db_path")
        if query.get("include_sessions") and db_path and Path(db_path).is_file():
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0) as conn:
                for st, cnt in conn.execute("SELECT status, COUNT(*) FROM sessions WHERE status IN ('running','waiting','idle') GROUP BY status"):
                    if st == "running":
                        running = int(cnt)
                    elif st == "waiting":
                        waiting = int(cnt)
                    elif st == "idle":
                        idle = int(cnt)
        return self.record("vps", {
            "units": units,
            "include_sessions": bool(query.get("include_sessions")),
            "service_states": states,
            "disk_free_mb": max(0, disk_free_mb),
            "running_sessions": running,
            "waiting_sessions": waiting,
            "idle_sessions": idle,
        })

    def avito(self, query):
        src_path = self.config.get("avito_listings_path")
        if not src_path:
            raise AccessRevoked
        fp = Path(src_path)
        if not fp.is_file():
            raise AccessRevoked
        items = []
        if fp.suffix == ".json":
            raw_data = json.loads(fp.read_text(encoding="utf-8"))
            items = raw_data.get("items", raw_data) if isinstance(raw_data, dict) else raw_data
        else:
            for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("- "):
                    low = line.lower()
                    st = "published" if ("опубликован" in low or "published" in low) else "draft"
                    items.append({"batch": query["batch"], "status": st, "price_rub": 0, "photos": 1})
        batch = query["batch"]
        flt = query["status_filter"]
        in_batch = [i for i in items if isinstance(i, dict) and (batch == "all" or i.get("batch", batch) == batch)]
        pub = sum(1 for i in in_batch if i.get("status") == "published")
        drf = sum(1 for i in in_batch if i.get("status") != "published")
        matched = in_batch if flt == "all" else [i for i in in_batch if (i.get("status") == "published") == (flt == "published")]
        total_price = sum(int(i.get("price_rub") or 0) for i in matched if int(i.get("price_rub") or 0) >= 0)
        missing_photos = sum(1 for i in matched if int(i.get("photos", 1) or 0) <= 0)
        return self.record("avito", {
            "batch": batch,
            "status_filter": flt,
            "total_items": len(in_batch),
            "matched_items": len(matched),
            "published_count": pub,
            "draft_count": drf,
            "total_price_rub": total_price,
            "missing_photo_count": missing_photos,
        })


def _redact_line(text: str) -> str:
    text = re.sub(r"(?i)(Bearer\\s+)[A-Za-z0-9._~+/=-]{8,}", r"[REDACTED]", text)
    text = re.sub(r"(?:sk-(?:ant-|proj-)?|gh[pousr]_|ya29\.|bot\d{6,15}:)[A-Za-z0-9_:-]{12,}", "[REDACTED]", text)
    return text


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

