"""Профиль движения по самой анимации, без видео: P.seek(k/60) и координата объекта из DOM.

Кадр — чистая функция t, поэтому это точная траектория, которую видит зритель, без шума детектора и кодека.
task-path: токен (#tok, центр в координатах SVG) и его видимость — верхний элемент в центре токена принадлежит
токену (иначе он за узлом). weekly-limit: ширина окна графика (#clip) — это x курсора.
Метрики:
- stop_and_go: объект остановился (скорость < 2% пика) меньше чем на 0.3 с и снова поехал — «запнулся»;
- teleports_visible: сдвиг больше 15 px за кадр, видимый в обоих кадрах;
- speed_jump_max: наибольший скачок скорости между соседними кадрами (без телепортов), в долях пиковой скорости.
Запуск: uv run --frozen python profile_dom.py
"""
import json, math, pathlib
from playwright.sync_api import sync_playwright

here = pathlib.Path(__file__).parent
FPS = 60
JS_TOK = """k=>{P.seek(k);const g=$('tok'),m=g.getCTM(),s=$('stage').getScreenCTM(),x=m.e,y=m.f,
 px=s.a*x+s.e,py=s.d*y+s.f,el=document.elementFromPoint(px,py);return [x,y,!!(el&&g.contains(el))&&+(g.getAttribute('opacity')??1)>0.05]}"""
JS_CLIP = "k=>{P.seek(k);return [+$('clip').getAttribute('width'),0,true]}"


def run(page, path, kind):
    page.goto(path.as_uri())
    T = page.evaluate('P.T')
    js = JS_TOK if kind == 'task-path' else JS_CLIP
    pos = [page.evaluate(js, k / FPS) for k in range(round(T * FPS) + 1)]
    v = [math.hypot(b[0] - a[0], b[1] - a[1]) * FPS for a, b in zip(pos, pos[1:])]
    vis = [a[2] and b[2] for a, b in zip(pos, pos[1:])]
    tele = [x > 15 * FPS for x in v]
    peak = max(x for x, t in zip(v, tele) if not t)
    rest = [x < 0.02 * peak for x in v]
    # «запинка»: движение → покой короче 0.3 с → снова движение, всё время на виду
    sg, k = 0, 0
    while k < len(v):
        if rest[k] and k > 0 and not rest[k - 1] and not tele[k - 1]:
            j = k
            while j < len(v) and rest[j]:
                j += 1
            if j < len(v) and not tele[j] and j - k < 0.3 * FPS and all(vis[k - 1:j + 1]):
                sg += 1
            k = j
        k += 1
    jumps = [abs(v[i] - v[i - 1]) / peak for i in range(1, len(v)) if not tele[i] and not tele[i - 1] and vis[i] and vis[i - 1]]
    return {'file': str(path.relative_to(here.parent)), 'frames': len(pos), 'peak_speed': round(peak, 1),
            'stop_and_go': sg, 'teleports_visible': sum(1 for t, s in zip(tele, vis) if t and s),
            'speed_jump_max': round(max(jumps), 3), 'speed_jump_p99': round(sorted(jumps)[int(len(jumps) * .99)], 4)}


res = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={'width': 1040, 'height': 760})
    for kind in ('task-path', 'weekly-limit'):
        for d in ('V-665', 'V-668'):
            res.append(run(page, here.parent / d / f'{kind}.html', kind))
    b.close()
(here / 'profile_dom.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
