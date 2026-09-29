"""Собирает самостоятельные примеры из src/*.src.html и каркаса плеера, взятого прямо из скилла html-motion."""
import json, pathlib, re
here = pathlib.Path(__file__).parent
skill = (here.parents[2] / '.orchestra/pipelines/default/prompts/skills/html-motion.md').read_text()
tpl = re.search(r'^```html motion-template\n(.*?)^```', skill, re.S | re.M).group(1)
parts = {
    'STYLE': re.search(r'<style>.*?</style>', tpl, re.S).group(0),
    'CONTROLS': re.search(r'<div class="cap".*?<ol class="ch" id="chap"></ol>', tpl, re.S).group(0),
    'PLAYER': re.search(r'// ── ПЛЕЕР ──.*?(?=\n</script>)', tpl, re.S).group(0),
}
data = json.dumps(json.loads((here / 'weekly-limit-data.json').read_text()), ensure_ascii=False, separators=(',', ':'))
for src in sorted((here / 'src').glob('*.src.html')):
    html = src.read_text().replace('<!--STYLE-->', parts['STYLE']).replace('<!--CONTROLS-->', parts['CONTROLS']).replace('/*PLAYER*/', parts['PLAYER'] + '\n').replace('/*DATA*/', data)
    out = here / src.name.replace('.src', '')
    out.write_text(html)
    print(out.name, len(html.encode()), 'байт')
