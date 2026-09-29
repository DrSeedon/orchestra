"""Детерминизм паузы/перемотки и офлайн-работа вариантов A–D (Chromium и WebKit).

Кадр на паузе должен совпадать пиксель в пиксель с кадром, полученным прямой
перемоткой в то же время из другого состояния. Контекст браузера offline=True: CDN недоступен.
"""
import io, json, pathlib, sys
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

here = pathlib.Path(__file__).parent
FILES = ['a-states.html', 'b-waapi.html', 'c-gsap-cdn.html', 'c-gsap-inline.html', 'd-canvas.html']


def shot(page):
    el = page.locator('#stage, #cv').first
    return Image.open(io.BytesIO(el.screenshot())).convert('RGB')


def diff(a, b):
    if a.size != b.size:
        return -1
    return sum(1 for px in ImageChops.difference(a, b).getdata() if max(px) > 8)


def run(browser, name):
    ctx = browser.new_context(viewport={'width': 1000, 'height': 600}, offline=True)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
    page.goto((here / name).as_uri())
    page.wait_for_timeout(200)
    r = {'file': name, 'errors': errors}
    if not page.evaluate('(() => { try { return typeof P == "object" } catch { return false } })()'):
        r['works'] = False
        ctx.close()
        return r
    r['works'] = True
    # 1) прямая перемотка против перемотки назад из конца
    page.evaluate('P.seek(3.0)'); f1 = shot(page)
    page.evaluate('P.seek(8)'); page.evaluate('P.seek(3.0)'); f2 = shot(page)
    r['seek_back_diff_px'] = diff(f1, f2)
    # 2) пауза во время проигрывания против прямой перемотки в то же t
    page.evaluate('P.seek(0); P.play()'); page.wait_for_timeout(2300); page.evaluate('P.pause()')
    tp = page.evaluate('P.t'); fp = shot(page)
    page.evaluate('P.seek(8)'); page.evaluate(f'P.seek({tp})'); fs = shot(page)
    r['pause_t'] = round(tp, 3); r['pause_vs_seek_diff_px'] = diff(fp, fs)
    # 3) естественный конец против перемотки в конец
    page.select_option('#rate', '2'); page.evaluate('P.seek(6.5); P.play()'); page.wait_for_timeout(1500)
    fe = shot(page); r['end_t'] = page.evaluate('P.t')
    page.evaluate('P.seek(0)'); page.evaluate('P.seek(P.T)'); r['end_vs_seek_diff_px'] = diff(fe, shot(page))
    page.select_option('#rate', '1')
    # 4) клавиши: пробел запускает и ставит на паузу, стрелка — конец шага
    page.evaluate('P.seek(0)'); page.locator('#bPlay').focus(); page.keyboard.press('Space'); page.wait_for_timeout(400)
    page.keyboard.press('Space'); t1 = page.evaluate('P.t'); page.wait_for_timeout(300); t2 = page.evaluate('P.t')
    r['space_play_then_pause'] = bool(t1 > 0.1 and abs(t2 - t1) < 1e-6)
    page.keyboard.press('ArrowRight'); r['arrow_right_t'] = round(page.evaluate('P.t'), 3)
    page.keyboard.press('ArrowRight'); r['arrow_right2_t'] = round(page.evaluate('P.t'), 3)
    page.keyboard.press('ArrowLeft'); r['arrow_left_t'] = round(page.evaluate('P.t'), 3)
    r['caption_at_end_of_step1'] = page.evaluate("P.seek(2); document.getElementById('capT').textContent")
    ctx.close()
    return r


out = {}
with sync_playwright() as p:
    for engine in ('chromium',):  # WebKit на VPS не запускается: нет libgtk-4
        b = getattr(p, engine).launch()
        out[engine] = [run(b, f) for f in FILES]
        b.close()
(here / 'check.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
for engine, rows in out.items():
    for r in rows:
        print(engine, json.dumps(r, ensure_ascii=False))
