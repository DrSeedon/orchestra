# Candidate cand-08

## ORIGIN commit 83d824805f (2026-06-16): fix: readable bash/read/grep result images — bigger font, word wrap, line limit
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/diff_image.py b/app/diff_image.py
index 504d18fe0..e77a99de7 100644
--- a/app/diff_image.py
+++ b/app/diff_image.py
@@ -6,29 +6,42 @@ from PIL import Image, ImageDraw, ImageFont
 
 
 _FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
 
 MAX_LINES_EDIT = 50
 MAX_LINES_WRITE = 30
 
 
+WRAP_COLS = 90
+
+
 def _load_fonts():
     try:
         return (
+            ImageFont.truetype(_FONT_PATH, 16),
             ImageFont.truetype(_FONT_PATH, 13),
-            ImageFont.truetype(_FONT_PATH, 11),
         )
     except Exception:
-        # PIL may not be installed or font missing — graceful degradation with
-        # the built-in bitmap font rather than crashing TG diff rendering
         f = ImageFont.load_default()
         return f, f
 
 
+def _wrap_line(text: str, cols: int = WRAP_COLS) -> list[str]:
+    if len(text) <= cols:
+        return [text]
+    parts = []
+    while len(text) > cols:
+        parts.append(text[:cols])
+        text = text[cols:]
+    if text:
+        parts.append(text)
+    return parts
+
+
 def _short_path(file_path: str) -> str:
     p = file_path
     p = re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', p)
     for prefix in ('/mnt/data/Projects/Python/', '/home/'):
         if p.startswith(prefix):
             p = p[len(prefix):]
     return p
 
@@ -89,28 +102,24 @@ def _inline_diff(line: str, other: str | None):
 
 _BG = {'del': (50, 20, 20), 'add': (15, 40, 25)}
 _BG_G = {'del': (70, 25, 25), 'add': (20, 55, 30)}
 _CLR = {'del': (254, 202, 202), 'add': (187, 247, 208), 'ctx': (148, 163, 184)}
 _CLR_G = {'del': (248, 113, 113), 'add': (74, 222, 128), 'ctx': (71, 85, 105)}
 _HL = {'del': (120, 40, 40), 'add': (15, 70, 40)}
 _SIGN = {'del': '−', 'add': '+', 'ctx': ' '}
 
-LINE_H = 22
-GUTTER_W = 24
-PAD_X = 10
-HEADER_H = 26
+LINE_H = 26
+GUTTER_W = 28
+PAD_X = 12
+HEADER_H = 30
 
 
-def _measure_max_w(font, lines_text: list[str]) -> int:
-    max_w = 700
-    for text in lines_text:
-        tw = font.getlength(text) + GUTTER_W + PAD_X * 2 + 20
-        max_w = max(max_w, int(tw))
-    return min(max_w, 1200)
+def _measure_max_w(_font, _lines_text: list[str]) -> int:
+    return 800
 
 
 def _draw_header(draw, max_w: int, label: str, font_small):
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 5), label, fill=(100, 116, 139), font=font_small)
 
 
 def _draw_truncated(draw, y: int, remaining: int, font_small):
@@ -140,32 +149,35 @@ def render_edit_diff(file_path: str, old_string: str, new_string: str) -> bytes
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"✏️ {_short_path(file_path)}", font_small)
 
     y = HEADER_H + 2
     for typ, text, other in display:
+        text = text[:WRAP_COLS]
+        if other is not None:
+            other = other[:WRAP_COLS]
         if typ in ('del', 'add'):
             draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
-            draw.text((8, y + 3), _SIGN[typ], fill=_CLR_G[typ], font=font)
+            draw.text((10, y + 4), _SIGN[typ], fill=_CLR_G[typ], font=font)
             parts = _inline_diff(text, other)
             x = GUTTER_W + PAD_X
             for part_text, is_hl in parts:
                 if is_hl:
                     tw = font.getlength(part_text)
                     draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
