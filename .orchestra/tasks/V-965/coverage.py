"""V-965: JS/CSS coverage + transfer sizes of the dashboard first load.
Usage: uv run --frozen python -I .orchestra/tasks/V-965/coverage.py <base_url> <out.json>
Session cookie is derived in-process from .env (never printed); presence writes are blocked."""
import json, sys, hmac, hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright

base, out = sys.argv[1], sys.argv[2]
env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
tok = hmac.new(env["DASHBOARD_PASSWORD"].encode(), env["DASHBOARD_USER"].encode(), hashlib.sha256).hexdigest()

def painted(length, ranges):
    cov = bytearray(length)
    for s, e, used in sorted(ranges, key=lambda r: -(r[1] - r[0])):
        start, end = max(0, s), min(e, length)
        cov[start:end] = bytes([1 if used else 0]) * (end - start)
    return sum(cov)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": "session", "value": tok, "url": base}])
    page = ctx.new_page()
    blocked_writes = []
    def block_presence(route):
        blocked_writes.append(route.request.method)
        route.abort()
    page.route(base + "/api/owner-activity/events", block_presence)
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable"); cdp.send("Debugger.enable"); cdp.send("DOM.enable"); cdp.send("CSS.enable")
    cdp.send("Profiler.enable"); cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
    cdp.send("CSS.startRuleUsageTracking")
    scripts, sheets, net, methods = {}, {}, {}, []
    cdp.on("Debugger.scriptParsed", lambda e: scripts.__setitem__(e["scriptId"], (e["url"], e["endColumn"], e["length"] if "length" in e else None)))
    cdp.on("CSS.styleSheetAdded", lambda e: sheets.__setitem__(e["header"]["styleSheetId"], (e["header"]["sourceURL"], e["header"]["length"])))
    def on_req(e): net[e["requestId"]] = {"url": e["request"]["url"], "method": e["request"]["method"], "type": e.get("type")}; methods.append(e["request"]["method"])
    def on_fin(e):
        if e["requestId"] in net: net[e["requestId"]]["encoded"] = e["encodedDataLength"]
    cdp.on("Network.requestWillBeSent", on_req); cdp.on("Network.loadingFinished", on_fin)
    page.goto(base + "/", wait_until="load"); page.wait_for_timeout(6000)
    nav = page.evaluate("""() => { const n = performance.getEntriesByType('navigation')[0]; const f = performance.getEntriesByName('first-contentful-paint')[0];
      return {dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd, fcp: f ? f.startTime : null}; }""")
    cov = cdp.send("Profiler.takePreciseCoverage")["result"]
    css = cdp.send("CSS.stopRuleUsageTracking")["ruleUsage"]
    jsrows = {}
    for sc in cov:
        url = sc["url"]
        if not url.startswith(base): continue
        src = cdp.send("Debugger.getScriptSource", {"scriptId": sc["scriptId"]})["scriptSource"]
        rngs = [(r["startOffset"], r["endOffset"], r["count"] > 0) for f in sc["functions"] for r in f["ranges"]]
        units = len(src.encode("utf-16-le")) // 2
        used = painted(units, rngs)
        jsrows[url] = {"utf16_units": units, "used_utf16_units": used}
    cssrows = {}
    for sid, (url, ln) in sheets.items():
        if url.startswith(base): cssrows[url] = {"utf16_units": ln, "used_utf16_units": 0, "ranges": []}
    for r in css:
        u = sheets.get(r["styleSheetId"], ("", 0))[0]
        if u in cssrows and r["used"]: cssrows[u]["ranges"].append((r["startOffset"], r["endOffset"]))
    for u, d in cssrows.items():
        cv = bytearray(d["utf16_units"])
        for s, e in d.pop("ranges"):
            start, end = max(0, s), min(e, d["utf16_units"])
            cv[start:end] = b"\x01" * (end - start)
        d["used_utf16_units"] = sum(cv)
    xfer = {}
    for r in net.values():
        if r["url"].startswith(base) and "encoded" in r: xfer[r["url"]] = {"encoded": r["encoded"], "type": r["type"], "method": r["method"]}
    json.dump({"base": base, "nav": nav, "js": jsrows, "css": cssrows, "transfer": xfer,
               "methods": sorted(set(methods)), "blocked_presence_posts": len(blocked_writes)},
              open(out, "w"), indent=1)
    b.close()
