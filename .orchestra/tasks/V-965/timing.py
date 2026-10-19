"""V-965: cold-cache first-load timing under throttling; variant B moves the 5 head <script> tags
to the end of <body>. The route edit is simulated and presence writes are blocked."""
import json, re, statistics, sys, hmac, hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
base, out = sys.argv[1], sys.argv[2]
env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
tok = hmac.new(env["DASHBOARD_PASSWORD"].encode(), env["DASHBOARD_USER"].encode(), hashlib.sha256).hexdigest()
HEAD = re.compile(r'^\s*<script src="[^"]*(?:i18n\.js|marked\.min\.js|purify\.min\.js|diff_match_patch\.js|highlight\.min\.js)[^"]*"></script>\n', re.M)
PROFILES = {"lan": None, "4g": (1.6e6/8, 0.150), "slow": (0.4e6/8, 0.300)}  # bytes/s, latency s
def run(browser, prof, cpu, variant):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": "session", "value": tok, "url": base}])
    page = ctx.new_page(); cdp = ctx.new_cdp_session(page)
    page.route(base + "/api/owner-activity/events", lambda route: route.abort())
    if PROFILES[prof]:
        bps, lat = PROFILES[prof]
        cdp.send("Network.enable"); cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": lat*1000, "downloadThroughput": bps, "uploadThroughput": bps})
    if cpu > 1: cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})
    if variant == "B":
        def h(route):
            r = route.fetch(); body = r.text(); moved = "".join(HEAD.findall(body)); body = HEAD.sub("", body)
            body = body.replace('<script src="/static/js/theme.js', moved + '<script src="/static/js/theme.js', 1) if moved else body
            route.fulfill(response=r, body=body)
        page.route(base + "/", h)
    page.goto(base + "/", wait_until="load"); page.wait_for_timeout(1500)
    m = page.evaluate("""() => { const n = performance.getEntriesByType('navigation')[0]; const f = performance.getEntriesByName('first-contentful-paint')[0];
       return {fcp: f ? f.startTime : null, dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd}; }""")
    ctx.close(); return m
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for prof, cpu in [("lan", 1), ("lan", 4), ("4g", 1), ("4g", 4), ("slow", 4)]:
        for var in "AB":
            runs = [run(b, prof, cpu, var) for _ in range(5)]
            res[f"{prof}/cpu{cpu}/{var}"] = {k: round(statistics.median(r[k] for r in runs)) for k in ("fcp", "dcl", "load")} | {"runs": runs}
            print(prof, cpu, var, {k: res[f"{prof}/cpu{cpu}/{var}"][k] for k in ("fcp","dcl","load")}, flush=True)
    b.close()
json.dump(res, open(out, "w"), indent=1)
