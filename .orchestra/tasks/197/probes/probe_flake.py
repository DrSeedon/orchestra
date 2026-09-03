"""Why does test_silent_turn_marker... time out with the #197 change?

Reproduce the helper's path and capture console errors + timing of the wait conditions.
"""
import json, re, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/rev197-opus")
import tests.test_frontend as F
from playwright.sync_api import sync_playwright

R = []


def run():
    tmp = Path(tempfile.mkdtemp()) / "orchestra.db"
    F._seed_dashboard_db(tmp)
    proc, origin = F._start_dashboard_server(tmp)
    F._DASHBOARD_ORIGIN = origin
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for attempt in range(6):
                page = b.new_page()
                console, pageerrors = [], []
                page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
                page.on("pageerror", lambda e: pageerrors.append(str(e)))
                rows = [F._silent_turn_row(51001),
                        F._silent_turn_row(51009, "status", "turn ended")]
                page.add_init_script("""() => {
                    window.EventSource = class S { constructor(u){this.url=u;this.readyState=1;}
                    close(){this.readyState=2;} };
                }""")
                page.add_init_script(F._notify_stub("granted"))
                F._route_frontend_sources(page)
                hcalls = []
                page.route(re.compile(rf"/api/sessions/{F._NOTIFY_AGENT}/logs\?"),
                           lambda r: (hcalls.append(1), r.fulfill(
                               status=200, content_type="application/json",
                               body=json.dumps(rows if len(hcalls) == 1 else [], ensure_ascii=False)))[-1])
                page.route(re.compile(rf"/api/sessions/{F._NOTIFY_AGENT}/stream\?"),
                           lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))
                rec = {"attempt": attempt}
                t0 = time.monotonic()
                page.goto(origin, wait_until="domcontentloaded")
                try:
                    page.wait_for_function(
                        "() => typeof selectAgent === 'function' && selectedAgent && currentScope && orchData.length",
                        timeout=8000)
                    rec["gate1_s"] = round(time.monotonic() - t0, 2)
                except Exception as e:
                    rec["gate1_FAIL"] = type(e).__name__
                    rec["gate1_state"] = page.evaluate(
                        "() => ({sel: typeof selectAgent, selectedAgent: typeof selectedAgent!=='undefined'?selectedAgent:'undef',"
                        " scope: typeof currentScope!=='undefined'?currentScope:'undef',"
                        " orch: typeof orchData!=='undefined'?orchData.length:'undef',"
                        " agentChildren: document.getElementById('agent-list')?.children.length,"
                        " snapshotFn: typeof snapshotLoad})")
                    rec["console_tail"] = console[-12:]
                    rec["pageerrors"] = pageerrors[:5]
                    R.append(rec); page.close(); continue
                page.evaluate("() => _pollStop('sessions')")
                page.evaluate("name => selectAgent(name)", F._NOTIFY_AGENT)
                page.wait_for_function("name => selectedAgent === name", arg=F._NOTIFY_AGENT)
                try:
                    page.wait_for_function("() => !refreshInProgress", timeout=8000)
                    rec["gate2_s"] = round(time.monotonic() - t0, 2)
                except Exception as e:
                    rec["gate2_FAIL"] = type(e).__name__
                    rec["console_tail"] = console[-12:]
                    R.append(rec); page.close(); continue
                try:
                    page.wait_for_function("""() => {
                        const ids=[...document.querySelectorAll('#chat [data-chat-log-id]')].map(n=>n.dataset.chatLogId);
                        return ids.includes('51009');}""", timeout=8000)
                    rec["gate3_s"] = round(time.monotonic() - t0, 2)
                    rec["ok"] = True
                except Exception as e:
                    rec["gate3_FAIL"] = type(e).__name__
                    rec["ids"] = page.evaluate(
                        "() => [...document.querySelectorAll('#chat [data-chat-log-id]')].map(n=>n.dataset.chatLogId)")
                    rec["history_calls"] = len(hcalls)
                    rec["console_tail"] = console[-14:]
                    rec["pageerrors"] = pageerrors[:5]
                R.append(rec)
                page.close()
            b.close()
    finally:
        F._DASHBOARD_ORIGIN = ""
        F._stop_dashboard_server(proc)
    print("JSONRESULT" + json.dumps(R, ensure_ascii=False))


run()
