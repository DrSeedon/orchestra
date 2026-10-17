# Candidate cand-20

## ORIGIN commit 1473e37459 (2026-07-01): #proxy-fix: check liveness via Anthropic, ipinfo geo best-effort
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/backend_claude.py b/app/backend_claude.py
index 34abc9fd4..b5408e17f 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -235,79 +235,102 @@ class ClaudeBackend:
         self._client = self._make_client()
         try:
             await asyncio.wait_for(self._client.connect(), timeout=60)
         except BaseException as e:
             logger.error(f"ClaudeBackend reconnect failed: {e}")
             await self._cleanup_failed_client()
             raise
 
+    @staticmethod
+    def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
+        """Mark an event as belonging to a sub-agent so the UI nests it.
+
+        sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
+        the type is preserved (tool_use stays tool_use) — the frontend groups by
+        subagent_id, not by a renamed type."""
+        if sub_id is not None:
+            event.metadata = {**event.metadata, "subagent_id": sub_id}
+        return event
+
     def _convert(self, msg) -> list[AgentEvent]:
         events = []
         if isinstance(msg, StreamEvent):
-            # v1 streaming scope: ONLY main-agent text. Skip subagent partials
-            # (parent_tool_use_id set) and non-text deltas (thinking/tool-arg/sig).
-            # The final AssistantMessage still carries everything and is persisted.
+            # Main-agent text partials → "stream". Subagent partials (parent_tool_use_id
+            # set) → "subagent_stream" tagged with sub_id so the UI nests them under the
+            # sub-agent block instead of dropping them (which looked like a hang).
             ev = msg.event or {}
-            if msg.parent_tool_use_id is not None:
-                return events
             if ev.get("type") != "content_block_delta":
                 return events
             delta = ev.get("delta") or {}
             if delta.get("type") != "text_delta":
                 return events
             text = delta.get("text") or ""
-            if text:
+            if not text:
+                return events
+            sub_id = msg.parent_tool_use_id
+            if sub_id is not None:
+                events.append(AgentEvent("subagent_stream", text, metadata={"subagent_id": sub_id}))
+            else:
                 events.append(AgentEvent("stream", text))
             return events
 
         if isinstance(msg, AssistantMessage):
+            # Subagent messages carry parent_tool_use_id → tag events so the UI groups
+            # them under the sub-agent block instead of mixing with the parent's stream.
+            sub_id = getattr(msg, "parent_tool_use_id", None)
             for block in msg.content:
                 if isinstance(block, TextBlock) and block.text:
-                    events.append(AgentEvent("text", block.text))
+                    events.append(self._tag_sub(AgentEvent("text", block.text), sub_id))
                 elif isinstance(block, ThinkingBlock) and block.thinking:
-                    events.append(AgentEvent("thinking", block.thinking))
+                    events.append(self._tag_sub(AgentEvent("thinking", block.thinking), sub_id))
                 elif isinstance(block, ToolUseBlock):
                     try:
                         inp = _json.dumps(block.input, ensure_ascii=False, indent=2)
                     except Exception:
                         inp = str(block.input)
                     short_name = block.name.split('__')[-1] if '__' in block.name else block.name
-                    events.append(AgentEvent("tool_use", f"{block.name}: {inp}",
-                                             metadata={"tool_name": block.name, "short_name": short_name}))
+                    events.append(self._tag_sub(AgentEvent("tool_use", f"{block.name}: {inp}",
+                                             metadata={"tool_name": block.name, "short_name": short_name}), sub_id))
                 elif isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
-                    events.append(AgentEvent("tool_result", _extract_tool_result(block)))
+                    events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
             err = getattr(msg, "error", None)
             if err:
                 events.append(AgentEvent("error", f"model error: {err}"))
 
         elif isinstance(msg, UserMessage):
+            sub_id = getattr(msg, "parent_tool_use_id", None)
             if hasattr(msg, 'content') and isinstance(msg.content, list):
                 for block in msg.content:
                     if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
-                        events.append(AgentEvent("tool_result", _extract_tool_result(block)))
+                        events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
 
         elif isinstance(msg, TaskStartedMessage):
             desc = getattr(msg, "description", "") or ""
             task_type = getattr(msg, "task_type", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
-            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}"))
+            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}",
+                                     metadata={"subagent_id": task_id}))
 
         elif isinstance(msg, TaskProgressMessage):
             desc = getattr(msg, "description", "") or ""
             last_tool = getattr(msg, "last_tool_name", "") or ""
+            task_id = getattr(msg, "task_id", "") or ""
             usage = getattr(msg, "usage", None)
             tokens = usage.total_tokens if usage and hasattr(usage, "total_tokens") else 0
-            events.append(AgentEvent("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}"))
+            events.append(AgentEvent("subagent_progress", f"{desc} | tool={last_tool} | tokens={tokens}",
+                                     metadata={"subagent_id": task_id}))
 
         elif isinstance(msg, TaskNotificationMessage):
             desc = getattr(msg, "description", "") or ""
             status = getattr(msg, "status", "") or ""
             summary = getattr(msg, "summary", "") or ""
-            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}"))
+            task_id = getattr(msg, "task_id", "") or ""
+            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}",
+                                     metadata={"subagent_id": task_id}))
 
         elif isinstance(msg, ResultMessage):
             sr = getattr(msg, "stop_reason", None) or "unknown"
             nt = getattr(msg, "num_turns", 0) or 0
             if msg.session_id:
                 self._session_id = msg.session_id
 
             is_err = bool(getattr(msg, "is_error", False))
