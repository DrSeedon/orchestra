# Candidate cand-56

## ORIGIN commit 65e7e3cf70 (2026-07-24): fix: sandbox HTML artifact previews
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

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


## LATER FIX 6ba1141c91 (73.6 days later): V-736: #V-736: restore CI on main
lines of origin it changed/deleted: 13
(code only, capped 400 lines)

V-736: #V-736: restore CI on main

Orchestra-Operation: 8b660deb-845c-446d-923b-e05e589ee683


diff --git a/app/db.py b/app/db.py
index fafad79cf..83981113d 100644
--- a/app/db.py
+++ b/app/db.py
@@ -2372,24 +2372,24 @@ def usage_exchange_rate(hours: int = 72, min_five_hour_pct: float = 30.0) -> dic
 def _usage_providers_from_row(row: dict) -> dict:
     providers = json.loads(row.pop("provider_usage", "{}") or "{}")
     if providers:
         return providers
     windows = []
     # NULL в колонке = источник молчал (#150). Окно без числа — не точка данных:
     # отдать его с `utilization: None` значило бы переложить ноль на потребителя.
     fh_pct, sd_pct = row.get("five_hour_pct"), row.get("seven_day_pct")
-    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct == 0):
+    if fh_pct is not None:
         windows.append({
             "id": "five_hour", "label": "5h",
             "utilization": fh_pct,
             "window_minutes": 300,
             "resets_at": row.get("five_hour_resets_at") or None,
         })
-    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct == 0):
+    if sd_pct is not None:
         windows.append({
             "id": "seven_day", "label": "7d",
             "utilization": sd_pct,
             "window_minutes": 10080,
             "resets_at": row.get("seven_day_resets_at") or None,
         })
     return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}
 
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 9afc2c5e5..a7de05d73 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -3287,16 +3287,27 @@ async def switch_branch(name: str, req: dict):
                                 "error": (
                                     f"cannot close task {previous_task_id} as done: "
                                     f"{held_work['reason']}; merge or discard that work first"
                                 ),
                                 "waited_seconds": round(waited_seconds, 2),
                             },
                             status_code=409,
                         )
