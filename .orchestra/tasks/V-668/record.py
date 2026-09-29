"""Покадровая запись примера в MP4, 60 к/с.

Экранная запись Playwright (record_video_dir, V-665) шла 25 к/с и повторяла кадры: браузер отдаёт кадр, когда
успевает, а не по часам. Кадр плеера — чистая функция времени, поэтому кадр k снимается как P.seek(k/60): это ровно
то, что показывает проигрывание в момент k/60, только без пропусков. Кнопке пуска ставится вид «играет».
page.clock (поддельные часы) не подошёл: run_for принимает целые мс, а поддельный requestAnimationFrame
срабатывает на границах 16 мс, и шаг времени между кадрами прыгал бы 16/32 мс.
"""
import pathlib, subprocess, sys
from playwright.sync_api import sync_playwright

here = pathlib.Path(__file__).parent
out = here / 'video'; out.mkdir(exist_ok=True)
name, FPS = sys.argv[1], 60
mp4 = out / f'{name}.mp4'
ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-f', 'image2pipe', '-i', '-',
                       '-c:v', 'libx264', '-preset', 'slow', '-crf', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(mp4)],
                      stdin=subprocess.PIPE)
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1040, 'height': 700}, offline=True)
    page = ctx.new_page()
    page.goto((here / f'{name}.html').as_uri())
    T = page.evaluate('P.T')
    shot = lambda: ff.stdin.write(page.screenshot(type='png', animations='allow'))
    for _ in range(FPS // 2):  # полсекунды стоп-кадра до пуска
        shot()
    page.evaluate("$('bPlay').classList.add('on')")
    n = round(T * FPS)
    for k in range(1, n + 1):
        page.evaluate(f'P.seek({k / FPS})')
        shot()
    for _ in range(FPS):  # секунда финального кадра
        shot()
    b.close()
ff.stdin.close(); ff.wait()
print(mp4, mp4.stat().st_size, 'байт,', n, 'кадров проигрывания')
