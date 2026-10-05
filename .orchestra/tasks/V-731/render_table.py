"""Render the V-731 model comparison as a large, phone-readable PNG table."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).with_name("table.png")
W, H = 2880, 1900
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
INK, MUTED, RULE = "#182430", "#526171", "#c9d2dc"
HEAD, ALT, BG = "#e8eef5", "#f6f8fb", "#ffffff"

headers = ["Модель", "API-equivalent, $", "Токены", "Ходы / usage", "Время агента", "Ролик · Deepgram · кадры", "MP4"]
rows = [
    ["Sonnet 5.5", "$7.1693", "Вход 25,031,106\nКэш 25,031,012\n(read 24,898,210; write 132,802)\nВыход 72,037 · reasoning — нет данных", "7\nturn_usage", "≈1 ч 59 мин\nдоставка → последний учтённый ход\n(в отчёте также ≈3 ч agent-time)", "403.6 с\nRecall 97.96% overall\nmin: нет данных\n≥40 кадров", "/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/course-pilot/.orchestra/tasks/V-170/video3d/v2/out/final.mp4"],
    ["Luna", "$0.3308", "Вход 21,582,342\nКэш 21,076,352 (read)\nКэш-запись 0\nВыход 138,884 · reasoning — нет данных", "11\nturn_usage", "≈2 ч 13 мин\nначало подготовки →\nфинальная проверка", "251.33 с\nRecall среднее 99.5%\nминимум 93%\n30 кадров", "/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/bench3d-luna/.orchestra/tasks/V-170/video3d-v2/out/lesson.mp4"],
    ["Opus 5.5", "$6.1887", "Вход 12,710,984\nКэш 12,710,852\n(read 12,454,038; write 256,814)\nВыход 74,423 · reasoning — нет данных", "3\nturn_usage", "≈1 ч 21 мин\n14:19 → отчёт 15:40\n(bench-opus.md)", "289.3 с\nRecall среднее/мин. 100%\n(без нормализации 94.7%)\n15 кадров", "/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/bench3d-opus/.orchestra/tasks/V-170/video3d-v2-opus/out/rashozhdenie-v2-opus.mp4"],
    ["GPT-6 Sol", "$2.5012\nbackend_codex.py", "Вход 8,991,255\nКэш 8,775,168\nКэш-запись 0\nВыход 31,395 · reasoning 11,285", "1\nturn.completed", "43 мин 51 с\nstarted.txt → finished.txt", "195.413 с\nRecall среднее 94.4%\nминимум 89.7%\n17 кадров", "/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/bench3d-sol/.orchestra/tasks/V-170/video3d-v2/out/video3d-v2.mp4"],
    ["GPT-6.1 Sol", "$4.0223\nDevDay, внешний тариф", "Вход 18,534,980\nКэш 18,129,280\nКэш-запись 0\nВыход 139,797 · reasoning 96,186", "1\nturn.completed", "1 ч 34 мин 46 с\nstarted.txt → finished.txt", "507.458 с\nRecall среднее 99.70%\nминимум 97.06%\n54 кадра", "/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/bench3d-sol61/.orchestra/tasks/V-170/video3d/v2/out/signals-v2-sol61.mp4"],
]


def f(size, bold=False, mono=False):
    return ImageFont.truetype(MONO if mono else BOLD if bold else FONT, size)


def wrap_text(text, font_obj, max_width):
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = word if not line else line + " " + word
            if draw.textlength(candidate, font=font_obj) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            while draw.textlength(word, font=font_obj) > max_width:
                fit = 1
                for index in range(2, len(word) + 1):
                    if draw.textlength(word[:index], font=font_obj) > max_width:
                        break
                    fit = index
                lines.append(word[:fit])
                word = word[fit:]
            line = word
        if line:
            lines.append(line)
    return lines


image = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(image)
draw.text((60, 38), "Пять прогонов: учебный 3D-ролик v2", fill=INK, font=f(42, True))
draw.text((62, 96), "API-equivalent · вход и кэш · проверка ролика · время работы · итоговый MP4", fill=MUTED, font=f(24))

margin, top = 48, 155
widths = [300, 245, 650, 200, 320, 415, 650]
row_h, head_h = 275, 78
x_positions = [margin]
for width in widths[:-1]:
    x_positions.append(x_positions[-1] + width)
table_w = sum(widths)

draw.rounded_rectangle((margin, top, margin + table_w, top + head_h), radius=12, fill=HEAD)
for j, title in enumerate(headers):
    x = x_positions[j] + 16
    draw.text((x, top + 22), title, fill=INK, font=f(21, True))
    if j:
        draw.line((x_positions[j], top + 10, x_positions[j], top + head_h - 10), fill=RULE, width=2)

for i, row in enumerate(rows):
    y0 = top + head_h + i * row_h
    y1 = y0 + row_h
    draw.rectangle((margin, y0, margin + table_w, y1), fill=ALT if i % 2 == 0 else BG)
    draw.line((margin, y1, margin + table_w, y1), fill=RULE, width=2)
    for j, value in enumerate(row):
        x = x_positions[j] + 15
        max_w = widths[j] - 30
        if j == 0:
            ft = f(26, True)
        elif j == 6:
            ft = f(18, mono=True)
        else:
            ft = f(20, bold=(j == 1))
        wrapped = wrap_text(value, ft, max_w)
        line_h = 27 if j == 6 else 29
        y = y0 + 22
        if j in (0, 1, 3):
            y += max(0, (row_h - len(wrapped) * line_h) // 2 - 22)
        for line in wrapped:
            draw.text((x, y), line, fill=INK if j != 1 else "#163f69", font=ft)
            y += line_h
        if j:
            draw.line((x_positions[j], y0 + 10, x_positions[j], y1 - 10), fill=RULE, width=1)

foot_y = top + head_h + len(rows) * row_h + 24
draw.text((60, foot_y), "Прогоны шли параллельно; машину делили. Рендер Opus — примерно в 4 раза медленнее v1.", fill=INK, font=f(21, True))
draw.text((60, foot_y + 37), "Sonnet повторно использовал сделанный им v1; остальные четыре прогона начаты с 43ae572.", fill=MUTED, font=f(20))
draw.text((60, foot_y + 73), "Оба Sol — codex exec без инструментов Orchestra. GPT-6.1 Sol оценён по внешнему DevDay тарифу.", fill=MUTED, font=f(20))
draw.text((60, foot_y + 109), "Reasoning показан отдельно там, где run.jsonl его сообщает; он входит в output и второй раз не считается.", fill=MUTED, font=f(20))
draw.text((60, foot_y + 151), "Источник подробностей и оговорок: V-731/report.md", fill=MUTED, font=f(18))

image.save(OUT, format="PNG", optimize=True)
print(f"{OUT} {W}x{H}")
