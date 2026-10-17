# Candidate cand-32

## ORIGIN commit 853a3903a2 (2026-06-12): fix: show original quality images from Read — API for dashboard, send_photo for TG (no more base64 spam)
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 2897117d5..65efa9fe8 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2607,16 +2607,19 @@ function addChatEntry(type, content, ts, anchor) {
                 header.style.color = '#38bdf8';
                 div.dataset.isGrep = '1';
                 div.dataset.grepPattern = d.pattern || '';
                 div.dataset.grepPath = grepPath;
             } catch {}
         }
         const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
         const isReadTool = rawName === 'Read';
+        if (isReadTool) {
+            try { const d = JSON.parse(body); if (d.file_path) div.dataset.filePath = d.file_path; } catch {}
+        }
         const diffEl = isEditTool ? renderEditDiff(body) : null;
         const readEl = isReadTool ? renderReadView(body) : null;
 
         if (readEl) {
             div.appendChild(readEl);
             div.dataset.isRead = '1';
             div.style.cursor = 'pointer';
             div.addEventListener('click', () => {
@@ -2698,19 +2701,23 @@ function addChatEntry(type, content, ts, anchor) {
             if (lastTool) {
                 delete lastTool.dataset.lastTool;
                 const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
                 if (skeleton) skeleton.remove();
             }
             const target = lastTool || div;
             if (b64Match) {
                 const img = document.createElement('img');
-                img.src = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
+                // Use original file via API if Read tool has file_path — SDK compresses base64
+                const origPath = lastTool && lastTool.dataset.filePath;
+                const thumbSrc = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
+                img.src = origPath ? `/api/files/raw?path=${encodeURIComponent(origPath)}` : thumbSrc;
+                img.onerror = () => { img.src = thumbSrc; };
                 img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;margin-top:6px;cursor:pointer';
-                img.addEventListener('click', () => _showImageOverlay(img.src));
+                img.addEventListener('click', () => _showImageOverlay(origPath ? img.src : thumbSrc));
                 target.appendChild(img);
             } else {
                 const placeholder = document.createElement('div');
                 placeholder.className = 'text-xs';
                 placeholder.style.cssText = 'color:#64748b;margin-top:4px';
                 placeholder.textContent = '🖼 [Image result]';
                 target.appendChild(placeholder);
             }
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index a41708f08..bd689d698 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -1252,16 +1252,35 @@ async def stream_logs(orch_name: str, thread_id: int):
                                     await _mirror_send(orch_name, pretty)
                                     _last_tool_msg = None
                                     _last_tool_text = ""
                                     _last_tool_name = ""
                                     _last_tool_raw = ""
                                     continue
                             except Exception as e:
                                 logger.debug(f"worker_info pretty-print failed, falling back to raw: {e}")
+                        # Read tool returned an image — send original file instead of base64 spam
+                        if _last_tool_name == "Read" and ("'type': 'image'" in c or '"type": "image"' in c or "'type':'image'" in c):
+                            try:
+                                import json as _json
+                                _colon = _last_tool_raw.index(":")
+                                _read_params = _json.loads(_last_tool_raw[_colon + 1:].strip())
+                                _img_path = _read_params.get("file_path", "")
+                                if _img_path and Path(_img_path).is_file():
+                                    from aiogram.types import FSInputFile
+                                    await bot.send_photo(config["group_id"], FSInputFile(_img_path),
+                                                         message_thread_id=thread_id, caption=f"📷 {Path(_img_path).name}")
+                                    if _last_tool_msg:
+                                        _last_tool_msg = None
+                                        _last_tool_text = ""
+                                    _last_tool_name = ""
+                                    _last_tool_raw = ""
+                                    continue
+                            except Exception as _e:
+                                logger.debug(f"Read image send failed, falling back: {_e}")
                         result_preview = c[:80].replace("\n", " ").strip()
                         result_body = c[:800]
                         # Result image for Read/Grep/Bash — if sent, skip text
                         _result_img_sent = False
                         if _last_tool_name in ("Read", "Grep", "Bash"):
                             _result_img_sent = await _send_result_image(_last_tool_name, _last_tool_raw, c, config["group_id"], thread_id)
                         if not _result_img_sent:
                             if _last_tool_msg:


## LATER FIX 8b07359500 (60.9 days later): #212: #212: restore truncated Read images from full log
lines of origin it changed/deleted: 5
(code only, capped 400 lines)

#212: #212: restore truncated Read images from full log


diff --git a/app/static/js/app.js b/app/static/js/app.js
index 67a34e7fe..3ce8de982 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -92,16 +92,58 @@ function _stampChatLogNode(node, payload) {
 
 // Обрезанное сообщение не должно выглядеть законченным. Маркер вешается в _insert —
 // единственной воронке, через которую узлы попадают в чат, поэтому он один на все ветки
 // отрисовки (текст, инструмент, картинка).
 function _fmtKb(bytes) {
     return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} МБ` : `${Math.round(bytes / 1024)} КБ`;
 }
 
+function _toolResultImageSrc(content) {
+    const data = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{100,})['"]/);
+    if (!data) return '';
+    const media = content.match(/['"]?media_type['"]?\s*[:=]\s*['"]([^'"]+)['"]/);
+    return `data:${media?.[1] || 'image/png'};base64,${data[1].replace(/\s/g, '')}`;
+}
+
+function _loadImageSrc(img, src) {
+    if (!src) return Promise.resolve(false);
+    return new Promise(resolve => {
+        const done = ok => {
+            img.onload = null;
+            img.onerror = null;
+            resolve(ok);
+        };
+        img.onload = () => done(true);
+        img.onerror = () => done(false);
+        img.src = src;
+    });
+}
+
+async function _restoreToolResultImage(img, payload) {
+    if (!payload?.id) return false;
+    try {
+        const full = await api(`/api/logs/${payload.id}`);
+        const src = _toolResultImageSrc(full.content || '');
+        return _loadImageSrc(img, src);
+    } catch (e) {
+        console.warn(`Image result ${payload.id} unavailable: ${e.name}: ${e.message}`);
+        return false;
+    }
+}
+
+async function _loadToolResultImage(img, origPath, inlineSrc, payload) {
+    if (origPath) {
+        const rawSrc = `/api/files/raw?path=${encodeURIComponent(origPath)}&t=${Date.now()}`;
+        if (await _loadImageSrc(img, rawSrc)) return true;
+    }
+    if (await _loadImageSrc(img, inlineSrc)) return true;
+    return _restoreToolResultImage(img, payload);
+}
+
 function _attachTruncNotice(node, row, type, ts) {
     const shown = new TextEncoder().encode(row.content || '').length;
     const notice = document.createElement('div');
     notice.className = 'trunc-notice';
     const text = document.createElement('span');
     text.textContent = `✂️ показано ${_fmtKb(shown)} из ${_fmtKb(row.trunc)}`;
     const btn = document.createElement('button');
     btn.type = 'button';
@@ -4805,33 +4847,35 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     header.style.color = '#64748b';
                 }
                 delete lastTool.dataset.lastTool;
                 addTimestamp(lastTool, ts);
                 return;
             }
         }
         if (_isBase64Image) {
-            const b64Match = content.match(/data['":\s]+['"]([A-Za-z0-9+/=\s]{100,})['"]/);
+            const inlineSrc = _toolResultImageSrc(content);
             if (lastTool) {
                 delete lastTool.dataset.lastTool;
                 const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
                 if (skeleton) skeleton.remove();
             }
             const target = lastTool || div;
-            if (b64Match) {
+            const origPath = lastTool && lastTool.dataset.filePath;
+            if (inlineSrc || origPath || payload?.id) {
                 const img = document.createElement('img');
-                // Use original file via API if Read tool has file_path — SDK compresses base64
-                const origPath = lastTool && lastTool.dataset.filePath;
-                const thumbSrc = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
-                img.src = origPath ? `/api/files/raw?path=${encodeURIComponent(origPath)}&t=${Date.now()}` : thumbSrc;
-                img.onerror = () => { img.src = thumbSrc; };
                 img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;margin-top:6px;cursor:pointer';
-                img.addEventListener('click', () => _showImageOverlay(origPath ? img.src : thumbSrc));
+                img.style.display = 'none';
+                img.addEventListener('click', () => _showImageOverlay(img.src));
                 target.appendChild(img);
+                // Use original file via API if Read tool has file_path — SDK compresses base64
+                _loadToolResultImage(img, origPath, inlineSrc, payload).then(ok => {
+                    if (ok) img.style.display = '';
+                    else img.replaceWith(Object.assign(document.createElement('div'), {textContent: '🖼 Image unavailable'}));
+                });
             } else {
                 const placeholder = document.createElement('div');
                 placeholder.className = 'text-xs';
                 placeholder.style.cssText = 'color:#64748b;margin-top:4px';
                 placeholder.textContent = '🖼 [Image result]';
                 target.appendChild(placeholder);
             }
             addTimestamp(target, ts);
diff --git a/docs/tasks/212/read-image-restored.png b/docs/tasks/212/read-image-restored.png
new file mode 100644
index 000000000..c4802f79a
Binary files /dev/null and b/docs/tasks/212/read-image-restored.png differ
diff --git a/docs/tasks/212/verify-read-image.py b/docs/tasks/212/verify-read-image.py
new file mode 100644
index 000000000..36e409162
--- /dev/null
+++ b/docs/tasks/212/verify-read-image.py
@@ -0,0 +1,91 @@
+"""Live browser acceptance for #212 using a real persisted Read image result."""
+from pathlib import Path
+from urllib.parse import parse_qs, urlparse
+
+from dotenv import dotenv_values
+from playwright.sync_api import sync_playwright
+
+
+ROOT = Path(__file__).resolve().parents[3]
+APP_JS = ROOT / "app/static/js/app.js"
+OUT = Path(__file__).with_name("read-image-restored.png")
+BASE = "http://127.0.0.1:8888"
+TOOL_ID = 70425
+RESULT_ID = 70427
+IMAGE_PATH = "/home/kesha/orchestra/data/uploads/0d6cf8360135.webp"
+
+
+def main() -> None:
+    env = dotenv_values("/home/kesha/orchestra/.env")
+    headers = {"Authorization": f"Bearer {env['INTERNAL_TOKEN']}"}
+    hits = {"app.js": 0, "missing_source": 0, "full_log": 0}
+
+    with sync_playwright() as playwright:
+        browser = playwright.chromium.launch(args=["--no-sandbox"])
+        context = browser.new_context(extra_http_headers=headers, viewport={"width": 1100, "height": 760})
+        page = context.new_page()
+
+        def route_js(route):
+            hits["app.js"] += 1
+            route.fulfill(status=200, content_type="text/javascript", body=APP_JS.read_text())
+
+        def route_raw(route):
+            path = parse_qs(urlparse(route.request.url).query).get("path", [""])[0]
+            if path == IMAGE_PATH:
+                hits["missing_source"] += 1
+                route.fulfill(status=404)
+            else:
+                route.continue_()
+
+        page.route("**/static/js/app.js*", route_js)
+        page.route("**/api/files/raw?**", route_raw)
+        page.on(
+            "response",
+            lambda response: hits.__setitem__(
+                "full_log", hits["full_log"] + (response.url.endswith(f"/api/logs/{RESULT_ID}"))
+            ),
+        )
+        page.goto(BASE, wait_until="load")
+        page.wait_for_function("() => typeof _restoreToolResultImage === 'function'")
+        page.wait_for_function("() => typeof selectedAgent !== 'undefined' && selectedAgent !== null")
+        page.evaluate(
+            """async ([toolId, resultId]) => {
+                selectedAgent = null;
+                if (eventSource) { eventSource.close(); eventSource = null; }
+                window.compactMode = false;
+                $('#chat').innerHTML = '';
+                const tool = await api(`/api/logs/${toolId}`);
+                const result = await api(`/api/logs/${resultId}`);
+                const clipped = result.content.slice(0, 16384);
+                addChatEntry(tool.type, tool.content, tool.ts, null, tool);
+                addChatEntry(result.type, clipped, result.ts, null, {
+                    ...result,
+                    content: clipped,
+                    trunc: new TextEncoder().encode(result.content).length,
+                });
+            }""",
+            [TOOL_ID, RESULT_ID],
+        )
+        page.wait_for_function("() => $('#chat img')?.naturalWidth > 0")
+        observed = page.evaluate(
+            """() => ({
+                width: $('#chat img').naturalWidth,
+                height: $('#chat img').naturalHeight,
+                placeholder: $('#chat').textContent.includes('[Image result]'),
+                source: $('#chat img').src.slice(0, 32),
+            })"""
+        )
+        # One full-log request builds the truncated fixture; the second is the fallback itself.
+        if hits != {"app.js": 1, "missing_source": 1, "full_log": 2}:
+            raise RuntimeError(f"unexpected request path: {hits}")
+        if observed["placeholder"] or observed["width"] <= 0:
+            raise RuntimeError(f"image was not restored: {observed}")
+        page.locator("#chat").screenshot(path=OUT)
+        print(f"hits={hits}")
+        print(f"image={observed}")
+        print(f"screenshot={OUT}")
+        browser.close()
+
+
+if __name__ == "__main__":
+    main()
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 53bf9c68e..2021b65d5 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1379,8 +1379,132 @@ def test_codex_view_image_loads_eagerly(
 
     page.wait_for_function(
         "() => document.querySelector('#chat .codex-tool-image')?.naturalWidth > 0"
     )
     assert image.evaluate("(img) => img.naturalWidth") == 2800
     assert requests == 2
     expect(image).not_to_have_class("codex-tool-image-error")
     page.close()
+
+
+def test_truncated_read_image_restores_full_log_when_source_file_is_gone(
+    dashboard_browser: Browser,
+):
+    root = Path(__file__).parent.parent
+    source = (root / "app/static/js/app.js").read_text()
+    page = dashboard_browser.new_page()
+    png = (
+        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
+        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
+    )
+    requests = {"file": 0, "log": []}
+
+    def missing_source(route):
+        requests["file"] += 1
+        route.fulfill(status=404)
+
+    def full_log(route):
+        log_id = int(route.request.url.rsplit("/", 1)[-1])
+        requests["log"].append(log_id)
+        image_data = png + " " * 20 if log_id == 42 else "A" * 120
+        route.fulfill(
+            status=200,
+            content_type="application/json",
+            json={
+                "id": log_id,
+                "type": "tool_result",
+                "content": (
+                    "{'type': 'image', 'source': {'type': 'base64', 'data': '"
+                    + image_data
+                    + "', 'media_type': 'image/png'}}"
+                ),
+            },
+        )
+
+    page.route("**/api/files/raw?**", missing_source)
+    page.route(re.compile(r".*/api/logs/\d+$"), full_log)
+    page.route(
+        "**/static/js/app.js*",
+        lambda route: route.fulfill(
+            status=200, content_type="text/javascript", body=source,
+        ),
+    )
+    _goto_dashboard_or_skip(page)
+    page.wait_for_function("() => typeof _restoreToolResultImage === 'function'")
+    page.wait_for_function(
+        "() => typeof selectedAgent !== 'undefined' && selectedAgent !== null"
+    )
+    page.evaluate(
+        """() => {
+            selectedAgent = null;
+            if (eventSource) {
+                eventSource.close();
+                eventSource = null;
+            }
+            window.compactMode = false;
+            document.querySelector('#chat').innerHTML = '';
+            addChatEntry(
+                'tool',
+                'Read: {"file_path":"/tmp/already-gone.png"}',
+                null, null, {tool_use_id: 'read-1'}
+            );
+            addChatEntry(
+                'tool_result',
+                "{'type': 'image', 'source': {'type': 'base64', 'data': 'cut",
+                null, null,
+                {id: 42, trunc: 50000, tool_use_id: 'read-1'}
+            );
+        }"""
+    )
+
+    page.wait_for_timeout(1000)
+    state = page.evaluate(
+        """() => ({
+            html: $('#chat').innerHTML,
+            src: $('#chat img')?.src,
+            width: $('#chat img')?.naturalWidth,
+        })"""
+    )
+    image = page.locator("#chat img")
+    assert state["width"] == 1, (state, requests)
+    assert image.evaluate("img => [img.naturalWidth, img.naturalHeight]") == [1, 1]
+    expect(page.locator("#chat")).not_to_contain_text("[Image result]")
+    assert requests == {"file": 1, "log": [42]}
+
+    page.evaluate(
+        """() => {
+            document.querySelector('#chat').innerHTML = '';
+            addChatEntry(
+                'tool',
+                'Read: {"file_path":"/tmp/already-gone.png"}',
+                null, null, {tool_use_id: 'read-2'}
+            );
+            addChatEntry(
+                'tool_result',
+                "{'type': 'image', 'source': {'type': 'base64', 'data': '"
+                    + 'A'.repeat(120) + "', 'media_type': 'image/png'}}",
+                null, null, {id: 42, tool_use_id: 'read-2'}
+            );
+        }"""
+    )
+    page.wait_for_function("() => $('#chat img')?.naturalWidth === 1")
+    assert requests == {"file": 2, "log": [42, 42]}
+
+    page.evaluate(
+        """() => {
+            document.querySelector('#chat').innerHTML = '';
+            addChatEntry(
+                'tool',
+                'Read: {"file_path":"/tmp/already-gone.png"}',
+                null, null, {tool_use_id: 'read-3'}
+            );
+            addChatEntry(
+                'tool_result',
+                "{'type': 'image', 'source': {'type': 'base64', 'data': 'cut",
+                null, null, {id: 43, trunc: 50000, tool_use_id: 'read-3'}
+            );
+        }"""
+    )
+    expect(page.locator("#chat")).to_contain_text("Image unavailable")
+    assert page.locator("#chat img").count() == 0
+    assert requests == {"file": 3, "log": [42, 42, 43]}
+    page.close()