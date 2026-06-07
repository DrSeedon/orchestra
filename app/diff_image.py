"""Render Edit/Write/Read/Grep tool output as PNG images using Pillow."""
import io
import re

from PIL import Image, ImageDraw, ImageFont


_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

MAX_LINES_EDIT = 50
MAX_LINES_WRITE = 30


def _load_fonts():
    try:
        return (
            ImageFont.truetype(_FONT_PATH, 13),
            ImageFont.truetype(_FONT_PATH, 11),
        )
    except Exception:
        f = ImageFont.load_default()
        return f, f


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

    # pair del+add for inline diff
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

LINE_H = 22
GUTTER_W = 24
PAD_X = 10
HEADER_H = 26


def _measure_max_w(font, lines_text: list[str]) -> int:
    max_w = 700
    for text in lines_text:
        tw = font.getlength(text) + GUTTER_W + PAD_X * 2 + 20
        max_w = max(max_w, int(tw))
    return min(max_w, 1200)


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
        if typ in ('del', 'add'):
            draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
            draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
            draw.text((8, y + 3), _SIGN[typ], fill=_CLR_G[typ], font=font)
            parts = _inline_diff(text, other)
            x = GUTTER_W + PAD_X
            for part_text, is_hl in parts:
                if is_hl:
                    tw = font.getlength(part_text)
                    draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
                draw.text((x, y + 3), part_text, fill=_CLR[typ], font=font)
                x += font.getlength(part_text)
        else:
            draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(15, 23, 42))
            draw.text((8, y + 3), ' ', fill=_CLR_G['ctx'], font=font)
            draw.text((GUTTER_W + PAD_X, y + 3), text, fill=_CLR['ctx'], font=font)
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
        draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
        draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
        draw.text((8, y + 3), '+', fill=(74, 222, 128), font=font)
        draw.text((GUTTER_W + PAD_X, y + 3), text, fill=(187, 247, 208), font=font)
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
    lines_text = content.split('\n')[:MAX_LINES_READ]
    font, font_small = _load_fonts()

    max_w = 700
    for text in lines_text:
        tw = font.getlength(text) + _GUTTER_W_READ + PAD_X * 2 + 20
        max_w = max(max_w, int(tw))
    max_w = min(max_w, 1200)

    img_h = HEADER_H + LINE_H * len(lines_text) + 4
    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
    draw.text((PAD_X, 5), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)

    y = HEADER_H + 2
    for i, text in enumerate(lines_text):
        line_no = str(offset + i + 1)
        draw.rectangle([0, y, _GUTTER_W_READ, y + LINE_H], fill=(15, 23, 42))
        nw = font_small.getlength(line_no)
        draw.text((_GUTTER_W_READ - nw - 4, y + 4), line_no, fill=(71, 85, 105), font=font_small)
        draw.text((_GUTTER_W_READ + PAD_X, y + 3), text, fill=(226, 232, 240), font=font)
        y += LINE_H

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_grep(pattern: str, results: list) -> bytes:
    """Render Grep results as PNG with match highlighting.

    results: list of (file, line_no, text, match_start, match_end)
    """
    font, font_small = _load_fonts()
    display = results[:MAX_LINES_GREP]

    max_w = 700
    for f, ln, text, ms, me in display:
        tw = font.getlength(f"{f}:{ln}: {text}") + PAD_X * 2 + 20
        max_w = max(max_w, int(tw))
    max_w = min(max_w, 1200)

    img_h = HEADER_H + LINE_H * len(display) + 4
    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
    draw.text((PAD_X, 5), f"🔍 grep: {pattern} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)

    y = HEADER_H + 2
    for f, ln, text, ms, me in display:
        prefix = f"{f}:{ln}: "
        draw.text((PAD_X, y + 3), prefix, fill=(100, 116, 139), font=font)
        x = PAD_X + font.getlength(prefix)
        before = text[:ms]
        match = text[ms:me]
        after = text[me:]
        draw.text((x, y + 3), before, fill=(226, 232, 240), font=font)
        x += font.getlength(before)
        tw = font.getlength(match)
        draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
        draw.text((x, y + 3), match, fill=(253, 224, 71), font=font)
        x += tw
        draw.text((x, y + 3), after, fill=(226, 232, 240), font=font)
        y += LINE_H

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


MAX_LINES_BASH = 30


def render_bash(command: str, output: str) -> bytes:
    """Render Bash tool — macOS-style terminal with command and output."""
    LINE_H, PAD_X, HEADER_H = 22, 12, 28
    font, font_small = _load_fonts()

    out_lines_all = output.split('\n')
    lines = out_lines_all[:MAX_LINES_BASH]
    truncated = len(out_lines_all) > MAX_LINES_BASH

    max_w = 650
    for text in [command] + lines:
        tw = font.getlength(text) + PAD_X * 2 + 30
        max_w = max(max_w, int(tw))
    max_w = min(max_w, 1200)

    extra = 1 if truncated else 0
    img_h = HEADER_H + LINE_H * (len(lines) + 1 + extra) + 6
    img = Image.new('RGB', (max_w, img_h), (13, 17, 23))
    draw = ImageDraw.Draw(img)

    # macOS-style header with traffic lights
    draw.rectangle([0, 0, max_w, HEADER_H], fill=(30, 30, 30))
    draw.ellipse([10, 8, 22, 20], fill=(255, 95, 86))
    draw.ellipse([28, 8, 40, 20], fill=(255, 189, 46))
    draw.ellipse([46, 8, 58, 20], fill=(39, 201, 63))
    draw.text((70, 7), "bash", fill=(150, 150, 150), font=font_small)

    y = HEADER_H + 4
    draw.text((PAD_X, y + 3), "$ ", fill=(74, 222, 128), font=font)
    draw.text((PAD_X + font.getlength("$ "), y + 3), command, fill=(226, 232, 240), font=font)
    y += LINE_H

    for text in lines:
        draw.text((PAD_X, y + 3), text, fill=(180, 190, 200), font=font)
        y += LINE_H

    if truncated:
        draw.text((PAD_X, y + 3), f"... +{len(out_lines_all) - MAX_LINES_BASH} more lines", fill=(100, 116, 139), font=font_small)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
