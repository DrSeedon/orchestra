# Candidate cand-26

## ORIGIN commit 538a2f5688 (2026-07-07): fix: send_file shows Download/Preview instead of 'Disabled on server'
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/routes/system.py b/app/routes/system.py
index bef4d9a65..1b7e96ed2 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -192,24 +192,27 @@ def _is_safe_path(path: str) -> bool:
 BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
                      '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z',
                      '.exe', '.bin', '.so', '.whl', '.dll', '.dylib', '.pyc',
                      '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.mp3', '.mp4',
                      '.wav', '.avi', '.mov', '.ttf', '.otf', '.woff', '.woff2'}
 
 
 @router.get("/api/files/raw")
-async def get_file_raw(path: str):
+async def get_file_raw(path: str, download: bool = False):
     if not _is_safe_path(path):
         return JSONResponse({"error": "access denied"}, status_code=403)
     from starlette.responses import FileResponse
     target = Path(path)
     if not target.is_file():
         return JSONResponse({"error": "not found"}, status_code=404)
-    return FileResponse(str(target))
+    # download=1 forces a save dialog (Content-Disposition: attachment); default lets
+    # the browser render inline (used for HTML preview in a new tab).
+    filename = target.name if download else None
+    return FileResponse(str(target), filename=filename)
 
 
 @router.get("/api/files/content")
 async def get_file_content(path: str):
     if not _is_safe_path(path):
         return JSONResponse({"error": "access denied"}, status_code=403)
     target = Path(path)
     if not target.exists():
