"""Does the FIRST painted frame present a snapshot as freshly-fetched live data?

initUsageBar(): _restoreUsageSnapshot(); renderUsageBar(); fetchUsage();
At that instant _usageError is false and _usageFetchPromise is null, so
_usageFreshnessHtml() takes the `stale` branch, and for a snapshot younger than
_USAGE_REFRESH_INTERVAL_MS (120000) it prints "обновлено сейчас" in grey.

Probe: hang /api/usage forever (so fetchUsage never resolves and never sets the error),
then sample the label. Control arm: snapshot older than 120 s must print "устарело".
"""
import json, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/rev197-opus")
import tests.test_frontend as F
from playwright.sync_api import sync_playwright

R = {}


def run():
    tmp = Path(tempfile.mkdtemp()) / "orchestra.db"
    F._seed_dashboard_db(tmp)
    proc, origin = F._start_dashboard_server(tmp)
    F._DASHBOARD_ORIGIN = origin
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for arm, age in (("snapshot_30s", 30_000), ("snapshot_300s", 300_000)):
                page = b.new_page()
                page.goto(origin, wait_until="domcontentloaded")
                page.evaluate(
                    "s => localStorage.setItem('orchestra_snapshot:usage', JSON.stringify(s))",
                    {"ts": int(time.time() * 1000) - age,
                     "data": {"anthropic": {"five_hour": {"utilization": 42, "resets_at": None},
                                            "seven_day": {"utilization": 77, "resets_at": None}},
                              "codex": {}, "grok": None}},
                )
                # HANG forever: fetchUsage() never settles -> _usageError stays false,
                # _usageFetchPromise is set only AFTER the first renderUsageBar() call.
                page.route("**/api/usage**", lambda r: None)
                page.reload(wait_until="domcontentloaded")
                samples = []
                for _ in range(14):
                    s = page.evaluate(
                        "() => { const e=document.getElementById('usage-freshness');"
                        " return {t: e?e.innerText:null, c: e?e.style.color:null,"
                        "  err: (typeof _usageError!=='undefined')&&_usageError,"
                        "  pend: (typeof _usageFetchPromise!=='undefined')&&!!_usageFetchPromise}; }")
                    samples.append(s)
                    page.wait_for_timeout(120)
                R[arm] = {"first": samples[0], "settled": samples[-1],
                          "distinct": sorted({json.dumps(x, ensure_ascii=False) for x in samples})[:4],
                          "bar": page.inner_text("#usage-bar").strip()[:160]}
                page.close()
            b.close()
    finally:
        F._DASHBOARD_ORIGIN = ""
        F._stop_dashboard_server(proc)
    print("JSONRESULT" + json.dumps(R, ensure_ascii=False))


run()
