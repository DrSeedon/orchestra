# Candidate cand-22

## ORIGIN commit 1f5001124e (2026-06-29): #86: #86: real per-day cost analytics from turn logs
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/routes/system.py b/app/routes/system.py
index dd7ec1742..eb178d06e 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -557,16 +557,56 @@ async def _usage_snapshot_loop():
 @router.get("/api/usage/history")
 async def usage_history(hours: int = 24):
     if is_auth_enabled():
         return []
     from app.db import usage_get_history
     return usage_get_history(hours)
 
 
+@router.get("/api/usage/daily")
+async def usage_daily(days: int = 30):
+    """Daily cost breakdown from turn-end logs."""
+    from app.db import _conn
+    c = _conn()
+    rows = c.execute("""
+        SELECT date(l.ts) as day,
+          COUNT(*) as turns,
+          ROUND(SUM(CAST(SUBSTR(l.content, INSTR(l.content, '$') + 1,
+            INSTR(SUBSTR(l.content, INSTR(l.content, '$') + 1), ' ') - 1) AS REAL)), 4) as cost_usd
+        FROM logs l
+        WHERE l.type='status' AND l.content LIKE '%turn ended%'
+          AND date(l.ts) >= date('now', ?)
+        GROUP BY date(l.ts)
+        ORDER BY day
+    """, (f"-{days} days",)).fetchall()
+    c.close()
+    return [{"day": r[0], "turns": r[1], "cost_usd": r[2]} for r in rows]
+
+
+@router.get("/api/usage/daily/agents")
+async def usage_daily_agents(days: int = 7):
+    """Per-agent daily cost breakdown from turn-end logs."""
+    from app.db import _conn
+    c = _conn()
+    rows = c.execute("""
+        SELECT date(l.ts) as day, s.name, s.model,
+          COUNT(*) as turns,
+          ROUND(SUM(CAST(SUBSTR(l.content, INSTR(l.content, '$') + 1,
+            INSTR(SUBSTR(l.content, INSTR(l.content, '$') + 1), ' ') - 1) AS REAL)), 4) as cost_usd
+        FROM logs l JOIN sessions s ON l.session_id = s.id
+        WHERE l.type='status' AND l.content LIKE '%turn ended%'
+          AND date(l.ts) >= date('now', ?)
+        GROUP BY date(l.ts), s.name
+        ORDER BY day DESC, cost_usd DESC
+    """, (f"-{days} days",)).fetchall()
+    c.close()
+    return [{"day": r[0], "agent": r[1], "model": r[2], "turns": r[3], "cost_usd": r[4]} for r in rows]
+
+
 # ── Misc ──
 
 @router.post("/api/report_bug")
 async def report_bug_endpoint(req: Request):
     data = await req.json()
     title = data.get("title", "Untitled")
     description = data.get("description", "")
     reporter = data.get("reporter", "unknown")
