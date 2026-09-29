"""Проверка примеров V-668 (сценарий V-665; ⏮ ⏭ ←/→ доезжают до цели за 0.4 с, поэтому после клавиш ждём 500 мс) в Chromium без сети: кадры, пауза, перемотка, клавиши, числа графика."""
import io, json, pathlib
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

here = pathlib.Path(__file__).parent
shots = here / 'shots'
shots.mkdir(exist_ok=True)


def img(page):
    return Image.open(io.BytesIO(page.locator('#stage').screenshot())).convert('RGB')


def diff(a, b):
    return sum(1 for px in ImageChops.difference(a, b).getdata() if max(px) > 8)


def check(browser, name):
    ctx = browser.new_context(viewport={'width': 1040, 'height': 760}, offline=True, device_scale_factor=1)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: m.type in ('error', 'warning') and errors.append(m.text))
    page.goto((here / f'{name}.html').as_uri())
    T = page.evaluate('P.T')
    r = {'file': name, 'T': T, 'steps': page.evaluate('P.S.length')}
    frames = {'start': 0, 'mid': T / 2, 'end': T}
    for label, t in frames.items():
        page.evaluate(f'P.seek({t})')
        page.screenshot(path=str(shots / f'{name}-{label}.png'), full_page=True)
        r[f'caption_{label}'] = page.locator('#capT').text_content()
    # пауза во время пуска == прямая перемотка в то же время
    page.evaluate('P.seek(0)'); page.click('#bPlay'); page.wait_for_timeout(3700); page.click('#bPlay')
    tp = page.evaluate('P.t'); a = img(page); page.screenshot(path=str(shots / f'{name}-paused.png'), full_page=True)
    page.evaluate('P.seek(P.T)'); page.evaluate(f'P.seek({tp})')
    r['paused_t'] = round(tp, 3); r['pause_vs_seek_diff_px'] = diff(a, img(page))
    # середина наплыва текста/подписи: кадр из двух разных исходных состояний совпадает (вся карточка, не только сцена)
    page.mouse.move(2, 2); page.wait_for_timeout(300)  # наведение на кнопку — состояние мыши, не времени
    card = lambda: Image.open(io.BytesIO(page.locator('.mv').screenshot(animations='disabled'))).convert('RGB')
    page.evaluate('P.seek(P.T)'); page.evaluate('P.seek(P.S[2] + 0.2)'); a = card()
    page.evaluate('P.seek(0)'); page.evaluate('P.seek(P.S[2] + 0.2)')
    r['crossfade_seek_two_states_diff_px'] = diff(a, card())
    # ползунок на середину мышью
    box = page.locator('#seek').bounding_box()
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    r['slider_click_mid_t'] = round(page.evaluate('P.t'), 2)
    # клавиши
    page.evaluate('P.seek(0)'); page.locator('body').click(position={'x': 5, 'y': 5})
    page.keyboard.press('ArrowRight'); page.wait_for_timeout(500); r['key_right_t'] = page.evaluate('P.t')
    page.keyboard.press('ArrowRight'); page.wait_for_timeout(500); r['key_right2_t'] = page.evaluate('P.t')
    page.keyboard.press('ArrowLeft'); page.wait_for_timeout(500); r['key_left_t'] = page.evaluate('P.t')
    page.keyboard.press('End'); r['key_end_t'] = page.evaluate('P.t')
    page.keyboard.press('Space'); page.wait_for_timeout(500); page.keyboard.press('Space')
    r['space_restarts_from_end_t'] = round(page.evaluate('P.t'), 2)
    # скорость 2x: за 1 с проходит около 2 с сцены
    page.evaluate('P.seek(0)'); page.select_option('#rate', '2'); page.evaluate('P.play()'); page.wait_for_timeout(1000); page.evaluate('P.pause()')
    r['rate2_after_1s_t'] = round(page.evaluate('P.t'), 2); page.select_option('#rate', '1')
    # клик по главе: запускает с начала шага
    page.locator('#chap li').nth(2).click(); page.wait_for_timeout(300); page.evaluate('P.pause()')
    r['chapter3_t'] = round(page.evaluate('P.t'), 2); r['chapter3_caption'] = page.locator('#capT').text_content()
    if name == 'weekly-limit':
        data = json.loads((here / 'weekly-limit-data.json').read_text())
        ends, got = [], []
        for i in range(r['steps'] - 1):
            page.evaluate(f'P.seek(P.S[{i}] + {page.evaluate(f"P.S[{i+1}]-P.S[{i}]")})')
            got.append(page.locator('#lab1').text_content())
        r['labels_at_step_ends'] = got
        r['event_pct'] = [e['pct'] for e in data['events']]
    # узкий экран
    page.set_viewport_size({'width': 390, 'height': 800}); page.evaluate(f'P.seek({T / 2})')
    page.screenshot(path=str(shots / f'{name}-narrow.png'), full_page=True)
    r['narrow_overflow_px'] = page.evaluate('document.documentElement.scrollWidth - innerWidth')
    r['errors'] = errors
    ctx.close()
    # reduced motion: шаг показывается сразу в конечном состоянии
    ctx = browser.new_context(viewport={'width': 1040, 'height': 760}, offline=True, reduced_motion='reduce')
    page = ctx.new_page(); page.goto((here / f'{name}.html').as_uri())
    page.evaluate('P.seek(P.S[1] + 0.01)'); a = img(page); page.evaluate('P.seek(P.S[2])'); r['reduced_motion_step_start_eq_end_diff_px'] = diff(a, img(page))
    ctx.close()
    return r


with sync_playwright() as p:
    b = p.chromium.launch()
    res = [check(b, n) for n in ('task-path', 'weekly-limit')]
    b.close()
(here / 'check_examples.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
