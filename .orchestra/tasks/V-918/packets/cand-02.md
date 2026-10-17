# Candidate cand-02

## ORIGIN commit be3151563d (2026-06-04): refactor: extract currency symbol to CUR constant, remove hardcoded ₽
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index ef7bb5b8f..ac884d147 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -483,34 +483,34 @@ async def get_worker_info(name: str) -> str:
     return json.dumps(result, ensure_ascii=False)
 
 
 @mcp.tool()
 async def task_create(title: str, project: str, price: int = 0,
                       description: str = "", assignee: str = "",
                       status: str = "new", priority: int = 2) -> str:
     """Create a new task. Returns task number and details.
-    price in exact rubles (e.g. 20000 = 20 000₽). 0 is valid (no price).
+    price in exact currency units (e.g. 20000 = 20 000). 0 is valid (no price).
     priority: 0=critical, 1=high, 2=medium (default), 3=low."""
     result = await _api("POST", "/api/tm/tasks", json={
         "title": title, "project": project, "price": price,
         "description": description, "assignee": assignee, "status": status,
         "scope": SCOPE, "priority": priority,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     return json.dumps(result, ensure_ascii=False)
 
 
 @mcp.tool()
 async def task_update(par: str, title: str = "", description: str = "",
                       price: int = -1, status: str = "",
                       assignee: str = "", priority: int = -1) -> str:
     """Update an existing task. Only provided fields are changed.
-    par: '42' or 'PAR-42' (legacy). price in exact rubles (-1 = don't change, 0 = set to zero).
+    par: '42' or 'PAR-42' (legacy). price in exact currency units (-1 = don't change, 0 = set to zero).
     Empty string = don't change for text fields. priority: 0-3 or -1=don't change."""
     body: dict = {}
     if title:
         body["title"] = title
     if description:
         body["description"] = description
     if price >= 0:
         body["price"] = price
@@ -555,17 +555,17 @@ async def task_get(par: str) -> str:
         return f"Error: {result['error']}"
     return json.dumps(result, ensure_ascii=False)
 
 
 @mcp.tool()
 async def payment_receive(amount: int, client: str = "",
                           date: str = "", note: str = "") -> str:
     """Record incoming payment. Auto-distributes to done tasks (smallest debt first).
-    amount in exact rubles (e.g. 30000 = 30 000₽)."""
+    amount in exact currency units (e.g. 30000 = 30 000)."""
     result = await _api("POST", "/api/tm/payments", json={
         "amount": amount, "client": client, "date": date, "note": note,
         "scope": SCOPE,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     return json.dumps(result, ensure_ascii=False)
 
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 6985a8b3e..913e935a1 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1,9 +1,10 @@
 const MAX_CHAT_NODES = 500;
+const CUR = '₽';
 let currentScope = null;
 let selectedAgent = null;
 let chatLogs = {};
 let localMessages = new Set();
 let pendingUserMsgs = [];
 let pendingBubble = null;
 let uiDebounceTimer = null;
 let refreshController = null;
@@ -1749,17 +1750,17 @@ function buildCompactToolLine(type, content, ts) {
             else if (rawName === 'mcp__orchestra__update_worker_description') preview = `✏️ ${parsed.name || '?'} — description`;
             else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
             else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
             else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
             else if (rawName === 'mcp__orchestra__task_create') { const _pp = {0:'🔴',1:'🟠',3:'🟢'}[parsed.priority]||''; preview = `📋 New: ${_pp}"${parsed.title || '?'}"${parsed.price ? ' | '+parsed.price+'k' : ''}`; }
             else if (rawName === 'mcp__orchestra__task_update') { const _f = Object.keys(parsed).filter(k=>k!=='par').map(k=>`${k}→${parsed[k]}`).join(', '); preview = `✏️ #${taskNum(parsed.par) || '?'}: ${_f}`; }
             else if (rawName === 'mcp__orchestra__task_list') { const _fl = [parsed.status,parsed.project,parsed.assignee].filter(Boolean).join(', '); preview = `📋 Tasks${_fl ? ' ('+_fl+')' : ''}`; }
             else if (rawName === 'mcp__orchestra__task_get') preview = `📋 #${taskNum(parsed.par) || '?'}`;
-            else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'}k ₽`;
+            else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'}k ${CUR}`;
             else if (rawName === 'mcp__orchestra__payment_status') preview = '💰 Balance';
             else if (rawName === 'mcp__orchestra__bg_create') { const _bi = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
             else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
             else if (rawName === 'mcp__orchestra__bg_cancel') preview = `⏹ Cancel job ${(parsed.job_id||'').slice(0,8)}`;
             else if (rawName.startsWith('mcp__yougile__')) { const yn = rawName.replace('mcp__yougile__',''); preview = `📋 ${yn}${parsed.title ? ': '+parsed.title : ''}`; }
             else if (rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch') { let _d = '?'; try { _d = new URL(parsed.url).hostname; } catch {} preview = `🌐 ${_d}`; }
             else if (parsed.file_path) preview = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') + (parsed.offset ? ` :${parsed.offset}` : '') + (parsed.limit ? ` (${parsed.limit} lines)` : '');
             else if (parsed.command) preview = parsed.command;
@@ -2422,21 +2423,21 @@ function addChatEntry(type, content, ts, anchor) {
             'mcp__orchestra__change_worker_model': (d) => ({ icon: '🔄', label: `Model: ${d.name||'?'} → ${d.model||'?'}`, color: '#38bdf8' }),
             'mcp__orchestra__update_worker_description': (d) => ({ icon: '✏️', label: `${d.name||'?'} — description updated`, color: '#38bdf8', sub: d.description ? `"${d.description}"` : '' }),
             'mcp__orchestra__merge_worker': (d) => ({ icon: '🔀', label: `Merge: ${d.name||'?'}`, color: '#a78bfa' }),
             'mcp__orchestra__list_agents': () => ({ icon: '🎼', label: 'Agents', color: '#a78bfa' }),
             'mcp__orchestra__list_orchestrators': () => ({ icon: '🎯', label: 'Orchestrators', color: '#a78bfa' }),
             'mcp__orchestra__list_jobs': () => ({ icon: '📊', label: 'Jobs', color: '#38bdf8' }),
             'mcp__orchestra__get_worker_logs': (d) => ({ icon: '📋', label: `Logs: ${d.name||'?'}`, color: '#a78bfa', sub: d.limit ? `${d.limit} entries` : '' }),
             'mcp__orchestra__get_worker_info': (d) => ({ icon: '🤖', label: `Info: ${d.name||'?'}`, color: '#a78bfa' }),
-            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `New: "${d.title||'?'}"`, color: '#22c55e', sub: d.price ? `${d.price}k ₽` : '' }),
+            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `New: "${d.title||'?'}"`, color: '#22c55e', sub: d.price ? `${d.price}k ${CUR}` : '' }),
             'mcp__orchestra__task_update': (d) => { const f = Object.keys(d).filter(k=>k!=='par').map(k=>`${k}→${d[k]}`).join(', '); return { icon: '✏️', label: `#${taskNum(d.par)||'?'}: ${f}`, color: '#38bdf8' }; },
             'mcp__orchestra__task_list': (d) => { const f = [d.status,d.project,d.assignee].filter(Boolean).join(', '); return { icon: '📋', label: `Tasks${f ? ' ('+f+')' : ''}`, color: '#a78bfa' }; },
             'mcp__orchestra__task_get': (d) => ({ icon: '📋', label: `Task #${taskNum(d.par)||'?'}`, color: '#a78bfa' }),
-            'mcp__orchestra__payment_receive': (d) => ({ icon: '💰', label: `+${d.amount||'?'}k ₽`, color: '#22c55e', sub: d.note || '' }),
+            'mcp__orchestra__payment_receive': (d) => ({ icon: '💰', label: `+${d.amount||'?'}k ${CUR}`, color: '#22c55e', sub: d.note || '' }),
             'mcp__orchestra__payment_status': () => ({ icon: '💰', label: 'Balance', color: '#eab308' }),
             'mcp__orchestra__bg_create': (d) => { const i = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[d.type]||'⚙️'; return { icon: i, label: `BG ${d.type||'job'}${d.delay_seconds ? ' '+Math.round(d.delay_seconds/60)+'m' : ''}`, color: '#38bdf8', sub: d.message || d.target || '' }; },
             'mcp__orchestra__bg_list': () => ({ icon: '📊', label: 'BG Jobs', color: '#a78bfa' }),
             'mcp__orchestra__bg_cancel': (d) => ({ icon: '⏹', label: `Cancel ${(d.job_id||'').slice(0,8)}`, color: '#94a3b8' }),
         };
         const isOrchSimple = _orchSimple[rawName];
         if (isOrchSimple) {
             try {
@@ -2814,17 +2815,17 @@ function addChatEntry(type, content, ts, anchor) {
                     const _k = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : String(v)) : v;
                     if (hdr) { hdr.textContent = `📋 #${parsed.par}: ${parsed.title || '?'}`; hdr.style.color = tn.includes('create') ? '#22c55e' : '#a78bfa'; }
                     const info = document.createElement('div');
                     info.style.cssText = 'margin-top:4px;display:grid;grid-template-columns:1fr 1fr;gap:2px 8px;font-size:10px;color:#64748b';
                     const stColor = {'done':'#22c55e','paid':'#22c55e','in_progress':'#38bdf8','new':'#e2e8f0','cancelled':'#ef4444'}[parsed.status] || '#e2e8f0';
                     if (parsed.status) info.innerHTML += `<div>Status: <b style="color:${stColor}">${parsed.status}</b></div>`;
                     if (parsed.project) info.innerHTML += `<div>Project: <span style="color:#94a3b8">${DOMPurify.sanitize(parsed.project)}</span></div>`;
                     const priceRub = parsed.price_rub ?? 0;
-                    info.innerHTML += `<div>Price: <b style="color:#eab308">${_k(priceRub)} ₽</b></div>`;
+                    info.innerHTML += `<div>Price: <b style="color:#eab308">${_k(priceRub)} ${CUR}</b></div>`;
                     if (priceRub > 0) info.innerHTML += `<div>Paid: ${_k(parsed.paid_rub||0)}/${_k(priceRub)}${parsed.debt_rub > 0 ? ` <span style="color:#ef4444">debt ${_k(parsed.debt_rub)}</span>` : ''}</div>`;
                     if (parsed.assignee) info.innerHTML += `<div>Assignee: ${DOMPurify.sanitize(parsed.assignee)}</div>`;
                     if (parsed.created_at) info.innerHTML += `<div>Created: ${(parsed.created_at||'').slice(0,10)}</div>`;
                     if (parsed.updated_at) info.innerHTML += `<div>Updated: ${(parsed.updated_at||'').slice(0,10)}</div>`;
                     if (parsed.completed_at) info.innerHTML += `<div>Done: ${(parsed.completed_at||'').slice(0,10)}</div>`;
                     if (parsed.paid_at) info.innerHTML += `<div>Paid: ${(parsed.paid_at||'').slice(0,10)}</div>`;
                     lastTool.appendChild(info);
                     if (parsed.description) {
@@ -2853,17 +2854,17 @@ function addChatEntry(type, content, ts, anchor) {
                     }
                 } else if (tn === 'mcp__orchestra__task_update') {
                     const _kr = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
                     const changes = [];
                     if (parsed.old_status && parsed.new_status && parsed.old_status !== parsed.new_status) changes.push(`status ${parsed.old_status}→${parsed.new_status}`);
                     if (parsed.updated) {
                         for (const f of parsed.updated) {
                             if (f === 'status') continue;
-                            if (f === 'price' && parsed.price_rub != null) changes.push(`price ${_kr(parsed.price_rub)} ₽`);
+                            if (f === 'price' && parsed.price_rub != null) changes.push(`price ${_kr(parsed.price_rub)} ${CUR}`);
                             else if (f === 'assignee' && parsed.assignee != null) changes.push(`assignee→${parsed.assignee || '—'}`);
                             else if (f === 'title') changes.push('title');
                             else if (f === 'description') changes.push('description');
                             else changes.push(f);
                         }
                     }
                     const parNum = (parsed.par || '?').replace(/^[A-Z]+-/, '');
                     const titleStr = parsed.title ? ` "${parsed.title.slice(0,40)}"` : '';
@@ -2897,17 +2898,17 @@ function addChatEntry(type, content, ts, anchor) {
                                 newEl.textContent = _duExp ? parsed.description : parsed.description.split('\n').slice(0,3).join('\n') + '…';
                                 newEl.style.maxHeight = _duExp ? 'none' : '40px';
                                 newEl.style.overflowY = _duExp ? 'visible' : 'hidden';
                             });
                         }
                     }
                     const detail = document.createElement('div');
                     detail.style.cssText = 'margin-top:3px;font-size:10px;color:#64748b;display:flex;gap:8px;flex-wrap:wrap';
-                    if (parsed.price_rub > 0) detail.innerHTML += `<span>Price: <b style="color:#eab308">${_kr(parsed.price_rub)} ₽</b></span>`;
+                    if (parsed.price_rub > 0) detail.innerHTML += `<span>Price: <b style="color:#eab308">${_kr(parsed.price_rub)} ${CUR}</b></span>`;
                     if (parsed.paid_rub > 0) detail.innerHTML += `<span>Paid: ${_kr(parsed.paid_rub)}</span>`;
                     if (parsed.debt_rub > 0) detail.innerHTML += `<span style="color:#ef4444">Debt: ${_kr(parsed.debt_rub)}</span>`;
                     if (detail.innerHTML) lastTool.appendChild(detail);
                 } else if (tn === 'mcp__orchestra__task_list') {
                     const tasks = parsed.tasks || [];
                     const _k = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
                     if (hdr) hdr.textContent = `📋 ${tasks.length} tasks` + (parsed.total_debt && parsed.total_debt !== '0' ? ` | debt: ${parsed.total_debt}` : '');
                     if (tasks.length > 0 && parsed.detailed) {
@@ -2916,17 +2917,17 @@ function addChatEntry(type, content, ts, anchor) {
                         const PREVIEW = 3;
                         for (const [i, t] of tasks.entries()) {
                             const card = document.createElement('div');
                             card.style.cssText = `padding:6px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${t.status==='done'||t.status==='paid'?'#22c55e':t.status==='in_progress'?'#38bdf8':'#334155'}${i >= PREVIEW ? ';display:none' : ''}`;
                             card.dataset.taskRow = '1';
                             let h = `<div style="font-size:11px;color:#e2e8f0;font-weight:600">${DOMPurify.sanitize(t.par)}: ${DOMPurify.sanitize(t.title)}</div>`;
                             h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px 8px;font-size:10px;color:#64748b;margin-top:3px">';
                             h += `<div>Status: <b style="color:#e2e8f0">${t.status}</b></div>`;
-                            if (t.price_rub > 0) h += `<div>Price: <b style="color:#eab308">${_k(t.price_rub)} ₽</b>${t.debt_rub > 0 ? ` <span style="color:#ef4444">debt ${_k(t.debt_rub)}</span>` : ''}</div>`;
+                            if (t.price_rub > 0) h += `<div>Price: <b style="color:#eab308">${_k(t.price_rub)} ${CUR}</b>${t.debt_rub > 0 ? ` <span style="color:#ef4444">debt ${_k(t.debt_rub)}</span>` : ''}</div>`;
                             if (t.project) h += `<div>Project: ${DOMPurify.sanitize(t.project)}</div>`;
                             if (t.assignee) h += `<div>→ ${DOMPurify.sanitize(t.assignee)}</div>`;
                             if (t.created_at) h += `<div>Created: ${t.created_at.slice(0,10)}</div>`;
                             if (t.completed_at) h += `<div>Done: ${t.completed_at.slice(0,10)}</div>`;
                             h += '</div>';
                             if (t.description) {
                                 const short = t.description.split('\n').slice(0,3).join('\n');
                                 h += `<div style="font-size:10px;color:#94a3b8;margin-top:3px;max-height:40px;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere">${DOMPurify.sanitize(short)}${t.description.length > short.length ? '…' : ''}</div>`;
@@ -2977,50 +2978,50 @@ function addChatEntry(type, content, ts, anchor) {
                                 container.querySelectorAll('[data-task-row]').forEach((r, i) => { if (i >= PREVIEW) r.style.display = _tlExp ? 'flex' : 'none'; });
                                 hint.textContent = _tlExp ? '▲ collapse' : `▼ ${tasks.length - PREVIEW} more`;
                             });
                         }
                     }
                 } else if (tn === 'mcp__orchestra__payment_receive') {
                     const _kr = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
                     const amt = parsed.amount_rub ? _kr(parsed.amount_rub) : (parsed.amount || '?') + 'k';
-                    if (hdr) { hdr.textContent = `💰 +${amt} ₽ received`; hdr.style.color = '#22c55e'; }
+                    if (hdr) { hdr.textContent = `💰 +${amt} ${CUR} received`; hdr.style.color = '#22c55e'; }
                     const payInfo = document.createElement('div');
                     payInfo.style.cssText = 'margin-top:4px;font-size:10px;color:#64748b';
                     let payHtml = '';
                     if (parsed.distributions && parsed.distributions.length > 0) {
                         payHtml += parsed.distributions.map(d => {
                             const a = d.allocated ? _kr(d.allocated) : (d.amount || '?') + 'k';
-                            return `<div style="display:flex;gap:6px"><span style="color:#94a3b8;min-width:60px">${d.par}</span><span style="color:#22c55e">+${a} ₽</span>${d.remaining != null ? `<span style="color:#475569">remaining: ${_kr(d.remaining)}</span>` : ''}</div>`;
+                            return `<div style="display:flex;gap:6px"><span style="color:#94a3b8;min-width:60px">${d.par}</span><span style="color:#22c55e">+${a} ${CUR}</span>${d.remaining != null ? `<span style="color:#475569">remaining: ${_kr(d.remaining)}</span>` : ''}</div>`;
                         }).join('');
                     }
-                    if (parsed.balance_rub != null) payHtml += `<div style="margin-top:2px;color:#eab308">Balance: ${_kr(parsed.balance_rub)} ₽</div>`;
+                    if (parsed.balance_rub != null) payHtml += `<div style="margin-top:2px;color:#eab308">Balance: ${_kr(parsed.balance_rub)} ${CUR}</div>`;
                     if (payHtml) { payInfo.innerHTML = payHtml; lastTool.appendChild(payInfo); }
                 } else if (tn === 'mcp__orchestra__payment_status') {
                     const _kr = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
                     const bal = parsed.balance_rub != null ? _kr(parsed.balance_rub) : (parsed.balance_display || '0');
                     const debt = parsed.total_debt_rub != null ? _kr(parsed.total_debt_rub) : (parsed.total_debt_display || '0');
                     if (hdr) {
-                        hdr.textContent = `💰 Balance: ${bal} ₽ | Debt: ${debt} ₽`;
+                        hdr.textContent = `💰 Balance: ${bal} ${CUR} | Debt: ${debt} ${CUR}`;
                         hdr.style.color = '#eab308';
                     }
                     const payments = parsed.recent_payments || parsed.payments || [];
                     if (payments.length > 0) {
                         const pEl = document.createElement('div');
                         pEl.style.cssText = 'margin-top:4px;font-size:10px;color:#64748b';
                         pEl.innerHTML = payments.slice(0, 5).map(p => {
                             const a = p.amount_rub ? _kr(p.amount_rub) : p.amount;
                             return `<div>${p.date}: <span style="color:#22c55e">+${a}</span>${p.note ? ' — '+DOMPurify.sanitize(p.note) : ''}</div>`;
                         }).join('');
                         lastTool.appendChild(pEl);
                     }
                     if (parsed.tasks_with_debt && parsed.tasks_with_debt.length > 0) {
                         const dEl = document.createElement('div');
                         dEl.style.cssText = 'margin-top:4px;font-size:10px;color:#ef4444';
-                        dEl.innerHTML = '<div style="color:#64748b;margin-bottom:2px">Debt:</div>' + parsed.tasks_with_debt.map(t => `<div>${t.par}: ${_kr(t.debt_rub || t.debt)} ₽</div>`).join('');
+                        dEl.innerHTML = '<div style="color:#64748b;margin-bottom:2px">Debt:</div>' + parsed.tasks_with_debt.map(t => `<div>${t.par}: ${_kr(t.debt_rub || t.debt)} ${CUR}</div>`).join('');
                         lastTool.appendChild(dEl);
                     }
                 } else if (tn === 'mcp__orchestra__bg_list') {
                     const jobs = Array.isArray(parsed) ? parsed : (parsed.jobs || []);
                     if (hdr) hdr.textContent = `📊 ${jobs.length} jobs`;
                     if (jobs.length > 0) {
                         const container = document.createElement('div');
                         container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
@@ -4903,19 +4904,19 @@ async function showTaskDetail(par) {
         const modal = document.getElementById('prompt-modal');
         const nameEl = document.getElementById('prompt-modal-name');
         const bodyEl = document.getElementById('prompt-modal-body');
         if (!modal || !nameEl || !bodyEl) return;
         nameEl.textContent = '#' + t.par + ' ' + t.title;
         let html = '<div class="space-y-3">';
         html += '<div class="grid grid-cols-2 gap-2 text-xs">';
         html += `<div><span class="text-slate-500">Status:</span> <span class="font-bold">${t.status}</span></div>`;
-        html += `<div><span class="text-slate-500">Price:</span> <span class="text-amber-400">${t.price_rub > 0 ? (t.price_rub/1000)+'k ₽' : '—'}</span></div>`;
+        html += `<div><span class="text-slate-500">Price:</span> <span class="text-amber-400">${t.price_rub > 0 ? (t.price_rub/1000)+'k ${CUR}' : '—'}</span></div>`;
         html += `<div><span class="text-slate-500">Paid:</span> ${(t.paid_rub||0)/1000}/${(t.price_rub||0)/1000}k</div>`;
-        html += `<div><span class="text-slate-500">Debt:</span> <span class="text-red-400">${t.debt_rub > 0 ? (t.debt_rub/1000)+'k ₽' : '0'}</span></div>`;
+        html += `<div><span class="text-slate-500">Debt:</span> <span class="text-red-400">${t.debt_rub > 0 ? (t.debt_rub/1000)+'k ${CUR}' : '0'}</span></div>`;
         html += `<div><span class="text-slate-500">Assignee:</span> ${escHtml(t.assignee || '—')}</div>`;
         const _PRI = {0:'🔴 Critical',1:'🟠 High',2:'🟡 Medium',3:'🟢 Low'};
         html += `<div><span class="text-slate-500">Priority:</span> ${_PRI[t.priority] || 'Medium'}</div>`;
         html += `<div><span class="text-slate-500">Project:</span> ${escHtml(t.project)}</div>`;
         html += `<div><span class="text-slate-500">Created:</span> ${(t.created_at||'').slice(0,10)}</div>`;
         if (t.updated_at) html += `<div><span class="text-slate-500">Updated:</span> ${t.updated_at.slice(0,10)}</div>`;
         if (t.completed_at) html += `<div><span class="text-slate-500">Done:</span> ${t.completed_at.slice(0,10)}</div>`;
         if (t.paid_at) html += `<div><span class="text-slate-500">Paid at:</span> ${t.paid_at.slice(0,10)}</div>`;


## LATER FIX 24b84184e6 (4.0 days later): fix: remove k suffix from prices — display exact amounts with space separator
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

fix: remove k suffix from prices — display exact amounts with space separator


diff --git a/app/static/js/app.js b/app/static/js/app.js
index ef20094a3..e0f5addc8 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1763,21 +1763,21 @@ function buildCompactToolLine(type, content, ts) {
             else if (rawName === 'mcp__orchestra__compact_worker') preview = `🗜 Compact: ${parsed.name || '?'}`;
             else if (rawName === 'mcp__orchestra__list_jobs') preview = '📊 Jobs';
             else if (rawName === 'mcp__orchestra__rename_worker') preview = `✏️ ${parsed.old_name || '?'} → ${parsed.new_name || '?'}`;
             else if (rawName === 'mcp__orchestra__change_worker_model') preview = `🔄 ${parsed.name || '?'} → ${parsed.model || '?'}`;
             else if (rawName === 'mcp__orchestra__update_worker_description') preview = `✏️ ${parsed.name || '?'} — description`;
             else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
             else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
             else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
-            else if (rawName === 'mcp__orchestra__task_create') { const _pp = {0:'🔴',1:'🟠',3:'🟢'}[parsed.priority]||''; preview = `📋 New: ${_pp}"${parsed.title || '?'}"${parsed.price ? ' | '+parsed.price+'k' : ''}`; }
+            else if (rawName === 'mcp__orchestra__task_create') { const _pp = {0:'🔴',1:'🟠',3:'🟢'}[parsed.priority]||''; preview = `📋 New: ${_pp}"${parsed.title || '?'}"${parsed.price ? ' | '+parsed.price+' ${CUR}' : ''}`; }
             else if (rawName === 'mcp__orchestra__task_update') { const _f = Object.keys(parsed).filter(k=>k!=='par').map(k=>`${k}→${parsed[k]}`).join(', '); preview = `✏️ #${taskNum(parsed.par) || '?'}: ${_f}`; }
             else if (rawName === 'mcp__orchestra__task_list') { const _fl = [parsed.status,parsed.project,parsed.assignee].filter(Boolean).join(', '); preview = `📋 Tasks${_fl ? ' ('+_fl+')' : ''}`; }
             else if (rawName === 'mcp__orchestra__task_get') preview = `📋 #${taskNum(parsed.par) || '?'}`;
-            else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'}k ${CUR}`;
+            else if (rawName === 'mcp__orchestra__payment_receive') preview = `💰 +${parsed.amount || '?'} ${CUR}`;
             else if (rawName === 'mcp__orchestra__payment_status') preview = '💰 Balance';
             else if (rawName === 'mcp__orchestra__bg_create') { const _bi = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
             else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
             else if (rawName === 'mcp__orchestra__bg_cancel') preview = `⏹ Cancel job ${(parsed.job_id||'').slice(0,8)}`;
             else if (rawName.startsWith('mcp__yougile__')) { const yn = rawName.replace('mcp__yougile__',''); preview = `📋 ${yn}${parsed.title ? ': '+parsed.title : ''}`; }
             else if (rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch') { let _d = '?'; try { _d = new URL(parsed.url).hostname; } catch {} preview = `🌐 ${_d}`; }
             else if (parsed.file_path) preview = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') + (parsed.offset ? ` :${parsed.offset}` : '') + (parsed.limit ? ` (${parsed.limit} lines)` : '');
             else if (parsed.command) preview = parsed.command;
@@ -2442,21 +2442,21 @@ function addChatEntry(type, content, ts, anchor) {
             'mcp__orchestra__change_worker_model': (d) => ({ icon: '🔄', label: `Model: ${d.name||'?'} → ${d.model||'?'}`, color: '#38bdf8' }),
             'mcp__orchestra__update_worker_description': (d) => ({ icon: '✏️', label: `${d.name||'?'} — description updated`, color: '#38bdf8', sub: d.description ? `"${d.description}"` : '' }),
             'mcp__orchestra__merge_worker': (d) => ({ icon: '🔀', label: `Merge: ${d.name||'?'}`, color: '#a78bfa' }),
             'mcp__orchestra__list_agents': () => ({ icon: '🎼', label: 'Agents', color: '#a78bfa' }),
             'mcp__orchestra__list_orchestrators': () => ({ icon: '🎯', label: 'Orchestrators', color: '#a78bfa' }),
             'mcp__orchestra__list_jobs': () => ({ icon: '📊', label: 'Jobs', color: '#38bdf8' }),
             'mcp__orchestra__get_worker_logs': (d) => ({ icon: '📋', label: `Logs: ${d.name||'?'}`, color: '#a78bfa', sub: d.limit ? `${d.limit} entries` : '' }),
             'mcp__orchestra__get_worker_info': (d) => ({ icon: '🤖', label: `Info: ${d.name||'?'}`, color: '#a78bfa' }),
-            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `New: "${d.title||'?'}"`, color: '#22c55e', sub: d.price ? `${d.price}k ${CUR}` : '' }),
+            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `New: "${d.title||'?'}"`, color: '#22c55e', sub: d.price ? `${d.price} ${CUR}` : '' }),
             'mcp__orchestra__task_update': (d) => { const f = Object.keys(d).filter(k=>k!=='par').map(k=>`${k}→${d[k]}`).join(', '); return { icon: '✏️', label: `#${taskNum(d.par)||'?'}: ${f}`, color: '#38bdf8' }; },
             'mcp__orchestra__task_list': (d) => { const f = [d.status,d.project,d.assignee].filter(Boolean).join(', '); return { icon: '📋', label: `Tasks${f ? ' ('+f+')' : ''}`, color: '#a78bfa' }; },
             'mcp__orchestra__task_get': (d) => ({ icon: '📋', label: `Task #${taskNum(d.par)||'?'}`, color: '#a78bfa' }),
-            'mcp__orchestra__payment_receive': (d) => ({ icon: '💰', label: `+${d.amount||'?'}k ${CUR}`, color: '#22c55e', sub: d.note || '' }),
+            'mcp__orchestra__payment_receive': (d) => ({ icon: '💰', label: `+${d.amount||'?'} ${CUR}`, color: '#22c55e', sub: d.note || '' }),
             'mcp__orchestra__payment_status': () => ({ icon: '💰', label: 'Balance', color: '#eab308' }),
             'mcp__orchestra__bg_create': (d) => { const i = {'timer':'⏰','file':'📄','command':'🖥️','ssh':'🔗','run':'▶️'}[d.type]||'⚙️'; return { icon: i, label: `BG ${d.type||'job'}${d.delay_seconds ? ' '+Math.round(d.delay_seconds/60)+'m' : ''}`, color: '#38bdf8', sub: d.message || d.target || '' }; },
             'mcp__orchestra__bg_list': () => ({ icon: '📊', label: 'BG Jobs', color: '#a78bfa' }),
             'mcp__orchestra__bg_cancel': (d) => ({ icon: '⏹', label: `Cancel ${(d.job_id||'').slice(0,8)}`, color: '#94a3b8' }),
         };
         const isOrchSimple = _orchSimple[rawName];
         if (isOrchSimple) {
             try {
@@ -2826,17 +2826,17 @@ function addChatEntry(type, content, ts, anchor) {
                 try { parsed = JSON.parse(content); } catch {}
                 const tn = lastTool.dataset.toolRawName;
                 if (!parsed || parsed.error) {
                     if (hdr) { hdr.textContent = `❌ ${parsed?.error || clean.slice(0, 80)}`; hdr.style.color = '#ef4444'; }
                     addTimestamp(lastTool, ts);
                     return;
                 }
                 if (tn === 'mcp__orchestra__task_create' || tn === 'mcp__orchestra__task_get') {
-                    const _k = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : String(v)) : v;
+                    const _k = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                     if (hdr) { hdr.textContent = `📋 #${parsed.par}: ${parsed.title || '?'}`; hdr.style.color = tn.includes('create') ? '#22c55e' : '#a78bfa'; }
                     const info = document.createElement('div');
                     info.style.cssText = 'margin-top:4px;display:grid;grid-template-columns:1fr 1fr;gap:2px 8px;font-size:10px;color:#64748b';
                     const stColor = {'done':'#22c55e','paid':'#22c55e','in_progress':'#38bdf8','new':'#e2e8f0','cancelled':'#ef4444'}[parsed.status] || '#e2e8f0';
                     if (parsed.status) info.innerHTML += `<div>Status: <b style="color:${stColor}">${parsed.status}</b></div>`;
                     if (parsed.project) info.innerHTML += `<div>Project: <span style="color:#94a3b8">${DOMPurify.sanitize(parsed.project)}</span></div>`;
                     const priceRub = parsed.price_rub ?? 0;
                     info.innerHTML += `<div>Price: <b style="color:#eab308">${_k(priceRub)} ${CUR}</b></div>`;
@@ -2867,17 +2867,17 @@ function addChatEntry(type, content, ts, anchor) {
                     if (parsed.sync_revision) sys.push(`rev: ${parsed.sync_revision}`);
                     if (sys.length > 0) {
                         const sEl = document.createElement('div');
                         sEl.style.cssText = 'margin-top:4px;font-size:9px;color:#475569;font-family:monospace';
                         sEl.textContent = sys.join(' · ');
                         lastTool.appendChild(sEl);
                     }
                 } else if (tn === 'mcp__orchestra__task_update') {
-                    const _kr = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
+                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                     const changes = [];
                     if (parsed.old_status && parsed.new_status && parsed.old_status !== parsed.new_status) changes.push(`status ${parsed.old_status}→${parsed.new_status}`);
                     if (parsed.updated) {
                         for (const f of parsed.updated) {
                             if (f === 'status') continue;
                             if (f === 'price' && parsed.price_rub != null) changes.push(`price ${_kr(parsed.price_rub)} ${CUR}`);
                             else if (f === 'assignee' && parsed.assignee != null) changes.push(`assignee→${parsed.assignee || '—'}`);
                             else if (f === 'title') changes.push('title');
@@ -2995,32 +2995,32 @@ function addChatEntry(type, content, ts, anchor) {
                                 if (e.target.tagName === 'A') return;
                                 _tlExp = !_tlExp;
                                 container.querySelectorAll('[data-task-row]').forEach((r, i) => { if (i >= PREVIEW) r.style.display = _tlExp ? 'flex' : 'none'; });
                                 hint.textContent = _tlExp ? '▲ collapse' : `▼ ${tasks.length - PREVIEW} more`;
                             });
                         }
                     }
                 } else if (tn === 'mcp__orchestra__payment_receive') {
-                    const _kr = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
+                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                     const amt = parsed.amount_rub ? _kr(parsed.amount_rub) : (parsed.amount || '?') + 'k';
                     if (hdr) { hdr.textContent = `💰 +${amt} ${CUR} received`; hdr.style.color = '#22c55e'; }
                     const payInfo = document.createElement('div');
                     payInfo.style.cssText = 'margin-top:4px;font-size:10px;color:#64748b';
                     let payHtml = '';
                     if (parsed.distributions && parsed.distributions.length > 0) {
                         payHtml += parsed.distributions.map(d => {
                             const a = d.allocated ? _kr(d.allocated) : (d.amount || '?') + 'k';
                             return `<div style="display:flex;gap:6px"><span style="color:#94a3b8;min-width:60px">${d.par}</span><span style="color:#22c55e">+${a} ${CUR}</span>${d.remaining != null ? `<span style="color:#475569">remaining: ${_kr(d.remaining)}</span>` : ''}</div>`;
                         }).join('');
                     }
                     if (parsed.balance_rub != null) payHtml += `<div style="margin-top:2px;color:#eab308">Balance: ${_kr(parsed.balance_rub)} ${CUR}</div>`;
                     if (payHtml) { payInfo.innerHTML = payHtml; lastTool.appendChild(payInfo); }
                 } else if (tn === 'mcp__orchestra__payment_status') {
-                    const _kr = (v) => typeof v === 'number' ? (v >= 1000 ? (v/1000)+'k' : v) : v;
+                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                     const bal = parsed.balance_rub != null ? _kr(parsed.balance_rub) : (parsed.balance_display || '0');
                     const debt = parsed.total_debt_rub != null ? _kr(parsed.total_debt_rub) : (parsed.total_debt_display || '0');
                     if (hdr) {
                         hdr.textContent = `💰 Balance: ${bal} ${CUR} | Debt: ${debt} ${CUR}`;
                         hdr.style.color = '#eab308';
                     }
                     const payments = parsed.recent_payments || parsed.payments || [];
                     if (payments.length > 0) {
diff --git a/app/tm.py b/app/tm.py
index 8a1cae559..6845af279 100644
--- a/app/tm.py
+++ b/app/tm.py
@@ -21,17 +21,25 @@ def _now() -> str:
     return datetime.now(timezone.utc).isoformat()
 
 
 def _today() -> str:
     return date.today().isoformat()
 
 
 def _fmt_amount(rub: int) -> str:
-    return str(rub)
+    if rub == 0:
+        return "0"
+    s = str(abs(rub))
+    groups = []
+    while s:
+        groups.append(s[-3:])
+        s = s[:-3]
+    formatted = " ".join(reversed(groups))
+    return f"-{formatted}" if rub < 0 else formatted
 
 
 def _parse_task_ref(ref: str) -> tuple[str, int]:
     """Parse '42', '#42', 'PAR-42' (legacy), 'ORC-1' (legacy) into (prefix, number).
     Returns ('', number) for plain numbers. Prefix kept for backward compat lookup."""
     import re
     ref = ref.strip().lstrip("#").upper()
     m = re.match(r"^([A-Z]{2,5})-(\d+)$", ref)
@@ -752,17 +760,17 @@ def api_create_task(project_id: str, title: str, price: int = 0,
             eff_scope = scope or None
             if eff_scope:
                 existing_by_scope = get_project_by_scope(conn, eff_scope)
                 if existing_by_scope and existing_by_scope["id"] != project_id:
                     eff_scope = None
             ensure_project(conn, project_id, scope=eff_scope)
             task = create_task(
                 conn, project_id, title,
-                price_rub=price * 1000,
+                price_rub=price,
                 description=description,
                 assignee=assignee,
                 status=status,
                 priority=priority,
             )
             conn.commit()
         except Exception:
             conn.rollback()
@@ -789,17 +797,17 @@ def api_update_task(par: str, title: str | None = None,
     with _conn() as conn:
         conn.execute("BEGIN IMMEDIATE")
         try:
             task = resolve_task_ref(conn, par, project)
             if not task:
                 raise ValueError(f"{par} not found")
             task_id = task["id"]
 
-            price_rub = price * 1000 if price is not None else None
+            price_rub = price if price is not None else None
             result = update_task(
                 conn, task_id,
                 title=title, description=description,
                 price_rub=price_rub, status=status,
                 assignee=assignee, priority=priority,
             )
 
             if status == "done":
@@ -893,17 +901,17 @@ def api_get_task(par: str, project: str = "") -> dict:
         "commits": commits,
         "yougile_id": task["yougile_task_id"],
         "sync_revision": task["sync_revision"],
     }
 
 
 def api_receive_payment(amount: int, client: str = "aleksandr-kislinskiy",
                         payment_date: str = "", note: str = "") -> dict:
-    amount_rub = amount * 1000
+    amount_rub = amount
     with _conn() as conn:
         conn.execute("BEGIN IMMEDIATE")
         try:
             result = receive_payment(conn, client, amount_rub, payment_date, note)
             conn.commit()
         except Exception:
             conn.rollback()
             raise