"""Render a smooth day/night Claude quota line using V-721 data."""
import math
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from draw_quota_gate import (
    BG, BLUE, FONT_BOLD_PATH, FONT_PATH, GRAY, GREEN, GRID, HEIGHT, INK,
    KR, MUTED, RED, UTC, WIDTH, baseline, eight_hours_ahead_with_night_hold,
    read_cycle,
)


OUTPUT = Path.home() / ".local/share/orchestra-videos/V-729/quota-gate-smooth.png"
PURPLE = "#7b35a6"
DAY_RATE = 89.0 * (1 - 0.057) / (7 * 16)
NIGHT_RATE = 89.0 * 0.057 / (7 * 8)
CURRENT_RATE = 91.0 / 168.0


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD_PATH if bold else FONT_PATH, size)


def smooth_line(moment: datetime, start: datetime) -> float:
    cursor = start
    increase = 0.0
    while cursor < moment:
        local = cursor.astimezone(KR)
        boundary = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        edge = min(boundary, moment)
        rate = DAY_RATE if 8 <= local.hour < 24 else NIGHT_RATE
        increase += (edge - cursor).total_seconds() / 3600 * rate
        cursor = edge
    return 10.0 + increase


def smooth_day_checkpoints(start: datetime, reset: datetime):
    local_start = start.astimezone(KR)
    day = local_start.date() + timedelta(days=1)
    checks = []
    while day <= reset.astimezone(KR).date():
        moment = datetime.combine(day, datetime.min.time(), KR).astimezone(UTC)
        if moment <= reset:
            checks.append((moment, smooth_line(moment, start) - baseline(moment, start, reset)))
        day += timedelta(days=1)
    return checks