diff --git a/app/static/js/app.js b/app/static/js/app.js
index 706f8980d..785e122e7 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -4427,164 +4427,119 @@ function _renderAnalyticsTabs() {
 }
 
 async function _loadAnalytics() {
     const body = document.getElementById('analytics-body');
     if (!body) return;
     body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
     try {
         const scope = currentScope;
-        const hoursMap = { today: 24, week: 168, month: 720, all: 8760 };
-        const [stats, sessions, usage, history] = await Promise.all([
+        const daysMap = { today: 1, week: 7, month: 30, all: 365 };
+        const days = daysMap[_analyticsPeriod];
+        const [stats, daily, agents, usage] = await Promise.all([
             api(`/api/stats${scope ? '?scope=' + encodeURIComponent(scope) : ''}`),
-            api(`/api/sessions${scope ? '?scope=' + encodeURIComponent(scope) : ''}`),
+            api(`/api/usage/daily?days=${days}`),
+            api(`/api/usage/daily/agents?days=${Math.min(days, 7)}`),
             api('/api/usage').catch(() => null),
-            api(`/api/usage/history?hours=${hoursMap[_analyticsPeriod]}`).catch(() => []),
         ]);
-        _renderAnalyticsBody(body, stats, sessions, usage, history);
+        _renderAnalyticsBody(body, stats, daily, agents, usage);
     } catch (e) {
         body.innerHTML = `<div class="text-center text-red-400 py-8">Failed to load: ${_escHtml(e.message)}</div>`;
     }
 }
 
-function _renderAnalyticsBody(body, stats, sessions, usage, history) {
-    const allSessions = Array.isArray(sessions) ? sessions : [];
-    const now = Date.now();
-    const periodMs = { today: 86400000, week: 7 * 86400000, month: 30 * 86400000, all: Infinity };
-    const cutoff = _analyticsPeriod === 'all' ? 0 : now - periodMs[_analyticsPeriod];
-
-    // Per-agent costs (all time from sessions)
-    const agentCosts = allSessions
-        .filter(s => s.status !== 'archived' || s.cost_usd > 0)
-        .map(s => ({ name: s.name, model: s.model || '?', cost: s.cost_usd || 0, status: s.status }))
-        .sort((a, b) => b.cost - a.cost);
-
-    // Period cost from history
-    const periodHistory = Array.isArray(history) ? history.filter(h => new Date(h.ts).getTime() >= cutoff) : [];
-
-    // Aggregate by day for chart
-    const dailyMap = {};
-    for (let i = 1; i < periodHistory.length; i++) {
-        const day = periodHistory[i].ts.slice(0, 10);
-        const costDiff = (periodHistory[i].cost_usd || 0) - (periodHistory[i - 1].cost_usd || 0);
-        if (costDiff > 0) dailyMap[day] = (dailyMap[day] || 0) + costDiff;
-        if (!dailyMap[day]) dailyMap[day] = dailyMap[day] || 0;
-    }
-    const dailyLabels = Object.keys(dailyMap).sort();
-    const dailyCosts = dailyLabels.map(d => Math.round(dailyMap[d] * 100) / 100);
-
-    // Utilization by day (average)
-    const utilMap = {};
-    const utilCount = {};
-    for (const h of periodHistory) {
-        const day = h.ts.slice(0, 10);
-        utilMap[day] = (utilMap[day] || 0) + (h.seven_day_pct || h.seven_day_util || 0);
-        utilCount[day] = (utilCount[day] || 0) + 1;
-    }
-    const dailyUtil = dailyLabels.map(d => utilMap[d] ? Math.round(utilMap[d] / utilCount[d]) : 0);
-
-    // Period total cost
-    const periodCost = dailyCosts.reduce((a, b) => a + b, 0);
+function _renderAnalyticsBody(body, stats, daily, agents, usage) {
+    const dailyData = Array.isArray(daily) ? daily : [];
+    const agentData = Array.isArray(agents) ? agents : [];
+    const today = new Date().toISOString().slice(0, 10);
+    const todayRow = dailyData.find(d => d.day === today);
+    const periodCost = dailyData.reduce((s, d) => s + (d.cost_usd || 0), 0);
+    const periodTurns = dailyData.reduce((s, d) => s + (d.turns || 0), 0);
 
     let html = '';
 
     // Overview cards
     html += '<div class="grid grid-cols-4 gap-3 mb-4">';
-    html += _analyticsCard('💰 Total', `$${(stats.total_cost_usd || 0).toFixed(0)}`, '#22c55e');
-    html += _analyticsCard('📅 Period', `$${periodCost.toFixed(0)}`, '#38bdf8');
-    html += _analyticsCard('🤖 Active', `${stats.active || 0}`, '#a78bfa');
-    html += _analyticsCard('📊 Sessions', `${stats.total_sessions || 0}`, '#f59e0b');
+    html += _analyticsCard('📅 Today', todayRow ? `$${todayRow.cost_usd.toFixed(0)}` : '$0', '#38bdf8', todayRow ? `${todayRow.turns} turns` : '');
+    html += _analyticsCard('📊 Period', `$${periodCost.toFixed(0)}`, '#a78bfa', `${periodTurns} turns`);
+    html += _analyticsCard('💰 All time', `$${(stats.total_cost_usd || 0).toFixed(0)}`, '#22c55e', `${stats.total_turns || 0} turns`);
+    html += _analyticsCard('🤖 Active', `${stats.active || 0}`, '#f59e0b', `${stats.total_sessions || 0} total`);
     html += '</div>';
 
     // Rate limits
     if (usage && usage.anthropic) {
         html += '<div class="grid grid-cols-2 gap-3 mb-4">';
         const a = usage.anthropic;
         if (a.five_hour) html += _analyticsRateBar('5h Window', a.five_hour, 5 * 3600000);
         if (a.seven_day) html += _analyticsRateBar('7d Window', a.seven_day, 7 * 86400000);
         html += '</div>';
     }
 
-    // Chart
-    html += '<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-4 mb-4"><canvas id="analytics-chart" height="200"></canvas></div>';
+    // Chart — real $/day from turn logs
+    html += '<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-4 mb-4" style="height:240px"><canvas id="analytics-chart"></canvas></div>';
+
+    // Top agents table
+    const todayAgents = agentData.filter(a => a.day === today).slice(0, 20);
+    const periodAgents = {};
+    for (const a of agentData) {
+        if (!periodAgents[a.agent]) periodAgents[a.agent] = { model: a.model, turns: 0, cost: 0 };
+        periodAgents[a.agent].turns += a.turns || 0;
+        periodAgents[a.agent].cost += a.cost_usd || 0;
+    }
+    const sortedAgents = Object.entries(periodAgents).sort((a, b) => b[1].cost - a[1].cost).slice(0, 30);
 
-    // Agent costs table
     html += '<div class="bg-slate-900/50 rounded-xl border border-slate-800 overflow-hidden">';
-    html += '<div class="px-3 py-2 border-b border-slate-800 text-xs font-bold text-slate-400">Cost by Agent</div>';
+    html += '<div class="px-3 py-2 border-b border-slate-800 text-xs font-bold text-slate-400">Top Agents (period)</div>';
     html += '<div class="max-h-[200px] overflow-y-auto">';
-    html += '<table class="w-full text-xs"><thead><tr class="text-slate-500 border-b border-slate-800/50"><th class="text-left px-3 py-1.5">Agent</th><th class="text-left px-3 py-1.5">Model</th><th class="text-left px-3 py-1.5">Status</th><th class="text-right px-3 py-1.5">Cost</th></tr></thead><tbody>';
-    for (const a of agentCosts.slice(0, 50)) {
-        const statusColor = a.status === 'running' ? '#22c55e' : a.status === 'idle' ? '#eab308' : '#64748b';
-        html += `<tr class="border-b border-slate-800/30 hover:bg-slate-800/30"><td class="px-3 py-1.5 font-medium text-slate-200">${_escHtml(a.name)}</td><td class="px-3 py-1.5 text-slate-500">${_escHtml(a.model)}</td><td class="px-3 py-1.5"><span style="color:${statusColor}">${a.status}</span></td><td class="px-3 py-1.5 text-right text-emerald-400">$${a.cost.toFixed(2)}</td></tr>`;
+    html += '<table class="w-full text-xs"><thead><tr class="text-slate-500 border-b border-slate-800/50"><th class="text-left px-3 py-1.5">Agent</th><th class="text-left px-3 py-1.5">Model</th><th class="text-right px-3 py-1.5">Turns</th><th class="text-right px-3 py-1.5">Cost</th></tr></thead><tbody>';
+    for (const [name, a] of sortedAgents) {
+        html += `<tr class="border-b border-slate-800/30 hover:bg-slate-800/30"><td class="px-3 py-1.5 font-medium text-slate-200">${_escHtml(name)}</td><td class="px-3 py-1.5 text-slate-500">${_escHtml(a.model || '?')}</td><td class="px-3 py-1.5 text-right text-slate-400">${a.turns}</td><td class="px-3 py-1.5 text-right text-emerald-400">$${a.cost.toFixed(2)}</td></tr>`;
     }
+    if (!sortedAgents.length) html += '<tr><td colspan="4" class="px-3 py-3 text-center text-slate-500 italic">No data</td></tr>';
     html += '</tbody></table></div></div>';
 
     body.innerHTML = html;
 
     // Render chart
-    if (dailyLabels.length > 0 && typeof Chart !== 'undefined') {
+    const labels = dailyData.map(d => d.day.slice(5));
+    const costs = dailyData.map(d => d.cost_usd || 0);
+    const turns = dailyData.map(d => d.turns || 0);
+    if (labels.length > 0 && typeof Chart !== 'undefined') {
         const ctx = document.getElementById('analytics-chart');
         if (ctx) {
             if (_analyticsChart) _analyticsChart.destroy();
             _analyticsChart = new Chart(ctx, {
                 type: 'bar',
                 data: {
-                    labels: dailyLabels.map(d => d.slice(5)),
+                    labels,
                     datasets: [
-                        {
-                            label: 'Cost ($)',
-                            data: dailyCosts,
-                            backgroundColor: 'rgba(99,102,241,0.6)',
-                            borderColor: '#6366f1',
-                            borderWidth: 1,
-                            yAxisID: 'y',
-                            order: 2,
-                        },
-                        {
-                            label: 'Utilization (%)',
-                            data: dailyUtil,
-                            type: 'line',
-                            borderColor: '#f97316',
-                            backgroundColor: 'rgba(249,115,22,0.1)',
-                            borderWidth: 2,
-                            pointRadius: 0,
-                            fill: true,
-                            tension: 0.3,
-                            yAxisID: 'y1',
-                            order: 1,
-                        },
+                        { label: 'Cost ($)', data: costs, backgroundColor: 'rgba(99,102,241,0.6)', borderColor: '#6366f1', borderWidth: 1, yAxisID: 'y', order: 2 },
+                        { label: 'Turns', data: turns, type: 'line', borderColor: '#22c55e', borderWidth: 2, pointRadius: 0, tension: 0.3, yAxisID: 'y1', order: 1 },
                     ],
                 },
                 options: {
-                    responsive: true,
-                    maintainAspectRatio: false,
+                    responsive: true, maintainAspectRatio: false,
                     interaction: { mode: 'index', intersect: false },
                     plugins: {
                         legend: { labels: { color: '#94a3b8', font: { size: 10 } } },
-                        tooltip: {
-                            backgroundColor: 'rgba(15,23,42,0.95)',
-                            borderColor: '#334155',
-                            borderWidth: 1,
-                            titleColor: '#e2e8f0',
-                            bodyColor: '#94a3b8',
-                        },
+                        tooltip: { backgroundColor: 'rgba(15,23,42,0.95)', borderColor: '#334155', borderWidth: 1, titleColor: '#e2e8f0', bodyColor: '#94a3b8' },
                     },
                     scales: {
                         x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(51,65,85,0.3)' } },
                         y: { position: 'left', title: { display: true, text: 'Cost ($)', color: '#94a3b8', font: { size: 10 } }, ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: 'rgba(51,65,85,0.3)' } },
-                        y1: { position: 'right', min: 0, max: 100, title: { display: true, text: 'Utilization %', color: '#f97316', font: { size: 10 } }, ticks: { color: '#f97316', font: { size: 9 } }, grid: { drawOnChartArea: false } },
+                        y1: { position: 'right', title: { display: true, text: 'Turns', color: '#22c55e', font: { size: 10 } }, ticks: { color: '#22c55e', font: { size: 9 } }, grid: { drawOnChartArea: false } },
                     },
                 },
             });
         }
     }
 }
 
-function _analyticsCard(label, value, color) {
-    return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3 text-center"><div class="text-[10px] text-slate-500 mb-1">${label}</div><div class="text-lg font-bold" style="color:${color}">${value}</div></div>`;
+function _analyticsCard(label, value, color, subtitle) {
+    return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3 text-center"><div class="text-[10px] text-slate-500 mb-1">${label}</div><div class="text-lg font-bold" style="color:${color}">${value}</div>${subtitle ? `<div class="text-[10px] text-slate-600 mt-0.5">${subtitle}</div>` : ''}</div>`;
 }
 
 function _analyticsRateBar(label, data, windowMs) {
     const pct = data.utilization || 0;
     const cd = _resetCountdown(data.resets_at);
     const rpNum = _resetPctNum(data.resets_at, windowMs);
     const pace = _paceIndicator(pct, data.resets_at, windowMs);
     const barColor = pct >= 80 ? '#ef4444' : pct >= 50 ? '#eab308' : '#22c55e';


## LATER FIX b7c1e79402 (19.0 days later): #usage: fix analytics agents/all-time period — request full range not capped 7d/365d
lines of origin it changed/deleted: 3
(code only, capped 400 lines)

#usage: fix analytics agents/all-time period — request full range not capped 7d/365d


diff --git a/app/routes/system.py b/app/routes/system.py
index 6bfbe7f69..de9a41727 100644
--- a/app/routes/system.py
+++ b/app/routes/system.py
@@ -641,17 +641,17 @@ async def usage_daily(days: int = 30):
         gap, cold = cache_by_day.get(day, (0, 0))
         hit_pct = round((gap - cold) / gap * 100) if gap else None
         out.append({"day": day, "turns": r[1], "cost_usd": r[2],
                     "cold_starts": cold, "cache_hit_pct": hit_pct})
     return out
 
 
 @router.get("/api/usage/daily/agents")
-async def usage_daily_agents(days: int = 7):
+async def usage_daily_agents(days: int = 30):
     """Per-agent daily cost breakdown from turn-end logs."""
     from app.db import _conn
     c = _conn()
     rows = c.execute("""
         SELECT date(l.ts) as day, s.name, s.model,
           COUNT(*) as turns,
           ROUND(SUM(CAST(SUBSTR(l.content, INSTR(l.content, '$') + 1,
             INSTR(SUBSTR(l.content, INSTR(l.content, '$') + 1), ' ') - 1) AS REAL)), 4) as cost_usd
diff --git a/app/static/js/app.js b/app/static/js/app.js
index e53d40af4..d5498f16f 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -4691,22 +4691,22 @@ function _renderAnalyticsTabs() {
 }
 
 async function _loadAnalytics() {
     const body = document.getElementById('analytics-body');
     if (!body) return;
     body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
     try {
         const scope = currentScope;
-        const daysMap = { today: 1, week: 7, month: 30, all: 365 };
+        const daysMap = { today: 1, week: 7, month: 30, all: 9999 };
         const days = daysMap[_analyticsPeriod];
         const [stats, daily, agents, usage] = await Promise.all([
             api(`/api/stats${scope ? '?scope=' + encodeURIComponent(scope) : ''}`),
             api(`/api/usage/daily?days=${days}`),
-            api(`/api/usage/daily/agents?days=${Math.min(days, 7)}`),
+            api(`/api/usage/daily/agents?days=${days}`),
             api('/api/usage').catch(() => null),
         ]);
         _renderAnalyticsBody(body, stats, daily, agents, usage);
     } catch (e) {
         body.innerHTML = `<div class="text-center text-red-400 py-8">Failed to load: ${_escHtml(e.message)}</div>`;
     }
 }
 