-                draw.text((x, y + 3), part_text, fill=_CLR[typ], font=font)
+                draw.text((x, y + 4), part_text, fill=_CLR[typ], font=font)
                 x += font.getlength(part_text)
         else:
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(15, 23, 42))
-            draw.text((8, y + 3), ' ', fill=_CLR_G['ctx'], font=font)
-            draw.text((GUTTER_W + PAD_X, y + 3), text, fill=_CLR['ctx'], font=font)
+            draw.text((10, y + 4), ' ', fill=_CLR_G['ctx'], font=font)
+            draw.text((GUTTER_W + PAD_X, y + 4), text, fill=_CLR['ctx'], font=font)
         y += LINE_H
 
     if truncated:
         _draw_truncated(draw, y, len(lines) - MAX_LINES_EDIT, font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
@@ -184,20 +196,21 @@ def render_write_diff(file_path: str, content: str) -> bytes:
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"📄 {_short_path(file_path)} (new)", font_small)
 
     y = HEADER_H + 2
     for text in display:
+        text = text[:WRAP_COLS]
         draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
         draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
-        draw.text((8, y + 3), '+', fill=(74, 222, 128), font=font)
-        draw.text((GUTTER_W + PAD_X, y + 3), text, fill=(187, 247, 208), font=font)
+        draw.text((10, y + 4), '+', fill=(74, 222, 128), font=font)
+        draw.text((GUTTER_W + PAD_X, y + 4), text, fill=(187, 247, 208), font=font)
         y += LINE_H
 
     if truncated:
         _draw_truncated(draw, y, len(lines_text) - MAX_LINES_WRITE, font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
@@ -205,126 +218,139 @@ def render_write_diff(file_path: str, content: str) -> bytes:
 
 MAX_LINES_READ = 25
 MAX_LINES_GREP = 20
 _GUTTER_W_READ = 40  # wider for line numbers
 
 
 def render_read(file_path: str, content: str, offset: int = 0) -> bytes:
     """Render Read tool result as PNG with line numbers."""
-    lines_text = content.split('\n')[:MAX_LINES_READ]
+    raw_lines = content.split('\n')
     font, font_small = _load_fonts()
 
-    max_w = 700
-    for text in lines_text:
-        tw = font.getlength(text) + _GUTTER_W_READ + PAD_X * 2 + 20
-        max_w = max(max_w, int(tw))
-    max_w = min(max_w, 1200)
+    display = []  # (line_no_str, text)
+    for i, ln in enumerate(raw_lines):
+        parts = _wrap_line(ln)
+        for j, p in enumerate(parts):
+            display.append((str(offset + i + 1) if j == 0 else "", p))
+        if len(display) >= MAX_LINES_READ:
+            break
+    display = display[:MAX_LINES_READ]
+    truncated = len(raw_lines) > MAX_LINES_READ
+    extra = 1 if truncated else 0
 
-    img_h = HEADER_H + LINE_H * len(lines_text) + 4
+    max_w = 800
+    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
-    draw.text((PAD_X, 5), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)
+    draw.text((PAD_X, 7), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
-    for i, text in enumerate(lines_text):
-        line_no = str(offset + i + 1)
+    for line_no, text in display:
         draw.rectangle([0, y, _GUTTER_W_READ, y + LINE_H], fill=(15, 23, 42))
-        nw = font_small.getlength(line_no)
-        draw.text((_GUTTER_W_READ - nw - 4, y + 4), line_no, fill=(71, 85, 105), font=font_small)
-        draw.text((_GUTTER_W_READ + PAD_X, y + 3), text, fill=(226, 232, 240), font=font)
+        if line_no:
+            nw = font_small.getlength(line_no)
+            draw.text((_GUTTER_W_READ - nw - 4, y + 5), line_no, fill=(71, 85, 105), font=font_small)
+        draw.text((_GUTTER_W_READ + PAD_X, y + 4), text, fill=(226, 232, 240), font=font)
         y += LINE_H
 
+    if truncated:
+        _draw_truncated(draw, y, len(raw_lines) - MAX_LINES_READ, font_small)
+
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
 
 
 def render_grep(pattern: str, results: list) -> bytes:
     """Render Grep results as PNG with match highlighting.
 
     results: list of (file, line_no, text, match_start, match_end)
     """
     font, font_small = _load_fonts()
     display = results[:MAX_LINES_GREP]
 
-    max_w = 700
-    for f, ln, text, ms, me in display:
-        tw = font.getlength(f"{f}:{ln}: {text}") + PAD_X * 2 + 20
-        max_w = max(max_w, int(tw))
-    max_w = min(max_w, 1200)
-
+    max_w = 800
     img_h = HEADER_H + LINE_H * len(display) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
-    draw.text((PAD_X, 5), f"🔍 grep: {pattern} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
+    draw.text((PAD_X, 7), f"🔍 grep: {pattern[:40]} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
     for f, ln, text, ms, me in display:
-        prefix = f"{f}:{ln}: "
-        draw.text((PAD_X, y + 3), prefix, fill=(100, 116, 139), font=font)
+        prefix = f"{_short_path(f)}:{ln}: "
+        full_line = prefix + text
+        if len(full_line) > WRAP_COLS:
+            text = text[:WRAP_COLS - len(prefix)]
+            if me > len(text):
+                me = len(text)
+        draw.text((PAD_X, y + 4), prefix, fill=(100, 116, 139), font=font)
         x = PAD_X + font.getlength(prefix)
         before = text[:ms]
         match = text[ms:me]
         after = text[me:]
-        draw.text((x, y + 3), before, fill=(226, 232, 240), font=font)
+        draw.text((x, y + 4), before, fill=(226, 232, 240), font=font)
         x += font.getlength(before)
         tw = font.getlength(match)
         draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
-        draw.text((x, y + 3), match, fill=(253, 224, 71), font=font)
+        draw.text((x, y + 4), match, fill=(253, 224, 71), font=font)
         x += tw
-        draw.text((x, y + 3), after, fill=(226, 232, 240), font=font)
+        draw.text((x, y + 4), after, fill=(226, 232, 240), font=font)
         y += LINE_H
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
 
 
 MAX_LINES_BASH = 30
 
 
 def render_bash(command: str, output: str) -> bytes:
     """Render Bash tool — macOS-style terminal with command and output."""
-    LINE_H, PAD_X, HEADER_H = 22, 12, 28
+    _LH, _PX, _HH = 26, 12, 32
     font, font_small = _load_fonts()
 
-    out_lines_all = output.split('\n')
-    lines = out_lines_all[:MAX_LINES_BASH]
-    truncated = len(out_lines_all) > MAX_LINES_BASH
-
-    max_w = 650
-    for text in [command] + lines:
-        tw = font.getlength(text) + PAD_X * 2 + 30
-        max_w = max(max_w, int(tw))
-    max_w = min(max_w, 1200)
-
+    raw_lines = output.split('\n')
+    wrapped = []
+    for ln in raw_lines:
+        wrapped.extend(_wrap_line(ln))
+        if len(wrapped) >= MAX_LINES_BASH:
+            break
+    display = wrapped[:MAX_LINES_BASH]
+    truncated = len(raw_lines) > MAX_LINES_BASH or len(wrapped) > MAX_LINES_BASH
+    cmd_wrapped = _wrap_line(command)
+
+    max_w = 800
     extra = 1 if truncated else 0
-    img_h = HEADER_H + LINE_H * (len(lines) + 1 + extra) + 6
+    total_lines = len(cmd_wrapped) + len(display) + extra
+    img_h = _HH + _LH * total_lines + 8
     img = Image.new('RGB', (max_w, img_h), (13, 17, 23))
     draw = ImageDraw.Draw(img)
 
-    # macOS-style header with traffic lights
-    draw.rectangle([0, 0, max_w, HEADER_H], fill=(30, 30, 30))
-    draw.ellipse([10, 8, 22, 20], fill=(255, 95, 86))
-    draw.ellipse([28, 8, 40, 20], fill=(255, 189, 46))
-    draw.ellipse([46, 8, 58, 20], fill=(39, 201, 63))
-    draw.text((70, 7), "bash", fill=(150, 150, 150), font=font_small)
+    draw.rectangle([0, 0, max_w, _HH], fill=(30, 30, 30))
+    draw.ellipse([12, 10, 24, 22], fill=(255, 95, 86))
+    draw.ellipse([30, 10, 42, 22], fill=(255, 189, 46))
+    draw.ellipse([48, 10, 60, 22], fill=(39, 201, 63))
+    draw.text((72, 8), "bash", fill=(150, 150, 150), font=font_small)
 
-    y = HEADER_H + 4
-    draw.text((PAD_X, y + 3), "$ ", fill=(74, 222, 128), font=font)
-    draw.text((PAD_X + font.getlength("$ "), y + 3), command, fill=(226, 232, 240), font=font)
-    y += LINE_H
+    y = _HH + 4
+    for i, part in enumerate(cmd_wrapped):
+        prefix = "$ " if i == 0 else "  "
+        draw.text((_PX, y + 3), prefix, fill=(74, 222, 128), font=font)
+        draw.text((_PX + font.getlength(prefix), y + 3), part, fill=(226, 232, 240), font=font)
+        y += _LH
 
-    for text in lines:
-        draw.text((PAD_X, y + 3), text, fill=(180, 190, 200), font=font)
-        y += LINE_H
+    for text in display:
+        draw.text((_PX, y + 3), text, fill=(180, 190, 200), font=font)
+        y += _LH
 
     if truncated:
-        draw.text((PAD_X, y + 3), f"... +{len(out_lines_all) - MAX_LINES_BASH} more lines", fill=(100, 116, 139), font=font_small)
+        remaining = len(raw_lines) - MAX_LINES_BASH
+        draw.text((_PX, y + 3), f"... +{max(remaining, 0)} more lines", fill=(100, 116, 139), font=font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()


## LATER FIX 5c0c41e62f (1.1 days later): fix: replace tab chars with spaces in diff_image renderers — removes □ tofu glyphs
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: replace tab chars with spaces in diff_image renderers — removes □ tofu glyphs


diff --git a/app/diff_image.py b/app/diff_image.py
index a0e620261..85f3e34d8 100644
--- a/app/diff_image.py
+++ b/app/diff_image.py
@@ -21,16 +21,17 @@ def _load_fonts():
             ImageFont.truetype(_FONT_PATH, 13),
         )
     except Exception:
         f = ImageFont.load_default()
         return f, f
 
 
 def _wrap_line(text: str, cols: int = WRAP_COLS) -> list[str]:
+    text = text.replace('\t', '    ')
     if len(text) <= cols:
         return [text]
     parts = []
     while len(text) > cols:
         parts.append(text[:cols])
         text = text[cols:]
     if text:
         parts.append(text)
@@ -149,19 +150,19 @@ def render_edit_diff(file_path: str, old_string: str, new_string: str) -> bytes
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"✏️ {_short_path(file_path)}", font_small)
 
     y = HEADER_H + 2
     for typ, text, other in display:
-        text = text[:WRAP_COLS]
+        text = text.replace('\t', '    ')[:WRAP_COLS]
         if other is not None:
-            other = other[:WRAP_COLS]
+            other = other.replace('\t', '    ')[:WRAP_COLS]
         if typ in ('del', 'add'):
             draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
             draw.text((10, y + 4), _SIGN[typ], fill=_CLR_G[typ], font=font)
             parts = _inline_diff(text, other)
             x = GUTTER_W + PAD_X
             for part_text, is_hl in parts:
                 if is_hl:
@@ -196,17 +197,17 @@ def render_write_diff(file_path: str, content: str) -> bytes:
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"📄 {_short_path(file_path)} (new)", font_small)
 
     y = HEADER_H + 2
     for text in display:
-        text = text[:WRAP_COLS]
+        text = text.replace('\t', '    ')[:WRAP_COLS]
         draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
         draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
         draw.text((10, y + 4), '+', fill=(74, 222, 128), font=font)
         draw.text((GUTTER_W + PAD_X, y + 4), text, fill=(187, 247, 208), font=font)
         y += LINE_H
 
     if truncated:
         _draw_truncated(draw, y, len(lines_text) - MAX_LINES_WRITE, font_small)
@@ -275,16 +276,17 @@ def render_grep(pattern: str, results: list) -> bytes:
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 7), f"🔍 grep: {pattern[:40]} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
     for f, ln, text, ms, me in display:
+        text = text.replace('\t', '    ')
         prefix = f"{_short_path(f)}:{ln}: "
         full_line = prefix + text
         if len(full_line) > WRAP_COLS:
             text = text[:WRAP_COLS - len(prefix)]
             if me > len(text):
                 me = len(text)
         draw.text((PAD_X, y + 4), prefix, fill=(100, 116, 139), font=font)
         x = PAD_X + font.getlength(prefix)


## LATER FIX d206a4c448 (23.3 days later): fix: no character loss — wrap instead of truncate everywhere
lines of origin it changed/deleted: 15
(code only, capped 400 lines)

fix: no character loss — wrap instead of truncate everywhere

Principle: no char must disappear — wrap long lines, never clip right edge.

diff_image.py (TG tool images):
- render_edit_diff / render_write_diff / render_grep / render_glob: replaced
  text[:WRAP_COLS] truncate with _wrap_line() — long lines flow to next visual
  row (first row keeps +/− sign; wrapped rows plain, no inline highlight)
- IMG_W=960 (was 800): 90-col wrapped rows were still clipping at the right
  edge — 90 chars × 9.6px + gutter needs ~960px, not 800
- _draw_truncated shows '(truncated)' when exact remaining unknown (was '+0')

File preview (app.js):
- plain-text / code / json branches: white-space pre → pre-wrap +
  overflow-wrap:anywhere, overflow-x hidden (wrap, not horizontal scroll/clip)

Chat bubbles (style.css):
- .chat-tool/.chat-tool-result/.chat-bot had overflow-x:hidden WITHOUT wrap →
  long lines clipped. Added overflow-wrap:anywhere + word-break:break-word

Verified: 160-char line renders fully in all 5 diff images (_END_MARKER visible,
no right-edge clip).


diff --git a/app/diff_image.py b/app/diff_image.py
index 9ebfc7b81..b8584df76 100644
--- a/app/diff_image.py
+++ b/app/diff_image.py
@@ -6,17 +6,20 @@ from PIL import Image, ImageDraw, ImageFont
 
 
 _FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
 
 MAX_LINES_EDIT = 50
 MAX_LINES_WRITE = 30
 
 
-WRAP_COLS = 140
+WRAP_COLS = 90
+# Image width must fit WRAP_COLS monospace chars + gutter, else wrapped rows
+# still clip at the right edge. DejaVuSansMono @16px ≈ 9.6px/char.
+IMG_W = 960
 
 
 def _load_fonts():
     try:
         return (
             ImageFont.truetype(_FONT_PATH, 16),
             ImageFont.truetype(_FONT_PATH, 13),
         )
@@ -110,107 +113,130 @@ _SIGN = {'del': '−', 'add': '+', 'ctx': ' '}
 
 LINE_H = 26
 GUTTER_W = 28
 PAD_X = 12
 HEADER_H = 30
 
 
 def _measure_max_w(_font, _lines_text: list[str]) -> int:
-    return 800
+    return IMG_W
 
 
 def _draw_header(draw, max_w: int, label: str, font_small):
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 5), label, fill=(100, 116, 139), font=font_small)
 
 
 def _draw_truncated(draw, y: int, remaining: int, font_small):
