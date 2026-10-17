# Candidate cand-35

## ORIGIN commit 1fc7a96f46 (2026-08-01): #118: #118: restore chat at last read boundary
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/css/style.css b/app/static/css/style.css
index bbe69ce4b..0b5eaa3c7 100644
--- a/app/static/css/style.css
+++ b/app/static/css/style.css
@@ -41,16 +41,24 @@ code, pre, kbd, samp, .font-mono,
   border: 1px solid rgba(129,140,248,0.55); border-radius: 999px;
   background: rgba(15,23,42,0.94); color: #c7d2fe;
   box-shadow: 0 6px 18px rgba(2,6,23,0.5);
   backdrop-filter: blur(10px); cursor: pointer;
   font-size: 10px; font-weight: 700; line-height: 1;
 }
 .chat-jump-latest:hover { background: #1e293b; color: #eef2ff; border-color: #818cf8; }
 .chat-jump-latest:focus-visible { outline: 2px solid #818cf8; outline-offset: 2px; }
+.chat-unread-divider {
+  display: flex; align-items: center; gap: 8px;
+  color: #f87171; font-size: 10px; font-weight: 700;
+  scroll-margin-top: 4px;
+}
+.chat-unread-divider::before, .chat-unread-divider::after {
+  content: ''; height: 1px; flex: 1; background: rgba(248,113,113,0.5);
+}
 .chat-user { background: rgba(99, 102, 241, 0.15); border-left: 3px solid var(--accent); }
 .chat-bot { border-left: 3px solid rgba(99,102,241,0.1); }
 .chat-tool { background: rgba(56, 189, 248, 0.05); border-left: 3px solid rgba(56, 189, 248, 0.3); font-size: 12px; }
 .chat-tool-result { background: rgba(34, 197, 94, 0.05); border-left: 3px solid rgba(34, 197, 94, 0.2); font-size: 12px; }
 .agent-item { transition: all 0.1s ease; }
 textarea:disabled, button:disabled { opacity: 0.4; cursor: not-allowed; }
 .chat-time { display: block; text-align: right; font-size: 9px; color: var(--ink-faint); margin-top: 4px; }
 .copy-btn { position: absolute; top: 4px; right: 4px; background: none; border: none; cursor: pointer; opacity: 0; transition: opacity 0.15s; font-size: 12px; padding: 2px 4px; border-radius: 6px; }
diff --git a/app/static/js/app.js b/app/static/js/app.js
index f5d9c85b3..d6e5923ca 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -27,27 +27,86 @@ let pendingBubble = null;
 let uiDebounceTimer = null;
 let refreshController = null;
 // UI debounce: rapid-fire messages from the user are batched into one send before the timer fires
 const UI_DEBOUNCE_MS = 2500;
 let scrollAfterLoad = true;
 let drafts = {};
 
 const _CHAT_BOTTOM_GAP = 80;
-let _pendingChatRestoreKey = null;
+const _CHAT_READ_RECEIPTS_KEY = 'orchestraChatReadReceipts';
+let _pendingChatRestore = null;
 let _chatHasNewBelow = false;
+let _chatReadCaptureRaf = null;
 
 function _chatPositionKey(scope = currentScope, agent = selectedAgent) {
     return scope && agent ? `${scope}\u0000${agent}` : '';
 }
 
 function _chatAtBottom(chat = $('#chat')) {
     return !chat || chat.scrollHeight - chat.scrollTop - chat.clientHeight < _CHAT_BOTTOM_GAP;
 }
 
+function _chatReadReceipts() {
+    try {
+        const receipts = JSON.parse(sessionStorage.getItem(_CHAT_READ_RECEIPTS_KEY) || '{}');
+        return receipts && typeof receipts === 'object' && !Array.isArray(receipts) ? receipts : {};
+    } catch (e) {
+        console.warn('Chat read receipts unavailable:', e.name, e.message);
+        return {};
+    }
+}
+
+function _chatReadReceipt(key) {
+    const id = Number(_chatReadReceipts()[key]);
+    return Number.isFinite(id) && id > 0 ? id : null;
+}
+
+function _saveChatReadReceipt(key, id) {
+    if (!key || !Number.isFinite(id) || id <= 0) return;
+    try {
+        const receipts = _chatReadReceipts();
+        if (Number(receipts[key]) >= id) return;
+        receipts[key] = id;
+        sessionStorage.setItem(_CHAT_READ_RECEIPTS_KEY, JSON.stringify(receipts));
+    } catch (e) {
+        console.warn('Chat read receipt save failed:', e.name, e.message);
+    }
+}
+
+function _stampChatLogNode(node, payload) {
+    const id = Number(payload?.id);
+    if (!node || !Number.isFinite(id)) return;
+    node.dataset.chatLogId = String(Math.max(id, Number(node.dataset.chatLogId) || 0));
+}
+
+function _captureChatReadFrontier() {
+    if (scrollAfterLoad) return;
+    const chat = $('#chat');
+    const key = _chatPositionKey();
+    if (!chat || !key) return;
+    const bounds = chat.getBoundingClientRect();
+    let lastVisibleId = null;
+    for (const node of chat.querySelectorAll(':scope > [data-chat-log-id]')) {
+        const rect = node.getBoundingClientRect();
+        if (rect.top < bounds.bottom - 1 && rect.bottom > bounds.top + 1) {
+            lastVisibleId = Math.max(lastVisibleId || 0, Number(node.dataset.chatLogId));
+        }
+    }
+    if (lastVisibleId) _saveChatReadReceipt(key, lastVisibleId);
+}
+
+function _scheduleChatReadCapture() {
+    if (_chatReadCaptureRaf) cancelAnimationFrame(_chatReadCaptureRaf);
+    _chatReadCaptureRaf = requestAnimationFrame(() => {
+        _chatReadCaptureRaf = null;
+        _captureChatReadFrontier();
+    });
+}
+
 function _syncChatJumpButton() {
     const chat = $('#chat');
     const button = $('#chat-jump-latest');
     if (!chat || !button) return;
     if (chat.scrollHeight <= chat.clientHeight + 1 || _chatAtBottom(chat)) {
         _chatHasNewBelow = false;
         button.classList.add('hidden');
         return;
@@ -68,37 +127,40 @@ function _scrollChatToBottom(behavior = 'auto') {
     if (!chat) return;
     _chatHasNewBelow = false;
     chat.scrollTo({top: chat.scrollHeight, behavior});
     _syncChatJumpButton();
 }
 
 function _prepareChatAnchorRestore(hasUnread) {
     clearTimeout(window._scrollResetTimer);
-    _pendingChatRestoreKey = hasUnread ? _chatPositionKey() : null;
+    const key = _chatPositionKey();
+    const afterId = hasUnread ? _chatReadReceipt(key) : null;
+    _pendingChatRestore = afterId ? {key, afterId} : null;
     _chatHasNewBelow = false;
     $('#chat-jump-latest')?.classList.add('hidden');
 }
 
 function _restoreChatAnchor(key) {
-    if (!key || key !== _pendingChatRestoreKey || key !== _chatPositionKey()) return;
-    _pendingChatRestoreKey = null;
+    if (!key || key !== _pendingChatRestore?.key || key !== _chatPositionKey()) return;
+    const {afterId} = _pendingChatRestore;
+    _pendingChatRestore = null;
     const chat = $('#chat');
     if (!chat) return;
-    const userMessages = chat.querySelectorAll('.chat-user');
-    const anchor = userMessages[userMessages.length - 1];
-    if (!anchor) {
-        _scrollChatToBottom();
-        return;
-    }
-    anchor.scrollIntoView({block: 'start'});
-    if (_chatAtBottom(chat)) {
+    const firstUnread = [...chat.querySelectorAll(':scope > [data-chat-log-id]')]
+        .find(node => Number(node.dataset.chatLogId) > afterId);
+    if (!firstUnread) {
         _scrollChatToBottom();
         return;
     }
+    const divider = document.createElement('div');
+    divider.className = 'chat-unread-divider';
+    divider.textContent = 'Непрочитанные';
+    chat.insertBefore(divider, firstUnread);
+    divider.scrollIntoView({block: 'start'});
     _chatHasNewBelow = true;
     _syncChatJumpButton();
 }
 
 function _scheduleChatInitialSettle() {
     const key = _chatPositionKey();
     clearTimeout(window._scrollResetTimer);
     window._scrollResetTimer = setTimeout(() => {
@@ -109,17 +171,20 @@ function _scheduleChatInitialSettle() {
     }, 500);
 }
 
 function initChatPositionMemory() {
     const chat = $('#chat');
     const button = $('#chat-jump-latest');
     if (!chat || !button || chat.dataset.positionReady === '1') return;
     chat.dataset.positionReady = '1';
-    chat.addEventListener('scroll', _syncChatJumpButton, {passive: true});
+    chat.addEventListener('scroll', () => {
+        _syncChatJumpButton();
+        _scheduleChatReadCapture();
+    }, {passive: true});
     button.addEventListener('click', () => _scrollChatToBottom('smooth'));
 }
 
 window.compactMode = localStorage.getItem('compactToolMode') === 'true';
 
 function saveDraft() {
     if (selectedAgent) drafts[selectedAgent] = { text: $('#chat-input').value, images: [...pastedImages] };
 }
@@ -1311,16 +1376,17 @@ function selectOrchestrator(name, scope) {
     localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));
 
     onOrchestratorChange();
     renderOrchTabs(orchData);
 }
 
 async function onOrchestratorChange() {
     saveDraft();
+    _captureChatReadFrontier();
     if (eventSource) { eventSource.close(); eventSource = null; }
     const picker = $('#orch-picker');
     const opt = picker.selectedOptions[0];
     currentScope = picker.value || null;
     const restoreUnreadAnchor = _unreadTabs.delete(currentScope);
     chatLogs = {};
     localMessages.clear();
     pendingUserMsgs = [];
@@ -1346,16 +1412,17 @@ async function onOrchestratorChange() {
     await refreshSessions(); connectSSE(); initFilePanel();
     if (_tasksTabActive) loadTasks();
     if (_jobsTabActive) loadJobs();
 }
 
 // === Agent Selection ===
 async function selectAgent(name) {
     saveDraft();
+    _captureChatReadFrontier();
     if (eventSource) { eventSource.close(); eventSource = null; }
     if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
     localMessages.clear();
     pendingUserMsgs = [];
     pendingBubble = null;
     _finalizedBubble = null;
     selectedAgent = name;
     _hideRateLimitBanner();
@@ -2784,16 +2851,17 @@ function addChatEntry(type, content, ts, anchor, payload) {
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
         appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
         return;
     }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
     const _insert = (el) => {
+        _stampChatLogNode(el, payload);
         if (anchor) return chat.insertBefore(el, anchor);
         const wasAtBottom = _chatAtBottom(chat);
         let inserted;
         if (streamBubble && streamBubble.parentNode === chat) {
             _insertedBeforeStream = true;
             inserted = chat.insertBefore(el, streamBubble);
         } else {
             inserted = chat.appendChild(el);
@@ -2980,17 +3048,19 @@ function addChatEntry(type, content, ts, anchor, payload) {
         streamPending += content;
         if (!_streamRafId) _streamRafId = requestAnimationFrame(_streamRenderTick);
         return;
     }
 
     // 'text' event signals streaming finished — flush typewriter buffer,
     // replace with authoritative DB content, finalize with copy/timestamp.
     if (type === 'text' && streamBubble) {
+        _stampChatLogNode(streamBubble, payload);
         _completeStreamBubble(content, ts);
+        _scheduleChatReadCapture();
         return;
     }
 
     if (type === 'thinking') {
         _removeCodexThinkingLive('reasoning');
         const card = _renderCodexThinking(content, '◇ Reasoning');
         addTimestamp(card, ts);
         _insert(card);
diff --git a/tests/test_frontend.py b/tests/test_frontend.py
index 24298b989..8584fc02f 100644
--- a/tests/test_frontend.py
+++ b/tests/test_frontend.py
@@ -711,133 +711,176 @@ def test_task_card_uses_real_long_description_and_shared_expandable_body(
     expect(page.locator("#xss-card img")).not_to_have_attribute("onerror", "window.taskXss=1")
 
     assert "taskBody.innerHTML = _taskCardBodyHtml(parsed);" in source
     assert "h += _taskCardBodyHtml(t);" in source
     assert "html += _taskCardBodyHtml(t);" in source
     page.close()
 
 
-def test_chat_uses_last_user_message_only_when_unread(
+def test_chat_restores_last_read_boundary_only_when_unread(
     dashboard_browser: Browser,
 ):
     root = Path(__file__).parent.parent
     source = (root / "app/static/js/app.js").read_text()
     helper_code = (
         "const _CHAT_BOTTOM_GAP"
         + source.split("const _CHAT_BOTTOM_GAP", 1)[1].split(
             "window.compactMode", 1,
         )[0]
     )
     page = dashboard_browser.new_page(viewport={"width": 900, "height": 700})
+    page.route(
+        "http://chat-receipts.test/",
+        lambda route: route.fulfill(status=200, content_type="text/html", body=""),
+    )
+    page.goto("http://chat-receipts.test/")
     page.set_content(
         """
         <style>
           .hidden { display:none !important }
           #chat { height:240px; overflow-y:auto }
           #chat > div { height:48px }
+          .chat-unread-divider { height:20px !important }
         </style>
         <div style="position:relative;width:500px">
           <div id="chat"></div>
           <button id="chat-jump-latest" class="hidden"></button>
         </div>
         """
     )
     page.add_script_tag(
         content="""
         const $ = selector => document.querySelector(selector);
         let currentScope = '/scope';
         let selectedAgent = 'agent-a';
         let scrollAfterLoad = false;
         """
         + helper_code
         + """
-        window.fillChat = (withUser = true, userLast = false) => {
+        sessionStorage.clear();
+        window.fillChat = (total = 24, start = 1) => {
             const chat = $('#chat');
             chat.innerHTML = '';
-            const total = 24;
-            for (let i = 0; i < total; i++) {
+            for (let id = start; id < start + total; id++) {
                 const row = document.createElement('div');
-                if (withUser && i === (userLast ? total - 1 : 9)) {
-                    row.className = 'chat-user';
-                    row.textContent = 'my last request';
-                } else {
-                    row.className = 'chat-bot';
-                    row.textContent = `agent work ${i}`;
-                }
+                row.className = 'chat-bot';
+                row.dataset.chatLogId = String(id);
+                row.textContent = `agent work ${id}`;
                 chat.appendChild(row);
             }
             chat.scrollTop = 0;
         };
         initChatPositionMemory();
         """,
     )
 
-    page.evaluate(
+    # Reading in the middle records the lowest visible log, not the user's last message.
+    read_id = page.evaluate(
         """() => {
-            fillChat();
-            $('#chat').scrollTop = $('#chat').scrollHeight;
-            _prepareChatAnchorRestore(false);
-            _restoreChatAnchor(_chatPositionKey());
+            window.fillChat(24);
+            $('#chat').scrollTop = 8 * 48;
+            _captureChatReadFrontier();
+            return _chatReadReceipt(_chatPositionKey());
         }"""
     )
-    assert page.evaluate("() => _chatAtBottom()") is True
-    expect(page.locator("#chat-jump-latest")).to_be_hidden()
+    assert 9 <= read_id < 24
 
-    page.evaluate("fillChat(); _prepareChatAnchorRestore(true); _restoreChatAnchor(_chatPositionKey())")
-    anchor_offset = page.evaluate(
+    page.evaluate(
         """() => {
-            const chat = $('#chat').getBoundingClientRect();
-            const anchor = $('#chat .chat-user').getBoundingClientRect();
-            return Math.abs(anchor.top - chat.top);
+            window.fillChat(30);
+            _prepareChatAnchorRestore(true);
+            _restoreChatAnchor(_chatPositionKey());
         }"""
     )
-    assert anchor_offset < 2
+    divider = page.locator(".chat-unread-divider")
+    expect(divider).to_have_count(1)
+    assert page.evaluate(
+        """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
+    ) == read_id + 1
     expect(page.locator("#chat-jump-latest")).to_be_visible()
     expect(page.locator("#chat-jump-latest")).to_have_text("↓ Новые ниже")
     page.locator("#chat-jump-latest").click()
     page.wait_for_function("() => _chatAtBottom()")
     expect(page.locator("#chat-jump-latest")).to_be_hidden()
 
+    # If the saved boundary fell outside the loaded window, start at the first
+    # available unread record instead of cascading through older history.
     page.evaluate(
         """() => {
-            selectedAgent = 'agent-without-user-message';
-            fillChat(false);
+            selectedAgent = 'agent-boundary-outside-window';
+            _saveChatReadReceipt(_chatPositionKey(), 50);
+            window.fillChat(24, 100);
             _prepareChatAnchorRestore(true);
             _restoreChatAnchor(_chatPositionKey());
         }"""
     )
-    assert page.evaluate("() => _chatAtBottom()") is True
+    assert page.evaluate(
+        """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
+    ) == 100
 
+    # A receipt at the old bottom puts the divider immediately before new work.
     page.evaluate(
         """() => {
-            selectedAgent = 'agent-user-message-is-last';
-            fillChat(true, true);
+            selectedAgent = 'agent-at-bottom';
+            window.fillChat(24);
+            $('#chat').scrollTop = $('#chat').scrollHeight;
+            _captureChatReadFrontier();
+            window.fillChat(28);
             _prepareChatAnchorRestore(true);
             _restoreChatAnchor(_chatPositionKey());
         }"""
     )
-    assert page.evaluate("() => _chatAtBottom()") is True
-    expect(page.locator("#chat-jump-latest")).to_be_hidden()
+    expect(page.locator(".chat-unread-divider")).to_have_count(1)
+    assert page.evaluate(
+        """() => Number($('.chat-unread-divider').nextElementSibling.dataset.chatLogId)"""
+    ) == 25
 
+    # Opening and leaving before history settles must not invent a read boundary.
     page.evaluate(
         """() => {
-            $('#chat').scrollTop = 0;
-            _syncChatJumpButton();
+            selectedAgent = 'agent-opened-and-left';
+            window.fillChat(24);
+            scrollAfterLoad = true;
+            _captureChatReadFrontier();
+            _prepareChatAnchorRestore(true);
+            _restoreChatAnchor(_chatPositionKey());
         }"""
     )
-    expect(page.locator("#chat-jump-latest")).to_have_text("↓ В конец")
-    page.evaluate("_markChatHasNewBelow()")
-    expect(page.locator("#chat-jump-latest")).to_have_text("↓ Новые ниже")
+    assert page.evaluate("() => _chatReadReceipt(_chatPositionKey())") is None
+    expect(page.locator(".chat-unread-divider")).to_have_count(0)
+
+    # Live work at the bottom stays pinned and advances the read frontier.
+    page.evaluate(
+        """() => {
+            selectedAgent = 'agent-live';
+            scrollAfterLoad = false;
+            window.fillChat(24);
+            $('#chat').scrollTop = $('#chat').scrollHeight;
+            _captureChatReadFrontier();
+            const wasAtBottom = _chatAtBottom();
+            const row = document.createElement('div');
+            row.className = 'chat-bot';
+            row.dataset.chatLogId = '25';
+            row.textContent = 'live work 25';
+            $('#chat').appendChild(row);
+            if (wasAtBottom) $('#chat').scrollTop = $('#chat').scrollHeight;
+            _captureChatReadFrontier();
+        }"""
+    )
+    assert page.evaluate("() => _chatAtBottom()") is True
+    assert page.evaluate("() => _chatReadReceipt(_chatPositionKey())") == 25
+    expect(page.locator(".chat-unread-divider")).to_have_count(0)
 
     assert "_scheduleChatInitialSettle();" in source
     assert "const restoreUnreadAnchor = _unreadTabs.delete(currentScope);" in source
     assert "_prepareChatAnchorRestore(restoreUnreadAnchor);" in source
     assert source.count("_unreadTabs.add(") == 1
     assert "localStorage" not in helper_code
+    assert "sessionStorage" in helper_code
     page.close()
 
 
 def test_codex_successful_mcp_startup_status_is_hidden(
     dashboard_browser: Browser,
 ):
     page = _open_tool_fixture_page(dashboard_browser)
     page.evaluate("""() => {


## LATER FIX 5e11d8772f (14.9 days later): fix: stabilize Grok session replay and chat finalization
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

fix: stabilize Grok session replay and chat finalization


diff --git a/app/backend_grok.py b/app/backend_grok.py
index f33ae2d50..ce76723b9 100644
--- a/app/backend_grok.py
+++ b/app/backend_grok.py
@@ -164,26 +164,81 @@ def _grok_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens:
     # Deliberately a short-context fallback. ACP exposes a turn aggregate, while the 200k
     # tier applies per model request; a tool-loop can mix tiers. Runtime costUsdTicks remains
     # the only exact source until ACP exposes per-request usage (docs/tasks/251/research.md).
     return (fresh * prices["input"] + cached * prices["cached"]
             + max(0, output_tokens) * prices["output"]) / 1_000_000
 
 
 def _content_text(content) -> str:
-    """Flatten an ACP content block (or list of them) to text."""
+    """Flatten an ACP content block (or list of them) to text.
+
+    Grok wraps tool results as `{type: "content", content: {type: "text", text: ...}}`
+    and MCP results as `{type: "MCP", tool_name, output: {OkayOutput: ...}}`.
+    Dumping the outer object left the dashboard showing raw JSON grids instead of
+    the tool output itself.
+    """
     if isinstance(content, dict):
-        if content.get("type") == "text":
+        ctype = content.get("type")
+        if ctype == "text":
+            return str(content.get("text", ""))
+        # Grok MCP tool_call_update payload (measured 15.08.2026).
+        if ctype == "MCP" or (
+            isinstance(content.get("output"), dict)
+            and ("tool_name" in content or "server_name" in content)
+        ):
+            output = content.get("output")
+            if isinstance(output, dict):
+                for key in (
+                    "OkayOutput", "ErrorOutput", "output", "text", "result", "content",
+                ):
+                    if key in output and output[key] not in (None, ""):
+                        return _content_text(output[key])
+                # Last resort: first non-empty string value in output.
+                for value in output.values():
+                    if isinstance(value, str) and value.strip():
+                        return value
+                    inner = _content_text(value)
+                    if inner.strip():
+                        return inner
+            elif output is not None:
+                return _content_text(output)
+        # Nested content wrapper from Grok tool_call_update / MCP results.
+        if "content" in content and ctype in (None, "content", "resource", "resource_link"):
+            inner = _content_text(content.get("content"))
+            if inner:
+                return inner
+        if "text" in content and ctype is None:
             return str(content.get("text", ""))
         return json.dumps(bounded_tool_arguments(content), ensure_ascii=False)
     if isinstance(content, list):
-        return "\n".join(_content_text(part) for part in content)
+        parts = [_content_text(part) for part in content]
+        return "\n".join(part for part in parts if part)
     return str(content) if content is not None else ""
 
 
+def _headers_to_acp(headers) -> list[dict]:
+    """ACP rejects bare http/sse MCP entries without a `headers` array (even empty)."""
+    if not headers:
+        return []
+    if isinstance(headers, dict):
+        return [{"name": str(k), "value": str(v)} for k, v in headers.items()]
+    if isinstance(headers, list):
+        out = []
+        for item in headers:
+            if not isinstance(item, dict):
+                continue
+            name = item.get("name")
+            if name is None:
+                continue
+            out.append({"name": str(name), "value": str(item.get("value", ""))})
+        return out
+    return []
+
+
 def _mcp_server_identity(server: dict) -> tuple:
     """Canonical identity for an ACP MCP config, excluding discovery metadata."""
     raw_env = server.get("env") or []
     if isinstance(raw_env, dict):
         env = tuple(sorted((str(k), str(v)) for k, v in raw_env.items()))
     else:
         env = tuple(sorted(
             (str(item.get("name")), str(item.get("value", "")))
@@ -254,16 +309,26 @@ class GrokBackend(JsonRpcStdioTransport):
         self._last_stderr = ""
         self._profile_path: Path | None = None
         # Turn bookkeeping. `_active_prompts` counts prompts accepted but not yet completed —
         # the agent queues extras, so the event loop must not stop at the first completion.
         self._active_prompts = 0
         self._queue_depth = 0
         self._completed_prompts: set[str] = set()
         self._tool_names: dict[str, str] = {}
+        # Grok only streams message/thought chunks — never a final item-complete event.
+        # Session persists `text`/`thinking`, not live `stream`/`thinking_stream`, so without
+        # these buffers assistant replies vanish from history and leave the UI bubble open
+        # across turns (messages glue, reasoning floats as a live card forever).
+        self._message_buf: list[str] = []
+        self._thought_buf: list[str] = []
+        # session/load replays prior turns as session/update notifications. If those land
+        # in the event stream they are re-logged as "new" tool/text/thinking rows and bury
+        # real user messages under a flood (measured: full history dumped at 07:36 and 07:40).
+        self._suppress_history_replay = False
         # turn_completed carries usage; the turn_end is emitted by the prompt completion.
         self._pending_usage: dict = {}
         self._model_context_window = GROK_CONTEXT_LIMITS.get(model, GROK_DEFAULT_CONTEXT)
         self._context_tokens: int | None = None
         self._mcp_canary: str | None = None
         self._issue_mcp_canary()
         # A matching name is insufficient: a repository can define another command under it.
         expected_configs = self._mcp_server_configs()
@@ -351,47 +416,61 @@ class GrokBackend(JsonRpcStdioTransport):
                 "clientCapabilities": {
                     "fs": {"readTextFile": False, "writeTextFile": False},
                     "terminal": False,
                 },
             })
             self._absorb_model_meta(result.get("_meta") or {})
             params = {"cwd": self.cwd, "mcpServers": self._mcp_server_configs()}
             result = None
-            if self._session_id:
-                try:
-                    result = await self._request(
-                        "session/load", {**params, "sessionId": self._session_id}
-                    )
-                except GrokProtocolError as exc:
-                    # A stale id must not brick the worker forever: the store is keyed by
-                    # (cwd, sessionId), so a moved or pruned worktree makes load fail
-                    # permanently. Start fresh — but never quietly, the lost history is
-                    # exactly what someone would otherwise spend an hour looking for.
-                    logger.warning(
-                        "Grok session/load failed for %s (%s) — starting a fresh session",
-                        self._session_id, exc,
-                    )
-                    self._notifications.put_nowait({
-                        "method": "_session/resume_failed",
-                        # NOT "sessionId": events() drops notifications whose sessionId is
-                        # not the current one, and this warning is about the OLD id — it
-                        # would filter out the very message announcing the lost history.
-                        "params": {"staleSessionId": self._session_id, "message": str(exc)},
-                    })
-                    self._session_id = None
-            if result is None:
-                result = await self._request("session/new", params)
-                session_id = result.get("sessionId")
-                if not session_id:
-                    raise RuntimeError("Grok ACP returned no session id")
-                self._session_id = session_id
-            self._absorb_models(result.get("models") or {})
+            # Drop session/update content while load/new runs — Grok replays the whole
+            # transcript into the notification queue, and the first turn after connect
+            # would re-persist it as brand-new logs.
+            self._suppress_history_replay = True
+            try:
+                if self._session_id:
+                    try:
+                        result = await self._request(
+                            "session/load", {**params, "sessionId": self._session_id}
+                        )
+                    except GrokProtocolError as exc:
+                        # A stale id must not brick the worker forever: the store is keyed by
+                        # (cwd, sessionId), so a moved or pruned worktree makes load fail
+                        # permanently. Start fresh — but never quietly, the lost history is
+                        # exactly what someone would otherwise spend an hour looking for.
+                        logger.warning(
+                            "Grok session/load failed for %s (%s) — starting a fresh session",
+                            self._session_id, exc,
+                        )
+                        self._notifications.put_nowait({
+                            "method": "_session/resume_failed",
+                            # NOT "sessionId": events() drops notifications whose sessionId is
+                            # not the current one, and this warning is about the OLD id — it
+                            # would filter out the very message announcing the lost history.
+                            "params": {
+                                "staleSessionId": self._session_id,
+                                "message": str(exc),
+                            },
+                        })
+                        self._session_id = None
+                if result is None:
+                    result = await self._request("session/new", params)
+                    session_id = result.get("sessionId")
+                    if not session_id:
+                        raise RuntimeError("Grok ACP returned no session id")
+                    self._session_id = session_id
+                self._absorb_models(result.get("models") or {})
+                # Anything already queued during load is history replay — drop content
+                # updates, keep MCP startup (isolation still needs them).
+                self._drain_history_replay_queue()
+            finally:
+                self._suppress_history_replay = False
             await self._verify_mcp_isolation()
         except BaseException:
+            self._suppress_history_replay = False
             await self.disconnect()
             raise
 
     async def _verify_mcp_isolation(self) -> None:
         """Fail connect unless the observed MCP roster exactly matches the launch plan.
 
         The GROK_HOME sandbox suppresses Claude-compat discovery, and a repo `.mcp.json` is
         additionally gated behind folder trust. Neither guarantee is ours to enforce, so the
@@ -691,16 +770,22 @@ class GrokBackend(JsonRpcStdioTransport):
                                 "method": "_prompt/result",
                                 "params": result,
                             })
                     continue
                 if message.get("method"):
                     # Track MCP startup here, not in events(): isolation is verified during
                     # connect(), before any consumer starts draining the event stream.
                     self._track_mcp(message)
+                    if (
+                        self._suppress_history_replay
+                        and message.get("method") == "session/update"
+                    ):
+                        # session/load replays prior turns; do not surface them as new events.
+                        continue
                     await self._notifications.put(message)
         except asyncio.CancelledError:
             return
         except Exception as exc:
             logger.exception("Grok ACP reader failed: %s", exc)
         finally:
             returncode = await proc.wait()
             error = RuntimeError(f"Grok ACP agent exited with code {returncode}")
@@ -846,17 +931,17 @@ class GrokBackend(JsonRpcStdioTransport):
                 "warning",
                 f"grok could not resume session {params.get('staleSessionId')} "
                 f"({params.get('message')}) — continuing in a NEW session, "
                 f"previous conversation history is not available",
             )]
 
         if method == "_prompt/failed":
             self._active_prompts = max(0, self._active_prompts - 1)
-            return [
+            return self._flush_open_streams() + [
                 AgentEvent("error", params.get("message", "Grok prompt failed"),
                            {"model_error": "error"}),
                 self._turn_end_event(False, "error", "error"),
             ]
 
         if method == "_x.ai/mcp/server_status":
             return self._mcp_status(params)
 
@@ -883,79 +968,136 @@ class GrokBackend(JsonRpcStdioTransport):
             turn_usage = TurnUsage(
                 AggregateUsage.normalized(),
                 current_context(
                     None,
                     self._model_context_window,
                     unknown_reason="Grok exited before reporting current context",
                 ),
             )
-            return [AgentEvent("turn_end", "stop_reason=process_exit", metadata={
-                "session_id": self._session_id,
-                "ok": False,
-                "stop_reason": f"process_exit_{params.get('returncode')}",
-                "returncode": params.get("returncode"),
-                "stderr_tail": params.get("stderr", ""),
-                "model_error": "server_error",
-                "errors": ["server_error"],
-                "cost_usd": 0,
-                **turn_usage.metadata(),
-            }, usage=turn_usage)]
+            return self._flush_open_streams() + [AgentEvent(
+                "turn_end", "stop_reason=process_exit", metadata={
+                    "session_id": self._session_id,
+                    "ok": False,
+                    "stop_reason": f"process_exit_{params.get('returncode')}",
+                    "returncode": params.get("returncode"),
+                    "stderr_tail": params.get("stderr", ""),
+                    "model_error": "server_error",
+                    "errors": ["server_error"],
+                    "cost_usd": 0,
+                    **turn_usage.metadata(),
+                }, usage=turn_usage,
+            )]
 
         return []
 
+    def _drain_history_replay_queue(self) -> None:
+        """Remove session/update content left in the queue after session/load."""
+        kept: list[dict] = []
+        while True:
+            try:
+                message = self._notifications.get_nowait()
+            except asyncio.QueueEmpty:
+                break
+            if message.get("method") == "session/update":
+                continue
+            kept.append(message)
+        for message in kept:
+            self._notifications.put_nowait(message)
+
+    def _flush_message(self) -> list[AgentEvent]:
+        text = "".join(self._message_buf)
+        self._message_buf.clear()
+        if not text:
+            return []
+        return [AgentEvent("text", text)]
+
+    def _flush_thought(self) -> list[AgentEvent]:
+        text = "".join(self._thought_buf)
+        self._thought_buf.clear()
+        if not text:
+            return []
+        return [AgentEvent("thinking", text)]
+
+    def _flush_open_streams(self) -> list[AgentEvent]:
+        # Thought before message: reasoning precedes the answer that used it.
+        return self._flush_thought() + self._flush_message()
+
     def _session_update(self, params: dict) -> list[AgentEvent]:
         update = params.get("update") or {}
         kind = update.get("sessionUpdate", "")
         meta = params.get("_meta") or {}
         total = meta.get("totalTokens")
         if isinstance(total, int) and total >= 0:
             self._context_tokens = total
 
         if kind == "agent_message_chunk":
-            return [AgentEvent("stream", _content_text(update.get("content")))]
+            chunk = _content_text(update.get("content"))
+            if chunk:
+                self._message_buf.append(chunk)
+            return [AgentEvent("stream", chunk)]
 
         if kind == "agent_thought_chunk":
-            return [AgentEvent("thinking_stream", _content_text(update.get("content")),
+            chunk = _content_text(update.get("content"))
+            if chunk:
+                self._thought_buf.append(chunk)
+            return [AgentEvent("thinking_stream", chunk,
                                {"activity": "reasoning",
                                 "item_id": str(meta.get("promptId") or "")})]
 
         if kind == "tool_call":
+            # Flush answer text before the tool so order is text → tool → result → text.
+            # Do NOT flush thinking here: Grok thinks between nearly every tool, and that
+            # produced 50+ reasoning cards per turn. One thinking card lands at turn_end.
+            events = self._flush_message()
             tool_id = str(update.get("toolCallId") or update.get("id") or "")
             name = str(update.get("title") or update.get("kind") or "tool")
             self._tool_names[tool_id] = name
-            return [AgentEvent(
+            events.append(AgentEvent(
                 "tool_use",
                 f"{name}: {json.dumps(bounded_tool_arguments(update.get('rawInput') or {}), ensure_ascii=False)}",
                 metadata={"tool_name": name, "short_name": name, "tool_use_id": tool_id},
-            )]
+            ))
+            return events
 
         if kind == "tool_call_update":
             return self._tool_call_update(update)
 
         if kind == "plan":
-            return [AgentEvent("plan", json.dumps(update.get("entries") or [],
-                                                  ensure_ascii=False))]
+            # Plan is mid-turn structure; keep reasoning open until the turn ends.
+            events = self._flush_message()
+            events.append(AgentEvent("plan", json.dumps(update.get("entries") or [],
+                                                        ensure_ascii=False)))
+            return events
         return []
 
     def _tool_call_update(self, update: dict) -> list[AgentEvent]:
         tool_id = str(update.get("toolCallId") or update.get("id") or "")
         status = update.get("status")
         title = update.get("title")
         if title and tool_id:
             # Grok routes MCP tools through a search_tool/use_tool meta-layer; the concrete
             # name (e.g. orchestra__list_agents) arrives on the update, not the initial call.
             self._tool_names[tool_id] = str(title)
         if status not in ("completed", "failed"):
             return []
         name = self._tool_names.get(tool_id, "tool")
         content = update.get("content")
-        text = _content_text(content) if content is not None else json.dumps(
-            {"status": status}, ensure_ascii=False
-        )
+        text = _content_text(content) if content is not None else ""
+        if not text.strip():
+            raw = update.get("rawOutput")
+            if raw is not None:
+                if isinstance(raw, (dict, list)):
+                    text = _content_text(raw)
+                    if not text.strip():
+                        text = json.dumps(bounded_tool_arguments(raw), ensure_ascii=False)
+                else:
+                    text = str(raw)
+        if not text.strip():