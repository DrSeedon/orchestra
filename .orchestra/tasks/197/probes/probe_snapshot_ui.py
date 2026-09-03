"""Browser probe (#197 review): does a localStorage snapshot render as LIVE data?

Runs against the repo's own dashboard fixture server (serves THIS worktree's static).
Scenario: seed a snapshot younger than _USAGE_REFRESH_INTERVAL_MS (120 s), make every
/api/usage request fail, reload, read the freshness label.

Control arm: seed a snapshot OLDER than 120 s -> label must differ (permissive/discriminating).
"""
import json
import sys
import time

sys.path.insert(0, "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/rev197-opus")

import tests.test_frontend as F
from playwright.sync_api import sync_playwright
from pathlib import Path
import tempfile

RESULT = {}


def run():
    tmp = Path(tempfile.mkdtemp()) / "orchestra.db"
    F._seed_dashboard_db(tmp)
    proc, origin = F._start_dashboard_server(tmp)
    F._DASHBOARD_ORIGIN = origin
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for arm, age_ms in (("fresh_snapshot", 30_000), ("old_snapshot", 300_000)):
                page = browser.new_page()
                logs = []
                page.on("console", lambda m: logs.append(f"{m.type}:{m.text}"))
                page.goto(origin, wait_until="domcontentloaded")
                snap = {
                    "ts": int(time.time() * 1000) - age_ms,
                    "data": {
                        "anthropic": {
                            "five_hour": {"utilization": 42, "resets_at": None},
                            "seven_day": {"utilization": 77, "resets_at": None},
                        },
                        "codex": {}, "grok": None,
                    },
                }
                page.evaluate(
                    "s => localStorage.setItem('orchestra_snapshot:usage', JSON.stringify(s))",
                    snap,
                )
                # every /api/usage dies -> nothing fresh can arrive
                page.route("**/api/usage**", lambda route: route.abort("failed"))
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                bar_text = page.inner_text("#usage-bar")
                fresh = page.evaluate(
                    "() => { const e=document.getElementById('usage-freshness');"
                    " return e ? {text:e.innerText, color:e.style.color} : null; }"
                )
                has_data = page.evaluate("() => typeof _usageData !== 'undefined' && !!_usageData")
                err = page.evaluate("() => typeof _usageError !== 'undefined' && _usageError")
                RESULT[arm] = {
                    "bar_text": bar_text.strip()[:200],
                    "freshness": fresh,
                    "_usageData_present": has_data,
                    "_usageError": err,
                    "console_warns": [l for l in logs if "snapshot" in l.lower()][:5],
                }
                page.close()
            # --- corrupt localStorage arm: page must still load
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(origin, wait_until="domcontentloaded")
            page.evaluate(
                "() => { localStorage.setItem('orchestra_snapshot:usage', '{not json');"
                " localStorage.setItem('orchestra_snapshot:sessions:/tmp/fe-scope','<<<broken'); }"
            )
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            RESULT["corrupt"] = {
                "page_errors": errors[:5],
                "agent_list_visible": page.locator("#agent-list").is_visible(),
                "agent_children": page.evaluate(
                    "() => document.getElementById('agent-list')?.children.length ?? -1"),
            }
            page.close()
            browser.close()
    finally:
        F._DASHBOARD_ORIGIN = ""
        F._stop_dashboard_server(proc)
    print("JSONRESULT" + json.dumps(RESULT, ensure_ascii=False))


run()
