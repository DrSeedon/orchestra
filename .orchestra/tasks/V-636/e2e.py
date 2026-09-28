# V-636: прогон живого пользователя на стенде реестра — N ходов подряд в одном чате.
# Конец хода — когда ВСЕ агенты проекта простаивают 20 с подряд (ответ воркера приходит
# оркестратору отдельным ходом). Печатает ответ хода, ошибки и видимые служебные плашки.
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

env = dict(l.strip().split("=", 1) for l in open("/home/kesha/projects/seedon/secrets/reestr-demo-access.env")
           if "=" in l and not l.startswith("#"))
U, P, B = env["DEMO_DASHBOARD_USER"], env["DEMO_DASHBOARD_PASSWORD"], env["DEMO_URL"].rstrip("/")
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
STEPS = sys.argv[2:]
if len(STEPS) == 1 and Path(STEPS[0]).is_file():
    STEPS = [l.strip() for l in open(STEPS[0]) if l.strip()]
SCOPE = "%2Fworkspace%2Fproject"
BAD = ["нет данных", "owner_mode_only", "OpenRouter", "Связь нестабильна", "правило допуска",
       "round failed", "Unprocessable", "auto-report", "Finished without", "[from:", "turn interrupted", "turn ended", "читатель событий", "context unknown",
       "loop_error", "Traceback", "stop_reason"]

with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
    pg = ctx.new_page()
    httpbad = []
    pg.on("response", lambda r: httpbad.append((r.status, r.url)) if r.status >= 400 else None)
    pg.goto(B); pg.fill("input[name=username]", U); pg.fill("input[name=password]", P)
    pg.click("button[type=submit]"); pg.wait_for_timeout(6000)

    def statuses():
        r = pg.request.get(f"{B}/api/sessions?scope={SCOPE}")
        return {s["name"]: s["status"] for s in r.json()}

    total_bad = 0
    for i, msg in enumerate(STEPS, 1):
        before = pg.inner_text("#chat")
        ta = pg.locator("textarea:visible").first; ta.fill(msg)
        pg.get_by_text("Отправить", exact=True).first.click()
        t0 = time.time(); idle_since = None; seen_running = False
        while time.time() - t0 < 600:
            pg.wait_for_timeout(3000)
            st = statuses()
            busy = any(v in ("running", "waiting", "starting") for v in st.values())
            seen_running |= busy
            if busy or not seen_running and time.time() - t0 < 30:
                idle_since = None; continue
            idle_since = idle_since or time.time()
            if time.time() - idle_since >= 20: break
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / f"step{i:02d}.png"))
        chat = pg.inner_text("#chat")
        new = chat[len(before):] if chat.startswith(before) else chat[-3000:]
        visible = pg.inner_text("body")
        found = [w for w in BAD if w.lower() in new.lower()]
        banners = {sel: pg.locator(sel).first.is_visible() for sel in ("#connection-banner", "#quota-lines", "#ai-status")
                   if pg.locator(sel).count()}
        print(f"===== STEP {i} ({time.time()-t0:.0f}s) agents={statuses()}\n>>> {msg}\n{new.strip()[-3500:]}")
        print("visible-bad:", found, "banners:", banners)
        total_bad += bool(found) or any(banners.get(k) for k in ("#connection-banner", "#quota-lines"))
    for x in httpbad: print("HTTP", x)
    print("STEPS WITH PROBLEMS:", total_bad)
    b.close()