-    draw.text((GUTTER_W + PAD_X, y + 3), f"... +{remaining} more lines", fill=(100, 116, 139), font=font_small)
+    label = f"... +{remaining} more lines" if remaining > 0 else "... (truncated)"
+    draw.text((GUTTER_W + PAD_X, y + 3), label, fill=(100, 116, 139), font=font_small)
 
 
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
-    max_w = _measure_max_w(font, [text for _, text, _ in lines])
 
-    display = lines[:MAX_LINES_EDIT]
-    truncated = len(lines) > MAX_LINES_EDIT
+    # Expand each diff line into visual rows via wrapping so nothing is truncated.
+    # Inline highlight only on short lines (text≤WRAP_COLS) — on wrapped long lines
+    # the char-offset highlight can't map across rows, so plain-render them.
+    display = []  # (typ, row_text, other_or_None, is_first_row)
+    truncated = False
+    for typ, text, other in lines:
+        text = text.replace('\t', '    ')
+        other_c = other.replace('\t', '    ') if other is not None else None
+        if len(text) <= WRAP_COLS:
+            display.append((typ, text, other_c, True))
+        else:
+            for j, part in enumerate(_wrap_line(text)):
+                display.append((typ, part, None, j == 0))  # None → no inline highlight
+        if len(display) >= MAX_LINES_EDIT:
+            truncated = True
+            break
+    display = display[:MAX_LINES_EDIT]
     extra = 1 if truncated else 0
 
