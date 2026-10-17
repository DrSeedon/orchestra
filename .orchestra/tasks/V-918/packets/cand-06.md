# Candidate cand-06

## ORIGIN commit 1e469c95b6 (2026-06-07): feat: Edit/Write/Read/Grep/Bash diff images in TG — Pillow render, inline highlights
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/diff_image.py b/app/diff_image.py
new file mode 100644
index 000000000..1bbbd1724
--- /dev/null
+++ b/app/diff_image.py
@@ -0,0 +1,327 @@
+"""Render Edit/Write/Read/Grep tool output as PNG images using Pillow."""
+import io
+import re
+
+from PIL import Image, ImageDraw, ImageFont
+
+
+_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
+
+MAX_LINES_EDIT = 50
+MAX_LINES_WRITE = 30
+
+
+def _load_fonts():
+    try:
+        return (
+            ImageFont.truetype(_FONT_PATH, 13),
+            ImageFont.truetype(_FONT_PATH, 11),
+        )
+    except Exception:
+        f = ImageFont.load_default()
+        return f, f
+
+
+def _short_path(file_path: str) -> str:
+    p = file_path
+    p = re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', p)
+    for prefix in ('/mnt/data/Projects/Python/', '/home/'):
+        if p.startswith(prefix):
+            p = p[len(prefix):]
+    return p
+
+
+def _lcs_diff(a: list[str], b: list[str]):
+    """LCS-based diff. Returns list of ('ctx'|'add'|'del', line_a, line_b_or_None)."""
+    n, m = len(a), len(b)
+    dp = [[0] * (m + 1) for _ in range(n + 1)]
+    for i in range(1, n + 1):
+        for j in range(1, m + 1):
+            dp[i][j] = dp[i-1][j-1] + 1 if a[i-1] == b[j-1] else max(dp[i-1][j], dp[i][j-1])
+    raw = []
+    i, j = n, m
+    while i > 0 or j > 0:
+        if i > 0 and j > 0 and a[i-1] == b[j-1]:
+            raw.append(('ctx', a[i-1])); i -= 1; j -= 1
+        elif j > 0 and (i == 0 or dp[i][j-1] >= dp[i-1][j]):
+            raw.append(('add', b[j-1])); j -= 1
+        else:
+            raw.append(('del', a[i-1])); i -= 1
+    raw.reverse()
+
+    # pair del+add for inline diff
+    lines = []
+    idx = 0
+    while idx < len(raw):
+        if raw[idx][0] == 'del' and idx + 1 < len(raw) and raw[idx+1][0] == 'add':
+            lines.append(('del', raw[idx][1], raw[idx+1][1]))
+            lines.append(('add', raw[idx+1][1], raw[idx][1]))
+            idx += 2
+        else:
+            lines.append((raw[idx][0], raw[idx][1], None))
+            idx += 1
+    return lines
+
+
+def _inline_diff(line: str, other: str | None):
+    """Return list of (text, is_highlighted) for inline char diff."""
+    if other is None:
+        return [(line, False)]
+    pre = 0
+    while pre < min(len(line), len(other)) and line[pre] == other[pre]:
+        pre += 1
+    suf = 0
+    while suf < min(len(line) - pre, len(other) - pre) and line[-(suf+1)] == other[-(suf+1)]:
+        suf += 1
+    end = len(line) - suf if suf else len(line)
+    parts = []
+    if pre > 0:
+        parts.append((line[:pre], False))
+    if end > pre:
+        parts.append((line[pre:end], True))
+    if suf > 0:
+        parts.append((line[end:], False))
+    return parts or [(line, False)]
+
+
+_BG = {'del': (50, 20, 20), 'add': (15, 40, 25)}
+_BG_G = {'del': (70, 25, 25), 'add': (20, 55, 30)}
+_CLR = {'del': (254, 202, 202), 'add': (187, 247, 208), 'ctx': (148, 163, 184)}
+_CLR_G = {'del': (248, 113, 113), 'add': (74, 222, 128), 'ctx': (71, 85, 105)}
+_HL = {'del': (120, 40, 40), 'add': (15, 70, 40)}
+_SIGN = {'del': '−', 'add': '+', 'ctx': ' '}
+
+LINE_H = 22
+GUTTER_W = 24
+PAD_X = 10
+HEADER_H = 26
+
+
+def _measure_max_w(font, lines_text: list[str]) -> int:
+    max_w = 700
+    for text in lines_text:
+        tw = font.getlength(text) + GUTTER_W + PAD_X * 2 + 20
+        max_w = max(max_w, int(tw))
+    return min(max_w, 1200)
+
+
+def _draw_header(draw, max_w: int, label: str, font_small):
+    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
+    draw.text((PAD_X, 5), label, fill=(100, 116, 139), font=font_small)
+
+
+def _draw_truncated(draw, y: int, remaining: int, font_small):
+    draw.text((GUTTER_W + PAD_X, y + 3), f"... +{remaining} more lines", fill=(100, 116, 139), font=font_small)
+
+
+def render_edit_diff(file_path: str, old_string: str, new_string: str) -> bytes | None:
+    """Render Edit diff as PNG. Returns PNG bytes or None if no diff."""
+    if old_string == new_string:
+        return None
+
+    a = old_string.split('\n')
+    b = new_string.split('\n')
+    lines = _lcs_diff(a, b)
+
+    # Skip if only ctx lines (shouldn't happen but guard)
+    if all(t == 'ctx' for t, _, _ in lines):
+        return None
+
+    font, font_small = _load_fonts()
+    max_w = _measure_max_w(font, [text for _, text, _ in lines])
+
+    display = lines[:MAX_LINES_EDIT]
+    truncated = len(lines) > MAX_LINES_EDIT
+    extra = 1 if truncated else 0
+
+    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
+    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
+    draw = ImageDraw.Draw(img)
+
+    _draw_header(draw, max_w, f"✏️ {_short_path(file_path)}", font_small)
+
+    y = HEADER_H + 2
+    for typ, text, other in display:
+        if typ in ('del', 'add'):
+            draw.rectangle([0, y, max_w, y + LINE_H], fill=_BG[typ])
+            draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=_BG_G[typ])
+            draw.text((8, y + 3), _SIGN[typ], fill=_CLR_G[typ], font=font)
+            parts = _inline_diff(text, other)
+            x = GUTTER_W + PAD_X
+            for part_text, is_hl in parts:
+                if is_hl:
+                    tw = font.getlength(part_text)
+                    draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=_HL[typ])
+                draw.text((x, y + 3), part_text, fill=_CLR[typ], font=font)
+                x += font.getlength(part_text)
+        else:
+            draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(15, 23, 42))
+            draw.text((8, y + 3), ' ', fill=_CLR_G['ctx'], font=font)
+            draw.text((GUTTER_W + PAD_X, y + 3), text, fill=_CLR['ctx'], font=font)
+        y += LINE_H
+
+    if truncated:
+        _draw_truncated(draw, y, len(lines) - MAX_LINES_EDIT, font_small)
+
+    buf = io.BytesIO()
+    img.save(buf, format='PNG', optimize=True)
+    return buf.getvalue()
+
+
+def render_write_diff(file_path: str, content: str) -> bytes:
+    """Render Write (new file) as PNG. All lines green."""
+    lines_text = content.split('\n')
+    font, font_small = _load_fonts()
+
+    display = lines_text[:MAX_LINES_WRITE]
+    truncated = len(lines_text) > MAX_LINES_WRITE
+    extra = 1 if truncated else 0
+
+    max_w = _measure_max_w(font, display)
+    img_h = HEADER_H + LINE_H * (len(display) + extra) + 4
+    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
+    draw = ImageDraw.Draw(img)
+
+    _draw_header(draw, max_w, f"📄 {_short_path(file_path)} (new)", font_small)
+
+    y = HEADER_H + 2
+    for text in display:
+        draw.rectangle([0, y, max_w, y + LINE_H], fill=(15, 40, 25))
+        draw.rectangle([0, y, GUTTER_W, y + LINE_H], fill=(20, 55, 30))
+        draw.text((8, y + 3), '+', fill=(74, 222, 128), font=font)
+        draw.text((GUTTER_W + PAD_X, y + 3), text, fill=(187, 247, 208), font=font)
+        y += LINE_H
+
+    if truncated:
+        _draw_truncated(draw, y, len(lines_text) - MAX_LINES_WRITE, font_small)
+
+    buf = io.BytesIO()
+    img.save(buf, format='PNG', optimize=True)
+    return buf.getvalue()
+
+
+MAX_LINES_READ = 25
+MAX_LINES_GREP = 20
+_GUTTER_W_READ = 40  # wider for line numbers
+
+
+def render_read(file_path: str, content: str, offset: int = 0) -> bytes:
+    """Render Read tool result as PNG with line numbers."""
+    lines_text = content.split('\n')[:MAX_LINES_READ]
+    font, font_small = _load_fonts()
+
+    max_w = 700
+    for text in lines_text:
+        tw = font.getlength(text) + _GUTTER_W_READ + PAD_X * 2 + 20
+        max_w = max(max_w, int(tw))
+    max_w = min(max_w, 1200)
+
+    img_h = HEADER_H + LINE_H * len(lines_text) + 4
+    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
+    draw = ImageDraw.Draw(img)
+
+    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
+    draw.text((PAD_X, 5), f"📖 {_short_path(file_path)} :{offset + 1}", fill=(100, 116, 139), font=font_small)
+
+    y = HEADER_H + 2
+    for i, text in enumerate(lines_text):
+        line_no = str(offset + i + 1)
+        draw.rectangle([0, y, _GUTTER_W_READ, y + LINE_H], fill=(15, 23, 42))
+        nw = font_small.getlength(line_no)
+        draw.text((_GUTTER_W_READ - nw - 4, y + 4), line_no, fill=(71, 85, 105), font=font_small)
+        draw.text((_GUTTER_W_READ + PAD_X, y + 3), text, fill=(226, 232, 240), font=font)
+        y += LINE_H
+
+    buf = io.BytesIO()
+    img.save(buf, format='PNG', optimize=True)
+    return buf.getvalue()
+
+
+def render_grep(pattern: str, results: list) -> bytes:
+    """Render Grep results as PNG with match highlighting.
+
+    results: list of (file, line_no, text, match_start, match_end)
+    """
+    font, font_small = _load_fonts()
+    display = results[:MAX_LINES_GREP]
+
+    max_w = 700
+    for f, ln, text, ms, me in display:
+        tw = font.getlength(f"{f}:{ln}: {text}") + PAD_X * 2 + 20
+        max_w = max(max_w, int(tw))
+    max_w = min(max_w, 1200)
+
+    img_h = HEADER_H + LINE_H * len(display) + 4
+    img = Image.new('RGB', (max_w, img_h), (15, 23, 42))
+    draw = ImageDraw.Draw(img)
+
+    draw.line([0, HEADER_H, max_w, HEADER_H], fill=(30, 41, 59))
+    draw.text((PAD_X, 5), f"🔍 grep: {pattern} ({len(results)} matches)", fill=(100, 116, 139), font=font_small)
+
+    y = HEADER_H + 2
+    for f, ln, text, ms, me in display:
+        prefix = f"{f}:{ln}: "
+        draw.text((PAD_X, y + 3), prefix, fill=(100, 116, 139), font=font)
+        x = PAD_X + font.getlength(prefix)
+        before = text[:ms]
+        match = text[ms:me]
+        after = text[me:]
+        draw.text((x, y + 3), before, fill=(226, 232, 240), font=font)
+        x += font.getlength(before)
+        tw = font.getlength(match)
+        draw.rectangle([x - 1, y + 2, x + tw + 1, y + LINE_H - 2], fill=(120, 80, 0))
+        draw.text((x, y + 3), match, fill=(253, 224, 71), font=font)
+        x += tw
+        draw.text((x, y + 3), after, fill=(226, 232, 240), font=font)
+        y += LINE_H
+
+    buf = io.BytesIO()
+    img.save(buf, format='PNG', optimize=True)
+    return buf.getvalue()
+
+
+MAX_LINES_BASH = 30
+
+
+def render_bash(command: str, output: str) -> bytes:
+    """Render Bash tool — macOS-style terminal with command and output."""
+    LINE_H, PAD_X, HEADER_H = 22, 12, 28
+    font, font_small = _load_fonts()
+
+    out_lines_all = output.split('\n')
+    lines = out_lines_all[:MAX_LINES_BASH]
+    truncated = len(out_lines_all) > MAX_LINES_BASH
+
+    max_w = 650
+    for text in [command] + lines:
+        tw = font.getlength(text) + PAD_X * 2 + 30
+        max_w = max(max_w, int(tw))
+    max_w = min(max_w, 1200)
+
+    extra = 1 if truncated else 0
+    img_h = HEADER_H + LINE_H * (len(lines) + 1 + extra) + 6
+    img = Image.new('RGB', (max_w, img_h), (13, 17, 23))
+    draw = ImageDraw.Draw(img)
+
+    # macOS-style header with traffic lights
+    draw.rectangle([0, 0, max_w, HEADER_H], fill=(30, 30, 30))
+    draw.ellipse([10, 8, 22, 20], fill=(255, 95, 86))
+    draw.ellipse([28, 8, 40, 20], fill=(255, 189, 46))
+    draw.ellipse([46, 8, 58, 20], fill=(39, 201, 63))
+    draw.text((70, 7), "bash", fill=(150, 150, 150), font=font_small)
+
+    y = HEADER_H + 4
+    draw.text((PAD_X, y + 3), "$ ", fill=(74, 222, 128), font=font)
+    draw.text((PAD_X + font.getlength("$ "), y + 3), command, fill=(226, 232, 240), font=font)
+    y += LINE_H
+
+    for text in lines:
+        draw.text((PAD_X, y + 3), text, fill=(180, 190, 200), font=font)
+        y += LINE_H
+
+    if truncated:
+        draw.text((PAD_X, y + 3), f"... +{len(out_lines_all) - MAX_LINES_BASH} more lines", fill=(100, 116, 139), font=font_small)
+
+    buf = io.BytesIO()
+    img.save(buf, format='PNG', optimize=True)
+    return buf.getvalue()
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index f8527c954..939fb47a3 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -850,16 +850,132 @@ async def ensure_topics():
             result = await bot.create_forum_topic(chat_id=chat_id, name=short, icon_custom_emoji_id=_ICON_IDLE)
             mirror["topic_id"] = result.message_thread_id
             save_config()
             logger.info(f"Created mirror topic for {name}: {result.message_thread_id}")
         except Exception as e:
             logger.warning(f"Mirror topic creation failed for {name}: {e}")
 
 
