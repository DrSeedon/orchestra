"""Профиль движения по MP4: положение объекта в каждом кадре → скорость, остановки, «зависшие» кадры.

task-path: центр синей плашки-токена (блоки 6×6, залитые #007aff больше чем на 70%: тонкие обводки
так не заполняют блок). weekly-limit: x вертикальной линии курсора (столбец с длинным рядом тёмных пикселей).
Запуск: uv run --frozen --with numpy python measure.py video.mp4 task-path|weekly-limit
"""
import json, subprocess, sys
import numpy as np


def frames(path):
    """Кадры по одному (все сразу в int16 не влезают в память: 1740 кадров 1040×700 — 7.6 ГБ)."""
    info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height,r_frame_rate',
                                      '-of', 'json', path], capture_output=True, check=True).stdout)['streams'][0]
    w, h = info['width'], info['height']; num, den = map(int, info['r_frame_rate'].split('/'))
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    def gen():
        while buf := proc.stdout.read(w * h * 3):
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3).astype(np.int16)
    return gen(), num / den, h


def token(f, y_max):
    s = f[:y_max]
    blue = (np.abs(s[..., 0] - 0) < 40) & (np.abs(s[..., 1] - 122) < 40) & (s[..., 2] > 215)
    H, W = blue.shape[0] // 6 * 6, blue.shape[1] // 6 * 6
    blk = blue[:H, :W].reshape(H // 6, 6, W // 6, 6).mean((1, 3)) > 0.7
    ys, xs = np.nonzero(blk)
    if len(xs) < 4:
        return None
    # субпиксельный центр: вес — «синева» пикселя в рамке найденных блоков
    y0, y1, x0, x1 = ys.min() * 6 - 4, ys.max() * 6 + 10, xs.min() * 6 - 4, xs.max() * 6 + 10
    wgt = np.clip(s[max(y0, 0):y1, max(x0, 0):x1, 2] - s[max(y0, 0):y1, max(x0, 0):x1, 0], 0, None).astype(float)
    gy, gx = np.mgrid[max(y0, 0):max(y0, 0) + wgt.shape[0], max(x0, 0):max(x0, 0) + wgt.shape[1]]
    return (float((gx * wgt).sum() / wgt.sum()), float((gy * wgt).sum() / wgt.sum()))


def cursor(f, y_max):
    g = f[:y_max].max(-1)
    cols = (g < 150).sum(0)
    c = int(np.argmax(cols))
    if cols[c] < 120:
        return None
    # субпиксельный x: вес — темнота столбцов ±3 px вокруг линии, только в строках, где линия есть
    rows = g[:, c] < 150
    dark = (255 - g[rows, max(c - 3, 0):c + 4]).clip(0, None).astype(float).sum(0)
    dark = (dark - dark.min()).clip(0, None)
    xs = np.arange(max(c - 3, 0), max(c - 3, 0) + len(dark))
    return (float((xs * dark).sum() / dark.sum()), 0.0)


def profile(path, kind):
    fr, fps, height = frames(path)
    y_max = int(height * 0.62)  # сцена в верхней части кадра; ниже подписи и главы (там синяя активная глава)
    pos, d, prev = [], [], None
    for f in fr:
        pos.append((token if kind == 'task-path' else cursor)(f, y_max))
        if prev is not None:  # диффы соседних кадров по сцене: 0 между двумя ненулевыми = кадр повторён (рывок)
            d.append(float(np.abs(f[:y_max] - prev).mean()))
        prev = f[:y_max]
    moving = [x > 0.02 for x in d]
    # повторённый кадр: изменение меньше четверти соседних, а соседи движутся (стоп → догон)
    hitch = sum(1 for k in range(1, len(d) - 1) if moving[k - 1] and moving[k + 1] and d[k] < 0.25 * min(d[k - 1], d[k + 1]))
    # скорость объекта, px/с, по кадрам, где он виден в двух соседних кадрах
    v = []
    for k in range(1, len(pos)):
        a, b = pos[k - 1], pos[k]
        v.append(None if a is None or b is None else float(np.hypot(b[0] - a[0], b[1] - a[1]) * fps))
    vv = [x for x in v if x is not None]
    mov = [x for x in vv if x > 5]
    med = float(np.median(mov)) if mov else 0.0
    # остановка посреди движения: объект стоит (< 5% медианной скорости) 1+ кадр между кадрами движения
    stops, k, idx = 0, 0, [i for i, x in enumerate(v) if x is not None]
    speeds = [v[i] for i in idx]
    first = next((i for i, x in enumerate(speeds) if x > 0.05 * med), None)
    last = max((i for i, x in enumerate(speeds) if x > 0.05 * med), default=None)
    if first is not None:
        k = first
        while k <= last:
            if speeds[k] <= 0.05 * med:
                stops += 1
                while k <= last and speeds[k] <= 0.05 * med:
                    k += 1
            k += 1
    # «рывок»: скачок скорости между соседними кадрами при движении, в долях медианной скорости
    dv = [abs(speeds[i] - speeds[i - 1]) / med for i in range(1, len(speeds)) if med and (speeds[i] > 5 or speeds[i - 1] > 5)]
    return {'file': path, 'fps': fps, 'frames': len(pos), 'hitch_frames': hitch,
            'moving_frames': sum(moving), 'median_speed_px_s': round(med, 1),
            'stops_inside_motion': stops,
            'speed_jump_p95': round(float(np.percentile(dv, 95)), 3) if dv else None,
            'speed_jump_max': round(float(max(dv)), 3) if dv else None,
            'speed': [None if x is None else round(x, 1) for x in v]}


if __name__ == '__main__':
    r = profile(sys.argv[1], sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else None
    if out:
        json.dump(r, open(out, 'w'), indent=0)
    print(json.dumps({k: v for k, v in r.items() if k != 'speed'}, ensure_ascii=False))
