"""Render Edit/Write/Read/Grep tool output as PNG images using Pillow."""
import io
import re

from PIL import Image, ImageDraw, ImageFont


_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

MAX_LINES_EDIT = 50
MAX_LINES_WRITE = 30


WRAP_COLS = 90


def _load_fonts():
    try:
        return (
            ImageFont.truetype(_FONT_PATH, 16),
            ImageFont.truetype(_FONT_PATH, 13),
        )
    except Exception:
        f = ImageFont.load_default()
        return f, f


def _wrap_line(text: str, cols: int = WRAP_COLS) -> list[str]:
    if len(text) <= cols:
        return [text]
    parts = []
    while len(text) > cols:
        parts.append(text[:cols])
        text = text[cols:]
    if text:
        parts.append(text)
    return parts


def _short_path(file_path: str) -> str:
    p = file_path
    p = re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', p)
    for prefix in ('/mnt/data/Projects/Python/', '/home/'):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def _lcs_diff(a: list[str], b: list[str]):
    """LCS-based diff. Returns list of ('ctx'|'add'|'del', line_a, line_b_or_None)."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = dp[i-1][j-1] + 1 if a[i-1] == b[j-1] else max(dp[i-1][j], dp[i][j-1])
    raw = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and a[i-1] == b[j-1]:
            raw.append(('ctx', a[i-1])); i -= 1; j -= 1
        elif j > 0 and (i == 0 or dp[i][j-1] >= dp[i-1][j]):
            raw.append(('add', b[j-1])); j -= 1
        else:
            raw.append(('del', a[i-1])); i -= 1
    raw.reverse()

    # Pair consecutive del+add into linked pairs so _inline_diff can highlight
    # the exact characters that changed (not just the whole line)
    lines = []
    idx = 0
    while idx < len(raw):
        if raw[idx][0] == 'del' and idx + 1 < len(raw) and raw[idx+1][0] == 'add':
            lines.append(('del', raw[idx][1], raw[idx+1][1]))
            lines.append(('add', raw[idx+1][1], raw[idx][1]))
            idx += 2
        else:
            lines.append((raw[idx][0], raw[idx][1], None))
            idx += 1
    return lines


def _inline_diff(line: str, other: str | None):
    """Return list of (text, is_highlighted) for inline char diff."""
    if other is None:
        return [(line, False)]
    pre = 0
    while pre < min(len(line), len(other)) and line[pre] == other[pre]:
        pre += 1
    suf = 0
    while suf < min(len(line) - pre, len(other) - pre) and line[-(suf+1)] == other[-(suf+1)]:
        suf += 1
    end = len(line) - suf if suf else len(line)
    parts = []
    if pre > 0:
        parts.append((line[:pre], False))
    if end > pre:
        parts.append((line[pre:end], True))
    if suf > 0:
        parts.append((line[end:], False))
    return parts or [(line, False)]


_BG = {'del': (50, 20, 20), 'add': (15, 40, 25)}
_BG_G = {'del': (70, 25, 25), 'add': (20, 55, 30)}
_CLR = {'del': (254, 202, 202), 'add': (187, 247, 208), 'ctx': (148, 163, 184)}
_CLR_G = {'del': (248, 113, 113), 'add': (74, 222, 128), 'ctx': (71, 85, 105)}
_HL = {'del': (120, 40, 40), 'add': (15, 70, 40)}
_SIGN = {'del': '−', 'add': '+', 'ctx': ' '}

LINE_H = 26
GUTTER_W = 28
PAD_X = 12
HEADER_H = 30


def _measure_max_w(_font, _lines_text: list[str]) -> int:
    return 800


def _draw_header(draw, max_w: int, label: str, font_small):
    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
    draw.text((PAD_X, 5), label, fill=(100, 116, 139), font=font_small)


def _draw_truncated(draw, y: int, remaining: int, font_small):
    draw.text((GUTTER_W + PAD_X, y + 3), f"... +{remaining} more lines", fill=(100, 116, 139), font=font_small)


def render_edit_diff(file_path: str, old_string: str, new_string: str) -> bytes | None:
    """Render Edit diff as PNG. Returns PNG bytes or None if no diff."""
    if old_string == new_string:
        return None

    a = old_string.split('\n')
    b = new_string.split('\n')
    lines = _lcs_diff(a, b)

    # Skip if only ctx lines (shouldn't happen but guard)
    if all(t == 'ctx' for t, _, _ in lines):
        return None

    font, font_small = _load_fonts()
    max_w = _measure_max_w(font, [text for _, text, _ in lines])

    display = lines[:MAX_LINES_EDIT]
    truncated = len(lines) > MAX_LINES_EDIT
    extra = 1 if truncated else 0

    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    _draw_header(draw, max_w, f"✏️ {_short_path(file_path)}", font_small)

    y = HEADER_H + 2
    for typ, text, other in display:
        text = text[:WRAP_COLS]
        if other is not None:
            other = other[:WRAP_COLS]
        if typ in ('del', 'add'):
            draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
            draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
            draw.text((10, y + 4), _SIGN[typ], fill=_CLR_G[typ], font=font)
            parts = _inline_diff(text, other)
            x = GUTTER_W + PAD_X
            for part_text, is_hl in parts:
                if is_hl:
                    tw = font.getlength(part_text)
                    draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
                draw.text((x, y + 4), part_text, fill=_CLR[typ], font=font)
                x += font.getlength(part_text)
        else:
            draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(15, 23, 42))
            draw.text((10, y + 4), ' ', fill=_CLR_G['ctx'], font=font)
            draw.text((GUTTER_W + PAD_X, y + 4), text, fill=_CLR['ctx'], font=font)
        y += LINE_H

    if truncated:
        _draw_truncated(draw, y, len(lines) - MAX_LINES_EDIT, font_small)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_write_diff(file_path: str, content: str) -> bytes:
    """Render Write (new file) as PNG. All lines green."""
    lines_text = content.split('\n')
    font, font_small = _load_fonts()

    display = lines_text[:MAX_LINES_WRITE]
    truncated = len(lines_text) > MAX_LINES_WRITE
    extra = 1 if truncated else 0

    max_w = _measure_max_w(font, display)
    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    _draw_header(draw, max_w, f"📄 {_short_path(file_path)} (new)", font_small)

    y = HEADER_H + 2
    for text in display:
        text = text[:WRAP_COLS]
        draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
        draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
        draw.text((10, y + 4), '+', fill=(74, 222, 128), font=font)
        draw.text((GUTTER_W + PAD_X, y + 4), text, fill=(187, 247, 208), font=font)
        y += LINE_H

    if truncated:
        _draw_truncated(draw, y, len(lines_text) - MAX_LINES_WRITE, font_small)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


MAX_LINES_READ = 25
MAX_LINES_GREP = 20
_GUTTER_W_READ = 40  # wider for line numbers


def render_read(file_path: str, content: str, offset: int = 0) -> bytes:
    """Render Read tool result as PNG with line numbers."""
    raw_lines = content.split('\n')
    font, font_small = _load_fonts()

    display = []  # (line_no_str, text)
    for i, ln in enumerate(raw_lines):
        parts = _wrap_line(ln)
        for j, p in enumerate(parts):
            display.append((str(offset + i + 1) if j == 0 else "", p))
        if len(display) >= MAX_LINES_READ:
            break
    display = display[:MAX_LINES_READ]
    truncated = len(raw_lines) > MAX_LINES_READ
    extra = 1 if truncated else 0

    max_w = 800
    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
    draw.text((PAD_X, 7), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)

    y = HEADER_H + 2
    for line_no, text in display:
        draw.rectangle([0, y, _GUTTER_W_READ, y + LINE_H], fill=(15, 23, 42))
        if line_no:
            nw = font_small.getlength(line_no)
            draw.text((_GUTTER_W_READ - nw - 4, y + 5), line_no, fill=(71, 85, 105), font=font_small)
        draw.text((_GUTTER_W_READ + PAD_X, y + 4), text, fill=(226, 232, 240), font=font)
        y += LINE_H

    if truncated:
        _draw_truncated(draw, y, len(raw_lines) - MAX_LINES_READ, font_small)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_grep(pattern: str, results: list) -> bytes:
    """Render Grep results as PNG with match highlighting.

    results: list of (file, line_no, text, match_start, match_end)
    """
    font, font_small = _load_fonts()
    display = results[:MAX_LINES_GREP]

    max_w = 800
    img_h = HEADER_H + LINE_H * len(display) + 4
    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
    draw.text((PAD_X, 7), f"🔍 grep: {pattern[:40]} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)

    y = HEADER_H + 2
    for f, ln, text, ms, me in display:
        prefix = f"{_short_path(f)}:{ln}: "
        full_line = prefix + text
        if len(full_line) > WRAP_COLS:
            text = text[:WRAP_COLS - len(prefix)]
            if me > len(text):
                me = len(text)
        draw.text((PAD_X, y + 4), prefix, fill=(100, 116, 139), font=font)
        x = PAD_X + font.getlength(prefix)
        before = text[:ms]
        match = text[ms:me]
        after = text[me:]
        draw.text((x, y + 4), before, fill=(226, 232, 240), font=font)
        x += font.getlength(before)
        tw = font.getlength(match)
        draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
        draw.text((x, y + 4), match, fill=(253, 224, 71), font=font)
        x += tw
        draw.text((x, y + 4), after, fill=(226, 232, 240), font=font)
        y += LINE_H

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


MAX_LINES_BASH = 30


def render_bash(command: str, output: str) -> bytes:
    """Render Bash tool — macOS-style terminal with command and output."""
    _LH, _PX, _HH = 26, 12, 32
    font, font_small = _load_fonts()

    raw_lines = output.split('\n')
    wrapped = []
    for ln in raw_lines:
        wrapped.extend(_wrap_line(ln))
        if len(wrapped) >= MAX_LINES_BASH:
            break
    display = wrapped[:MAX_LINES_BASH]
    truncated = len(raw_lines) > MAX_LINES_BASH or len(wrapped) > MAX_LINES_BASH
    cmd_wrapped = _wrap_line(command)

    max_w = 800
    extra = 1 if truncated else 0
    total_lines = len(cmd_wrapped) + len(display) + extra
    img_h = _HH + _LH * total_lines + 8
    img = Image.new('RGB', (max_w, img_h), (13, 17, 23))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, max_w, _HH], fill=(30, 30, 30))
    draw.ellipse([12, 10, 24, 22], fill=(255, 95, 86))
    draw.ellipse([30, 10, 42, 22], fill=(255, 189, 46))
    draw.ellipse([48, 10, 60, 22], fill=(39, 201, 63))
    draw.text((72, 8), "bash", fill=(150, 150, 150), font=font_small)

    y = _HH + 4
    for i, part in enumerate(cmd_wrapped):
        prefix = "$ " if i == 0 else "  "
        draw.text((_PX, y + 3), prefix, fill=(74, 222, 128), font=font)
        draw.text((_PX + font.getlength(prefix), y + 3), part, fill=(226, 232, 240), font=font)
        y += _LH

    for text in display:
        draw.text((_PX, y + 3), text, fill=(180, 190, 200), font=font)
        y += _LH

    if truncated:
        remaining = len(raw_lines) - MAX_LINES_BASH
        draw.text((_PX, y + 3), f"... +{max(remaining, 0)} more lines", fill=(100, 116, 139), font=font_small)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
