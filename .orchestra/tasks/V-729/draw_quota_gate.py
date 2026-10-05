"""Render a phone-readable Claude quota gate chart from the V-721 profile."""
import csv
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from app.db import DB_PATH


TASK_DIR = Path(__file__).parent
V721_DIR = TASK_DIR.parent / "V-721"
OUTPUT = Path.home() / ".local/share/orchestra-videos/V-729/quota-gate.png"
KR = ZoneInfo("Asia/Krasnoyarsk")
UTC = timezone.utc
WIDTH, HEIGHT = 1920, 1200
BG = "#ffffff"
INK = "#17202b"
MUTED = "#506070"
GRID = "#dce2e8"
GRAY = "#777f87"
ORANGE = "#df7622"
GREEN = "#16824a"
BLUE = "#1769c2"
RED = "#c83b3b"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def read_cycle():
    with (V721_DIR / "weekly-windows.csv").open(newline="") as source:
        cycle = next(row for row in csv.DictReader(source) if row["reset_kr"].startswith("2026-10-06"))
    start = parse_time(cycle["window_start_kr"])
    reset = parse_time(cycle["reset_kr"])
    cutoff = parse_time(cycle["last_sample_kr"])

    db = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    rows = db.execute(
        """SELECT ts, seven_day_pct, seven_day_resets_at
           FROM usage_snapshots
           WHERE ts >= ? AND ts <= ? AND seven_day_pct IS NOT NULL
             AND seven_day_resets_at IS NOT NULL AND seven_day_resets_at != ''
           ORDER BY ts""",
        (start.isoformat(), cutoff.isoformat()),
    ).fetchall()
    db.close()

    data = []
    target_reset = round(reset.timestamp() / 60) * 60
    for row in rows:
        stamp = parse_time(row["ts"])
        reset_value = round(parse_time(row["seven_day_resets_at"]).timestamp() / 60) * 60
        if reset_value == target_reset:
            data.append((stamp, float(row["seven_day_pct"])))
    if not data:
        raise RuntimeError(f"No V-721-window snapshots found in usage_snapshots (selected {len(rows)}, target {target_reset}, first reset {round(parse_time(rows[0]['seven_day_resets_at']).timestamp() / 60) * 60})")
    return start, reset, cutoff, data


def baseline(moment: datetime, start: datetime, reset: datetime) -> float:
    progress = (moment - start).total_seconds() / (reset - start).total_seconds()
    return min(99.0, 10.0 + 91.0 * max(0.0, min(1.0, progress)))


def next_8am_line(moment: datetime, start: datetime, reset: datetime) -> float:
    local = moment.astimezone(KR)
    target_day = local.date() + (timedelta(days=1) if local.hour >= 8 else timedelta())
    target = datetime.combine(target_day, datetime.min.time().replace(hour=8), KR).astimezone(UTC)
    return baseline(min(target, reset), start, reset)


def eight_hours_ahead_with_night_hold(moment: datetime, start: datetime, reset: datetime) -> float:
    local = moment.astimezone(KR)
    if local.hour < 8:
        previous_midnight = datetime.combine(local.date(), datetime.min.time(), KR).astimezone(UTC)
        previous_day = previous_midnight - timedelta(seconds=1)
        return min(99.0, baseline(previous_day, start, reset) + 8 * 91.0 / 168.0)
    return min(99.0, baseline(moment, start, reset) + 8 * 91.0 / 168.0)


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD_PATH if bold else FONT_PATH, size)