+                    elif force:
+                        return JSONResponse(
+                            {
+                                "error": (
+                                    f"cannot switch away from task {previous_task_id}: "
+                                    f"{held_work['reason']} — merge or discard that work first"
+                                ),
+                                "waited_seconds": round(waited_seconds, 2),
+                            },
+                            status_code=409,
+                        )
                 try:
                     verdict = await asyncio.to_thread(
                         _existing_branch_verdict, worktree_path, new_branch,
                         found.scope or scope, force,
                     )
                     if verdict.get("error"):
                         return JSONResponse(
                             {**verdict, "waited_seconds": round(waited_seconds, 2)},
diff --git a/tests/test_explainer_video.py b/tests/test_explainer_video.py
index c883ddff5..81844256d 100644
--- a/tests/test_explainer_video.py
+++ b/tests/test_explainer_video.py
@@ -7,16 +7,27 @@ import importlib.util
 from pathlib import Path
 
 ROOT = Path(__file__).resolve().parents[1]
 spec = importlib.util.spec_from_file_location("explainer_make", ROOT / "scripts/explainer_video/make.py")
 make = importlib.util.module_from_spec(spec)
 spec.loader.exec_module(make)
 
 
+def _mock_tts_installation(tmp_path, monkeypatch):
+    python = tmp_path / "venv" / "bin" / "python"
+    python.parent.mkdir(parents=True)
+    python.write_text("test interpreter placeholder")
+    model = tmp_path / "vosk-model"
+    model.mkdir()
+    (model / "model.onnx").touch()
+    monkeypatch.setattr(make, "TTS_PYTHON", python)
+    monkeypatch.setattr(make, "TTS_MODEL", model)
+
+
 def test_deepgram_digits_latin_and_glued_words_match_screen_text():
     heard = make.tokens("а deepinfra иstreamlake держат кэш 7680 токенов")
     say, sub = "А Дип Инфра и Стрим Лейк держат кеш", "А DeepInfra и StreamLake держат кеш, 7 680 токенов"
     assert all(h is not None for h in make.align([sub], heard)[0])
     assert None in make.align([say], heard)[0]  # транслитерацию Deepgram пишет латиницей
 
 
 def test_missing_word_is_reported_per_phrase():
@@ -83,16 +94,17 @@ def test_english_voice_reads_latin_and_digits_but_rejects_cyrillic():
     with pytest.raises(SystemExit):
         make.check_steps(ok, "ru")
 
 
 def test_ruaccent_marks_text_before_it_reaches_vosk_synthesis(tmp_path, monkeypatch):
     import json
     import wave
 
+    _mock_tts_installation(tmp_path, monkeypatch)
     monkeypatch.setattr(make.sys, "argv", ["make.py", "scene.html", "--out", str(tmp_path), "--stills"])
     monkeypatch.setattr(make, "read_steps", lambda *_: [{"t": "Лимит", "say": "История лимита.", "sub": None, "hold": None}])
     before_path = list(make.sys.path)
     jobs = []
     accent_calls = []
 
     def fake_accent_process(argv, **kwargs):
         phrases = json.loads(kwargs["input"])
@@ -185,31 +197,33 @@ def test_english_cli_branch_does_not_load_or_run_ruaccent(monkeypatch, tmp_path)
 
     monkeypatch.setattr(make, "synthesize", synthesize)
     monkeypatch.setattr(make, "plan", lambda *_: {"steps": [], "T": 0})
     monkeypatch.setattr(make, "voice_track", lambda *_: None)
     monkeypatch.setattr(make, "render", lambda *_args, **_kwargs: None)
     make.main()
 
 
-def test_missing_ruaccent_fails_with_install_command(monkeypatch):
+def test_missing_ruaccent_fails_with_install_command(tmp_path, monkeypatch):
     import pytest
 
+    _mock_tts_installation(tmp_path, monkeypatch)
     def missing(argv, **_kwargs):
         return make.subprocess.CompletedProcess(argv, 2, stdout="", stderr="RUACCENT_NOT_INSTALLED")
 
     monkeypatch.setattr(make.subprocess, "run", missing)
     with pytest.raises(SystemExit, match="ruaccent==1.5.8.3"):
         make.mark_stress([{"say": "Фраза."}], "ru", enabled=True)
 
 
 def test_cache_key_changes_when_accented_text_changes(tmp_path, monkeypatch):
     import json
     import wave
 
+    _mock_tts_installation(tmp_path, monkeypatch)
     jobs_seen = []
 
     def fake_run(*argv, **kwargs):
         if "tts_worker.py" in argv[1]:
             jobs = json.loads(kwargs["input"])
             jobs_seen.extend(job["text"] for job in jobs)
             for job in jobs:
                 with wave.open(job["out"], "wb") as output:
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index b6909cada..0c6647582 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -11,17 +11,17 @@ import os
 import re
 import socket
 import subprocess
 import tempfile
 import sys
 import time
 import urllib.error
 import urllib.request
-from urllib.parse import quote
+from urllib.parse import parse_qs, quote, urlsplit
 from datetime import datetime, timezone
 from pathlib import Path
 
 import pytest
 from playwright.sync_api import Browser, Page, expect, sync_playwright
 from playwright.sync_api import TimeoutError as PlaywrightTimeout
 from starlette.requests import Request
 
@@ -56,29 +56,16 @@ def _load_i18n(page: Page) -> None:
 _DASHBOARD_START_TIMEOUT_S = 120.0
 HTML_ARTIFACT_CSP = (
     "sandbox allow-scripts; "
     "default-src 'unsafe-inline' 'unsafe-eval' data: blob:; "
     "connect-src 'none'"
 )
 
 
-def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox():
-    source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
-    html_branch = source.split("if (/\\.html?$/i.test(path)) {", 1)[1].split(
-        "return;", 1,
-    )[0]
-    match = re.search(r'<iframe[^`]+sandbox="([^"]+)"', html_branch)
-
-    assert match
-    assert "openBtn.href = rawUrl;" in html_branch
-    assert set(match.group(1).split()) == {"allow-scripts"}
-    assert "allow-same-origin" not in match.group(1)
-
-
 def test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result():
     source = (Path(__file__).parent.parent / "app/static/js/app.js").read_text()
     helper = source.split("function _historyTransferMessage", 1)[1].split(
         "async function _showModelPicker", 1,
     )[0]
     picker = source.split("async function _showModelPicker", 1)[1].split(
         "function updateAgentInfo", 1,
     )[0]
@@ -205,16 +192,40 @@ def test_raw_video_supports_range_and_full_download(tmp_path, monkeypatch):
     assert cached.status_code == 304
     assert cached.content == b""
     assert cached_by_date.status_code == 304
     assert replaced.status_code == 200
     assert replaced.content == b"rewritten media content"
     assert replaced.headers["etag"] != full.headers["etag"]
 
 
+def test_html_preview_uses_protected_raw_url_and_opaque_origin_sandbox(
+    dashboard_browser: Browser,
+):
+    page = dashboard_browser.new_page()
+    _route_frontend_sources(page)
+    page.route(
+        "**/api/files/raw*",
+        lambda route: route.fulfill(status=200, content_type="text/html", body="<p>preview</p>"),
+    )
+    _goto_dashboard(page)
+    page.wait_for_function("() => typeof openFilePreview === 'function'")
+    page.evaluate("openFilePreview('/tmp/harness.html')")
+
+    iframe = page.locator("#file-preview-content iframe")
+    expect(iframe).to_have_count(1)
+    assert set((iframe.get_attribute("sandbox") or "").split()) == {"allow-scripts"}
+    open_link = page.locator("#file-preview-open")
+    assert open_link.get_attribute("target") == "_blank"
+    raw_url = urlsplit(open_link.get_attribute("href") or "")
+    assert raw_url.path == "/api/files/raw"
+    assert parse_qs(raw_url.query)["path"] == ["/tmp/harness.html"]
+    page.close()
+
+
 def _dashboard_base() -> str:
     if not _DASHBOARD_ORIGIN:
         pytest.fail("dashboard fixture did not start — dashboard_browser is required")
     return _DASHBOARD_ORIGIN
 
 
 def _free_port() -> int:
     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
@@ -1724,17 +1735,19 @@ def test_send_file_single_keeps_existing_rendering(
             null,
             null,
             {tool_use_id: 'send-file-test'},
         );
     }""")
 
     card = page.locator('[data-tool-raw-name="mcp__orchestra__send_file"]')
     expect(card.locator(".sf-file-list")).to_have_count(0)
-    expect(card.locator("button")).to_have_count(2)
+    expect(card.locator("button")).to_have_count(3)
+    expect(card.get_by_role("button", name=re.compile("Download"))).to_have_count(1)
+    expect(card.get_by_role("button", name=re.compile("Open"))).to_have_count(1)
     expect(card.locator(".sf-actions")).to_have_count(0)
     page.close()
 
 
 def _open_tool_correlation_page(
     browser: Browser,
     compact_mode: bool,
     source_path: Path | None = None,
diff --git a/tests/test_message_delivery_receipts_380.py b/tests/test_message_delivery_receipts_380.py
index 164f5cf24..64259595e 100644
--- a/tests/test_message_delivery_receipts_380.py
+++ b/tests/test_message_delivery_receipts_380.py
@@ -1476,19 +1476,19 @@ async def test_t380_r7_accept_while_runner_exits_cannot_lose_wake(
     registry = getattr(module, "_target_runner_tasks", None)
     assert isinstance(registry, dict), "#380 missing behavior: per-target runner registry"
     empty_seen = threading.Event()
     allow_empty_return = threading.Event()
     inserted = []
     thread_failures = []
     gated_once = False
 
-    def gated_next(target_session_id):
+    def gated_next(target_session_id, *, connection=None):
         nonlocal gated_once
-        row = next_delivery(target_session_id)
+        row = next_delivery(target_session_id, connection=connection)
         if row is None and not gated_once:
             gated_once = True
             empty_seen.set()
             assert allow_empty_return.wait(2), "#380 lost-wake insertion thread stalled"
         return row
 
     monkeypatch.setattr(module, "_next_target_delivery", gated_next)
     manager = _ImmediateManager()
diff --git a/tests/test_model_text_control_flow.py b/tests/test_model_text_control_flow.py
index 2591c6a9c..26ff6d9c7 100644
--- a/tests/test_model_text_control_flow.py
+++ b/tests/test_model_text_control_flow.py
@@ -183,17 +183,18 @@ def test_claude_adapter_keeps_primary_limit_signal(status):
     from app.backend_claude import ClaudeBackend
     backend = ClaudeBackend(model='claude-sonnet-5[1m]', cwd='/tmp')
     converted = backend._convert(RateLimitEvent(
         rate_limit_info=RateLimitInfo(status=status, rate_limit_type='seven_day',
                                      overage_status='rejected', resets_at=2000000000),
         uuid='signal-id', session_id='session'))
     event = next(e for e in converted if e.type == 'provider_limit')
     assert event.metadata == {'status': status, 'rate_limit_type': 'seven_day',
-                             'resets_at': 2000000000, 'overage_status': 'rejected', 'event_id': 'signal-id'}
+                             'resets_at': 2000000000, 'overage_status': 'rejected',
+                             'event_id': 'signal-id', 'raw': {}}
 
 
 @pytest.mark.asyncio
 async def test_limit_arriving_during_admission_stops_retry_before_submit(session):
     from app.events import MessageProvenance
     entered = asyncio.Event()
     release = asyncio.Event()
     async def admission(_model):
diff --git a/tests/test_switch_after_continue_620.py b/tests/test_switch_after_continue_620.py
index c02a85348..e469c0049 100644
--- a/tests/test_switch_after_continue_620.py
+++ b/tests/test_switch_after_continue_620.py
@@ -117,17 +117,17 @@ async def test_switch_releases_clean_worker_and_requeues_previous_task(monkeypat
 
     result = await _switch(name, repo, next_ref)
 
     assert result.get("ok") is True, result
     released = _task(current["id"])
     assert (released["status"], released["worker_session_id"]) == ("new", None)
     runs = _runs(name)
     assert (runs[current_ref]["status"], runs[current_ref]["failure_code"]) == (
-        "interrupted", "binding_released",
+        "interrupted", "task_superseded",
     )
     assert runs[next_ref]["status"] == "requested"
     assigned = _task(following["id"])
     assert (assigned["status"], assigned["worker_session_id"]) == ("in_progress", name)
     lifecycle = get_session(name)
     assert (lifecycle["task_id"], lifecycle["branch"]) == (next_ref, f"task-{next_ref}/{name}")
     assert result["task_status"]["previous_tasks"] == [
         {"task": current_ref, "outcome": "released"},
@@ -186,13 +186,13 @@ async def test_switch_keeps_binding_while_worker_holds_unlanded_work(
     extra = {
         "plain": {},
         "force": {"force": True},
         "complete_previous": {"complete_previous": True, "acceptance_note": "claimed done"},
     }[mode]
 
     result = await _switch(name, repo, tm.public_task_ref(following), **extra)
 
-    if mode == "complete_previous":
+    if mode in {"force", "complete_previous"}:
         assert result.status_code == 409
     else:
         assert result.get("ok") is not True, result
     _assert_still_bound(name, current, following)
diff --git a/tests/test_usage_analytics_frontend.py b/tests/test_usage_analytics_frontend.py
index e3b9cec42..7dde01715 100644
--- a/tests/test_usage_analytics_frontend.py
+++ b/tests/test_usage_analytics_frontend.py
@@ -765,17 +765,17 @@ def test_new_frontend_remains_compatible_with_old_analytics_payload(browser):
     )
 
     page.evaluate("openAnalyticsModal()")
     expect(page.locator(".analytics-kpi-grid > article:first-child")).to_contain_text(
         "716 priced turns"
     )
 
     page.locator('[data-analytics-view="agents"]').click()
-    expect(page.locator("#analytics-agent-table")).to_contain_text("$1,74")
+    expect(page.locator("#analytics-agent-table")).to_contain_text("$1.74")
 
     page.locator('[data-analytics-view="efficiency"]').click()
     expect(page.locator(".analytics-model-list")).to_contain_text("60.8%")
     page.close()
 
 
 def test_modal_has_no_document_overflow_at_390px(browser):
     page = _page(browser, width=390, height=844)
diff --git a/tests/test_usage_readiness.py b/tests/test_usage_readiness.py
index c72554f58..5d9fee21f 100644
--- a/tests/test_usage_readiness.py
+++ b/tests/test_usage_readiness.py
@@ -198,24 +198,24 @@ async def test_readiness_endpoint_returns_the_execution_time_decision(isolated_u
     assert result["state"] == "available" and result["allowed"] is True
     assert result["progress"] is None and result["limit_pct"] is None
     assert result["hard_limit_pct"] == 99.0
 
 
 @pytest.mark.asyncio
 async def test_readiness_endpoint_blocks_above_the_line(isolated_usage):
     data = _anthropic(95)
-    # Ровно середина недельного окна: линия 55.5%, факт 95% — выше неё.
+    # В середине окна линия сдвинута на восемь часов: 59.8333%, факт 95% — выше неё.
     data["seven_day"]["resets_at"] = datetime.fromtimestamp(
         NOW + 10080 * 60 / 2, timezone.utc,
     ).isoformat()
     system._usage_cache.update({"data": data, "ts": NOW})
     result = await system.usage_readiness("claude-opus-5[1m]")
     assert result["state"] == "blocked" and result["allowed"] is False