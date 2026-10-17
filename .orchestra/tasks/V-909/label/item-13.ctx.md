# Context for item-13

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index afbf4f31c..deacb73f2 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -1,25 +1,30 @@
 /* usage.js — usage bar rendering, sparklines, countdown. Loaded before app.js. */
 
 let _usageData = null;
 let _usageError = false;
 let _usageCountdownInterval = null;
+let _usageFetchPromise = null;
+let _usageLastSuccessAt = 0;
+let _usageLastFetchStartedAt = 0;
+const _USAGE_REFRESH_INTERVAL_MS = 120000;
+const _USAGE_CLICK_DEBOUNCE_MS = 1000;
 
 // Color encodes pace vs. ideal burn rate: green = under budget, red = over,
 // yellow = on track. When resetPct is known, diff drives color rather than raw %.
 function _usageColor(usagePct, resetPct) {
     if (resetPct == null) {
         if (usagePct >= 80) return '#ef4444';
         if (usagePct >= 50) return '#eab308';
         return '#22c55e';
     }
     const diff = usagePct - resetPct;
     if (diff < -10) return '#22c55e';
     if (diff > 10) return '#ef4444';
     // Smooth hue transition between yellow (60°) and red/green for near-ideal pace
     const hue = Math.max(0, Math.min(120, 60 - diff * 6));
     return `hsl(${hue}, 80%, 50%)`;
 }
 
 function _resetCountdown(isoStr) {
     if (!isoStr) return '';
     const ms = new Date(isoStr) - Date.now();
@@ -84,54 +89,69 @@ function _codexWindowLabel(windowMinutes) {
     return `${windowMinutes}m`;
 }
 
 function _usageProviderAccent(providerId) {
     const meta = _PROVIDER_META[providerId] || {};
     return meta.usageAccent || _PROVIDER_COLORS[meta.provider] || _PROVIDER_COLORS.unknown;
 }
 
 function _usageProviderWindows(providerId, capacity) {
     const meta = _PROVIDER_META[providerId];
     return meta.windows(capacity || {})
         .filter(([, window]) => window)
         .map(([label, window, defaultMinutes]) => ({
             label,
             window: defaultMinutes && !window.window_minutes
                 ? {...window, window_minutes:defaultMinutes}
                 : window,
         }));
 }
 
+function _usageFreshnessHtml() {
+    if (_usageFetchPromise) {
+        return '<span id="usage-freshness" style="color:#38bdf8">обновление…</span>';
+    }
+    if (!_usageLastSuccessAt) return '';
+    const ageMinutes = Math.floor((Date.now() - _usageLastSuccessAt) / 60000);
+    const age = ageMinutes < 1 ? 'сейчас' : `${ageMinutes} мин назад`;
+    if (_usageError) {
+        return `<span id="usage-freshness" style="color:#eab308">ошибка обновления · данные от ${age}</span>`;
+    }
+    const stale = Date.now() - _usageLastSuccessAt >= _USAGE_REFRESH_INTERVAL_MS;
+    return `<span id="usage-freshness" style="color:${stale ? '#eab308' : '#64748b'}">${stale ? 'устарело' : 'обновлено'} ${age}</span>`;
+}
+
 function renderUsageBar() {
     const bar = document.getElementById('usage-bar');
     if (!bar) return;
     if (!_usageData) {
         if (_usageError) {
             bar.style.cssText = 'display:flex;align-items:center;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#eab308;flex-shrink:0';
             bar.textContent = '⚠ Usage unavailable';
         } else {
             bar.innerHTML = '';
             bar.style.display = 'none';
         }
         return;
     }
-    bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap';
+    bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap;cursor:pointer';
+    bar.title = 'Нажмите, чтобы обновить usage';
 
     const a = _usageData.anthropic || {};
     const cx = _usageData.codex || {};
     const gx = _usageData.grok || null;
     const o = _usageData.orchestra || {};
     const parts = [];
 
     if (_usageError) parts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
 
     const fh = a.five_hour;
     if (fh) {
         const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
         const c = _usageColor(fh.utilization, rpNum);
         const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
         const cd = _resetCountdown(fh.resets_at);
         const pace = _paceIndicator(fh.utilization, fh.resets_at, 5 * 3600000);
         parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
     }
     const sd = a.seven_day;
     if (sd) {
@@ -162,40 +182,42 @@ function renderUsageBar() {
                 const windowMs = window.window_minutes * 60000;
                 const rpNum = _resetPctNum(window.resets_at, windowMs);
                 const c = _usageColor(window.utilization, rpNum);
                 const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
                 const cd = _resetCountdown(window.resets_at);
                 const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
                 const label = _codexWindowLabel(window.window_minutes);
                 parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">${label}: ${_miniBar(window.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
             }
         }
     }
 
     parts.push('<span style="flex:1"></span>');
 
     if (typeof o.total_cost_usd === 'number') {
         parts.push(`<span style="color:#22c55e">${MODEL_COST_CURRENCY}${o.total_cost_usd.toFixed(0)}</span>`);
     }
     if (typeof o.agents_count === 'number') {
         parts.push(`<span style="color:#64748b">${o.agents_count} agents</span>`);
     }
+    const freshness = _usageFreshnessHtml();
+    if (freshness) parts.push(freshness);
     parts.push('<span id="usage-info-btn" style="color:#475569;font-size:12px;cursor:help;transition:color 0.15s">ⓘ</span>');
 
     bar.innerHTML = parts.join('');
 
     const infoBtn = document.getElementById('usage-info-btn');
     if (infoBtn) {
         let tip = null, showTimer = null, hideTimer = null;
         const hideTip = () => {
             clearTimeout(showTimer);
             clearTimeout(hideTimer);
             if (tip) { tip.remove(); tip = null; }
         };
         const delayedHide = () => {
             hideTimer = setTimeout(() => {
                 if (tip && tip.matches(':hover')) return;
                 hideTip();
             }, 200);
         };
         infoBtn.addEventListener('mouseenter', () => {
             clearTimeout(hideTimer);
@@ -501,41 +523,65 @@ function _renderSparklines(slot, providerFilter = null) {
                 ? `<span data-spark-nav="newer" data-spark-key="${series.key}" style="cursor:pointer;color:#64748b">▶</span>`
                 : isAnchor ? '<span style="color:#1e293b">▶</span>' : '';
             html += `<div data-usage-series="${series.key}" style="margin-bottom:5px"><div style="font-size:10px;display:flex;align-items:center;gap:4px">${older}<span style="color:${color};font-weight:600">${series.windowLabel}</span><span style="color:#64748b">${current}% · ${periodLabel}</span>${newer}</div>`;
             html += `<div style="font-size:8px;color:#475569;margin-bottom:2px">━ usage &nbsp;┈ ideal pace</div>${mkSvg(points.pts, points.ideal, color, getGuides(period))}</div>`;
         });
         html += '</div>';
     }
     slot.innerHTML = html || '<div style="font-size:10px;color:#475569;font-style:italic">Collecting data...</div>';
     slot.querySelectorAll('[data-spark-nav]').forEach(button => {
         button.addEventListener('click', event => {
             event.stopPropagation();
             const key = button.dataset.sparkKey;
             const delta = button.dataset.sparkNav === 'older' ? 1 : -1;
             _sparkPeriodIdx[key] = Math.max(0, (_sparkPeriodIdx[key] || 0) + delta);
             _renderSparklines(slot, providerFilter);
         });
     });
 }
 
 async function fetchUsage() {
+    if (_usageFetchPromise) return _usageFetchPromise;
+    _usageLastFetchStartedAt = Date.now();
+    _usageFetchPromise = (async () => {
+        try {
+            _usageData = await api('/api/usage');
+            _usageError = false;
+            _usageLastSuccessAt = Date.now();
+        } catch (error) {
+            _usageError = true;
+            const detail = error instanceof Error
+                ? `${error.name}: ${error.message || '(no message)'}`
+                : String(error);
+            console.error(`Usage fetch failed: ${detail}`);
+        }
+    })();
+    renderUsageBar();
     try {
-        _usageData = await api('/api/usage');
-        _usageError = false;
-    } catch (error) {
-        _usageError = true;
-        const detail = error instanceof Error
-            ? `${error.name}: ${error.message || '(no message)'}`
-            : String(error);
-        console.error(`Usage fetch failed: ${detail}`);
+        await _usageFetchPromise;
+    } finally {
+        _usageFetchPromise = null;
+        renderUsageBar();
     }
-    renderUsageBar();
 }
 
 function initUsageBar() {
     fetchUsage();
+    const bar = document.getElementById('usage-bar');
+    if (bar) {
+        bar.addEventListener('click', () => {
+            if (_usageFetchPromise) return;
+            if (Date.now() - _usageLastFetchStartedAt < _USAGE_CLICK_DEBOUNCE_MS) return;
+            fetchUsage();
+        });
+    }
+    document.addEventListener('visibilitychange', () => {
+        if (document.visibilityState !== 'visible') return;
+        const lastRefresh = Math.max(_usageLastSuccessAt, _usageLastFetchStartedAt);
+        if (Date.now() - lastRefresh >= _USAGE_REFRESH_INTERVAL_MS) fetchUsage();
+    });
     // Full data refresh every 2 minutes; countdown rerender every minute (no API call)
-    setInterval(fetchUsage, 120000);
+    setInterval(fetchUsage, _USAGE_REFRESH_INTERVAL_MS);
     _usageCountdownInterval = setInterval(() => {
         if (_usageData) renderUsageBar();
     }, 60000);
 }
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 6c7e0cb1b..3d88349f5 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -40,40 +40,89 @@ def _page(browser: Browser, grok):
                     seven_day: {utilization: 31, resets_at: reset},
                 },
                 codex: {
                     primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                     spark: {
                         primary: {utilization: 7, window_minutes: 10080, resets_at: reset},
                     },
                 },
                 grok: grok ? {
                     primary: {utilization: 10, window_minutes: 10080, resets_at: reset},
                 } : null,
                 orchestra: {},
             };
             renderUsageBar();
         }""",
         grok,
     )
     return page
 
 
+def _interactive_page(browser: Browser):
+    page = browser.new_page(viewport={"width": 1440, "height": 900})
+    page.set_content('<body><div id="usage-bar"></div></body>')
+    page.evaluate(
+        """() => {
+            window.marked = {setOptions() {}, parse(value) { return value; }};
+            window.DOMPurify = {addHook() {}};
+            window.usageRequests = 0;
+            window.usagePending = [];
+            window.api = () => {
+                usageRequests += 1;
+                return new Promise((resolve, reject) => {
+                    usagePending.push({resolve, reject});
+                });
+            };
+        }"""
+    )
+    page.add_script_tag(path=str(UTILS_JS))
+    page.add_script_tag(path=str(USAGE_JS))
+    page.evaluate("() => initUsageBar()")
+    return page
+
+
+def _settle_usage(page, utilization, *, reject=False):
+    page.evaluate(
+        """([utilization, reject]) => {
+            const pending = usagePending.shift();
+            if (reject) {
+                pending.reject(new DOMException('signal timed out', 'TimeoutError'));
+                return;
+            }
+            const reset = new Date(Date.now() + 4 * 86400000).toISOString();
+            pending.resolve({
+                anthropic: {
+                    five_hour: {utilization, resets_at: reset},
+                    seven_day: {utilization: 31, resets_at: reset},
+                },
+                codex: {
+                    primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
+                },
+                grok: null,
+                orchestra: {},
+            });
+        }""",
+        [utilization, reject],
+    )
+    page.wait_for_function("() => _usageFetchPromise === null")
+
+
 def test_compact_bar_replaces_spark_with_grok(browser):
     page = _page(browser, True)
 
     expect(page.locator("#usage-bar")).to_contain_text("Grok")
     expect(page.locator("#usage-bar")).not_to_contain_text("Spark")
     expect(page.locator("#usage-bar")).to_contain_text("7d")
     page.close()
 
 
 def test_usage_control_keeps_spark_and_adds_grok_third_column(browser):
     page = _page(browser, True)
     page.locator("#usage-info-btn").hover()
 
     expect(page.locator("[data-usage-provider]")).to_have_count(3)
     expect(page.locator('[data-usage-provider="codex"]')).to_contain_text("Spark")
     expect(page.locator('[data-usage-provider="grok"]')).to_contain_text("Grok")
     expect(page.locator('[data-usage-provider="grok"]')).to_contain_text("Использовано")
     page.close()
 
 
@@ -99,40 +148,100 @@ def test_usage_fetch_failure_stays_visible_and_logs_exception(browser):
     page.evaluate(
         """() => {
             window.marked = {setOptions() {}, parse(value) { return value; }};
             window.DOMPurify = {addHook() {}};
             window.api = async () => {
                 throw new DOMException('signal timed out', 'TimeoutError');
             };
         }"""
     )
     page.add_script_tag(path=str(UTILS_JS))
     page.add_script_tag(path=str(USAGE_JS))
 
     page.evaluate("() => fetchUsage()")
 
     expect(page.locator("#usage-bar")).to_be_visible()
     expect(page.locator("#usage-bar")).to_contain_text("Usage unavailable")
     assert errors == ["Usage fetch failed: TimeoutError: signal timed out"]
     page.close()
 
 
+def test_usage_refreshes_on_click_and_stale_tab_return_without_request_storm(browser):
+    page = _interactive_page(browser)
+    errors = []
+    page.on(
+        "console",
+        lambda message: errors.append(message.text) if message.type == "error" else None,
+    )
+    _settle_usage(page, 88)
+
+    expect(page.locator("#usage-freshness")).to_have_text("обновлено сейчас")
+    expect(page.locator("#usage-freshness")).to_be_in_viewport()
+    expect(page.locator("#usage-bar")).to_contain_text("88%")
+
+    page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
+    page.locator("#usage-bar").click()
+    page.locator("#usage-bar").click()
+    page.locator("#usage-bar").click()
+    assert page.evaluate("() => usageRequests") == 2
+    expect(page.locator("#usage-freshness")).to_have_text("обновление…")
+    _settle_usage(page, 2)
+
+    expect(page.locator("#usage-bar")).to_contain_text("2%")
+    expect(page.locator("#usage-freshness")).to_have_text("обновлено сейчас")
+
+    page.evaluate(
+        """() => {
+            window.testVisibility = 'hidden';
+            Object.defineProperty(document, 'visibilityState', {
+                configurable: true,
+                get: () => window.testVisibility,
+            });
+            _usageLastSuccessAt = Date.now() - _USAGE_REFRESH_INTERVAL_MS - 1;
+            _usageLastFetchStartedAt = 0;
+            renderUsageBar();
+            document.dispatchEvent(new Event('visibilitychange'));
+        }"""
+    )
+    assert page.evaluate("() => usageRequests") == 2
+    expect(page.locator("#usage-freshness")).to_contain_text("устарело 2 мин назад")
+
+    page.evaluate(
+        """() => {
+            window.testVisibility = 'visible';
+            document.dispatchEvent(new Event('visibilitychange'));
+            document.dispatchEvent(new Event('visibilitychange'));
+        }"""
+    )
+    assert page.evaluate("() => usageRequests") == 3
+    _settle_usage(page, 3)
+    expect(page.locator("#usage-bar")).to_contain_text("3%")
+
+    page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
+    page.locator("#usage-bar").click()
+    _settle_usage(page, 0, reject=True)
+    expect(page.locator("#usage-bar")).to_contain_text("3%")
+    expect(page.locator("#usage-freshness")).to_contain_text("ошибка обновления")
+    assert errors == ["Usage fetch failed: TimeoutError: signal timed out"]
+    page.close()
+
+
 def test_history_period_requires_two_points(browser):
     page = _page(browser, True)
 
     result = page.evaluate(
         """() => {
             const point = {
                 ts: new Date().toISOString(),
                 utilization: 10,
                 window_minutes: 10080,
                 resets_at: new Date(Date.now() + 4 * 86400000).toISOString(),
             };
             const periods = _usagePeriods({points: [point]});
             _sparkData = [{
                 ts: point.ts,
                 providers: {
                     grok: {
                         label: 'Grok',
                         windows: [{id: 'primary', label: '7d', ...point}],
                     },
                 },


## Later history of the touched files on main (after this commit)

34 later commits touch these paths; the first 40 (oldest first):
5e079a6c7 2026-08-03 #10: #10: usage-панель перестала врать ценой и молчать заглушкой
ede489b39 2026-08-03 #13: #13: разрешение истории usage по диапазону + разрывы вместо выдуманных линий
b41f617ce 2026-08-03 #13, #9, #19: #13: CHANGELOG v2.31.0 и Known tradeoff отдельной секцией в отчёте
d6a700f0b 2026-08-03 #22: #22: usage.js больше не перекрывается app.js — панель истории была мертва в проде
14d3f9d04 2026-08-04 #58: #58 (1/3): api() ставит таймаут ВСЕГДА — вечный лоадинг вылечен
e25ca71e4 2026-08-07 #150: #150: null в five_hour_pct/seven_day_pct — дыра в графике, а не ноль
bff96d941 2026-08-07 #162: #162: research — курс 5h→7d измерен, в недельный лимит влезает ~7 пятичасовых окон
ba10d0dcb 2026-08-13 #163: #163: keep usage controls visible on narrow desktops
98add51ec 2026-08-19 #344, #343: #344: линии допуска по квоте на дашборде, снос прежних квотных панелей
a44feb4bb 2026-08-19 #356: #356: route usage bars to quota release status
e5d28b83a 2026-08-19 #356: fix undefined _c in usage bar — верхняя строка расхода пропадала целиком
a73e8ed66 2026-08-19 #356: usage-bar — 5h без статуса разблокировки, Spark со своей подписью
7da073458 2026-08-19 #356: split quota usage usage bar into provider rows
7484fe0bc 2026-08-19 #356: layout usage bar in two provider columns
24d6308d4 2026-08-20 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера
c74d0d75b 2026-08-22 #368: #368: Phase 1 — исследование источников счётчика запросов OpenRouter (гибрид: локальный счёт + /activity)
c6022d4ad 2026-08-23 fix: open usage details without refreshing the bar
aa33578e2 2026-08-23 #234: #234: add red acceptance tests
3318068b0 2026-08-28 Unify restart and connection status across dashboard
772e3a748 2026-08-28 Extract dashboard connection state from app monolith
e65a8d21d 2026-08-29 Give subscription usage refresh its real timeout budget
ba51a7d01 2026-09-01 прогресс окна в usage-баре с точностью до сотых
e2f792040 2026-09-03 #447: show worker quota headroom in usage bar
f8e00522e 2026-09-03 #430: research .orchestra path migration
0f415e840 2026-09-03 #452: compact quota headroom labels
2268e0fed 2026-09-04 usage: у недельных окон показывать момент сброса по Красноярску
b112d9b32 2026-09-17 #V-584: подписи окон Codex по длительности, как у Claude
0fc5abfe9 2026-09-17 V-584: #V-584: русский интерфейс дашборда и переключатель RU/EN
d72bf45ca 2026-09-17 V-589: #V-589: quota-lines.js и usage.js на английском, русский перевод в словарь
bcd844068 2026-10-04 V-693: #V-693: record CI triage and confirmed CSS defect
8dd91d5e1 2026-10-05 V-700: #V-700: fix dashboard CI and i18n issues
5819f6d96 2026-10-07 V-747: #V-747: format usage and quota percentages
aa7a76100 2026-10-14 V-847: #V-847: parallelize full pytest and isolate fixtures
edfac4356 2026-10-15 V-876: WIP #V-876: design tokens, theme.js, model/status badges from one source

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 5e079a6c7 #10: #10: usage-панель перестала врать ценой и молчать заглушкой

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index deacb73f2..d7bc2a946 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -288,11 +288,16 @@ function renderUsageBar() {
                     h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
                     h += _row('💰 Стоимость', `${MODEL_COST_CURRENCY}${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                     if (typeof _usageData.voice_cost_usd === 'number') {
                         h += `<div style="font-size:10px">${_row('🎤 Voice', `${MODEL_COST_CURRENCY}${_usageData.voice_cost_usd.toFixed(2)}`, '#94a3b8')}</div>`;
                     }
-                    h += _row('Подписка', `${MODEL_COST_CURRENCY}100+${MODEL_COST_CURRENCY}100/мес`, '#64748b');
+                    // Цена подписки приходит из SUBSCRIPTION_COST (.env). Не задана — строки
+                    // нет: захардкоженная константа уже провисела неверной, а рядом стоят
+                    // посчитанные числа, и выдуманное среди них неотличимо от настоящего.
+                    if (_usageData.subscription_cost) {
+                        h += _row('Подписка', escHtml(_usageData.subscription_cost), '#64748b');
+                    }
                     h += '</div>';
                 }
                 if (typeof _o.agents_count === 'number') {
                     h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 Агенты: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
                 }
@@ -310,25 +315,40 @@ function renderUsageBar() {
         });
         infoBtn.addEventListener('mouseleave', () => { infoBtn.style.color = '#475569'; delayedHide(); });
     }
 }
 
-let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {};
+let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {}, _sparkError = '';
 // Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
 async function _loadSparkline(tipEl) {
     const slots = [...tipEl.querySelectorAll('[data-usage-history]')];
     if (!slots.length) return;
     const now = Date.now();
     if (!_sparkData || now - _sparkDataTs >= 300000) {
         try {
-            _sparkData = await api('/api/usage/history?hours=8760');
+            // Год снимков — это мегабайты (замер 03.08: 8403 строки, 4.29 МБ), а общий
+            // таймаут api() = 5 с выбран для обычных мелких ответов. На этом запросе
+            // он срабатывал раньше ответа, и падение пряталось за пустым catch.
+            _sparkData = await api('/api/usage/history?hours=8760',
+                                   { signal: AbortSignal.timeout(30000) });
             _sparkDataTs = now;
-        } catch { _sparkData = null; }
+            _sparkError = '';
+        } catch (e) {
+            _sparkData = null;
+            _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
+            console.error(`usage history fetch failed: ${_sparkError}`);
+        }
     }
     if (!Array.isArray(_sparkData) || _sparkData.length < 1) {
+        // Раньше здесь во всех случаях висело «Collecting data...» — и когда сбор
+        // действительно не начался, и когда запрос упал. Это разные вещи.
+        const why = _sparkError
+            ? `История не загрузилась — ${_sparkError}`
+            : 'Снимков ещё нет: график появится после двух замеров в одном окне';
         slots.forEach(slot => {
-            slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic">Collecting data...</div>';
+            slot.innerHTML = `<div style="font-size:10px;color:${_sparkError ? '#eab308' : '#475569'};font-style:italic"></div>`;
+            slot.firstChild.textContent = why;
         });
         return;
     }
     _sparkPeriodIdx = {};
     slots.forEach(slot => {
@@ -525,11 +545,26 @@ function _renderSparklines(slot, providerFilter = null) {
             html += `<div data-usage-series="${series.key}" style="margin-bottom:5px"><div style="font-size:10px;display:flex;align-items:center;gap:4px">${older}<span style="color:${color};font-weight:600">${series.windowLabel}</span><span style="color:#64748b">${current}% · ${periodLabel}</span>${newer}</div>`;
             html += `<div style="font-size:8px;color:#475569;margin-bottom:2px">━ usage &nbsp;┈ ideal pace</div>${mkSvg(points.pts, points.ideal, color, getGuides(period))}</div>`;
         });
         html += '</div>';
     }
-    slot.innerHTML = html || '<div style="font-size:10px;color:#475569;font-style:italic">Collecting data...</div>';
+    if (!html) {
+        // Строки есть, но по ЭТОМУ провайдеру графика не выходит. Раньше тут стояло
+        // то же «Collecting data...», что и при полном отсутствии данных, — из-за чего
+        // «данных нет вообще» и «нет данных по Codex» выглядели одинаково.
+        const hasPoints = [...grouped.keys()].some(id => !providerFilter || providerFilter.has(id));
+        const firstTs = data[0]?.ts ? new Date(data[0].ts) : null;
+        const since = firstTs && !isNaN(firstTs)
+            ? ` Снимки ведутся с ${firstTs.toLocaleDateString()}.`
+            : '';
+        slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic"></div>';
+        slot.firstChild.textContent = hasPoints
+            ? `Мало точек: на график нужно ≥2 замера в одном окне.${since}`
+            : `Этого провайдера в истории нет.${since}`;
+        return;
+    }
+    slot.innerHTML = html;
     slot.querySelectorAll('[data-spark-nav]').forEach(button => {
         button.addEventListener('click', event => {
             event.stopPropagation();
             const key = button.dataset.sparkKey;
             const delta = button.dataset.sparkNav === 'older' ? 1 : -1;
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 3d88349f5..dfa295837 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -257,7 +257,9 @@ def test_history_period_requires_two_points(browser):
         }"""
     )
 
     assert result["periods"] == []
     assert result["svgCount"] == 0
-    assert "Collecting data" in result["text"]
+    # Заглушка теперь называет ПРИЧИНУ вместо «Collecting data...»: одной точки мало,
+    # а сбор при этом идёт — раньше этот случай был неотличим от «данных нет вообще».
+    assert "Мало точек" in result["text"]
     page.close()
### ede489b39 #13: #13: разрешение истории usage по диапазону + разрывы вместо выдуманных линий

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index d7bc2a946..2e96843f8 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -315,23 +315,29 @@ function renderUsageBar() {
         });
         infoBtn.addEventListener('mouseleave', () => { infoBtn.style.color = '#475569'; delayedHide(); });
     }
 }
 
-let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {}, _sparkError = '';
+let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {}, _sparkError = '', _sparkStepMin = 5;
 // Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
 async function _loadSparkline(tipEl) {
     const slots = [...tipEl.querySelectorAll('[data-usage-history]')];
     if (!slots.length) return;
     const now = Date.now();
     if (!_sparkData || now - _sparkDataTs >= 300000) {
         try {
-            // Год снимков — это мегабайты (замер 03.08: 8403 строки, 4.29 МБ), а общий
-            // таймаут api() = 5 с выбран для обычных мелких ответов. На этом запросе
-            // он срабатывал раньше ответа, и падение пряталось за пустым catch.
-            _sparkData = await api('/api/usage/history?hours=8760',
-                                   { signal: AbortSignal.timeout(30000) });
+            // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался
+            // раньше этого запроса (год в 5-минутной сетке — 4.36 МБ), а падение
+            // пряталось за пустым catch. Сейчас сервер сам выбирает разрешение и
+            // возвращает шаг сетки вместе с данными, но запас по таймауту оставлен.
+            const history = await api('/api/usage/history?hours=8760',
+                                      { signal: AbortSignal.timeout(30000) });
+            if (!Array.isArray(history?.rows)) {
+                throw new Error(`ответ без rows: ${JSON.stringify(history).slice(0, 80)}`);
+            }
+            _sparkData = history.rows;
+            _sparkStepMin = Number(history.step_minutes) || 5;
             _sparkDataTs = now;
             _sparkError = '';
         } catch (e) {
             _sparkData = null;
             _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
@@ -445,27 +451,38 @@ function _renderSparklines(slot, providerFilter = null) {
     const mkSvg = (pts, idealPts, color, guides) => {
         const allV = [...pts.map(p=>p.v), ...idealPts.map(p=>p.v)];
         let yMin = Math.floor(Math.min(...allV)), yMax = Math.ceil(Math.max(...allV));
         if (yMax - yMin < 5) { yMin = Math.max(0, yMin - 3); yMax = yMin + 6; }
         const yRange = yMax - yMin || 1;
-        const toStr = (arr) => arr.map(p => {
-            const x = PL + p.t * gw;
-            const y = gh - ((Math.min(p.v, 100) - yMin) / yRange) * gh;
-            return `${x.toFixed(1)},${y.toFixed(1)}`;
-        }).join(' ');
+        const yOf = (p) => gh - ((Math.min(p.v, 100) - yMin) / yRange) * gh;
+        const toStr = (arr) => arr.map(p => `${(PL + p.t * gw).toFixed(1)},${yOf(p).toFixed(1)}`).join(' ');
+        // Точка с gap открывает новый отрезок: между ней и предыдущей снимков не
+        // было, и одна полилиния через дырку нарисовала бы выдуманные данные.
+        const segments = (arr) => {
+            const out = [];
+            for (const p of arr) {
+                if (p.gap || !out.length) out.push([]);
+                out[out.length - 1].push(p);
+            }
+            return out;
+        };
         const totalH = H + 12;
         let s = `<svg width="${W}" height="${totalH}" viewBox="0 0 ${W} ${totalH}" style="display:block">`;
         s += `<text x="${PL - 3}" y="8" text-anchor="end" fill="#64748b" font-size="9">${yMax}%</text>`;
         s += `<text x="${PL - 3}" y="${gh - 1}" text-anchor="end" fill="#64748b" font-size="9">${yMin}%</text>`;
         for (const guide of guides) {
             const mx = PL + guide.t * gw;
             s += `<line x1="${mx}" y1="0" x2="${mx}" y2="${gh}" stroke="rgba(100,116,139,0.3)" stroke-width="0.5"/>`;
             s += `<text x="${mx}" y="${H + 11}" text-anchor="middle" fill="#64748b" font-size="8">${guide.label}</text>`;
         }
-        if (idealPts.length >= 2) s += `<polyline points="${toStr(idealPts)}" fill="none" stroke="#475569" stroke-width="1" stroke-dasharray="4 3" stroke-linejoin="round" opacity="0.6"/>`;
-        if (pts.length >= 2) s += `<polyline points="${toStr(pts)}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
-        else if (pts.length === 1) { const px = PL + pts[0].t * gw, py = gh - ((Math.min(pts[0].v, 100) - yMin) / yRange) * gh; s += `<circle cx="${px}" cy="${py}" r="3" fill="${color}"/>`; }
+        for (const seg of segments(idealPts)) {
+            if (seg.length >= 2) s += `<polyline points="${toStr(seg)}" fill="none" stroke="#475569" stroke-width="1" stroke-dasharray="4 3" stroke-linejoin="round" opacity="0.6"/>`;
+        }
+        for (const seg of segments(pts)) {
+            if (seg.length >= 2) s += `<polyline points="${toStr(seg)}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
+            else s += `<circle cx="${(PL + seg[0].t * gw).toFixed(1)}" cy="${yOf(seg[0]).toFixed(1)}" r="${pts.length === 1 ? 3 : 1.5}" fill="${color}"/>`;
+        }
         s += '</svg>';
         return s;
     };
 
     const getGuides = (slice) => {
@@ -482,22 +499,30 @@ function _renderSparklines(slot, providerFilter = null) {
             guides.push({t:(at - t0) / range, label});
         }
         return guides;
     };
 
+    // Сервер отдаёт сетку с известным шагом и не выдаёт точку там, где снимков
+    // не было. Значит соседи дальше шага = провал в данных, а не редкая выборка.
+    const gapMs = _sparkStepMin * 1.5 * 60000;
+
     const mkPts = (slice) => {
         if (!slice.length) return { pts: [], ideal: [] };
         const t0 = new Date(slice[0].ts).getTime(), tN = new Date(slice[slice.length-1].ts).getTime();
         const range = tN - t0 || 1;
         const pts = [], ideal = [];
+        let prevMs = null;
         for (const point of slice) {
-            const t = (new Date(point.ts).getTime() - t0) / range;
-            pts.push({t, v:point.utilization});
-            if (!point.resets_at) { ideal.push({t, v:0}); continue; }
+            const ms = new Date(point.ts).getTime();
+            const t = (ms - t0) / range;
+            const gap = prevMs !== null && ms - prevMs > gapMs;
+            prevMs = ms;
+            pts.push({t, v:point.utilization, gap});
+            if (!point.resets_at) { ideal.push({t, v:0, gap}); continue; }
             const windowMs = point.window_minutes * 60000;
             const remain = new Date(point.resets_at) - new Date(point.ts);
-            ideal.push({t, v:Math.max(0, Math.min(100, (windowMs - remain) / windowMs * 100))});
+            ideal.push({t, v:Math.max(0, Math.min(100, (windowMs - remain) / windowMs * 100)), gap});
         }
         return { pts, ideal };
     };
 
     const grouped = new Map();
### b41f617ce #13, #9, #19: #13: CHANGELOG v2.31.0 и Known tradeoff отдельной секцией в отчёте

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 2e96843f8..695c3f217 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -316,28 +316,53 @@ function renderUsageBar() {
         infoBtn.addEventListener('mouseleave', () => { infoBtn.style.color = '#475569'; delayedHide(); });
     }
 }
 
 let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {}, _sparkError = '', _sparkStepMin = 5;
+let _sparkOldestTs = '';
+// Грузим ровно то, что рисуем: график показывает один период якорного окна, а самое
+// длинное окно у провайдеров — 7 суток. История растёт вечно, и тянуть её целиком
+// значит вернуться к тому же таймауту через пару лет. Остальное приезжает по клику ◀.
+const _SPARK_VIEW_HOURS = 168;
+
+function _sparkMessage(slot, text, isError) {
+    slot.innerHTML = `<div style="font-size:10px;color:${isError ? '#eab308' : '#475569'};font-style:italic"></div>`;
+    slot.firstChild.textContent = text;
+}
+
+async function _fetchHistory(until) {
+    // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался раньше этого
+    // запроса (год в 5-минутной сетке — 4.36 МБ), а падение пряталось за пустым catch.
+    const query = until
+        ? `hours=${_SPARK_VIEW_HOURS}&until=${encodeURIComponent(until)}`
+        : `hours=${_SPARK_VIEW_HOURS}`;
+    const history = await api(`/api/usage/history?${query}`,
+                              { signal: AbortSignal.timeout(30000) });
+    if (!Array.isArray(history?.rows)) {
+        throw new Error(`ответ без rows: ${JSON.stringify(history).slice(0, 80)}`);
+    }
+    _sparkStepMin = Number(history.step_minutes) || 5;
+    _sparkOldestTs = history.oldest_ts || '';
+    return history.rows;
+}
+
+// Есть ли на сервере снимки старше самого старого загруженного.
+function _sparkHasOlder() {
+    if (!_sparkOldestTs || !_sparkData?.length) return false;
+    // Через Date, а не сравнением строк: смешать «+00:00» и «Z» достаточно, чтобы
+    // лексикографический порядок соврал, а стрелка исчезла или зациклилась.
+    return new Date(_sparkData[0].ts) > new Date(_sparkOldestTs);
+}
+
 // Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
 async function _loadSparkline(tipEl) {
     const slots = [...tipEl.querySelectorAll('[data-usage-history]')];
     if (!slots.length) return;
     const now = Date.now();
     if (!_sparkData || now - _sparkDataTs >= 300000) {
         try {
-            // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался
-            // раньше этого запроса (год в 5-минутной сетке — 4.36 МБ), а падение
-            // пряталось за пустым catch. Сейчас сервер сам выбирает разрешение и
-            // возвращает шаг сетки вместе с данными, но запас по таймауту оставлен.
-            const history = await api('/api/usage/history?hours=8760',
-                                      { signal: AbortSignal.timeout(30000) });
-            if (!Array.isArray(history?.rows)) {
-                throw new Error(`ответ без rows: ${JSON.stringify(history).slice(0, 80)}`);
-            }
-            _sparkData = history.rows;
-            _sparkStepMin = Number(history.step_minutes) || 5;
+            _sparkData = await _fetchHistory('');
             _sparkDataTs = now;
             _sparkError = '';
         } catch (e) {
             _sparkData = null;
             _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
@@ -348,14 +373,11 @@ async function _loadSparkline(tipEl) {
         // Раньше здесь во всех случаях висело «Collecting data...» — и когда сбор
         // действительно не начался, и когда запрос упал. Это разные вещи.
         const why = _sparkError
             ? `История не загрузилась — ${_sparkError}`
             : 'Снимков ещё нет: график появится после двух замеров в одном окне';
-        slots.forEach(slot => {
-            slot.innerHTML = `<div style="font-size:10px;color:${_sparkError ? '#eab308' : '#475569'};font-style:italic"></div>`;
-            slot.firstChild.textContent = why;
-        });
+        slots.forEach(slot => _sparkMessage(slot, why, Boolean(_sparkError)));
         return;
     }
     _sparkPeriodIdx = {};
     slots.forEach(slot => {
         const providerFilter = new Set(slot.dataset.usageHistory.split(','));
@@ -528,10 +550,17 @@ function _renderSparklines(slot, providerFilter = null) {
     const grouped = new Map();
     for (const series of _usageHistorySeries(data)) {
         if (!grouped.has(series.providerId)) grouped.set(series.providerId, []);
         grouped.get(series.providerId).push(series);
     }
+    // Порядок серий задаёт цвет из палитры. Без сортировки он зависел от того, какое
+    // окно попалось в первой строке данных: подгрузили старый кусок, где 5h ещё не
+    // было, — и 5h с 7d менялись местами и цветами прямо под курсором.
+    for (const providerSeries of grouped.values()) {
+        providerSeries.sort((a, b) =>
+            (a.points[0]?.window_minutes || 0) - (b.points[0]?.window_minutes || 0));
+    }
     let html = '';
     for (const [providerId, providerSeries] of grouped) {
         if (providerFilter && !providerFilter.has(providerId)) continue;
         const palette = providerColors[providerId] || ['#c084fc', '#f0abfc'];
         // The longest window owns period navigation. Shorter windows use the
@@ -542,11 +571,13 @@ function _renderSparklines(slot, providerFilter = null) {
         const periods = _usagePeriods(anchorSeries);
         if (!periods.length) continue;
         const periodIdx = Math.max(0, Math.min(_sparkPeriodIdx[anchorSeries.key] || 0, periods.length - 1));
         _sparkPeriodIdx[anchorSeries.key] = periodIdx;
         const anchorPeriod = periods[periods.length - 1 - periodIdx];
-        const hasOlder = periodIdx < periods.length - 1;
+        // Стрелка живёт, даже когда загруженные периоды кончились: следующий приедет
+        // по клику. Иначе ленивая загрузка выглядела бы как потеря истории.
+        const hasOlder = periodIdx < periods.length - 1 || _sparkHasOlder();
         const hasNewer = periodIdx > 0;
         const anchorMinutes = anchorSeries.points[0]?.window_minutes || 0;
         const periodLabel = periodIdx === 0
             ? 'current'
             : anchorMinutes >= 10080
@@ -560,11 +591,11 @@ function _renderSparklines(slot, providerFilter = null) {
             const isAnchor = series.key === anchorSeries.key;
             const color = palette[index % palette.length];
             const current = period[period.length - 1].utilization;
             const points = mkPts(period);
             const older = isAnchor && hasOlder
-                ? `<span data-spark-nav="older" data-spark-key="${series.key}" style="cursor:pointer;color:#64748b">◀</span>`
+                ? `<span data-spark-nav="older" data-spark-key="${series.key}" data-spark-periods="${periods.length}" style="cursor:pointer;color:#64748b">◀</span>`
                 : isAnchor ? '<span style="color:#1e293b">◀</span>' : '';
             const newer = isAnchor && hasNewer
                 ? `<span data-spark-nav="newer" data-spark-key="${series.key}" style="cursor:pointer;color:#64748b">▶</span>`
                 : isAnchor ? '<span style="color:#1e293b">▶</span>' : '';
             html += `<div data-usage-series="${series.key}" style="margin-bottom:5px"><div style="font-size:10px;display:flex;align-items:center;gap:4px">${older}<span style="color:${color};font-weight:600">${series.windowLabel}</span><span style="color:#64748b">${current}% · ${periodLabel}</span>${newer}</div>`;
@@ -575,11 +606,14 @@ function _renderSparklines(slot, providerFilter = null) {
     if (!html) {
         // Строки есть, но по ЭТОМУ провайдеру графика не выходит. Раньше тут стояло
         // то же «Collecting data...», что и при полном отсутствии данных, — из-за чего
         // «данных нет вообще» и «нет данных по Codex» выглядели одинаково.
         const hasPoints = [...grouped.keys()].some(id => !providerFilter || providerFilter.has(id));
-        const firstTs = data[0]?.ts ? new Date(data[0].ts) : null;
+        // Именно первый снимок ВООБЩЕ, а не первый загруженный: с ленивой подгрузкой
+        // data[0] — это граница текущего куска, и «снимки ведутся с» врало бы.
+        const since0 = _sparkOldestTs || data[0]?.ts;
+        const firstTs = since0 ? new Date(since0) : null;
         const since = firstTs && !isNaN(firstTs)
             ? ` Снимки ведутся с ${firstTs.toLocaleDateString()}.`
             : '';
         slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic"></div>';
         slot.firstChild.textContent = hasPoints
@@ -587,15 +621,28 @@ function _renderSparklines(slot, providerFilter = null) {
### d6a700f0b #22: #22: usage.js больше не перекрывается app.js — панель истории была мертва в проде

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 695c3f217..b3b61df26 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -327,11 +327,13 @@ const _SPARK_VIEW_HOURS = 168;
 function _sparkMessage(slot, text, isError) {
     slot.innerHTML = `<div style="font-size:10px;color:${isError ? '#eab308' : '#475569'};font-style:italic"></div>`;
     slot.firstChild.textContent = text;
 }
 
-async function _fetchHistory(until) {
+// Имя с префиксом _spark: app.js уже держит глобальный _fetchHistory(name, scope)
+// и грузится ПОСЛЕ usage.js, поэтому его объявление перекрывало это.
+async function _sparkFetch(until) {
     // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался раньше этого
     // запроса (год в 5-минутной сетке — 4.36 МБ), а падение пряталось за пустым catch.
     const query = until
         ? `hours=${_SPARK_VIEW_HOURS}&until=${encodeURIComponent(until)}`
         : `hours=${_SPARK_VIEW_HOURS}`;
@@ -358,11 +360,11 @@ async function _loadSparkline(tipEl) {
     const slots = [...tipEl.querySelectorAll('[data-usage-history]')];
     if (!slots.length) return;
     const now = Date.now();
     if (!_sparkData || now - _sparkDataTs >= 300000) {
         try {
-            _sparkData = await _fetchHistory('');
+            _sparkData = await _sparkFetch('');
             _sparkDataTs = now;
             _sparkError = '';
         } catch (e) {
             _sparkData = null;
             _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
@@ -631,11 +633,11 @@ function _renderSparklines(slot, providerFilter = null) {
             _sparkPeriodIdx[key] = idx;
             const loaded = Number(button.dataset.sparkPeriods) || 1;
             if (delta > 0 && idx >= loaded - 1 && _sparkHasOlder()) {
                 _sparkMessage(slot, 'Загружаю предыдущий период…', false);
                 try {
-                    _sparkData = (await _fetchHistory(_sparkData[0].ts)).concat(_sparkData);
+                    _sparkData = (await _sparkFetch(_sparkData[0].ts)).concat(_sparkData);
                 } catch (e) {
                     _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
                     console.error(`usage history chunk failed: ${_sparkError}`);
                     _sparkMessage(slot, `Предыдущий период не загрузился — ${_sparkError}`, true);
                     return;
### 14d3f9d04 #58: #58 (1/3): api() ставит таймаут ВСЕГДА — вечный лоадинг вылечен

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index b3b61df26..17c2c83e4 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -335,12 +335,11 @@ async function _sparkFetch(until) {
     // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался раньше этого
     // запроса (год в 5-минутной сетке — 4.36 МБ), а падение пряталось за пустым catch.
     const query = until
         ? `hours=${_SPARK_VIEW_HOURS}&until=${encodeURIComponent(until)}`
         : `hours=${_SPARK_VIEW_HOURS}`;
-    const history = await api(`/api/usage/history?${query}`,
-                              { signal: AbortSignal.timeout(30000) });
+    const history = await api(`/api/usage/history?${query}`, { timeoutMs: 30000 });
     if (!Array.isArray(history?.rows)) {
         throw new Error(`ответ без rows: ${JSON.stringify(history).slice(0, 80)}`);
     }
     _sparkStepMin = Number(history.step_minutes) || 5;
     _sparkOldestTs = history.oldest_ts || '';
### e25ca71e4 #150: #150: null в five_hour_pct/seven_day_pct — дыра в графике, а не ноль

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 17c2c83e4..f46c8470b 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -387,16 +387,22 @@ async function _loadSparkline(tipEl) {
 }
 
 function _historyProviders(row) {
     if (row?.providers && typeof row.providers === 'object') return row.providers;
     const windows = [];
-    if (row?.five_hour_resets_at || Number(row?.five_hour_pct)) {
-        windows.push({id:'five_hour', label:'5h', utilization:Number(row.five_hour_pct) || 0,
+    // null в колонке = источник не ответил (#150). `Number(null)` даёт 0, и окно
+    // с нулём нарисовало бы провал в пол там, где данных нет вовсе
+    const pct = value => (value == null || value === '' || !Number.isFinite(Number(value)))
+        ? null : Number(value);
+    const fiveHour = pct(row?.five_hour_pct);
+    const sevenDay = pct(row?.seven_day_pct);
+    if (fiveHour !== null && (row.five_hour_resets_at || fiveHour)) {
+        windows.push({id:'five_hour', label:'5h', utilization:fiveHour,
             window_minutes:300, resets_at:row.five_hour_resets_at || null});
     }
-    if (row?.seven_day_resets_at || Number(row?.seven_day_pct)) {
-        windows.push({id:'seven_day', label:'7d', utilization:Number(row.seven_day_pct) || 0,
+    if (sevenDay !== null && (row.seven_day_resets_at || sevenDay)) {
+        windows.push({id:'seven_day', label:'7d', utilization:sevenDay,
             window_minutes:10080, resets_at:row.seven_day_resets_at || null});
     }
     return windows.length ? {anthropic:{label:'Claude', windows}} : {};
 }
 
### bff96d941 #162: #162: research — курс 5h→7d измерен, в недельный лимит влезает ~7 пятичасовых окон

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index f46c8470b..5caff4f97 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -75,12 +75,25 @@ function _etaToLimit(currentPct, isoStr, windowMs) {
     else if (etaMin < 1440) label = `${Math.floor(etaMin/60)}h ${etaMin%60}m`;
     else label = `${Math.floor(etaMin/1440)}d ${Math.floor((etaMin%1440)/60)}h`;
     return `<span style="color:${color}">⏳${label}</span>`;
 }
 
-function _miniBar(pct, color) {
-    return `<span style="display:inline-flex;align-items:center;gap:4px"><span style="display:inline-block;width:80px;height:6px;border-radius:3px;background:rgba(51,65,85,0.5);overflow:hidden;vertical-align:middle"><span style="display:block;width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${color}"></span></span><span style="color:#e2e8f0;font-weight:600">${pct}%</span></span>`;
+function _miniBar(pct, color, lockedPct = 0) {
+    // lockedPct — хвост шкалы, который выглядит свободным, но упирается в ДРУГОЙ лимит (#162).
+    // Без него пустое место на полосе читается как «столько ещё можно потратить».
+    const locked = lockedPct > 0
+        ? `<span style="position:absolute;right:0;top:0;height:100%;width:${Math.min(lockedPct, 100)}%;background:repeating-linear-gradient(45deg,rgba(148,163,184,0.5) 0 2px,rgba(148,163,184,0.12) 2px 4px)"></span>`
+        : '';
+    return `<span style="display:inline-flex;align-items:center;gap:4px"><span style="position:relative;display:inline-block;width:80px;height:6px;border-radius:3px;background:rgba(51,65,85,0.5);overflow:hidden;vertical-align:middle"><span style="display:block;width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${color}"></span>${locked}</span><span style="color:#e2e8f0;font-weight:600">${pct}%</span></span>`;
+}
+
+// Недельное окно связывает пятичасовое, только когда остатка недели не хватает
+// даже на полтора пятичасовых расхода. Выше — прибор молчит, вид не меняется.
+function _quotaCap() {
+    const head = _usageData && _usageData.quota_headroom;
+    if (!head || typeof head.windows_left !== 'number' || head.windows_left >= 1.5) return null;
+    return head;
 }
 
 function _codexWindowLabel(windowMinutes) {
     if (windowMinutes === 300) return '5h';
     if (windowMinutes === 10080) return '7d';
@@ -149,11 +162,20 @@ function renderUsageBar() {
         const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
         const c = _usageColor(fh.utilization, rpNum);
         const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
         const cd = _resetCountdown(fh.resets_at);
         const pace = _paceIndicator(fh.utilization, fh.resets_at, 5 * 3600000);
-        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
+        const cap = _quotaCap();
+        let capHtml = '';
+        if (cap) {
+            const label = cap.windows_left < 0.05
+                ? 'недельный выбран'
+                : `осталось ${cap.windows_left.toFixed(1)} окна`;
+            const hint = `Недельный лимит: доступно ${cap.available_pct}% из показанных ${(100 - fh.utilization).toFixed(0)}% (курс ${cap.rate} за ${cap.window_hours} ч)`;
+            capHtml = ` <span style="font-size:10px">·</span> <span data-quota-cap style="color:#f59e0b" title="${hint}">${label}</span>`;
+        }
+        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c, cap ? cap.locked_pct : 0)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}${capHtml}</span>`);
     }
     const sd = a.seven_day;
     if (sd) {
         const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
         const c = _usageColor(sd.utilization, rpNum);
### ba10d0dcb #163: #163: keep usage controls visible on narrow desktops

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 5caff4f97..6cdfae4fc 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -131,10 +131,16 @@ function _usageFreshnessHtml() {
     }
     const stale = Date.now() - _usageLastSuccessAt >= _USAGE_REFRESH_INTERVAL_MS;
     return `<span id="usage-freshness" style="color:${stale ? '#eab308' : '#64748b'}">${stale ? 'устарело' : 'обновлено'} ${age}</span>`;
 }
 
+function _renderUsageBarShell(bar, groups) {
+    bar.innerHTML = `<div class="usage-limits">${groups.join('')}</div>`
+        + `<div class="usage-actions">${_usageFreshnessHtml()}`
+        + '<span id="usage-info-btn" title="Usage details and history">ⓘ</span></div>';
+}
+
 function renderUsageBar() {
     const bar = document.getElementById('usage-bar');
     if (!bar) return;
     if (!_usageData) {
         if (_usageError) {
@@ -144,20 +150,20 @@ function renderUsageBar() {
             bar.innerHTML = '';
             bar.style.display = 'none';
         }
         return;
     }
-    bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap;cursor:pointer';
+    bar.style.cssText = 'display:flex;align-items:flex-start;gap:10px;padding:4px 12px;min-height:28px;height:auto;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:visible;white-space:nowrap;cursor:pointer';
     bar.title = 'Нажмите, чтобы обновить usage';
 
     const a = _usageData.anthropic || {};
     const cx = _usageData.codex || {};
     const gx = _usageData.grok || null;
-    const o = _usageData.orchestra || {};
-    const parts = [];
+    const groups = [];
+    const claudeParts = [];
 
-    if (_usageError) parts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
+    if (_usageError) claudeParts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
 
     const fh = a.five_hour;
     if (fh) {
         const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
         const c = _usageColor(fh.utilization, rpNum);
@@ -171,34 +177,40 @@ function renderUsageBar() {
                 ? 'недельный выбран'
                 : `осталось ${cap.windows_left.toFixed(1)} окна`;
             const hint = `Недельный лимит: доступно ${cap.available_pct}% из показанных ${(100 - fh.utilization).toFixed(0)}% (курс ${cap.rate} за ${cap.window_hours} ч)`;
             capHtml = ` <span style="font-size:10px">·</span> <span data-quota-cap style="color:#f59e0b" title="${hint}">${label}</span>`;
         }
-        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c, cap ? cap.locked_pct : 0)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}${capHtml}</span>`);
+        claudeParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c, cap ? cap.locked_pct : 0)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}${capHtml}</span>`);
     }
     const sd = a.seven_day;
     if (sd) {
         const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
         const c = _usageColor(sd.utilization, rpNum);
         const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
         const cd = _resetCountdown(sd.resets_at);
         const pace = _paceIndicator(sd.utilization, sd.resets_at, 7 * 86400000);
-        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
+        claudeParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
+    }
+    if (claudeParts.length) {
+        groups.push(`<span class="usage-provider-group" data-usage-compact-provider="claude">${claudeParts.join('')}</span>`);
     }
 
     const compactProviders = [
         {id:'codex', windows:_usageProviderWindows('codex', cx)},
         {id:'grok', windows:_usageProviderWindows('grok', gx), showUnavailable:true},
     ].filter(provider => provider.windows.length || provider.showUnavailable);
     if (compactProviders.length) {
-        parts.push('<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>');
         for (const provider of compactProviders) {
             const meta = _PROVIDER_META[provider.id];
             const color = _usageProviderAccent(provider.id);
-            parts.push(`<span style="color:${color};font-weight:600">${meta.compactTitle || meta.title}</span>`);
+            const providerParts = [
+                '<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>',
+                `<span style="color:${color};font-weight:600">${meta.compactTitle || meta.title}</span>`,
+            ];
             if (!provider.windows.length) {
-                parts.push('<span style="color:#64748b">: нет данных</span>');
+                providerParts.push('<span style="color:#64748b">: нет данных</span>');
+                groups.push(`<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">${providerParts.join('')}</span>`);
                 continue;
             }
             for (const item of provider.windows) {
                 const window = item.window;
                 const windowMs = window.window_minutes * 60000;
@@ -206,28 +218,17 @@ function renderUsageBar() {
                 const c = _usageColor(window.utilization, rpNum);
                 const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
                 const cd = _resetCountdown(window.resets_at);
                 const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
                 const label = _codexWindowLabel(window.window_minutes);
-                parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">${label}: ${_miniBar(window.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
+                providerParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">${label}: ${_miniBar(window.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
             }
+            groups.push(`<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">${providerParts.join('')}</span>`);
         }
     }
 
-    parts.push('<span style="flex:1"></span>');
-
-    if (typeof o.total_cost_usd === 'number') {
-        parts.push(`<span style="color:#22c55e">${MODEL_COST_CURRENCY}${o.total_cost_usd.toFixed(0)}</span>`);
-    }
-    if (typeof o.agents_count === 'number') {
-        parts.push(`<span style="color:#64748b">${o.agents_count} agents</span>`);
-    }
-    const freshness = _usageFreshnessHtml();
-    if (freshness) parts.push(freshness);
-    parts.push('<span id="usage-info-btn" style="color:#475569;font-size:12px;cursor:help;transition:color 0.15s">ⓘ</span>');
-
-    bar.innerHTML = parts.join('');
+    _renderUsageBarShell(bar, groups);
 
     const infoBtn = document.getElementById('usage-info-btn');
     if (infoBtn) {
         let tip = null, showTimer = null, hideTimer = null;
         const hideTip = () => {
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index dfa295837..96f1f3d79 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -5,10 +5,11 @@ from playwright.sync_api import Browser, expect, sync_playwright
 
 
 ROOT = Path(__file__).parent.parent
 UTILS_JS = ROOT / "app/static/js/utils.js"
 USAGE_JS = ROOT / "app/static/js/usage.js"
+STYLE_CSS = ROOT / "app/static/css/style.css"
 
 
 @pytest.fixture(scope="module")
 def browser():
     with sync_playwright() as playwright:
@@ -113,10 +114,43 @@ def test_compact_bar_replaces_spark_with_grok(browser):
     expect(page.locator("#usage-bar")).not_to_contain_text("Spark")
     expect(page.locator("#usage-bar")).to_contain_text("7d")
     page.close()
 
 
+def test_usage_controls_stay_visible_across_desktop_widths(browser):
+    for width in (1280, 1440, 1680, 1920):