def main():
    start, reset, cutoff, actual = read_cycle()
    start_kr, reset_kr, cutoff_kr = start.astimezone(KR), reset.astimezone(KR), cutoff.astimezone(KR)
    actual.sort()
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    draw.text((80, 42), "Квотный гейт Claude: неделя до сброса", fill=INK, font=font(42, True))
    draw.text((82, 100), "29 сентября, 14:00 → 6 октября, 14:00 · Красноярск · сброс во вторник", fill=MUTED, font=font(24))

    # The legend is intentionally prominent for phone viewing.
    legend_y = 163
    items = [(GRAY, "--", "Как сейчас"), (ORANGE, "-", "До конца ночи"),
             (GREEN, "-", "Компромисс +8 ч"), (BLUE, "-", "Реальный расход"),
             (RED, "-", "Стоп 99%")]
    positions = [82, 415, 820, 1220, 1600]
    for (color, style, label), x in zip(items, positions):
        for k in range(4):
            x1 = x + k * 16
            if style == "--" and k % 2:
                continue
            draw.line((x1, legend_y + 16, x1 + 12, legend_y + 16), fill=color, width=5)
        draw.text((x + 66, legend_y), label, fill=INK, font=font(23, True))

    left, top, right, bottom = 124, 236, 1825, 895
    plot_w, plot_h = right - left, bottom - top
    y_max = 105.0
    x_total = (reset - start).total_seconds()

    def xy(moment: datetime, value: float):
        x = left + (moment - start).total_seconds() / x_total * plot_w
        y = bottom - value / y_max * plot_h
        return round(x), round(y)

    # Night bands cover the local 00:00–08:00 period for every day.
    day = start_kr.date()
    while day <= reset_kr.date():
        night_start = datetime.combine(day, datetime.min.time(), KR).astimezone(UTC)
        night_end = night_start + timedelta(hours=8)
        a = max(start, night_start)
        b = min(reset, night_end)
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

    # Daily labels make the x-axis readable while retaining the local reset hour.
    for day_offset in range(8):
        tick = start + timedelta(days=day_offset)
        if tick > reset:
            tick = reset
        x, _ = xy(tick, 0)
        local_tick = tick.astimezone(KR)
        weekday = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")[local_tick.weekday()]
        label = f"{weekday} {local_tick:%d} · {local_tick:%H:%M}"
        draw.line((x, top, x, bottom), fill="#e8ebef", width=1)
        draw.text((x - 54, bottom + 14), label, fill=MUTED, font=font(18))
    draw.text((left + 12, bottom - 34), "ночью 00–08", fill="#66717d", font=font(18, True))

    times = [start + timedelta(minutes=10 * index) for index in range(math.ceil(x_total / 600) + 1)]
    times = [t for t in times if t <= reset] + [reset]
    base_pts = [xy(t, baseline(t, start, reset)) for t in times]
    orange_pts = [xy(t, next_8am_line(t, start, reset)) for t in times]
    green_pts = [xy(t, eight_hours_ahead_with_night_hold(t, start, reset)) for t in times]
    draw.line(base_pts, fill=GRAY, width=5, joint="curve")
    draw.line(orange_pts, fill=ORANGE, width=6, joint="curve")
    draw.line(green_pts, fill=GREEN, width=6, joint="curve")

    stop_y = xy(start, 99)[1]
    for x in range(left, right, 24):
        draw.line((x, stop_y, min(x + 12, right), stop_y), fill=RED, width=5)
    draw.rounded_rectangle((right - 208, stop_y - 42, right, stop_y - 7), radius=9, fill="#ffffff")
    draw.text((right - 198, stop_y - 40), "СТОП 99%", fill=RED, font=font(20, True))

    # The blue series is drawn as observed step changes, with no invented interpolation.
    blue_points = [xy(start, actual[0][1])]
    previous = actual[0][1]
    for moment, value in actual:
        point_x = xy(moment, previous)[0]
        blue_points.append((point_x, xy(moment, previous)[1]))
        blue_points.append(xy(moment, value))
        previous = value
    draw.line(blue_points, fill=BLUE, width=7, joint="curve")

    today = datetime(2026, 10, 5, tzinfo=KR).date()
    first_today_over = None
    for moment, usage in actual:
        if moment.astimezone(KR).date() == today and usage > baseline(moment, start, reset):
            first_today_over = (moment, usage, baseline(moment, start, reset))
            break
    if first_today_over:
        moment, usage, limit = first_today_over
        px, py = xy(moment, usage)
        draw.ellipse((px - 11, py - 11, px + 11, py + 11), fill=BLUE, outline="white", width=4)
        note_x, note_y = left + 14, top + 48
        draw.rounded_rectangle((note_x, note_y, note_x + 492, note_y + 78), radius=12, fill="#ffffff", outline=BLUE, width=3)
        draw.text((note_x + 14, note_y + 18), f"05.10 {moment.astimezone(KR):%H:%M}: {usage:.0f}% > {limit:.1f}% — воркеры ждут", fill=INK, font=font(18, True))

    last_time, last_usage = actual[-1]
    actual_end_x, actual_end_y = xy(last_time, last_usage)
    draw.ellipse((actual_end_x - 10, actual_end_y - 10, actual_end_x + 10, actual_end_y + 10), fill=BLUE, outline="white", width=4)
    orange_now = next_8am_line(last_time, start, reset)
    green_now = eight_hours_ahead_with_night_hold(last_time, start, reset)
    for y in range(actual_end_y + 12, bottom, 12):
        draw.line((actual_end_x, y, actual_end_x, min(y + 6, bottom)), fill=BLUE, width=2)

    draw.text((80, 965), "Как читать: если синяя выше серой — новые ходы воркеров ждут; оркестраторы работают всегда.", fill=INK, font=font(24, True))
    draw.text((80, 1005), f"05.10 {last_time.astimezone(KR):%H:%M}: факт {last_usage:.0f}%; линии были бы: серая {baseline(last_time, start, reset):.1f}%, зелёная {green_now:.1f}%, оранжевая {orange_now:.1f}%.", fill=INK, font=font(20, True))
    draw.text((80, 1047), "Оранжевая/зелёная показывают лишь больший порог допуска. При другом гейте расход мог бы стать другим — это прикидка, не прогноз.", fill=MUTED, font=font(20))
    draw.text((80, 1087), "Синяя заканчивается на последнем снимке 05.10 в " + cutoff_kr.strftime("%H:%M") + "; после него данных нет.", fill=MUTED, font=font(20))
    draw.text((80, 1138), "Источник: usage_snapshots · окно 29.09–06.10 · формулы и граница периода — V-721", fill=MUTED, font=font(18))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, format="PNG", optimize=True)
    print(f"saved={OUTPUT}")
    print(f"size={WIDTH}x{HEIGHT} snapshots={len(actual)} cutoff_kr={cutoff_kr.isoformat()}")
    print(f"last={last_time.astimezone(KR).isoformat()} actual={last_usage:.1f} baseline={baseline(last_time, start, reset):.3f} green={green_now:.3f} orange={orange_now:.3f}")
    if first_today_over:
        print(f"first_today_over={first_today_over[0].astimezone(KR).isoformat()} actual={first_today_over[1]:.1f} baseline={first_today_over[2]:.3f}")


if __name__ == "__main__":
    main()
