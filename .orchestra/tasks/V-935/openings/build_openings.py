"""V-935: три готовые сцены открытия на одной схеме — для кадров «начало / конец наезда».
Запуск: python3 build_openings.py <animation.md> > openings.html"""
import re
import sys
from pathlib import Path

md = Path(sys.argv[1]).read_text()
tpl = re.search(r"```html motion-template\n(.*?)```", md, re.S).group(1)
SCENES = ["night-desk", "board", "cafe"]
SVG = '<svg id="stage" viewBox="0 0 1280 590" role="img" aria-label="Три сцены открытия">' + "".join(
    f'<g id="pic{k}" opacity="0"></g>' for k in range(3)) + """
<g id="diaLayer" opacity="0"><g id="dia">
 <rect x="470" y="40" width="340" height="100" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>
 <text x="640" y="104" text-anchor="middle" font-size="38" font-weight="600">оркестратор</text>
 <g font-size="36">""" + "".join(
    f'<rect x="{x}" y="330" width="300" height="100" rx="14" fill="#fff" stroke="#d9dce3" stroke-width="2"/>'
    f'<text x="{x + 150}" y="393" text-anchor="middle">воркер</text><path d="M640 140L{x + 150} 330" stroke="#c9ced8" stroke-width="3"/>'
    for x in (90, 490, 890)) + "</g></g></g></svg>"
JS = r"""
const SC = %s, BOX = {x: 96, y: 18, w: 1088, h: 556};
const PICS = SC.map((s, k) => Paper.picture('pic' + k, BOX, {scene: s}));
const VIEWS = SC.map(s => Paper.view(s));
PICS.forEach((p, k) => Paper.mini(p, 'dia', VIEWS[k]));
const STEPS = SC.map(s => ({t: s, say: Paper.SCENES[s].title, d: 4.5}));
STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);
function draw(i, p, t) {
  const st = []; let at = 0; for (const s of STEPS) { st.push(at); at += s.d; }
  PICS.forEach((pic, k) => {
    const t0 = st[k], d = STEPS[k].d;
    Paper.brush(pic, t, t0, 1.2); Paper.live(pic, t);
    Paper.camera(pic, t, {...VIEWS[k], t0: t0 + 1.8, t1: t0 + d - .4});
    $('pic' + k).setAttribute('opacity', i === k ? 1 : 0);
  });
  // в конце наезда — переход в настоящую схему на том же месте
  $('diaLayer').setAttribute('opacity', Paper.fade(t, st[i] + STEPS[i].d - .5, .35).toFixed(3));
}
""" % SCENES
html = re.sub(r'<div class="stg"><svg id="stage".*?</svg></div>', lambda _: f'<div class="stg">{SVG}</div>', tpl, count=1, flags=re.S)
html = re.sub(r"const STEPS = \[.*?\];\n", lambda _: JS.lstrip("\n"), html, count=1, flags=re.S)
sys.stdout.write(html)