+def _diff_images_enabled() -> bool:
+    return os.getenv("TG_DIFF_IMAGES", "true").lower() not in ("0", "false", "no")
+
+
+async def _send_png_to_tg(png: bytes, chat_id: int, thread_id: int, label: str) -> None:
+    """Send PNG bytes as a photo to TG. Temp file cleaned up after send."""
+    import uuid, tempfile
+    if not png or not bot:
+        return
+    tmp = os.path.join(tempfile.gettempdir(), f"diff-{uuid.uuid4().hex}.png")
+    with open(tmp, "wb") as f:
+        f.write(png)
+    try:
+        from aiogram.types import FSInputFile
+        await bot.send_photo(chat_id, FSInputFile(tmp), message_thread_id=thread_id)
+    finally:
+        try:
+            os.unlink(tmp)
+        except Exception:
+            pass
+
+
+async def _send_diff_image(tool_name: str, raw_content: str, chat_id: int, thread_id: int) -> None:
+    """Parse Edit/Write tool call, render diff PNG, send to TG. Errors silently logged."""
+    if not _diff_images_enabled():
+        return
+    import json
+    try:
+        colon = raw_content.index(":")
+        params = json.loads(raw_content[colon + 1:].strip())
+    except Exception:
+        return
+    try:
+        from app.diff_image import render_edit_diff, render_write_diff
+        if tool_name == "Edit":
+            png = render_edit_diff(params.get("file_path", ""), params.get("old_string", ""), params.get("new_string", ""))
+        else:  # Write
+            png = render_write_diff(params.get("file_path", ""), params.get("content", ""))
+        await _send_png_to_tg(png, chat_id, thread_id, tool_name)
+    except Exception as e:
+        logger.debug(f"diff image send failed ({tool_name}): {e}")
+
+
+async def _send_result_image(tool_name: str, tool_raw: str, result: str, chat_id: int, thread_id: int) -> None:
+    """Render Read/Grep tool_result as PNG and send to TG."""
+    if not _diff_images_enabled():
+        return
+    try:
+        if tool_name == "Read":
+            import json
+            # tool_raw: "Read: {\"file_path\": ..., \"offset\": ...}"
+            try:
+                colon = tool_raw.index(":")
+                params = json.loads(tool_raw[colon + 1:].strip())
+                file_path = params.get("file_path", "")
+                offset = int(params.get("offset", 0))
+            except Exception:
+                file_path = ""
+                offset = 0
+            from app.diff_image import render_read
+            png = render_read(file_path, result, offset)
+            await _send_png_to_tg(png, chat_id, thread_id, "Read")
+
+        elif tool_name == "Grep":
+            import json, re as _re
+            # Parse pattern from tool_raw
+            try:
+                colon = tool_raw.index(":")
+                params = json.loads(tool_raw[colon + 1:].strip())
+                pattern = params.get("pattern", "")
+            except Exception:
+                pattern = ""
+
+            # result format: "path/file.py:42:matching line text\n..."
+            # or files_with_matches: just paths
+            parsed = []
+            for line in result.splitlines():
+                # expect "file:lineno:text" format
+                m = _re.match(r'^(.+?):(\d+):(.*)$', line)
+                if not m:
+                    continue  # files_with_matches or no match — skip
+                fpath, lineno, text = m.group(1), int(m.group(2)), m.group(3)
+                fpath = _re.sub(r'^.*/worktrees/[^/]+/[^/]+/', '', fpath)
+                # Find match position in text
+                ms, me = 0, len(text)
+                if pattern:
+                    try:
+                        pm = _re.search(pattern, text)
+                        if pm:
+                            ms, me = pm.start(), pm.end()
+                    except Exception:
+                        pass
+                parsed.append((fpath, lineno, text, ms, me))
+
+            if not parsed:
+                return  # files_with_matches mode or empty — no image
+
+            from app.diff_image import render_grep
+            png = render_grep(pattern, parsed)
+            await _send_png_to_tg(png, chat_id, thread_id, "Grep")
+
+        elif tool_name == "Bash":
+            import json
+            try:
+                colon = tool_raw.index(":")
+                params = json.loads(tool_raw[colon + 1:].strip())
+                command = params.get("command", "")
+            except Exception:
+                command = ""
+            from app.diff_image import render_bash
+            png = render_bash(command, result)
+            await _send_png_to_tg(png, chat_id, thread_id, "Bash")
+    except Exception as e:
+        logger.debug(f"result image send failed ({tool_name}): {e}")
+
+
 async def stream_logs(orch_name: str, thread_id: int):
     from app.db import get_logs, get_session_by_name, get_all_sessions
 
     scope = None
     for s in get_all_sessions():
         if s["name"] == orch_name:
             scope = s.get("scope", "")
             break