def main():
    start, reset, cutoff, actual = read_cycle()
    start_kr, reset_kr, cutoff_kr = start.astimezone(KR), reset.astimezone(KR), cutoff.astimezone(KR)
    actual.sort()

    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.text((80, 42), "Квотный гейт Claude: плавный дневной подъём", fill=INK, font=font(42, True))
    draw.text((82, 100), "29 сентября, 14:00 → 6 октября, 14:00 · Красноярск · сброс во вторник", fill=MUTED, font=font(24))

    legend_y = 163
    items = [(GRAY, "--", "Как сейчас"), (GREEN, "-", "Прежняя ступень +8 ч"),
             (PURPLE, "-", "Плавно: день/ночь"), (BLUE, "-", "Реальный расход"),
             (RED, "-", "Стоп 99%")]
    positions = [82, 390, 890, 1325, 1640]
    for (color, style, label), x in zip(items, positions):
        for k in range(4):
            x1 = x + k * 16
            if style == "--" and k % 2:
                continue
            draw.line((x1, legend_y + 16, x1 + 12, legend_y + 16), fill=color, width=5)
        draw.text((x + 66, legend_y), label, fill=INK, font=font(22, True))

    left, top, right, bottom = 124, 236, 1825, 895
    plot_w, plot_h = right - left, bottom - top
    x_total = (reset - start).total_seconds()

    def xy(moment: datetime, value: float):
        x = left + (moment - start).total_seconds() / x_total * plot_w
        y = bottom - value / 105.0 * plot_h
        return round(x), round(y)

    day = start_kr.date()
    while day <= reset_kr.date():
        night_start = datetime.combine(day, datetime.min.time(), KR).astimezone(UTC)
        night_end = night_start + timedelta(hours=8)
        a, b = max(start, night_start), min(reset, night_end)
        if b > a:
            xa, _ = xy(a, 0)
            xb, _ = xy(b, 0)
            draw.rectangle((xa, top, xb, bottom), fill="#eef0f2")
        day += timedelta(days=1)

    for pct in range(0, 101, 10):
        y = xy(start, pct)[1]
        draw.line((left, y, right, y), fill=GRID, width=2)
        draw.text((left - 76, y - 16), f"{pct}%", fill=MUTED, font=font(20))
    draw.rectangle((left, top, right, bottom), outline="#7f8a96", width=2)
    draw.text((left, top - 34), "% недельного лимита", fill=INK, font=font(22, True))

    for day_offset in range(8):
        tick = min(start + timedelta(days=day_offset), reset)
        x, _ = xy(tick, 0)
        local_tick = tick.astimezone(KR)
        weekday = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")[local_tick.weekday()]
        label = f"{weekday} {local_tick:%d} · {local_tick:%H:%M}"
        draw.line((x, top, x, bottom), fill="#e8ebef", width=1)
        draw.text((x - 54, bottom + 14), label, fill=MUTED, font=font(18))
    draw.text((left + 12, bottom - 34), "ночью 00–08", fill="#66717d", font=font(18, True))

    samples = [start + timedelta(minutes=5 * i) for i in range(math.ceil(x_total / 300) + 1)]
    samples = [moment for moment in samples if moment <= reset] + [reset]
    gray_pts = [xy(moment, baseline(moment, start, reset)) for moment in samples]
    green_pts = [xy(moment, eight_hours_ahead_with_night_hold(moment, start, reset)) for moment in samples]
    purple_pts = [xy(moment, smooth_line(moment, start)) for moment in samples]
    draw.line(gray_pts, fill=GRAY, width=5, joint="curve")
    draw.line(green_pts, fill=GREEN, width=5, joint="curve")
    draw.line(purple_pts, fill=PURPLE, width=8, joint="curve")

    stop_y = xy(start, 99)[1]
    for x in range(left, right, 24):
        draw.line((x, stop_y, min(x + 12, right), stop_y), fill=RED, width=5)
    draw.rounded_rectangle((right - 208, stop_y - 42, right, stop_y - 7), radius=9, fill="#ffffff")
    draw.text((right - 198, stop_y - 40), "СТОП 99%", fill=RED, font=font(20, True))

    blue_points = [xy(start, actual[0][1])]
    previous = actual[0][1]
    for moment, value in actual:
        px = xy(moment, previous)[0]
        blue_points.append((px, xy(moment, previous)[1]))
        blue_points.append(xy(moment, value))
        previous = value
    draw.line(blue_points, fill=BLUE, width=7, joint="curve")

    first_today_over = None
    for moment, usage in actual:
        if moment.astimezone(KR).date().isoformat() == "2026-10-05" and usage > baseline(moment, start, reset):
            first_today_over = moment, usage, baseline(moment, start, reset)
            break
    if first_today_over:
        moment, usage, limit = first_today_over
        px, py = xy(moment, usage)
        draw.ellipse((px - 11, py - 11, px + 11, py + 11), fill=BLUE, outline="white", width=4)
        note_x, note_y = left + 14, top + 48
        draw.rounded_rectangle((note_x, note_y, note_x + 492, note_y + 78), radius=12, fill="#ffffff", outline=BLUE, width=3)
        draw.text((note_x + 14, note_y + 18), f"05.10 {moment.astimezone(KR):%H:%M}: {usage:.0f}% > {limit:.1f}% — воркеры ждут", fill=INK, font=font(18, True))

    last_time, last_usage = actual[-1]
    last_x, last_y = xy(last_time, last_usage)
    draw.ellipse((last_x - 10, last_y - 10, last_x + 10, last_y + 10), fill=BLUE, outline="white", width=4)
    for y in range(last_y + 12, bottom, 12):
        draw.line((last_x, y, last_x, min(y + 6, bottom)), fill=BLUE, width=2)

    checks = smooth_day_checkpoints(start, reset)
    last_full_day = next((delta for moment, delta in reversed(checks) if moment < reset), 0.0)
    avg_midnight_extra = sum(delta for _, delta in checks) / len(checks)
    day_extra = (DAY_RATE - CURRENT_RATE) * 16
    night_offset = (NIGHT_RATE - CURRENT_RATE) * 8

    draw.text((80, 965), "Как читать: если синяя выше серой — новые ходы воркеров ждут; оркестраторы работают всегда.", fill=INK, font=font(24, True))
    draw.text((80, 1004), f"Фиолетовая: {DAY_RATE:.3f} п.п./ч днём 08–24 и {NIGHT_RATE:.3f} ночью 00–08 (ночь — доля расхода 5,7%).", fill=PURPLE, font=font(20, True))
    draw.text((80, 1044), f"К полуночи 06.10 прибавка к серой {last_full_day:+.2f} п.п. (среднее полуночных срезов {avg_midnight_extra:+.2f}); дневной разгон даёт +{day_extra:.2f}, медленная ночь −{abs(night_offset):.2f} п.п.", fill=INK, font=font(18, True))
    draw.text((80, 1085), "Это уровень квотной линии, не прогноз расхода. Синяя — фактические снимки; после 05.10 " + cutoff_kr.strftime("%H:%M") + " данных нет.", fill=MUTED, font=font(20))
    draw.text((80, 1138), "Источник: usage_snapshots · окно 29.09–06.10 · расчёты и границы — V-721", fill=MUTED, font=font(18))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, format="PNG", optimize=True)
    print(f"saved={OUTPUT}")
    print(f"size={WIDTH}x{HEIGHT} snapshots={len(actual)} cutoff_kr={cutoff_kr.isoformat()}")
    print(f"rates_day={DAY_RATE:.9f} rates_night={NIGHT_RATE:.9f} total_delta={DAY_RATE*112+NIGHT_RATE*56:.9f}")
    print(f"last_snapshot={last_time.astimezone(KR).isoformat()} actual={last_usage:.1f} smooth={smooth_line(last_time,start):.3f} baseline={baseline(last_time,start,reset):.3f}")
    print(f"last_full_day_extra={last_full_day:.6f} avg_midnight_extra={avg_midnight_extra:.6f} day_gain_vs_baseline={day_extra:.6f} night_offset_vs_baseline={night_offset:.6f}")
    if first_today_over:
        print(f"first_today_over={first_today_over[0].astimezone(KR).isoformat()} actual={first_today_over[1]:.1f} baseline={first_today_over[2]:.3f}")


if __name__ == "__main__":
    main()