+    max_w = _measure_max_w(font, [t for _, t, _, _ in display])
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"✏️ {_short_path(file_path)}", font_small)
 
     y = HEADER_H + 2
-    for typ, text, other in display:
-        text = text.replace('\t', '    ')[:WRAP_COLS]
-        if other is not None:
-            other = other.replace('\t', '    ')[:WRAP_COLS]
+    for typ, text, other, is_first in display:
         if typ in ('del', 'add'):
             draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
-            draw.text((10, y + 4), _SIGN[typ], fill=_CLR_G[typ], font=font)
-            parts = _inline_diff(text, other)
+            draw.text((10, y + 4), _SIGN[typ] if is_first else ' ', fill=_CLR_G[typ], font=font)
             x = GUTTER_W + PAD_X
-            for part_text, is_hl in parts:
-                if is_hl:
-                    tw = font.getlength(part_text)
-                    draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
-                draw.text((x, y + 4), part_text, fill=_CLR[typ], font=font)
-                x += font.getlength(part_text)
+            if other is not None:
+                parts = _inline_diff(text, other)
+                for part_text, is_hl in parts:
+                    if is_hl:
+                        tw = font.getlength(part_text)
+                        draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
+                    draw.text((x, y + 4), part_text, fill=_CLR[typ], font=font)
+                    x += font.getlength(part_text)
+            else:
+                draw.text((x, y + 4), text, fill=_CLR[typ], font=font)
         else:
             draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(15, 23, 42))
             draw.text((10, y + 4), ' ', fill=_CLR_G['ctx'], font=font)
             draw.text((GUTTER_W + PAD_X, y + 4), text, fill=_CLR['ctx'], font=font)
         y += LINE_H
 
     if truncated:
