# V-636: вход на стенд, наблюдение 60 с: неуспешные/медленные запросы, баннеры.
import sys, time
from playwright.sync_api import sync_playwright
env=dict(l.strip().split("=",1) for l in open("/home/kesha/projects/seedon/secrets/reestr-demo-access.env") if "=" in l and not l.startswith("#"))
U=env["DEMO_DASHBOARD_USER"]; P=env["DEMO_DASHBOARD_PASSWORD"]; B=env["DEMO_URL"]
OUT=sys.argv[1]; wait=int(sys.argv[2]) if len(sys.argv)>2 else 60
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1440,"height":900}, locale="ru-RU"); pg=ctx.new_page()
    t={}
    pg.on("request", lambda r: t.__setitem__(r.url, time.time()))
    def done(r):
        dt=time.time()-t.get(r.url,time.time())
        if r.status>=400 or dt>3: print("RESP", r.status, f"{dt:.1f}s", r.url)
    pg.on("response", done)
    pg.on("requestfailed", lambda r: print("FAILED", r.url, r.failure))
    pg.on("console", lambda m: print("CONSOLE", m.type, m.text[:200]) if m.type in ("error","warning") else None)
    pg.goto(B); pg.fill("input[name=username]", U); pg.fill("input[name=password]", P); pg.click("button[type=submit]")
    pg.wait_for_timeout(wait*1000)
    pg.screenshot(path=OUT)
    for sel in ["#connection-banner", "#quota-lines"]:
        loc=pg.locator(sel)
        if loc.count(): print(sel, "visible=", loc.first.is_visible(), repr(loc.first.inner_text()[:200]))
    b.close()