diff --git a/app/static/js/app.js b/app/static/js/app.js
index cc4dd8493..60dac8cd0 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -3103,28 +3103,36 @@ function addChatEntry(type, content, ts, anchor, payload) {
                 const hdr = lastTool.querySelector('.flex.items-center');
                 const hasError = content.includes('error') || content.includes('Error') || content.includes('failed');
                 if (hdr) {
                     hdr.textContent = hasError ? '❌ Send failed' : '✅ Sent to TG';
                     hdr.style.color = hasError ? '#ef4444' : '#22c55e';
                 }
                 const fp = lastTool.dataset.filePath;
                 if (!hasError && fp) {
-                    const openBtn = document.createElement('button');
-                    openBtn.textContent = '📂 Открыть';
-                    openBtn.style.cssText = 'margin-top:4px;padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid rgba(99,102,241,0.3);background:rgba(15,23,42,0.95);color:#a5b4fc;cursor:pointer;transition:all 0.15s;backdrop-filter:blur(8px)';
-                    openBtn.onmouseenter = () => { openBtn.style.borderColor = 'rgba(99,102,241,0.6)'; openBtn.style.color = '#c7d2fe'; };
-                    openBtn.onmouseleave = () => { openBtn.style.borderColor = 'rgba(99,102,241,0.3)'; openBtn.style.color = '#a5b4fc'; };
-                    openBtn.onclick = () => {
-                        fetch(`/api/open-file?path=${encodeURIComponent(fp)}`)
-                            .then(r => { if (r.status === 403) throw new Error('disabled'); if (!r.ok) throw new Error('fail'); return r.json(); })
-                            .then(() => { openBtn.textContent = '✅ Opened'; setTimeout(() => { openBtn.textContent = '📂 Открыть'; }, 1500); })
-                            .catch(e => { openBtn.textContent = e.message === 'disabled' ? '🚫 Disabled on server' : '❌ Not found'; setTimeout(() => { openBtn.textContent = '📂 Открыть'; }, 2000); });
+                    const btnRow = document.createElement('div');
+                    btnRow.style.cssText = 'margin-top:4px;display:flex;gap:6px;flex-wrap:wrap';
+                    const _fileBtn = (label, onClick) => {
+                        const b = document.createElement('button');
+                        b.textContent = label;
+                        b.style.cssText = 'padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid rgba(99,102,241,0.3);background:rgba(15,23,42,0.95);color:#a5b4fc;cursor:pointer;transition:all 0.15s;backdrop-filter:blur(8px)';
+                        b.onmouseenter = () => { b.style.borderColor = 'rgba(99,102,241,0.6)'; b.style.color = '#c7d2fe'; };
+                        b.onmouseleave = () => { b.style.borderColor = 'rgba(99,102,241,0.3)'; b.style.color = '#a5b4fc'; };
+                        b.onclick = onClick;
+                        return b;
                     };
-                    lastTool.appendChild(openBtn);
+                    btnRow.appendChild(_fileBtn('📥 Download', () => {
+                        window.open(`/api/files/raw?path=${encodeURIComponent(fp)}&download=1`, '_blank');
+                    }));
+                    if (/\.html?$/i.test(fp)) {
+                        btnRow.appendChild(_fileBtn('👁 Preview', () => {
+                            window.open(`/api/files/raw?path=${encodeURIComponent(fp)}`, '_blank');
+                        }));
+                    }
+                    lastTool.appendChild(btnRow);
                 }
                 addTimestamp(lastTool, ts);
                 return;
             }
             const _tmTools = ['mcp__orchestra__task_create','mcp__orchestra__task_update','mcp__orchestra__task_list','mcp__orchestra__task_get','mcp__orchestra__payment_receive','mcp__orchestra__payment_status','mcp__orchestra__bg_list','mcp__orchestra__get_worker_info'];
             if (_tmTools.includes(lastTool.dataset.toolRawName)) {
                 const hdr = lastTool.querySelector('.flex.items-center');
                 let parsed = null;


## LATER FIX 65e7e3cf70 (17.2 days later): fix: sandbox HTML artifact previews
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

fix: sandbox HTML artifact previews


diff --git a/app/routes/system.py b/app/routes/system.py
index 75b528c19..810b1e65d 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -207,20 +207,27 @@ BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
 @router.get("/api/files/raw")
 async def get_file_raw(path: str, download: bool = False):
     if not _is_safe_path(path):
         return JSONResponse({"error": "access denied"}, status_code=403)
     from starlette.responses import FileResponse
     target = Path(path)
     if not target.is_file():
         return JSONResponse({"error": "not found"}, status_code=404)
+    headers = {}
+    if target.suffix.lower() in {".html", ".htm"}:
+        headers["Content-Security-Policy"] = (
+            "sandbox allow-scripts; "
+            "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
+            "connect-src 'none'"
+        )
     # download=1 forces a save dialog (Content-Disposition: attachment); default lets
-    # the browser render inline (used for HTML preview in a new tab).
+    # the browser render HTML inline under the sandbox CSP.
     filename = target.name if download else None
-    return FileResponse(str(target), filename=filename)
+    return FileResponse(str(target), filename=filename, headers=headers)
 
 
 @router.get("/api/files/content")
 async def get_file_content(path: str):
     if not _is_safe_path(path):
         return JSONResponse({"error": "access denied"}, status_code=403)
     target = Path(path)
     if not target.exists():
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 6029c412f..e76592fed 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -510,17 +510,17 @@ async function openFilePreview(path) {
     dlBtn.href = rawUrl;
     dlBtn.download = fileName;
     dlBtn.classList.remove('hidden');
     if (/\.html?$/i.test(path)) {
         openBtn.href = rawUrl;
         openBtn.classList.remove('hidden');
         contentEl.className = 'flex-1 p-0';
         contentEl.style.cssText = 'overflow:hidden;max-height:calc(80vh - 48px)';
-        contentEl.innerHTML = `<iframe src="${rawUrl}" style="width:100%;height:100%;border:none;border-radius:0 0 12px 12px;min-height:60vh" sandbox="allow-scripts allow-same-origin"></iframe>`;
+        contentEl.innerHTML = `<iframe src="${rawUrl}" style="width:100%;height:100%;border:none;border-radius:0 0 12px 12px;min-height:60vh" sandbox="allow-scripts"></iframe>`;
         return;
     }
     openBtn.classList.add('hidden');
     try {
         const res = await fetch(`/api/files/content?path=${encodeURIComponent(path)}`);
         const data = await res.json();
         if (data.error) {
             const sizeStr = data.size ? ` (${(data.size / 1024).toFixed(1)} KB)` : '';
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index b4ae4ecd6..937ff5ed9 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -1,21 +1,67 @@
 """Playwright smoke tests for Orchestra dashboard.
 
 Requires: Orchestra running on localhost:8888 (no auth).
 Run: pytest tests/test_frontend.py -v
 """
 
 import os
+import re
 from pathlib import Path
 
 import pytest
 from playwright.sync_api import Browser, Page, expect, sync_playwright
 
 BASE = os.environ.get("ORCHESTRA_TEST_BASE", "http://localhost:8888")
+HTML_ARTIFACT_CSP = (
+    "sandbox allow-scripts; "
+    "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
+    "connect-src 'none'"
+)
+
+
+def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
+    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
+    html_branch = source.split("if (/\\.html?$/i.test(path)) {", 1)[1].split(
+        "return;", 1,
+    )[0]
+    match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)
+
+    assert match
+    assert "openBtn.href = rawUrl;" in html_branch
+    assert set(match.group(1).split()) == {"allow-scripts"}
+    assert "allow-same-origin" not in match.group(1)
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize("suffix", [".html", ".HTM"])
+async def test_raw_html_response_has_sandbox_csp(tmp_path, monkeypatch, suffix):
+    from app.routes import system
+
+    target = tmp_path / f"artifact{suffix}"
+    target.write_text("<script>document.body.textContent = 'works'</script>")
+    monkeypatch.setattr(system, "_ALLOWED_ROOTS", [str(tmp_path)])
+
+    response = await system.get_file_raw(str(target))
+
+    assert response.headers["content-security-policy"] == HTML_ARTIFACT_CSP
+
+
+@pytest.mark.asyncio
+async def test_raw_non_html_response_has_no_artifact_csp(tmp_path, monkeypatch):
+    from app.routes import system
+
+    target = tmp_path / "notes.txt"
+    target.write_text("safe text")
+    monkeypatch.setattr(system, "_ALLOWED_ROOTS", [str(tmp_path)])
+
+    response = await system.get_file_raw(str(target))
+
+    assert "content-security-policy" not in response.headers
 
 
 @pytest.fixture(scope="module")
 def dashboard_browser():
     with sync_playwright() as playwright:
         browser = playwright.chromium.launch()
         yield browser
         browser.close()