-        _draw_truncated(draw, y, len(lines) - MAX_LINES_EDIT, font_small)
+        _draw_truncated(draw, y, 0, font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
 
 
 def render_write_diff(file_path: str, content: str) -> bytes:
     """Render Write (new file) as PNG. All lines green."""
     lines_text = content.split('\n')
     font, font_small = _load_fonts()
 
-    display = lines_text[:MAX_LINES_WRITE]
+    # Wrap each line so nothing is truncated; only the first visual row shows '+'
+    display = []  # (text, is_first_row)
+    for ln in lines_text:
+        parts = _wrap_line(ln)
+        for j, p in enumerate(parts):
+            display.append((p, j == 0))
+        if len(display) >= MAX_LINES_WRITE:
+            break
+    display = display[:MAX_LINES_WRITE]
     truncated = len(lines_text) > MAX_LINES_WRITE
     extra = 1 if truncated else 0
 
-    max_w = _measure_max_w(font, display)
+    max_w = _measure_max_w(font, [t for t, _ in display])
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     _draw_header(draw, max_w, f"📄 {_short_path(file_path)} (new)", font_small)
 
     y = HEADER_H + 2
-    for text in display:
-        text = text.replace('\t', '    ')[:WRAP_COLS]
+    for text, is_first in display:
         draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
         draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
-        draw.text((10, y + 4), '+', fill=(74, 222, 128), font=font)
+        draw.text((10, y + 4), '+' if is_first else ' ', fill=(74, 222, 128), font=font)
         draw.text((GUTTER_W + PAD_X, y + 4), text, fill=(187, 247, 208), font=font)
         y += LINE_H
 
     if truncated:
         _draw_truncated(draw, y, len(lines_text) - MAX_LINES_WRITE, font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
@@ -233,17 +259,17 @@ def render_read(file_path: str, content: str, offset: int = 0) -> bytes:
         for j, p in enumerate(parts):
             display.append((str(offset + i + 1) if j == 0 else "", p))
         if len(display) >= MAX_LINES_READ:
             break
     display = display[:MAX_LINES_READ]
     truncated = len(raw_lines) > MAX_LINES_READ
     extra = 1 if truncated else 0
 
-    max_w = 800
+    max_w = IMG_W
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 7), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
@@ -264,46 +290,62 @@ def render_read(file_path: str, content: str, offset: int = 0) -> bytes:
 
 
 def render_grep(pattern: str, results: list) -> bytes:
     """Render Grep results as PNG with match highlighting.
 
     results: list of (file, line_no, text, match_start, match_end)
     """
     font, font_small = _load_fonts()
-    display = results[:MAX_LINES_GREP]
 
-    max_w = 800
+    # Build visual rows: prefix+text on row 0 (with highlight if it fits), long
+    # tails wrapped onto continuation rows so no char is lost.
+    rows = []  # (prefix, before, match, after, cont_text)  cont_text set → plain wrapped row
+    for f, ln, text, ms, me in results:
+        text = text.replace('\t', '    ')
+        prefix = f"{_short_path(f)}:{ln}: "
+        avail = WRAP_COLS - len(prefix)
+        if len(text) <= avail:
+            rows.append((prefix, text[:ms], text[ms:me], text[me:], None))
+        else:
+            # first row: highlight only if match is fully within the visible head
+            head = text[:avail]
+            if me <= avail:
+                rows.append((prefix, head[:ms], head[ms:me], head[me:], None))
+            else:
+                rows.append((prefix, head, "", "", None))
+            for part in _wrap_line(text[avail:], WRAP_COLS):
+                rows.append((None, "", "", "", part))
+        if len(rows) >= MAX_LINES_GREP:
+            break
+    display = rows[:MAX_LINES_GREP]
+
+    max_w = IMG_W
     img_h = HEADER_H + LINE_H * len(display) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 7), f"🔍 grep: {pattern[:40]} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
