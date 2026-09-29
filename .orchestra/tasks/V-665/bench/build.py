"""Собирает варианты B/C/D из общей разметки A и считает размер сцены/плеера."""
import re, json, pathlib
here = pathlib.Path(__file__).parent
head = (here/'a-states.html').read_text().split('<script>')[0]  # общая разметка = всё до скрипта варианта A
svg = re.search(r'<svg id="stage".*?</svg>', head, re.S).group(0)
canvas_head = head.replace(svg, '<canvas id="cv" style="width:100%;aspect-ratio:900/220;display:block" role="img" aria-label="Задача идёт от владельца к воркеру"></canvas>')
if not (here/'gsap.min.js').exists():  # сторонний код не коммитим, для замера скачиваем
    import urllib.request; urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js', here/'gsap.min.js')
def js(n): return (here/n).read_text()
(here/'b-waapi.html').write_text(head.replace('A · состояния шагов + render(t)','B · Web Animations API')+'<script>\n'+js('b-waapi.js')+'</script></body></html>\n')
(here/'c-gsap-cdn.html').write_text(head.replace('A · состояния шагов + render(t)','C · GSAP (CDN)')+'<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>\n<script>\n'+js('c-gsap.js')+'</script></body></html>\n')
(here/'c-gsap-inline.html').write_text(head.replace('A · состояния шагов + render(t)','C · GSAP (встроен)')+'<script>\n'+js('gsap.min.js')+'\n</script>\n<script>\n'+js('c-gsap.js')+'</script></body></html>\n')
(here/'d-canvas.html').write_text(canvas_head.replace('A · состояния шагов + render(t)','D · Canvas + draw(t)')+'<script>\n'+js('d-canvas.js')+'</script></body></html>\n')

try:
    import tiktoken; enc = tiktoken.get_encoding('o200k_base'); tok = lambda s: len(enc.encode(s))
except ImportError:
    tok = lambda s: None
def part(src, a, b):
    i = src.index(a); j = src.index(b, i) if b else len(src); return src[i:j]
rows = []
for name, scene_markup in [('a-states.html', svg), ('b-waapi.html', svg), ('c-gsap-cdn.html', svg), ('c-gsap-inline.html', svg), ('d-canvas.html', '')]:
    src = (here/name).read_text()
    code = src[src.rindex('<script>'):]
    scene = scene_markup + part(code, '// ── СЦЕНА ──', '// ── ПЛЕЕР ──')
    player = part(code, '// ── ПЛЕЕР ──', '</script>')
    rows.append(dict(file=name, file_bytes=len(src.encode()), scene_bytes=len(scene.encode()), scene_lines=scene.count('\n'),
                     scene_tokens=tok(scene), player_bytes=len(player.encode()), player_lines=player.count('\n'), player_tokens=tok(player),
                     file_tokens=tok(src)))
print(json.dumps(rows, ensure_ascii=False, indent=1))
(here/'sizes.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1))