diff --git a/app/proxy_manager.py b/app/proxy_manager.py
index f4aad0e0f..c21b8fe70 100644
--- a/app/proxy_manager.py
+++ b/app/proxy_manager.py
@@ -21,18 +21,23 @@ COUNTRY_FLAGS = {
     "RU": "🇷🇺", "UA": "🇺🇦", "KZ": "🇰🇿", "BY": "🇧🇾",
     "JP": "🇯🇵", "KR": "🇰🇷", "SG": "🇸🇬", "AU": "🇦🇺",
     "CA": "🇨🇦", "BR": "🇧🇷", "IN": "🇮🇳", "TR": "🇹🇷",
     "PL": "🇵🇱", "CZ": "🇨🇿", "RO": "🇷🇴", "BG": "🇧🇬",
     "HK": "🇭🇰", "TW": "🇹🇼", "IE": "🇮🇪", "ES": "🇪🇸",
     "IT": "🇮🇹", "PT": "🇵🇹", "DK": "🇩🇰", "LT": "🇱🇹",
     "LV": "🇱🇻", "EE": "🇪🇪", "IS": "🇮🇸", "MD": "🇲🇩",
 }
-IP_CHECK_URL = "https://ipinfo.io/json"
-IP_CHECK_TIMEOUT = 8
+# Liveness = can we reach Anthropic (what we actually use)? ANY HTTP response
+# (200/401/403/404) means the proxy tunnels fine. ipinfo.io was giving false
+# "dead" for live proxies (intermittent timeouts) — it's now best-effort geo only.
+LIVENESS_URL = "https://api.anthropic.com"
+GEO_URL = "https://ipinfo.io/json"
+CHECK_TIMEOUT = 8
+GEO_TIMEOUT = 5
 
 
 @dataclass
 class ProxyEntry:
     id: str
     name: str
     url: str
 
@@ -83,34 +88,46 @@ class ProxyManager:
     async def check_proxy(self, proxy_id: str) -> dict:
         entries = self._get_entries()
         entry = next((e for e in entries if e.id == proxy_id), None)
         if not entry:
             return {"error": f"proxy '{proxy_id}' not found"}
         return await self._do_check(entry)
 
     async def _do_check(self, entry: ProxyEntry) -> dict:
+        """Two-tier: liveness via Anthropic (any HTTP response = alive), geo via
+        ipinfo (best-effort — its flakiness must NOT mark a live proxy dead)."""
+        proxy = entry.url if entry.url and entry.url != "direct" else None
         try:
-            kwargs = {"timeout": IP_CHECK_TIMEOUT, "verify": False}
-            if entry.url and entry.url != "direct":
-                kwargs["proxy"] = entry.url
-            async with httpx.AsyncClient(**kwargs) as client:
-                resp = await client.get(IP_CHECK_URL)
+            async with httpx.AsyncClient(timeout=CHECK_TIMEOUT, verify=False, proxy=proxy) as client:
+                await client.get(LIVENESS_URL)  # any response (200/401/403/404) = tunnel works
+        except Exception as e:
+            return {"id": entry.id, "ok": False, "error": str(e) or "unreachable"}
+        result = {"id": entry.id, "ok": True}
+        try:
+            result.update(await self._geo(proxy))  # best-effort, never flips ok
+        except Exception:
+            pass  # geo is decoration — its failure must not mark a live proxy dead
+        return result
+
+    async def _geo(self, proxy: str | None) -> dict:
+        try:
+            async with httpx.AsyncClient(timeout=GEO_TIMEOUT, verify=False, proxy=proxy) as client:
+                resp = await client.get(GEO_URL)
                 if resp.status_code != 200:
-                    return {"id": entry.id, "ok": False, "error": f"HTTP {resp.status_code}"}
+                    return {}
                 data = resp.json()
-                country = data.get("country", "??")
+                country = data.get("country", "")
                 return {
-                    "id": entry.id, "ok": True,
-                    "ip": data.get("ip", "?"), "country": country,
+                    "ip": data.get("ip", ""), "country": country,
                     "city": data.get("city", ""), "org": data.get("org", ""),
                     "flag": COUNTRY_FLAGS.get(country, "🏳️"),
                 }
-        except Exception as e:
-            return {"id": entry.id, "ok": False, "error": str(e)}
+        except Exception:
+            return {}  # geo unavailable — proxy still reported alive
 
     async def list_proxies(self) -> dict:
         """List proxies from .env. `active` = current HTTPS_PROXY (read-only).
 
         No liveness here — call check/{id} or check_all for that (on-demand).
         """
         entries = self._get_entries()
         active_id = _active_id(entries)
diff --git a/app/session.py b/app/session.py
index 36880bfb9..debc318f2 100644
--- a/app/session.py
+++ b/app/session.py
@@ -521,16 +521,33 @@ class AgentSession:
 
     def _handle_event(self, event: AgentEvent) -> None:
         if event.type == "stream":
             # Live partials: push to in-memory broker for SSE fan-out, NEVER persist.
             # The final "text" event (below) is the DB source of truth.
             from app.live_broker import broker
             broker.publish(self.id, {"type": "stream", "content": event.content})
             return