-    for f, ln, text, ms, me in display:
-        text = text.replace('\t', '    ')
-        prefix = f"{_short_path(f)}:{ln}: "
-        full_line = prefix + text
-        if len(full_line) > WRAP_COLS:
-            text = text[:WRAP_COLS - len(prefix)]
-            if me > len(text):
-                me = len(text)
+    for prefix, before, match, after, cont in display:
+        if cont is not None:  # wrapped continuation row — indent under prefix
+            draw.text((PAD_X + 16, y + 4), cont, fill=(226, 232, 240), font=font)
+            y += LINE_H
+            continue
         draw.text((PAD_X, y + 4), prefix, fill=(100, 116, 139), font=font)
         x = PAD_X + font.getlength(prefix)
-        before = text[:ms]
-        match = text[ms:me]
-        after = text[me:]
         draw.text((x, y + 4), before, fill=(226, 232, 240), font=font)
         x += font.getlength(before)
-        tw = font.getlength(match)
-        draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
-        draw.text((x, y + 4), match, fill=(253, 224, 71), font=font)
-        x += tw
+        if match:
+            tw = font.getlength(match)
+            draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
+            draw.text((x, y + 4), match, fill=(253, 224, 71), font=font)
+            x += tw
         draw.text((x, y + 4), after, fill=(226, 232, 240), font=font)
         y += LINE_H
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
     return buf.getvalue()
 
 
