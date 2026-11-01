"""Render the quota timeline from live usage_snapshots (read-only) and save a screenshot."""
import json, sqlite3, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import test_t344_quota_lines_browser as T
from playwright.sync_api import sync_playwright

con = sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
rows, last = [], 0
for ts, pu in con.execute("select ts, provider_usage from usage_snapshots where ts>=? order by id", ("2026-10-22T20:00",)):
    t = datetime.fromisoformat(ts).timestamp()
    if t - last < 1800: continue
    last = t
    w = next((x for x in (json.loads(pu).get("codex") or {}).get("windows", []) if x.get("window_minutes") == 10080), None)
    if w: rows.append({"ts": ts, "providers": {"codex": {"windows": [w]}}})
final = rows[-1]["providers"]["codex"]["windows"][0]
now = datetime.fromisoformat(rows[-1]["ts"])
payload = T._payload(codex_util=final["utilization"], codex_progress=0.1)
payload["generated_at"] = now.isoformat()
payload["rule"].update({"tolerance_start_pp": 10.0, "tolerance_end_pp": 1.0})
c = payload["buckets"][0]
c["window"].update({"resets_at": final["resets_at"], "window_minutes": 10080, "id": final["id"]})
c["timeline"] = {"points": [{"ts": datetime.fromisoformat(r["ts"]).timestamp(),
    "utilization": r["providers"]["codex"]["windows"][0]["utilization"],
    "resets_at": r["providers"]["codex"]["windows"][0]["resets_at"]} for r in rows]}
payload["buckets"] = [c]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page, errors = T._render(b, payload, reset_history={"step_minutes": 30, "rows": rows})
    page.add_style_tag(content=".ql-body { max-height: none !important; overflow: visible !important; } body{background:#151c2e} svg text{fill:#aab} .ql-trace{stroke:#f472b6;stroke-width:2;fill:none} polyline.ql-gated{stroke:#fb923c !important;stroke-width:2 !important;fill:none !important;stroke-dasharray:6 3 !important;display:inline !important;opacity:1 !important} .ql-timeline-projection{opacity:.5}")
    print(page.locator("[data-ql-timeline-threshold]").count(), page.locator("[data-ql-timeline-history]").count())
    page.set_viewport_size({"width": 1280, "height": 1400})
    page.locator("[data-ql-timeline='all']").screenshot(path=str(Path(__file__).with_name("quota-chart-fixed.png")))
    print(errors)