+        if event.type == "subagent_stream":
+            # Live sub-agent output → broker only (ephemeral, like main stream).
+            # subagent_id lets the UI nest it under the right sub-agent block.
+            from app.live_broker import broker
+            broker.publish(self.id, {"type": "subagent_stream", "content": event.content,
+                                     "subagent_id": event.metadata.get("subagent_id", "")})
+            return
+        # Sub-agent tool_use/text/tool_result (tagged with subagent_id) → broker ONLY
+        # (ephemeral live nesting under the sub-agent block). NOT persisted — the DB
+        # record is subagent_start/end; persisting these too would double-render them
+        # (once in the accordion via broker, once in the main flow on reload).
+        sub_id = event.metadata.get("subagent_id")
+        if sub_id and event.type in ("tool_use", "tool_result", "text", "thinking"):
+            from app.live_broker import broker
+            broker.publish(self.id, {"type": "subagent_event", "event_type": event.type,
+                                     "content": event.content[:2000], "subagent_id": sub_id})
+            return
         if event.type == "text":
             from app.live_broker import broker
             broker.clear_accum(self.id)
             self._log("text", event.content)
             self._turn_logs.append(event.content)
         elif event.type == "thinking":
             self._log("thinking", event.content)
         elif event.type == "tool_use":
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 1bab70e59..760752b90 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -175,20 +175,20 @@ function connectSSE() {
                 if (isLocal) {
                     for (const m of localMessages) {
                         if (l.content === m || l.content.endsWith(m) || l.content.includes(m)) {
                             localMessages.delete(m);
                             break;
                         }
                     }
                 } else {
-                    addChatEntry(l.type, l.content, l.ts);
+                    addChatEntry(l.type, l.content, l.ts, null, l);
                 }
             } else {
-                addChatEntry(l.type, l.content, l.ts);
+                addChatEntry(l.type, l.content, l.ts, null, l);
             }
             if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null };
             // Live stream partials carry no id — skip id bookkeeping for them
             if (Number.isFinite(l.id)) {
                 if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
                 if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                     chatLogs[selectedAgent].firstId = l.id;
                     updateLoadMoreBtn();
@@ -2058,20 +2058,58 @@ function _findLastBefore(parent, selector, anchor) {
     while (node) {
         if (node.matches(selector)) return node;
         node = node.previousElementSibling;
     }
     return null;
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
+
+// Append a live sub-agent log line into its accordion body. If the accordion
+// isn't there yet (race: stream before start), no-op — the sub-agent block owns
+// its own rendering; live lines are best-effort decoration.
+function appendSubagentLog(subId, evType, content) {
+    const chat = $('#chat');
+    const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
+    if (!host) return;
+    const body = host.querySelector('.sa-body');
+    if (!body) return;
+    if (evType === 'stream') {
+        // Coalesce contiguous stream text into one line (typewriter feel)
+        let last = body.lastElementChild;
+        if (last && last.classList.contains('sa-stream')) {
+            last.textContent += content;
+        } else {
+            last = document.createElement('div');
+            last.className = 'sa-stream';
+            last.textContent = content;
+            body.appendChild(last);
+        }
+    } else {
+        const line = document.createElement('div');
+        const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
+        line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
+        const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
+        line.textContent = `${icon} ${short}`;
+        body.appendChild(line);
+    }
+    body.scrollTop = body.scrollHeight;
+}
+
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
-function addChatEntry(type, content, ts, anchor) {
+// payload = full SSE log object (carries subagent_id for sub-agent nesting)
+function addChatEntry(type, content, ts, anchor, payload) {
     if (HIDE_THINKING && type === 'thinking') return;
+    // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
+    if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
+        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
+        return;
+    }
     if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
     const chat = $('#chat');
     let _insertedBeforeStream = false;
     const _insert = (el) => {
         if (anchor) return chat.insertBefore(el, anchor);
         if (streamBubble && streamBubble.parentNode === chat) {
             _insertedBeforeStream = true;
             return chat.insertBefore(el, streamBubble);
@@ -2234,48 +2272,79 @@ function addChatEntry(type, content, ts, anchor) {
             const eq = p.indexOf('=');
             if (eq > 0 && /^\w+$/.test(p.slice(0, eq))) meta[p.slice(0, eq)] = p.slice(eq + 1);
             else if (p) textParts.push(p);
         }
         const desc = textParts[0] || textParts[1] || '';
         const el = document.createElement('div');
         el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';
 
+        const subId = (payload && payload.subagent_id) || meta.id || '';
+
         if (type === 'subagent_start') {
+            // Collapsible accordion: header + body where live sub-agent logs nest.
             el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
-            el.innerHTML = `🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>`;
-            if (meta.type) {
-                const sub = document.createElement('div');
-                sub.style.cssText = 'font-size:10px;color:#64748b;margin-top:1px;padding-left:20px';
-                sub.textContent = `type: ${meta.type}`;
-                el.appendChild(sub);
-            }
+            if (subId) el.dataset.subagentId = subId;
+            const header = document.createElement('div');
+            header.style.cssText = 'cursor:pointer;user-select:none';
+            header.innerHTML = `<span class="sa-caret">▶</span> 🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
+            const body = document.createElement('div');
+            body.className = 'sa-body';
+            body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
+            let _expanded = false;
+            header.addEventListener('click', () => {
+                _expanded = !_expanded;
+                body.style.display = _expanded ? 'block' : 'none';
+                header.querySelector('.sa-caret').textContent = _expanded ? '▼' : '▶';
+            });
+            el.appendChild(header);
+            el.appendChild(body);
         } else if (type === 'subagent_progress') {
-            el.style.cssText += ';color:#64748b';
+            // Update the live progress line inside the matching accordion (or standalone)
             const tokens = meta.tokens ? (parseInt(meta.tokens) >= 1000 ? (parseInt(meta.tokens) / 1000).toFixed(1) + 'k' : meta.tokens) : '';
-            el.textContent = `⏳ "${desc}" — ${meta.tool ? 'using ' + meta.tool : ''}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
-        } else {
+            const line = `⏳ ${meta.tool ? 'using ' + meta.tool : 'working'}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
+            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
+            if (host) {
+                let prog = host.querySelector('.sa-progress');
+                if (!prog) {
+                    prog = document.createElement('div');
+                    prog.className = 'sa-progress';
+                    prog.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
+                    host.appendChild(prog);
+                }
+                prog.textContent = line;
+                return;  // updated in place, no new bubble
+            }
+            el.style.cssText += ';color:#64748b';
+            el.textContent = `⏳ "${desc}" — ${line}`;
+        } else {  // subagent_end → mark the accordion done + collapse
             const ok = !meta.status || meta.status === 'completed';
+            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
+            const summaryText = textParts.slice(1).join(' | ').trim();
+            if (host) {
+                const hdr = host.querySelector('div');
+                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
+                const prog = host.querySelector('.sa-progress');
+                if (prog) prog.remove();
+                if (summaryText) {
+                    const sumEl = document.createElement('div');
+                    sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
+                    sumEl.textContent = summaryText;
+                    host.appendChild(sumEl);
+                }
+                host.style.borderLeftColor = ok ? '#22c55e' : '#ef4444';
+                return;  // updated existing accordion, no new bubble
+            }
             el.style.cssText += `;border-left:3px solid ${ok ? '#22c55e' : '#ef4444'};background:rgba(${ok ? '34,197,94' : '239,68,68'},0.06);color:${ok ? '#86efac' : '#fca5a5'}`;
             el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
-            const summaryText = textParts.slice(1).join(' | ').trim();
             if (summaryText) {
                 const sumEl = document.createElement('div');
-                sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;max-height:40px;overflow:hidden;white-space:pre-wrap';
-                sumEl.textContent = summaryText.length > 200 ? summaryText.slice(0, 200) + '…' : summaryText;
+                sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
+                sumEl.textContent = summaryText.length > 300 ? summaryText.slice(0, 300) + '…' : summaryText;
                 el.appendChild(sumEl);
-                if (summaryText.length > 200) {
-                    el.style.cursor = 'pointer';
-                    let _saExp = false;
-                    el.addEventListener('click', () => {
-                        _saExp = !_saExp;
-                        sumEl.textContent = _saExp ? summaryText : summaryText.slice(0, 200) + '…';
-                        sumEl.style.maxHeight = _saExp ? 'none' : '40px';
-                    });
-                }
             }
         }
         addTimestamp(el, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(el);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
diff --git a/app/tg_bridge.py b/app/tg_bridge.py
index e0922c342..f5d7f57dd 100644
--- a/app/tg_bridge.py
+++ b/app/tg_bridge.py
@@ -1348,16 +1348,23 @@ async def stream_logs(orch_name: str, thread_id: int):
                     elif t == "error":
                         text = f"❌ {c}"
                     elif t == "status":
                         if "turn ended" in c:
                             still_running = _any_running_in_scope(scope)
                             if not still_running:
                                 await _update_topic_status(orch_name, False)
                         text = f"⚡ {c}"
+                    elif t == "subagent_end":
+                        # Only the FINAL of a sub-agent (start/progress/stream = spam, dropped).
+                        # Content: "desc | status=X | summary". Show desc + ok/fail.
+                        _parts = [p.strip() for p in c.split("|")]
+                        _desc = _parts[0] if _parts else ""
+                        _ok = "status=failed" not in c
+                        text = f"{'✅' if _ok else '❌'} Sub-agent {'done' if _ok else 'failed'}: {_desc}"
                     else:
                         continue
                     is_important = t in ("text", "error", "user_message")
                     for chunk in _split_message(text):
                         try:
                             converted, entities = md_convert(chunk)
                             from aiogram.types import MessageEntity as AioEntity
                             aio_ents = [AioEntity(**e.to_dict()) for e in entities] if entities else None
diff --git a/tests/test_backend_stream.py b/tests/test_backend_stream.py
index 1399414ee..a54548c5f 100644
--- a/tests/test_backend_stream.py
+++ b/tests/test_backend_stream.py
@@ -1,17 +1,18 @@
-"""Task #83 — ClaudeBackend._convert StreamEvent scope filter.
+"""ClaudeBackend._convert StreamEvent scope filter + sub-agent tagging.
 
-v1 streaming: ONLY main-agent text_delta becomes a "stream" AgentEvent.
-Everything else (thinking/tool-arg deltas, subagent partials, non-delta events)
-is dropped — the final AssistantMessage still carries them and is persisted.
+Main-agent text_delta → "stream". Sub-agent text_delta (parent_tool_use_id set)
+→ "subagent_stream" tagged with subagent_id (surfaced, not dropped). Non-text
+deltas (thinking/tool-arg/sig) and non-delta events are still dropped.
 """
 from claude_agent_sdk import StreamEvent
 
 from app.backend_claude import ClaudeBackend
+from app.events import AgentEvent
 
 
 def _backend():
     return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")
 
 
 def _stream(event, parent_tool_use_id=None):
     return StreamEvent(uuid="u", session_id="s", event=event,
@@ -61,22 +62,40 @@ def test_signature_delta_dropped():
     b = _backend()
     msg = _stream({
         "type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "sig"},
     })
     assert b._convert(msg) == []
 
 
-def test_subagent_text_delta_dropped():
+def test_subagent_text_delta_becomes_subagent_stream():
+    # Sub-agent partials are no longer dropped — they surface as subagent_stream
+    # tagged with subagent_id so the UI nests them under the sub-agent block.
     b = _backend()
     msg = _stream({
         "type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "sub"},
     }, parent_tool_use_id="toolu_123")
-    assert b._convert(msg) == []
+    out = b._convert(msg)
+    assert len(out) == 1
+    assert out[0].type == "subagent_stream"
+    assert out[0].content == "sub"
+    assert out[0].metadata.get("subagent_id") == "toolu_123"
 
 
 def test_non_delta_events_dropped():
     b = _backend()
     for etype in ("message_start", "content_block_start",
                   "content_block_stop", "message_delta", "message_stop"):
         assert b._convert(_stream({"type": etype})) == []
+
+
+def test_tag_sub_marks_only_subagent_events():
+    # main agent (sub_id None) → event unchanged; sub-agent → subagent_id stamped
+    main = ClaudeBackend._tag_sub(AgentEvent("tool_use", "x", metadata={"tool_name": "Bash"}), None)
+    assert "subagent_id" not in main.metadata
+    assert main.metadata["tool_name"] == "Bash"
+
+    sub = ClaudeBackend._tag_sub(AgentEvent("tool_use", "x", metadata={"tool_name": "Bash"}), "toolu_9")
+    assert sub.metadata["subagent_id"] == "toolu_9"
+    assert sub.metadata["tool_name"] == "Bash"  # existing metadata preserved
+    assert sub.type == "tool_use"  # type unchanged — UI groups by id, not type
diff --git a/tests/test_proxy.py b/tests/test_proxy.py
index ba55dcc54..d38ed7991 100644
--- a/tests/test_proxy.py
+++ b/tests/test_proxy.py
@@ -44,16 +44,49 @@ async def test_active_direct_when_no_env(monkeypatch):
 def test_no_mutation_methods_gone():
     # hot-switch / DB persistence removed — .env is the only source
     mgr = pm.ProxyManager()
     assert not hasattr(mgr, "select_proxy")
     assert not hasattr(mgr, "load_saved_proxy")
     assert not hasattr(mgr, "refresh_loop")
 
 
+@pytest.mark.asyncio
+async def test_check_geo_failure_keeps_alive(monkeypatch):
+    # liveness (Anthropic) OK but geo (ipinfo) throwing must NOT flip ok→false
+    mgr = pm.ProxyManager()
+
+    class _Resp:
+        status_code = 404  # any response = tunnel works
+
+    class _Client:
+        def __init__(self, **kw): ...
+        async def __aenter__(self): return self
+        async def __aexit__(self, *a): ...
+        async def get(self, url): return _Resp()
+
+    monkeypatch.setattr(pm.httpx, "AsyncClient", _Client)
+
+    async def boom(proxy):
+        raise RuntimeError("ipinfo timeout")
+
+    monkeypatch.setattr(mgr, "_geo", boom)
+    r = await mgr._do_check(pm.ProxyEntry(id="c", name="C", url="http://127.0.0.1:12343"))
+    assert r["ok"] is True  # geo blew up, liveness held
+
+
+@pytest.mark.asyncio
+async def test_check_dead_proxy_real_error():
+    # unreachable proxy → ok:false with a NON-empty error (not "")
+    entry = pm.ProxyEntry(id="d", name="D", url="http://127.0.0.1:19998")
+    r = await pm.ProxyManager()._do_check(entry)
+    assert r["ok"] is False
+    assert r["error"], "error must be non-empty for a dead proxy"
+
+
 def test_set_env_preserves_tokens(tmp_path, monkeypatch):
     env = tmp_path / ".env"
     env.write_text(
         "HTTPS_PROXY=http://127.0.0.1:12343\n"
         "HTTP_PROXY=http://127.0.0.1:12343\n"
         "TG_BOT_TOKEN=123:ABC_secret\n"
         "YOUGILE_KEY=xyz|special@chars\n"
         "PROXY_LIST=Direct|direct,Contabo|http://127.0.0.1:12343\n",


## LATER FIX 3b2b2415a2 (16.1 days later): fix: correlate subagent lifecycle events
lines of origin it changed/deleted: 12
(code only, capped 400 lines)

fix: correlate subagent lifecycle events


diff --git a/app/backend_claude.py b/app/backend_claude.py
index 57e4e17c5..834d369fb 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -109,16 +109,22 @@ class ClaudeBackend:
         # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
         self._inherit_claude_md = inherit_claude_md
         # F2: user-MCP из профильного .claude.json (базовый слой merge).
         self._user_mcp_servers = user_mcp_servers or {}
         self._effort = effort
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
         self._pending_model_error = ""
+        # SDK content events point at parent tool_use_id, while Task* lifecycle
+        # messages use task_id. Keep the bridge so live output and persisted
+        # lifecycle records address the same UI card.
+        self._subagent_tool_to_task: dict[str, str] = {}
+        self._subagent_descriptions: dict[str, str] = {}
+        self._subagent_types: dict[str, str] = {}
 
     @property
     def session_id(self) -> Optional[str]:
         return self._session_id
 
     def _make_client(self) -> ClaudeSDKClient:
         import os
         cli = shutil.which("claude") or os.environ.get("CLAUDE_CLI_PATH", "claude")
@@ -272,16 +278,24 @@ class ClaudeBackend:
             return {}
         get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
         return {
             "total_tokens": get("total_tokens", 0) or 0,
             "tool_uses": get("tool_uses", 0) or 0,
             "duration_ms": get("duration_ms", 0) or 0,
         }
 
+    def _resolve_subagent_id(self, parent_tool_use_id):
+        if parent_tool_use_id is None:
+            return None
+        return self._subagent_tool_to_task.get(
+            str(parent_tool_use_id),
+            str(parent_tool_use_id),
+        )
+
     @staticmethod
     def _tag_sub(event: AgentEvent, sub_id) -> AgentEvent:
         """Mark an event as belonging to a sub-agent so the UI nests it.
 
         sub_id None (main agent) → event unchanged. Otherwise stamp subagent_id;
         the type is preserved (tool_use stays tool_use) — the frontend groups by
         subagent_id, not by a renamed type."""
         if sub_id is not None:
@@ -298,27 +312,29 @@ class ClaudeBackend:
             if ev.get("type") != "content_block_delta":
                 return events
             delta = ev.get("delta") or {}
             if delta.get("type") != "text_delta":
                 return events
             text = delta.get("text") or ""
             if not text:
                 return events
-            sub_id = msg.parent_tool_use_id
+            sub_id = self._resolve_subagent_id(msg.parent_tool_use_id)
             if sub_id is not None:
                 events.append(AgentEvent("subagent_stream", text, metadata={"subagent_id": sub_id}))
             else:
                 events.append(AgentEvent("stream", text))
             return events
 
         if isinstance(msg, AssistantMessage):
             # Subagent messages carry parent_tool_use_id → tag events so the UI groups
             # them under the sub-agent block instead of mixing with the parent's stream.
-            sub_id = getattr(msg, "parent_tool_use_id", None)
+            sub_id = self._resolve_subagent_id(
+                getattr(msg, "parent_tool_use_id", None)
+            )
             for block in msg.content:
                 if isinstance(block, TextBlock) and block.text:
                     events.append(self._tag_sub(AgentEvent("text", block.text), sub_id))
                 elif isinstance(block, ThinkingBlock) and block.thinking:
                     events.append(self._tag_sub(AgentEvent("thinking", block.thinking), sub_id))
                 elif isinstance(block, ToolUseBlock):
                     try:
                         inp = _json.dumps(block.input, ensure_ascii=False, indent=2)
@@ -334,57 +350,88 @@ class ClaudeBackend:
                 self._pending_model_error = str(err)
                 events.append(AgentEvent(
                     "error",
                     f"model error: {err}",
                     metadata={"model_error": str(err)},
                 ))
 
         elif isinstance(msg, UserMessage):
-            sub_id = getattr(msg, "parent_tool_use_id", None)
+            sub_id = self._resolve_subagent_id(
+                getattr(msg, "parent_tool_use_id", None)
+            )
             if hasattr(msg, 'content') and isinstance(msg.content, list):
                 for block in msg.content:
                     if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
                         events.append(self._tag_sub(AgentEvent("tool_result", _extract_tool_result(block)), sub_id))
 
         elif isinstance(msg, TaskStartedMessage):
             desc = getattr(msg, "description", "") or ""
             task_type = getattr(msg, "task_type", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
-            events.append(AgentEvent("subagent_start", f"{desc} | type={task_type} | id={task_id}",
+            tool_use_id = getattr(msg, "tool_use_id", "") or ""
+            if task_id:
+                self._subagent_descriptions[task_id] = desc
+                self._subagent_types[task_id] = task_type
+            if task_id and tool_use_id:
+                self._subagent_tool_to_task[tool_use_id] = task_id
+            events.append(AgentEvent(
+                "subagent_start",
+                f"{desc} | type={task_type} | id={task_id} | "
+                f"tool_use_id={tool_use_id}",
                                      metadata={"subagent_id": task_id, "phase": "start",
                                                "description": desc, "task_type": task_type,
                                                "sdk_session_id": getattr(msg, "session_id", "") or "",
-                                               "tool_use_id": getattr(msg, "tool_use_id", "") or ""}))
+                                               "tool_use_id": tool_use_id}))
 
         elif isinstance(msg, TaskProgressMessage):
             desc = getattr(msg, "description", "") or ""
             last_tool = getattr(msg, "last_tool_name", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
+            tool_use_id = getattr(msg, "tool_use_id", "") or ""
+            if task_id and desc:
+                self._subagent_descriptions[task_id] = desc
+            if task_id and tool_use_id:
+                self._subagent_tool_to_task[tool_use_id] = task_id
+            desc = desc or self._subagent_descriptions.get(task_id, "")
+            task_type = self._subagent_types.get(task_id, "")
             u = self._task_usage(getattr(msg, "usage", None))
             events.append(AgentEvent("subagent_progress",
-                                     f"{desc} | tool={last_tool} | tokens={u.get('total_tokens', 0)}",
+                                     f"{desc} | type={task_type} | id={task_id} | "
+                                     f"tool_use_id={tool_use_id} | tool={last_tool} | "
+                                     f"tokens={u.get('total_tokens', 0)}",
                                      metadata={"subagent_id": task_id, "phase": "progress",
-                                               "description": desc, "last_tool_name": last_tool,
+                                               "description": desc, "task_type": task_type,
+                                               "last_tool_name": last_tool,
                                                "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               "tool_use_id": tool_use_id,
                                                **u}))
 
         elif isinstance(msg, TaskNotificationMessage):
-            desc = getattr(msg, "description", "") or ""
             status = getattr(msg, "status", "") or ""
             summary = getattr(msg, "summary", "") or ""
             task_id = getattr(msg, "task_id", "") or ""
+            tool_use_id = getattr(msg, "tool_use_id", "") or ""
+            if task_id and tool_use_id:
+                self._subagent_tool_to_task[tool_use_id] = task_id
+            desc = self._subagent_descriptions.get(task_id, "")
+            task_type = self._subagent_types.get(task_id, "")
             output_file = getattr(msg, "output_file", "") or ""
             u = self._task_usage(getattr(msg, "usage", None))
             data = getattr(msg, "data", None)
-            events.append(AgentEvent("subagent_end", f"{desc} | status={status} | {summary[:500]}",
+            events.append(AgentEvent(
+                "subagent_end",
+                f"{desc} | type={task_type} | id={task_id} | "
+                f"tool_use_id={tool_use_id} | status={status} | {summary[:500]}",
                                      metadata={"subagent_id": task_id, "phase": "end",
-                                               "description": desc, "status": status,
+                                               "description": desc, "task_type": task_type,
+                                               "status": status,
                                                "summary": summary, "output_file": output_file,
                                                "sdk_session_id": getattr(msg, "session_id", "") or "",
+                                               "tool_use_id": tool_use_id,
                                                "raw_json": _json.dumps(data, ensure_ascii=False) if data else "",
                                                **u}))
 
         elif isinstance(msg, ResultMessage):
             sr = getattr(msg, "stop_reason", None) or "unknown"
             nt = getattr(msg, "num_turns", 0) or 0
             if msg.session_id:
                 self._session_id = msg.session_id
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 99c6bdc5d..e53d40af4 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -2171,23 +2171,32 @@ function _findLastBefore(parent, selector, anchor) {
         if (node.matches(selector)) return node;
         node = node.previousElementSibling;
     }
     return null;
 }
 
 const HIDE_THINKING = document.body.dataset.hideThinking === 'true';
 
-// Append a live sub-agent log line into its accordion body. If the accordion
-// isn't there yet (race: stream before start), no-op — the sub-agent block owns
-// its own rendering; live lines are best-effort decoration.
+// SDK stream events can beat TaskStarted by a few milliseconds. Buffer those
+// lines by parent tool id, then move them into the task-id card once it exists.
+const _pendingSubagentLogs = new Map();
 function appendSubagentLog(subId, evType, content) {
     const chat = $('#chat');
     const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
-    if (!host) return;
+    if (!host) {
+        if (!_pendingSubagentLogs.has(subId) && _pendingSubagentLogs.size >= 50) {
+            _pendingSubagentLogs.delete(_pendingSubagentLogs.keys().next().value);
+        }
+        const pending = _pendingSubagentLogs.get(subId) || [];
+        pending.push([evType, content]);
+        if (pending.length > 100) pending.shift();
+        _pendingSubagentLogs.set(subId, pending);
+        return;
+    }
     const body = host.querySelector('.sa-body');
     if (!body) return;
     if (evType === 'stream') {
         // Coalesce contiguous stream text into one line (typewriter feel)
         let last = body.lastElementChild;
         if (last && last.classList.contains('sa-stream')) {
             last.textContent += content;
         } else {
@@ -2202,16 +2211,26 @@ function appendSubagentLog(subId, evType, content) {
         line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
         const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
         line.textContent = `${icon} ${short}`;
         body.appendChild(line);
     }
     body.scrollTop = body.scrollHeight;
 }
 
+function _flushPendingSubagentLogs(sourceId, targetId) {
+    if (!sourceId || !targetId) return;
+    const pending = _pendingSubagentLogs.get(sourceId);
+    if (!pending) return;
+    _pendingSubagentLogs.delete(sourceId);
+    for (const [evType, content] of pending) {
+        appendSubagentLog(targetId, evType, content);
+    }
+}
+
 // Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
 // anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
 // payload = full SSE log object (carries subagent_id for sub-agent nesting)
 function addChatEntry(type, content, ts, anchor, payload) {
     if (HIDE_THINKING && type === 'thinking') return;
     // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
     if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
         appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
@@ -2394,24 +2413,27 @@ function addChatEntry(type, content, ts, anchor, payload) {
             if (eq > 0 && /^\w+$/.test(p.slice(0, eq))) meta[p.slice(0, eq)] = p.slice(eq + 1);
             else if (p) textParts.push(p);
         }
         const desc = textParts[0] || textParts[1] || '';
         const el = document.createElement('div');
         el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';
 
         const subId = (payload && payload.subagent_id) || meta.id || '';
+        const isBackground = meta.type === 'local_bash';
 
         if (type === 'subagent_start') {
             // Collapsible accordion: header + body where live sub-agent logs nest.
             el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
             if (subId) el.dataset.subagentId = subId;
+            el.dataset.subagentKind = isBackground ? 'background' : 'agent';
             const header = document.createElement('div');
             header.style.cssText = 'cursor:pointer;user-select:none';
-            header.innerHTML = `<span class="sa-caret">▶</span> 🤖 <span style="color:#e2e8f0">Sub-agent: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
+            const noun = isBackground ? 'Background task' : 'Sub-agent';
+            header.innerHTML = `<span class="sa-caret">▶</span> ${isBackground ? '⚙️' : '🤖'} <span style="color:#e2e8f0">${noun}: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
             const body = document.createElement('div');
             body.className = 'sa-body';
             body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
             let _expanded = false;
             header.addEventListener('click', () => {
                 _expanded = !_expanded;
                 body.style.display = _expanded ? 'block' : 'none';
                 header.querySelector('.sa-caret').textContent = _expanded ? '▼' : '▶';
@@ -2430,47 +2452,53 @@ function addChatEntry(type, content, ts, anchor, payload) {
                     prog.className = 'sa-progress';
                     prog.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
                     host.appendChild(prog);
                 }
                 prog.textContent = line;
                 return;  // updated in place, no new bubble
             }
             el.style.cssText += ';color:#64748b';
-            el.textContent = `⏳ "${desc}" — ${line}`;
+            el.textContent = `⏳ ${isBackground ? 'Background task' : 'Sub-agent'} "${desc}" — ${line}`;
         } else {  // subagent_end → mark the accordion done + collapse
             const ok = !meta.status || meta.status === 'completed';
             const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
             const summaryText = textParts.slice(1).join(' | ').trim();
             if (host) {
                 const hdr = host.querySelector('div');
-                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
+                const noun = host.dataset.subagentKind === 'background' ? 'Background task' : 'Sub-agent';
+                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
                 const prog = host.querySelector('.sa-progress');
                 if (prog) prog.remove();
                 if (summaryText) {
                     const sumEl = document.createElement('div');
                     sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
                     sumEl.textContent = summaryText;
                     host.appendChild(sumEl);
                 }
                 host.style.borderLeftColor = ok ? '#22c55e' : '#ef4444';
                 return;  // updated existing accordion, no new bubble
             }
             el.style.cssText += `;border-left:3px solid ${ok ? '#22c55e' : '#ef4444'};background:rgba(${ok ? '34,197,94' : '239,68,68'},0.06);color:${ok ? '#86efac' : '#fca5a5'}`;
-            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">Sub-agent ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
+            const noun = isBackground ? 'Background task' : 'Sub-agent';
+            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
             if (summaryText) {
                 const sumEl = document.createElement('div');
                 sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
                 sumEl.textContent = summaryText.length > 300 ? summaryText.slice(0, 300) + '…' : summaryText;
                 el.appendChild(sumEl);
             }
         }
         addTimestamp(el, ts);
         const wasAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
         _insert(el);
+        if (type === 'subagent_start' && subId) {
+            _flushPendingSubagentLogs(subId, subId);
+            _flushPendingSubagentLogs(meta.tool_use_id, subId);
+        }
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
     const div = document.createElement('div');
     div.className = `px-3 py-2 rounded-lg text-sm break-words ${
         type === 'user_message' ? 'chat-user ml-16' :
         type === 'tool' ? 'chat-tool' :
diff --git a/app/templates/dashboard.html b/app/templates/dashboard.html
index b2d03ee85..7b47c757d 100644
--- a/app/templates/dashboard.html
+++ b/app/templates/dashboard.html
@@ -248,17 +248,17 @@
             <!-- Agent Info -->
             <div id="agent-info" class="px-4 py-3 border-b border-slate-800/50 space-y-2">
                 <div class="flex items-center justify-between gap-2">
                     <span id="ai-name" class="font-semibold text-sm truncate min-w-0"></span>
                     <div class="flex items-center gap-2 shrink-0">
                         <button id="compact-btn" class="text-slate-500 hover:text-amber-300 text-xs hidden" title="Compact context">🗜</button>
                         <button id="restart-cli-btn" class="text-slate-500 hover:text-green-300 text-xs hidden" title="Restart CLI">♻️</button>
                         <button id="view-prompt-btn" class="text-slate-500 hover:text-indigo-300 text-xs hidden" title="View system prompt">📜</button>
-                        <button id="subagents-btn" class="text-slate-500 hover:text-purple-300 text-xs hidden" title="Sub-agents telemetry" onclick="openSubagentsModal()">🤖</button>
+                        <button id="subagents-btn" class="text-slate-500 hover:text-purple-300 text-xs hidden" title="Agent and background-task activity" onclick="openSubagentsModal()">🤖</button>
                         <span id="ai-status" class="text-xs font-mono"></span>
                     </div>
                 </div>
                 <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                     <span class="text-slate-500">Model</span><span id="ai-model" class="text-slate-300 break-all"></span>
                     <span class="text-slate-500">Role</span><span id="ai-role" class="text-purple-400 break-all"></span>
                     <span class="text-slate-500">Cost</span><span id="ai-cost" class="text-green-400"></span>
                     <span class="text-slate-500">Branch</span><span id="ai-branch" class="text-indigo-400 break-all font-mono"></span>
diff --git a/tests/test_backend_stream.py b/tests/test_backend_stream.py
index a54548c5f..10d657800 100644
--- a/tests/test_backend_stream.py
+++ b/tests/test_backend_stream.py
@@ -1,15 +1,20 @@
 """ClaudeBackend._convert StreamEvent scope filter + sub-agent tagging.
 
 Main-agent text_delta → "stream". Sub-agent text_delta (parent_tool_use_id set)
 → "subagent_stream" tagged with subagent_id (surfaced, not dropped). Non-text
 deltas (thinking/tool-arg/sig) and non-delta events are still dropped.
 """
-from claude_agent_sdk import StreamEvent
+from claude_agent_sdk import (
+    StreamEvent,
+    TaskNotificationMessage,
+    TaskProgressMessage,
+    TaskStartedMessage,
+)
 
 from app.backend_claude import ClaudeBackend
 from app.events import AgentEvent
 
 
 def _backend():
     return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")
 
@@ -77,16 +82,89 @@ def test_subagent_text_delta_becomes_subagent_stream():
     }, parent_tool_use_id="toolu_123")
     out = b._convert(msg)
     assert len(out) == 1
     assert out[0].type == "subagent_stream"
     assert out[0].content == "sub"
     assert out[0].metadata.get("subagent_id") == "toolu_123"
 
 
+def test_subagent_stream_resolves_parent_tool_use_to_task_id():
+    b = _backend()
+    start = TaskStartedMessage(
+        subtype="task_started",