@@ -322,17 +364,17 @@ def render_bash(command: str, output: str) -> bytes:
         if len(wrapped) >= MAX_LINES_BASH:
             break
     display = wrapped[:MAX_LINES_BASH]
     truncated = len(raw_lines) > MAX_LINES_BASH or len(wrapped) > MAX_LINES_BASH
     cmd_wrapped = []
     for ln in command.split('\n'):
         cmd_wrapped.extend(_wrap_line(ln))
 
-    max_w = 800
+    max_w = IMG_W
     extra = 1 if truncated else 0
     total_lines = len(cmd_wrapped) + len(display) + extra
     img_h = _HH + _LH * total_lines + 8
     img = Image.new('RGB', (max_w, img_h), (13, 17, 23))
     draw = ImageDraw.Draw(img)
 
     draw.rectangle([0, 0, max_w, _HH], fill=(30, 30, 30))
     draw.ellipse([12, 10, 24, 22], fill=(255, 95, 86))
@@ -370,31 +412,36 @@ _GLOB_ICONS = {
     'html': '🌐', 'css': '🎨', 'sh': '🖥', 'sql': '🗃',
 }
 
 
 def render_glob(pattern: str, results: str) -> bytes:
     """Render Glob results as PNG — file list with extension icons."""
     font, font_small = _load_fonts()
     raw_lines = [l.strip() for l in results.strip().splitlines() if l.strip()]