@@ -874,16 +990,18 @@ async def stream_logs(orch_name: str, thread_id: int):
         return
 
     from app.db import _conn
     _poll_conn = _conn()
     logs = get_logs(session_id, after_id=0, conn=_poll_conn)
     last_id = logs[-1]["id"] if logs else 0
     _last_tool_msg = None
     _last_tool_text = ""
+    _last_tool_name = ""   # track last tool for result image rendering
+    _last_tool_raw = ""    # full raw content of last tool call
     _idle_ticks = 0
 
     try:
         while True:
             try:
                 logs = get_logs(session_id, after_id=last_id, conn=_poll_conn)
                 _idle_ticks = 0 if logs else _idle_ticks + 1
                 for log in logs:
@@ -924,23 +1042,55 @@ async def stream_logs(orch_name: str, thread_id: int):
                         text = f"{head}\n{c}"
                     elif t == "tool":
                         tool_name = c.split(":")[0].strip() if ":" in c else "tool"
                         tool_body = c[len(tool_name)+1:].strip()[:1200] if ":" in c else c[:1200]
                         icon = _tg_tool_icon(tool_name)
                         short = _tg_tool_short(tool_name)
                         header = f"{icon} {short}"
                         _last_tool_text = f"{header}\n{tool_body}"
-                        _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
+                        _last_tool_name = tool_name
+                        _last_tool_raw = c
+                        # Special formatting for send_message — render as pretty HTML
+                        if "send_message" in tool_name:
+                            try:
+                                import json as _json
+                                colon_idx = c.index(":")
+                                sm_params = _json.loads(c[colon_idx + 1:].strip())
+                                sm_to = sm_params.get("to", "?")
+                                sm_msg = sm_params.get("message", "")
+                                # Convert ```code``` blocks to <pre>, rest HTML-escaped
+                                import re as _re
+                                # Split on code blocks first, then escape non-code parts
+                                parts_sm = _re.split(r'(```[a-z]*\n?.*?```)', sm_msg, flags=_re.DOTALL)
+                                escaped_parts = []
+                                for part in parts_sm:
+                                    if part.startswith('```'):
+                                        inner = _re.sub(r'^```[a-z]*\n?', '', part).rstrip('`').strip()
+                                        escaped_parts.append(f"<pre>{inner}</pre>")
+                                    else:
+                                        escaped_parts.append(part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
+                                sm_html = "".join(escaped_parts)
+                                sm_formatted = f"<b>→ {sm_to}</b>\n\n{sm_html}"
+                                if bot:
+                                    await bot.send_message(config["group_id"], sm_formatted, message_thread_id=thread_id, parse_mode="HTML")
+                            except Exception as _e:
+                                logger.debug(f"send_message pretty format failed: {_e}")
+                                _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
+                        else:
+                            _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                         try:
                             m_text, m_ents = md_convert(f"{header}\n{tool_body}")
                             from aiogram.types import MessageEntity as AioEntity
                             await _mirror_send(orch_name, m_text, entities=[AioEntity(**e.to_dict()) for e in m_ents] if m_ents else None)
                         except Exception:
                             await _mirror_send(orch_name, f"{header}\n{tool_body}")
+                        # Diff image for Edit/Write tools
+                        if tool_name in ("Edit", "Write"):
+                            await _send_diff_image(tool_name, c, config["group_id"], thread_id)
                         continue
                     elif t == "tool_result":
                         result_preview = c[:80].replace("\n", " ").strip()
                         result_body = c[:800]
                         if _last_tool_msg:
                             await _edit_tool_with_result(
                                 _last_tool_msg, config["group_id"],
                                 _last_tool_text, f"📎 {result_preview}", result_body,
@@ -950,16 +1100,21 @@ async def stream_logs(orch_name: str, thread_id: int):
                         else:
                             await _send_expandable(config["group_id"], thread_id, f"📎 {result_preview}", result_body)
                         try:
                             m_text, m_ents = md_convert(f"📎 {result_preview}\n{result_body}")
                             from aiogram.types import MessageEntity as AioEntity
                             await _mirror_send(orch_name, m_text, entities=[AioEntity(**e.to_dict()) for e in m_ents] if m_ents else None)
                         except Exception:
                             await _mirror_send(orch_name, f"📎 {result_preview}\n{result_body}")
+                        # Result image for Read/Grep/Bash tools
+                        if _last_tool_name in ("Read", "Grep", "Bash"):
+                            await _send_result_image(_last_tool_name, _last_tool_raw, c, config["group_id"], thread_id)
+                        _last_tool_name = ""
+                        _last_tool_raw = ""
                         continue
                     elif t == "error":
                         text = f"❌ {c}"
                     elif t == "status":
                         if "turn ended" in c:
                             still_running = _any_running_in_scope(scope)
                             if not still_running:
                                 await _update_topic_status(orch_name, False)


## LATER FIX 83d824805f (8.9 days later): fix: readable bash/read/grep result images — bigger font, word wrap, line limit
lines of origin it changed/deleted: 68
(code only, capped 400 lines)

fix: readable bash/read/grep result images — bigger font, word wrap, line limit


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


## LATER FIX c5faacebdf (10.1 days later): fix: send_message in TG now renders markdown formatting via md_convert instead of raw HTML
lines of origin it changed/deleted: 12
(code only, capped 400 lines)

fix: send_message in TG now renders markdown formatting via md_convert instead of raw HTML


diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index e757cb787..24c3e535b 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -1245,30 +1245,24 @@ async def stream_logs(orch_name: str, thread_id: int):
                         # the recipient name and message body are the useful parts
                         if not _diff_sent and "send_message" in tool_name:
                             try:
                                 import json as _json
                                 colon_idx = c.index(":")
                                 sm_params = _json.loads(c[colon_idx + 1:].strip())
                                 sm_to = sm_params.get("to", "?")
                                 sm_msg = sm_params.get("message", "")
-                                import re as _re
-                                parts_sm = _re.split(r'(```[a-z]*\n?.*?```)', sm_msg, flags=_re.DOTALL)
-                                escaped_parts = []
-                                for part in parts_sm:
-                                    if part.startswith('```'):
-                                        inner = _re.sub(r'^```[a-z]*\n?', '', part).rstrip('`').strip()
-                                        escaped_parts.append(f"<pre>{inner}</pre>")
-                                    else:
-                                        escaped_parts.append(part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
-                                sm_html = "".join(escaped_parts)
-                                sm_formatted = f"✉️ <b>→ {sm_to}</b>\n\n{sm_html}"
-                                if bot:
-                                    await bot.send_message(config["group_id"], sm_formatted, message_thread_id=thread_id, parse_mode="HTML")
-                                    _last_diff_sent = True
+                                sm_md = f"✉️ **→ {sm_to}**\n\n{sm_msg}"
+                                converted, entities = md_convert(sm_md)
+                                from aiogram.types import MessageEntity as AioEntity
+                                aio_ents = [AioEntity(**e.to_dict()) for e in entities] if entities else None
+                                for chunk in _split_message(converted):
+                                    await _tg_send_safe(config["group_id"], chunk, thread_id, entities=aio_ents, important=True)
+                                    aio_ents = None
+                                _last_diff_sent = True
                             except Exception as _e:
                                 logger.debug(f"send_message pretty format failed: {_e}")
                                 _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                         elif not _diff_sent:
                             _skip_expandable = (tool_name in ("Read", "Grep", "Bash", "Glob") and _result_images_enabled())
                             if not _skip_expandable:
                                 _last_tool_msg = await _send_expandable(config["group_id"], thread_id, header, tool_body)
                         try:


## LATER FIX d206a4c448 (32.2 days later): fix: no character loss — wrap instead of truncate everywhere
lines of origin it changed/deleted: 23
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