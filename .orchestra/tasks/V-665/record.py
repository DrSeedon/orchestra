"""Запись примера в MP4: Playwright record_video_dir (webm) → ffmpeg (H.264). Плеер сам ведёт время, запись = P.play() до конца."""
import pathlib, subprocess, sys
from playwright.sync_api import sync_playwright
here = pathlib.Path(__file__).parent
out = here / 'video'; out.mkdir(exist_ok=True)
name = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1040, 'height': 700}, offline=True, record_video_dir=str(out), record_video_size={'width': 1040, 'height': 700})
    page = ctx.new_page(); page.goto((here / f'{name}.html').as_uri()); page.wait_for_timeout(500)
    T = page.evaluate('P.T'); page.evaluate('P.play()'); page.wait_for_timeout(int(T * 1000) + 1000)
    webm = page.video.path(); ctx.close(); b.close()
mp4 = out / f'{name}.mp4'
subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', webm, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '28', '-movflags', '+faststart', str(mp4)], check=True)
pathlib.Path(webm).unlink()
print(mp4, mp4.stat().st_size)