-    display = raw_lines[:MAX_LINES_GLOB]
+    display = []  # wrapped path rows, no truncation
+    for path in raw_lines:
+        for part in _wrap_line(_short_path(path)):
+            display.append(part)
+        if len(display) >= MAX_LINES_GLOB:
+            break
+    display = display[:MAX_LINES_GLOB]
     truncated = len(raw_lines) > MAX_LINES_GLOB
     extra = 1 if truncated else 0
 
-    max_w = 800
+    max_w = IMG_W
     img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
     img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
     draw = ImageDraw.Draw(img)
 
     draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
     draw.text((PAD_X, 7), f"glob: {pattern[:50]} ({len(raw_lines)} files)", fill=(100, 116, 139), font=font_small)
 
     y = HEADER_H + 2
-    for path in display:
-        short = _short_path(path)[:WRAP_COLS]
+    for short in display:
         draw.text((PAD_X, y + 4), short, fill=(56, 189, 248), font=font)
         y += LINE_H
 
     if truncated:
         draw.text((PAD_X, y + 4), f"... +{len(raw_lines) - MAX_LINES_GLOB} more files", fill=(100, 116, 139), font=font_small)
 
     buf = io.BytesIO()
     img.save(buf, format='PNG', optimize=True)
diff --git a/app/static/css/style.css b/app/static/css/style.css
index 9ae472dba..098b44fbe 100644
--- a/app/static/css/style.css
+++ b/app/static/css/style.css
@@ -116,17 +116,17 @@ select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmln
 .websearch-title { display: block; font-size: 11px; font-weight: 600; color: #38bdf8; text-decoration: none; line-height: 1.4; }
 .websearch-title:hover { text-decoration: underline; }
 .websearch-snippet { font-size: 10px; color: #94a3b8; margin-top: 2px; line-height: 1.4; }
 .grep-results { display: flex; flex-direction: column; border-radius: 6px; overflow: hidden; border: 1px solid #1e293b; }
 .grep-result-row { display: flex; gap: 8px; padding: 2px 8px; min-height: 20px; align-items: baseline; border-bottom: 1px solid rgba(30,41,59,0.5); }
 .grep-result-row:hover { background: rgba(99,102,241,0.08); }
 .grep-meta { flex-shrink: 0; font-size: 10px; color: #64748b; white-space: nowrap; min-width: 120px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; font-family: 'JetBrains Mono', monospace; }
 .grep-code { font-size: 11px; color: #e2e8f0; white-space: pre-wrap; word-break: break-all; flex: 1; min-width: 0; font-family: 'JetBrains Mono', monospace; }
-.chat-tool, .chat-tool-result, .chat-bot { overflow-x: hidden; max-width: 100%; min-width: 0; }
+.chat-tool, .chat-tool-result, .chat-bot { overflow-x: hidden; max-width: 100%; min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
 .markdown-body th { background: rgba(30,41,59,0.8); color: #94a3b8; font-size: 11px; }
 .markdown-body td { background: transparent; color: #cbd5e1; font-size: 12px; }
 .markdown-body tr:nth-child(even) td { background: rgba(30,41,59,0.3); }
 .markdown-body input[type="checkbox"] { margin-right: 4px; accent-color: #6366f1; }
 .task-inject-btn { position: absolute; right: 4px; top: 1px; opacity: 0; cursor: pointer; font-size: 11px; color: #818cf8; transition: opacity 0.15s; }
 .task-item:hover .task-inject-btn { opacity: 1; }
 .job-cancel-btn { position: absolute; right: 2px; top: 2px; opacity: 0; cursor: pointer; font-size: 10px; color: #ef4444; transition: opacity 0.15s; }
 .flex:hover > .job-cancel-btn { opacity: 0.7; }
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 79754a2ba..71c954380 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -552,41 +552,41 @@ async function openFilePreview(path) {
                     html += '</tr>';
                 }
                 html += '</tbody></table>';
                 contentEl.innerHTML = html;
             } else if (ext === 'json') {
                 let pretty = raw;
                 try { pretty = JSON.stringify(JSON.parse(raw), null, 2); } catch {}
                 contentEl.className = 'flex-1 text-xs p-4';
-                contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px)';