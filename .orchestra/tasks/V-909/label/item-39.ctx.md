# Context for item-39

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index b04296c53..8ae66b680 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -220,68 +220,68 @@ function renderUsageBar() {
         }
         return;
     }
     bar.style.cssText = 'display:flex;align-items:flex-start;gap:10px;padding:4px 12px;min-height:28px;height:auto;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:visible;white-space:nowrap;cursor:pointer';
     bar.title = 'Нажмите, чтобы обновить usage';
 
     const a = _usageData.anthropic || {};
     const cx = _usageData.codex || {};
     const gx = _usageData.grok || null;
     const groups = [];
     const claudeParts = [];
 
     if (_usageError) claudeParts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
 
     const fh = a.five_hour;
     if (fh) {
         const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
         const c = _usageColor(fh.utilization, rpNum);
         const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
         const cd = _resetCountdown(fh.resets_at);
-        const release = _quotaMapLaneStatusText(fh, 'anthropic');
+        const release = '';
         claudeParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">5h: ${_miniBar(fh.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${release ? ` <span style="font-size:10px">·</span> ${release}` : ''}</span>`);
     }
     const sd = a.seven_day;
     if (sd) {
         const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
         const c = _usageColor(sd.utilization, rpNum);
         const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
         const cd = _resetCountdown(sd.resets_at);
         const release = _quotaMapLaneStatusText(sd, 'anthropic');
         claudeParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${release ? ` <span style="font-size:10px">·</span> ${release}` : ''}</span>`);
     }
     if (claudeParts.length) {
         groups.push(`<span class="usage-provider-group" data-usage-compact-provider="claude">${claudeParts.join('')}</span>`);
     }
 
     const compactProviders = [
         {id:'codex', bucketId:'codex', windows:_usageProviderWindows('codex', cx)},
-        {id:'codex', bucketId:'codex_spark', windows:_usageProviderWindows('codex', cx.spark)},
+        {id:'codex', bucketId:'codex_spark', windows:_usageProviderWindows('codex', cx.spark), compactTitle:'Codex Spark'},
         {id:'grok', bucketId:'grok', windows:_usageProviderWindows('grok', gx), showUnavailable:true},
     ].filter(provider => provider.windows.length || provider.showUnavailable);
     if (compactProviders.length) {
         for (const provider of compactProviders) {
             const meta = _PROVIDER_META[provider.id];
             const color = _usageProviderAccent(provider.id);
             const providerParts = [
                 '<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>',
-                `<span style="color:${color};font-weight:600">${meta.compactTitle || meta.title}</span>`,
+                `<span style="color:${color};font-weight:600">${provider.compactTitle || meta.compactTitle || meta.title}</span>`,
             ];
             if (!provider.windows.length) {
                 providerParts.push('<span style="color:#64748b">: нет данных</span>');
                 groups.push(`<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">${providerParts.join('')}</span>`);
                 continue;
             }
             for (const item of provider.windows) {
                 const window = item.window;
                 const windowMs = window.window_minutes * 60000;
                 const rpNum = _resetPctNum(window.resets_at, windowMs);
                 const c = _usageColor(window.utilization, rpNum);
                 const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
                 const cd = _resetCountdown(window.resets_at);
                 const release = _quotaMapLaneStatusText(window, provider.bucketId);
                 const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
                 const label = _codexWindowLabel(window.window_minutes);
                 providerParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">${label}: ${_miniBar(window.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${release ? ` <span style="font-size:10px">·</span> ${release}` : ''}</span>`);
             }
             groups.push(`<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">${providerParts.join('')}</span>`);
         }
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 96f1f3d79..02a6ab907 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -94,71 +94,143 @@ def _settle_usage(page, utilization, *, reject=False):
                 anthropic: {
                     five_hour: {utilization, resets_at: reset},
                     seven_day: {utilization: 31, resets_at: reset},
                 },
                 codex: {
                     primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                 },
                 grok: null,
                 orchestra: {},
             });
         }""",
         [utilization, reject],
     )
     page.wait_for_function("() => _usageFetchPromise === null")
 
 
 def test_compact_bar_replaces_spark_with_grok(browser):
     page = _page(browser, True)
 
     expect(page.locator("#usage-bar")).to_contain_text("Grok")
-    expect(page.locator("#usage-bar")).not_to_contain_text("Spark")
+    expect(page.locator("#usage-bar")).to_contain_text("Codex")
+    expect(page.locator("#usage-bar")).to_contain_text("Codex Spark")
     expect(page.locator("#usage-bar")).to_contain_text("7d")
     page.close()
 
 
+def test_usage_bar_shows_spark_label_and_release_statuses(browser):
+    page = _page(browser, True)
+    page.evaluate(
+        """() => {
+            const now = Date.now();
+            const fiveHReset = new Date(now + 1 * 3600000 + 45 * 60000).toISOString();
+            const sevenDReset = new Date(now + 5 * 86400000 + 15 * 3600000 + 46 * 60000).toISOString();
+            const sparkReset = new Date(now + 3 * 86400000 + 16 * 3600000 + 26 * 60000).toISOString();
+            _usageData = {
+                anthropic: {
+                    five_hour: {id: 'cl-5h', utilization: 58, window_minutes: 300, resets_at: fiveHReset},
+                    seven_day: {id: 'cl-7d', utilization: 100, window_minutes: 10080, resets_at: sevenDReset},
+                },
+                codex: {
+                    primary: {id: 'cd-7d', utilization: 100, window_minutes: 10080, resets_at: sevenDReset},
+                    spark: {
+                        primary: {id: 'sp-7d', utilization: 57, window_minutes: 10080, resets_at: sparkReset},
+                    },
+                },
+                grok: {
+                    primary: {utilization: 12, window_minutes: 10080, resets_at: sevenDReset},
+                },
+                orchestra: {},
+            };
+            _quotaMapData = {
+                buckets: [
+                    {
+                        bucket: 'anthropic',
+                        data_available: true,
+                        window: {id: 'cl-5h', window_minutes: 300, resets_at: fiveHReset},
+                        lanes: [{gated: false, blocked: false, release_status: 'open'}],
+                    },
+                    {
+                        bucket: 'anthropic',
+                        data_available: true,
+                        window: {id: 'cl-7d', window_minutes: 10080, resets_at: sevenDReset},
+                        lanes: [{gated: true, blocked: false, release_status: 'opens_in', release_in_seconds: 17300}],
+                    },
+                    {
+                        bucket: 'codex',
+                        data_available: true,
+                        window: {id: 'cd-7d', window_minutes: 10080, resets_at: sevenDReset},
+                        lanes: [{gated: true, blocked: false, release_status: 'opens_in', release_in_seconds: 17300}],
+                    },
+                    {
+                        bucket: 'codex_spark',
+                        data_available: true,
+                        window: {id: 'sp-7d', window_minutes: 10080, resets_at: sparkReset},
+                        lanes: [{gated: false, blocked: false, release_status: 'open'}],
+                    },
+                ],
+            };
+            renderUsageBar();
+        }"""
+    )
+    text = page.locator("#usage-bar").text_content() or ""
+    assert "5h:" in text
+    five_start = text.index("5h:")
+    seven_start = text.index("7d:")
+    assert "откроется" not in text[five_start:seven_start]
+    assert text.count("Codex") >= 1
+    assert "Codex Spark" in text
+    assert "откроется через" in text
+    assert "работает" in text
+    provider_texts = page.locator('[data-usage-compact-provider="codex"]').all_text_contents()
+    assert len(provider_texts) == 2
+    assert "Codex Spark" in provider_texts[1]
+    assert "7d:" in provider_texts[1]
+    page.close()
+
+
 def test_usage_controls_stay_visible_across_desktop_widths(browser):
     for width in (1280, 1440, 1680, 1920):
         page = _page(browser, True)
         page.set_viewport_size({"width": width, "height": 900})
         page.add_style_tag(path=str(STYLE_CSS))
         page.evaluate(
             """() => {
                 _usageData.orchestra = {total_cost_usd: 5687, agents_count: 197};
                 renderUsageBar();
             }"""
         )
         measured = page.evaluate(
             """() => {
                 const bar = document.querySelector('#usage-bar');
                 const info = document.querySelector('#usage-info-btn').getBoundingClientRect();
                 return {
                     infoRight: info.right,
                     viewport: innerWidth,
                     scrollWidth: bar.scrollWidth,
                     clientWidth: bar.clientWidth,
                     providers: [...document.querySelectorAll('[data-usage-compact-provider]')]
                         .map(node => node.dataset.usageCompactProvider),
                 };
             }"""
         )
-        assert measured["providers"] == ["claude", "codex", "grok"]
+        assert measured["providers"] == ["claude", "codex", "codex", "grok"]
         assert measured["infoRight"] <= measured["viewport"]
         assert measured["scrollWidth"] == measured["clientWidth"]
         expect(page.locator("#usage-bar")).not_to_contain_text("$5687")
         expect(page.locator("#usage-bar")).not_to_contain_text("197 agents")
         page.close()
 
 
 def test_usage_control_keeps_spark_and_adds_grok_third_column(browser):
     page = _page(browser, True)
     page.locator("#usage-info-btn").hover()
 
     expect(page.locator("[data-usage-provider]")).to_have_count(3)
     expect(page.locator('[data-usage-provider="codex"]')).to_contain_text("Spark")
     expect(page.locator('[data-usage-provider="grok"]')).to_contain_text("Grok")
     expect(page.locator('[data-usage-provider="grok"]')).to_contain_text("Использовано")
     page.close()
 
 
 def test_missing_grok_data_is_visible_and_never_rendered_as_zero(browser):
     page = _page(browser, False)


## Later history of the touched files on main (after this commit)

22 later commits touch these paths; the first 40 (oldest first):
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

### 7da073458 #356: split quota usage usage bar into provider rows

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 8ae66b680..86608c2cf 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -248,44 +248,54 @@ function renderUsageBar() {
         const cd = _resetCountdown(sd.resets_at);
         const release = _quotaMapLaneStatusText(sd, 'anthropic');
         claudeParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${release ? ` <span style="font-size:10px">·</span> ${release}` : ''}</span>`);
     }
     if (claudeParts.length) {
-        groups.push(`<span class="usage-provider-group" data-usage-compact-provider="claude">${claudeParts.join('')}</span>`);
+        groups.push(
+            '<span class="usage-provider-group" data-usage-compact-provider="claude">'
+            + '<span class="usage-provider-title" style="color:#38bdf8;font-weight:600">Claude</span>'
+            + `<span class="usage-provider-values">${claudeParts.join('')}</span>`
+            + '</span>',
+        );
     }
 
     const compactProviders = [
         {id:'codex', bucketId:'codex', windows:_usageProviderWindows('codex', cx)},
-        {id:'codex', bucketId:'codex_spark', windows:_usageProviderWindows('codex', cx.spark), compactTitle:'Codex Spark'},
+        {id:'codex-spark', bucketId:'codex_spark', windows:_usageProviderWindows('codex', cx.spark), compactTitle:'Codex Spark'},
         {id:'grok', bucketId:'grok', windows:_usageProviderWindows('grok', gx), showUnavailable:true},
     ].filter(provider => provider.windows.length || provider.showUnavailable);
     if (compactProviders.length) {
         for (const provider of compactProviders) {
             const meta = _PROVIDER_META[provider.id];
             const color = _usageProviderAccent(provider.id);
-            const providerParts = [
-                '<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>',
-                `<span style="color:${color};font-weight:600">${provider.compactTitle || meta.compactTitle || meta.title}</span>`,
-            ];
+            const providerParts = [];
             if (!provider.windows.length) {
-                providerParts.push('<span style="color:#64748b">: нет данных</span>');
-                groups.push(`<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">${providerParts.join('')}</span>`);
+                groups.push(
+                    `<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">`
+                    + `<span class="usage-provider-title" style="color:${color};font-weight:600">${provider.compactTitle || meta.compactTitle || meta.title}</span>`
+                    + '<span class="usage-provider-values"><span style="color:#64748b">нет данных</span></span>'
+                    + '</span>'
+                );
                 continue;
             }
             for (const item of provider.windows) {
                 const window = item.window;
                 const windowMs = window.window_minutes * 60000;
                 const rpNum = _resetPctNum(window.resets_at, windowMs);
                 const c = _usageColor(window.utilization, rpNum);
                 const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
                 const cd = _resetCountdown(window.resets_at);
                 const release = _quotaMapLaneStatusText(window, provider.bucketId);
-                const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
                 const label = _codexWindowLabel(window.window_minutes);
                 providerParts.push(`<span style="display:inline-flex;align-items:center;gap:3px">${label}: ${_miniBar(window.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${release ? ` <span style="font-size:10px">·</span> ${release}` : ''}</span>`);
             }
-            groups.push(`<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">${providerParts.join('')}</span>`);
+            groups.push(
+                `<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">`
+                + `<span class="usage-provider-title" style="color:${color};font-weight:600">${provider.compactTitle || meta.compactTitle || meta.title}</span>`
+                + `<span class="usage-provider-values">${providerParts.join('')}</span>`
+                + '</span>',
+            );
         }
     }
 
     _renderUsageBarShell(bar, groups);
 
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 02a6ab907..4a7fe8a49 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -6,10 +6,11 @@ from playwright.sync_api import Browser, expect, sync_playwright
 
 ROOT = Path(__file__).parent.parent
 UTILS_JS = ROOT / "app/static/js/utils.js"
 USAGE_JS = ROOT / "app/static/js/usage.js"
 STYLE_CSS = ROOT / "app/static/css/style.css"
+USAGE_SHOT_DIR = ROOT / "docs/tasks/356"
 
 
 @pytest.fixture(scope="module")
 def browser():
     with sync_playwright() as playwright:
@@ -83,12 +84,16 @@ def _interactive_page(browser: Browser):
 
 def _settle_usage(page, utilization, *, reject=False):
     page.evaluate(
         """([utilization, reject]) => {
             const pending = usagePending.shift();
+            const quotaPending = usagePending.shift();
             if (reject) {
                 pending.reject(new DOMException('signal timed out', 'TimeoutError'));
+                if (quotaPending) {
+                    quotaPending.reject(new DOMException('signal timed out', 'TimeoutError'));
+                }
                 return;
             }
             const reset = new Date(Date.now() + 4 * 86400000).toISOString();
             pending.resolve({
                 anthropic: {
@@ -99,10 +104,13 @@ def _settle_usage(page, utilization, *, reject=False):
                     primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                 },
                 grok: null,
                 orchestra: {},
             });
+            if (quotaPending) {
+                quotaPending.resolve({buckets: []});
+            }
         }""",
         [utilization, reject],
     )
     page.wait_for_function("() => _usageFetchPromise === null")
 
@@ -179,14 +187,109 @@ def test_usage_bar_shows_spark_label_and_release_statuses(browser):
     assert "откроется" not in text[five_start:seven_start]
     assert text.count("Codex") >= 1
     assert "Codex Spark" in text
     assert "откроется через" in text
     assert "работает" in text
-    provider_texts = page.locator('[data-usage-compact-provider="codex"]').all_text_contents()
-    assert len(provider_texts) == 2
-    assert "Codex Spark" in provider_texts[1]
-    assert "7d:" in provider_texts[1]
+    provider_texts = page.locator('[data-usage-compact-provider="codex-spark"]').all_text_contents()
+    assert len(provider_texts) == 1
+    assert "Codex Spark" in provider_texts[0]
+    assert "7d:" in provider_texts[0]
+    page.close()
+
+
+def test_usage_bar_renders_each_provider_on_own_line(browser):
+    USAGE_SHOT_DIR.mkdir(parents=True, exist_ok=True)
+
+    page = browser.new_page(viewport={"width": 1440, "height": 900})
+    page.set_content('<body><div id="usage-bar"></div></body>')
+    page.evaluate("() => { window.marked = {setOptions() {}, parse(value) { return value; } }; window.DOMPurify = { addHook() {} }; }")
+    page.add_script_tag(path=str(UTILS_JS))
+    page.add_script_tag(path=str(USAGE_JS))
+    page.add_style_tag(path=str(STYLE_CSS))
+
+    usage = {
+        "anthropic": {
+            "five_hour": {"utilization": 38, "window_minutes": 300, "resets_at": "2099-01-01T00:00:00.000Z"},
+            "seven_day": {"utilization": 60, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
+        },
### 7484fe0bc #356: layout usage bar in two provider columns

diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index 4a7fe8a49..fa198a6ad 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -194,20 +194,12 @@ def test_usage_bar_shows_spark_label_and_release_statuses(browser):
     assert "Codex Spark" in provider_texts[0]
     assert "7d:" in provider_texts[0]
     page.close()
 
 
-def test_usage_bar_renders_each_provider_on_own_line(browser):
+def test_usage_bar_renders_each_provider_as_two_columns(browser):
     USAGE_SHOT_DIR.mkdir(parents=True, exist_ok=True)
-
-    page = browser.new_page(viewport={"width": 1440, "height": 900})
-    page.set_content('<body><div id="usage-bar"></div></body>')
-    page.evaluate("() => { window.marked = {setOptions() {}, parse(value) { return value; } }; window.DOMPurify = { addHook() {} }; }")
-    page.add_script_tag(path=str(UTILS_JS))
-    page.add_script_tag(path=str(USAGE_JS))
-    page.add_style_tag(path=str(STYLE_CSS))
-
     usage = {
         "anthropic": {
             "five_hour": {"utilization": 38, "window_minutes": 300, "resets_at": "2099-01-01T00:00:00.000Z"},
             "seven_day": {"utilization": 60, "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
         },
@@ -250,47 +242,66 @@ def test_usage_bar_renders_each_provider_on_own_line(browser):
                 "window": {"id": "gk-7d", "window_minutes": 10080, "resets_at": "2099-01-01T00:00:00.000Z"},
                 "lanes": [{"gated": False, "blocked": False, "release_status": "open"}],
             },
         ],
     }
-    page.evaluate(
-        """([usage, quotaMap]) => {
-            const now = Date.now();
-            quotaMap.buckets[0].window.resets_at = new Date(now + 3600000).toISOString();
-            quotaMap.buckets[1].window.resets_at = new Date(now + 5 * 86400000).toISOString();
-            for (const item of [quotaMap.buckets[2], quotaMap.buckets[3], quotaMap.buckets[4]]) {
-                item.window.resets_at = new Date(now + 3 * 86400000).toISOString();
-            }
-            usage.anthropic.five_hour.resets_at = new Date(now + 3600000).toISOString();
-            usage.anthropic.seven_day.resets_at = new Date(now + 5 * 86400000).toISOString();
-            usage.codex.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
-            usage.codex.spark.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
-            usage.grok.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
-            window._usageDataFromApi = usage;
-            window._quotaMapDataFromApi = quotaMap;
-            window.api = (path) => path.includes('quota-map') ? Promise.resolve(_quotaMapDataFromApi) : Promise.resolve(_usageDataFromApi);
-            initUsageBar();
-        }""",
-        [usage, quota_map],
-    )
 
-    expect(page.locator("#usage-bar")).to_contain_text("5h:")
-    expect(page.locator("#usage-bar")).to_contain_text("7d:")
-    expect(page.locator("#usage-bar")).to_contain_text("Codex Spark")
-    expect(page.locator("[data-usage-compact-provider='claude']")).to_have_count(1)
-    expect(page.locator("[data-usage-compact-provider='codex']")).to_have_count(1)
-    expect(page.locator("[data-usage-compact-provider='codex-spark']")).to_have_count(1)
-    expect(page.locator("[data-usage-compact-provider='grok']")).to_have_count(1)
-    expect(page.locator("[data-usage-compact-provider='claude']")).to_contain_text("Claude")
-    expect(page.locator("[data-usage-compact-provider='codex']")).to_contain_text("Codex")
-    expect(page.locator("[data-usage-compact-provider='codex-spark']")).to_contain_text("Codex Spark")
-    expect(page.locator("[data-usage-compact-provider='grok']")).to_contain_text("Grok")
-    bounds = page.locator("#usage-bar").bounding_box()
-    assert bounds is not None
-    assert bounds["height"] <= 120
-    page.locator("#usage-bar").screenshot(path=str(USAGE_SHOT_DIR / "usage-bar-provider-lines.png"))
-    page.close()
+    for width in (1280, 1920):
+        page = browser.new_page(viewport={"width": width, "height": 900})
+        page.set_content('<body><div id="usage-bar"></div></body>')
+        page.evaluate("() => { window.marked = {setOptions() {}, parse(value) { return value; } }; window.DOMPurify = { addHook() {} }; }")
+        page.add_script_tag(path=str(UTILS_JS))
+        page.add_script_tag(path=str(USAGE_JS))
+        page.add_style_tag(path=str(STYLE_CSS))
+
+        page.evaluate(
+            """([usage, quotaMap]) => {
+                const now = Date.now();
+                quotaMap.buckets[0].window.resets_at = new Date(now + 3600000).toISOString();
+                quotaMap.buckets[1].window.resets_at = new Date(now + 5 * 86400000).toISOString();
+                for (const item of [quotaMap.buckets[2], quotaMap.buckets[3], quotaMap.buckets[4]]) {
+                    item.window.resets_at = new Date(now + 3 * 86400000).toISOString();
+                }
+                usage.anthropic.five_hour.resets_at = new Date(now + 3600000).toISOString();
+                usage.anthropic.seven_day.resets_at = new Date(now + 5 * 86400000).toISOString();
+                usage.codex.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
+                usage.codex.spark.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
+                usage.grok.primary.resets_at = new Date(now + 3 * 86400000).toISOString();
+                window._usageDataFromApi = usage;
+                window._quotaMapDataFromApi = quotaMap;
+                window.api = (path) => path.includes('quota-map')
+                    ? Promise.resolve(_quotaMapDataFromApi)
+                    : Promise.resolve(_usageDataFromApi);
+                initUsageBar();
+            }""",
+            [usage, quota_map],
+        )
+
+        expect(page.locator("#usage-bar")).to_contain_text("5h:")
+        expect(page.locator("#usage-bar")).to_contain_text("7d:")
+
+        claude = page.locator('[data-usage-compact-provider="claude"]').bounding_box()
+        codex = page.locator('[data-usage-compact-provider="codex"]').bounding_box()
+        spark = page.locator('[data-usage-compact-provider="codex-spark"]').bounding_box()
+        grok = page.locator('[data-usage-compact-provider="grok"]').bounding_box()
+        assert all([claude, codex, spark, grok])
+
+        assert codex["x"] - claude["x"] > 80
+        assert abs(spark["x"] - claude["x"]) <= 20
+        assert abs(grok["x"] - codex["x"]) <= 20
+
+        expect(page.locator('[data-usage-compact-provider="claude"]')).to_contain_text("Claude")
+        expect(page.locator('[data-usage-compact-provider="codex"]')).to_contain_text("Codex")
+        expect(page.locator('[data-usage-compact-provider="codex-spark"]')).to_contain_text("Codex Spark")
+        expect(page.locator('[data-usage-compact-provider="grok"]')).to_contain_text("Grok")
+
+        bounds = page.locator("#usage-bar").bounding_box()
+        assert bounds is not None
+        assert bounds["height"] < 63
+
+        page.locator("#usage-bar").screenshot(path=str(USAGE_SHOT_DIR / f"usage-bar-provider-grid-{width}.png"))
+        page.close()
 
 
 def test_usage_controls_stay_visible_across_desktop_widths(browser):
     for width in (1280, 1440, 1680, 1920):
         page = _page(browser, True)
### 24d6308d4 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 86608c2cf..da30a00eb 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -745,10 +745,21 @@ function _renderSparklines(slot, providerFilter = null) {
             _renderSparklines(slot, providerFilter);
         });
     });
 }
 
+// Снимок с прошлой загрузки страницы. Без него первый недошедший `/api/usage` на дырявом
+// канале давал «⚠ Usage unavailable» — не потому, что данных нет, а потому, что их негде
+// было взять: память пуста, пока не ответит сеть.
+function _restoreUsageSnapshot() {
+    if (_usageData) return;
+    const snapshot = snapshotLoad('usage');
+    if (!snapshot) return;
+    _usageData = snapshot.data;
+    _usageLastSuccessAt = snapshot.ts;
+}
+
 async function fetchUsage() {
     if (_usageFetchPromise) return _usageFetchPromise;
     _usageLastFetchStartedAt = Date.now();
     _usageFetchPromise = (async () => {
         try {
@@ -768,16 +779,19 @@ async function fetchUsage() {
                     ? `${reason.name}: ${reason.message || '(no message)'}`
                     : String(reason);
                 console.error(`Usage fetch failed: ${detail}`);
             }
             _usageLastSuccessAt = Date.now();
+            snapshotSave('usage', _usageData);
         } catch (error) {
             _usageError = true;
             const detail = error instanceof Error
                 ? `${error.name}: ${error.message || '(no message)'}`
                 : String(error);
             console.error(`Usage fetch failed: ${detail}`);
+            // Своих данных ещё нет — показываем прошлые с меткой возраста вместо пустоты.
+            _restoreUsageSnapshot();
         }
     })();
     renderUsageBar();
     try {
         await _usageFetchPromise;
@@ -786,10 +800,15 @@ async function fetchUsage() {
         renderUsageBar();
     }
 }
 
 function initUsageBar() {
+    // Сперва снимок, потом сеть: полоса заполнена с первого кадра, а свежий ответ её
+    // молча заменит. Обратный порядок показывал пустоту ровно на время запроса — на
+    // канале юзера это 2-6 с, а при провале навсегда.
+    _restoreUsageSnapshot();
+    renderUsageBar();
     fetchUsage();
     const bar = document.getElementById('usage-bar');
     if (bar) {
         bar.addEventListener('click', () => {
             if (_usageFetchPromise) return;
### c74d0d75b #368: #368: Phase 1 — исследование источников счётчика запросов OpenRouter (гибрид: локальный счёт + /activity)

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index da30a00eb..ee0f32f2f 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -256,10 +256,42 @@ function renderUsageBar() {
             + `<span class="usage-provider-values">${claudeParts.join('')}</span>`
             + '</span>',
         );
     }
 
+    const or = _usageData.openrouter || null;
+    if (or) {
+        const accent = '#a78bfa';
+        if (!or.available) {
+            // #368: недоступный счётчик — явное «нет данных», не ноль: ноль
+            // читается как «квота свободна».
+            groups.push(
+                `<span class="usage-provider-group" data-usage-compact-provider="openrouter">`
+                + `<span class="usage-provider-title" style="color:${accent};font-weight:600">OpenRouter</span>`
+                + '<span class="usage-provider-values"><span style="color:#64748b">нет данных</span></span>'
+                + '</span>',
+            );
+        } else {
+            const d = or.daily || {};
+            const m = or.minute || {};
+            const dailyLimit = d.limit || 1000;
+            const minuteLimit = m.limit || 20;
+            const used = Math.max(d.count || 0, 0);
+            const util = Math.round(used / dailyLimit * 1000) / 10;
+            const c = _usageColor(util, null);
+            const resetIso = new Date(Date.now() + 86400000).toISOString().slice(0, 13) + ':00:00Z';
+            const cd = _resetCountdown(resetIso);
+            groups.push(
+                `<span class="usage-provider-group" data-usage-compact-provider="openrouter">`
+                + `<span class="usage-provider-title" style="color:${accent};font-weight:600">OpenRouter</span>`
+                + `<span class="usage-provider-values"><span style="display:inline-flex;align-items:center;gap:3px">сутки: ${_miniBar(util, c)} <span style="color:#64748b">${used}/${dailyLimit}</span>${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}</span>`
+                + ` <span style="display:inline-flex;align-items:center;gap:3px">минута: <span style="color:${(m.count || 0) >= minuteLimit ? '#f87171' : '#94a3b8'}">${m.count || 0}/${minuteLimit}</span></span></span>`
+                + '</span>',
+            );
+        }
+    }
+
     const compactProviders = [
         {id:'codex', bucketId:'codex', windows:_usageProviderWindows('codex', cx)},
         {id:'codex-spark', bucketId:'codex_spark', windows:_usageProviderWindows('codex', cx.spark), compactTitle:'Codex Spark'},
         {id:'grok', bucketId:'grok', windows:_usageProviderWindows('grok', gx), showUnavailable:true},
     ].filter(provider => provider.windows.length || provider.showUnavailable);
@@ -373,13 +405,35 @@ function renderUsageBar() {
                 } else {
                     grokHtml += '<div style="color:#64748b;font-style:italic">Данные лимита недоступны</div>';
                 }
                 grokHtml += '</section>';
 
-                let h = '<div style="color:#e2e8f0;font-weight:700;margin-bottom:10px">📊 Usage control</div>';
+                const orMeta = _usageData?.openrouter || null;
+                let orHtml = '';
+                if (orMeta) {
+                    orHtml = '<section data-usage-provider="openrouter" style="min-width:0;border-left:1px solid rgba(51,65,85,0.65);padding-left:14px">';
+                    orHtml += '<div style="color:#a78bfa;font-weight:700;margin-bottom:7px">OpenRouter (free)</div>';
+                    if (!orMeta.available) {
+                        orHtml += `<div style="color:#64748b;font-style:italic">${escHtml(orMeta.reason || 'Данные недоступны')}</div>`;
+                    } else {
+                        const d = orMeta.daily || {}, m = orMeta.minute || {};
+                        orHtml += _row('Сутки', `${d.count}/${d.limit}`, '#cbd5e1');
+                        orHtml += _row('Минута', `${m.count}/${m.limit}`, '#cbd5e1');
+                        orHtml += _row('Источник счёта', 'локальный', '#64748b');
+                        const rec = orMeta.reconciliation;
+                        if (rec) {
+                            orHtml += `<div style="margin-top:4px;color:#94a3b8">Вчера (${escHtml(rec.day)}): провайдер ${rec.provider_requests}, локально ${rec.local_requests}, Δ ${rec.delta}</div>`;
+                            const bs = rec.local_by_status || {};
+                            const parts = Object.keys(bs).map(k => `${k}×${bs[k]}`).join(', ');
+                            if (parts) orHtml += `<div style="color:#64748b;font-size:10px">Локальные попытки вчера: ${escHtml(parts)}</div>`;
+                        }
+                    }
+                    orHtml += '</section>';
+                }
+
                 h += '<div id="usage-sparkline-slot" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px">';
-                h += claudeHtml + codexHtml + grokHtml + '</div>';
+                h += claudeHtml + codexHtml + grokHtml + orHtml + '</div>';
                 if (typeof _o.total_cost_usd === 'number') {
                     h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
                     h += _row('💰 Стоимость', `${MODEL_COST_CURRENCY}${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                     if (typeof _usageData.voice_cost_usd === 'number') {
                         h += `<div style="font-size:10px">${_row('🎤 Voice', `${MODEL_COST_CURRENCY}${_usageData.voice_cost_usd.toFixed(2)}`, '#94a3b8')}</div>`;
### c6022d4ad fix: open usage details without refreshing the bar

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index ee0f32f2f..d13704a4b 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -343,11 +343,11 @@ function renderUsageBar() {
             hideTimer = setTimeout(() => {
                 if (tip && tip.matches(':hover')) return;
                 hideTip();
             }, 200);
         };
-        infoBtn.addEventListener('mouseenter', () => {
+        const showTip = () => {
             clearTimeout(hideTimer);
             infoBtn.style.color = '#94a3b8';
             showTimer = setTimeout(async () => {
                 if (tip) return;
                 const _a = _usageData?.anthropic || {};
@@ -367,10 +367,11 @@ function renderUsageBar() {
                     if (rpNum != null) html += _row('Прогресс окна', `${rpNum}%`, '#64748b');
                     html += _row('Отклонение', pace, null);
                     if (eta) html += _row('Лимит через', eta, null);
                     return html + '</div>';
                 };
+                let h = '';
                 const claudeMeta = _PROVIDER_META.claude;
                 let claudeHtml = '<section data-usage-provider="claude" style="min-width:0;padding-right:2px">';
                 claudeHtml += `<div style="color:${_usageProviderAccent('claude')};font-weight:700;margin-bottom:7px">${claudeMeta.usageTitle}</div>`;
                 for (const item of _usageProviderWindows('claude', _a)) {
                     claudeHtml += _windowBlock(item.window, item.label, claudeMeta.windowAccent);
@@ -458,10 +459,16 @@ function renderUsageBar() {
                 tip.addEventListener('mouseenter', () => clearTimeout(hideTimer));
                 tip.addEventListener('mouseleave', () => { delayedHide(); });
                 document.body.appendChild(tip);
                 _loadSparkline(tip);
             }, 200);
+        };
+        infoBtn.addEventListener('mouseenter', showTip);
+        infoBtn.addEventListener('click', (event) => {
+            event.preventDefault();
+            event.stopPropagation();
+            if (!tip) showTip();
         });
         infoBtn.addEventListener('mouseleave', () => { infoBtn.style.color = '#475569'; delayedHide(); });
     }
 }
 
@@ -862,11 +869,12 @@ function initUsageBar() {
     _restoreUsageSnapshot();
     renderUsageBar();
     fetchUsage();
     const bar = document.getElementById('usage-bar');
     if (bar) {
-        bar.addEventListener('click', () => {
+        bar.addEventListener('click', (event) => {
+            if (event.target.closest('#usage-info-btn')) return;
             if (_usageFetchPromise) return;
             if (Date.now() - _usageLastFetchStartedAt < _USAGE_CLICK_DEBOUNCE_MS) return;
             fetchUsage();
         });
     }
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index fa198a6ad..fba43fb41 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -384,10 +384,32 @@ def test_usage_fetch_failure_stays_visible_and_logs_exception(browser):
     expect(page.locator("#usage-bar")).to_contain_text("Usage unavailable")
     assert errors == ["Usage fetch failed: TimeoutError: signal timed out"]
     page.close()
 
 
+def test_usage_info_click_opens_details_without_refreshing_usage(browser):
+    page = _interactive_page(browser)
+    _settle_usage(page, 42)
+    page.evaluate(
+        """() => {
+            _usageLastFetchStartedAt = 0;
+            const originalApi = api;
+            window.usageRefreshCalls = 0;
+            window.api = (url, opts) => {
+                if (url === '/api/usage') usageRefreshCalls += 1;
+                return originalApi(url, opts);
+            };
+        }"""
+    )
+
+    page.locator("#usage-info-btn").click()
+
+    expect(page.locator('[data-usage-provider="claude"]')).to_be_visible()
+    assert page.evaluate("() => usageRefreshCalls") == 0
+    page.close()
+
+
 def test_usage_refreshes_on_click_and_stale_tab_return_without_request_storm(browser):
     page = _interactive_page(browser)
     errors = []
     page.on(
         "console",
### aa33578e2 #234: #234: add red acceptance tests

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index d13704a4b..258c4b0ed 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -822,29 +822,40 @@ function _restoreUsageSnapshot() {
 async function fetchUsage() {
     if (_usageFetchPromise) return _usageFetchPromise;
     _usageLastFetchStartedAt = Date.now();
     _usageFetchPromise = (async () => {
         try {
-            const [usage, quotaMap] = await Promise.allSettled([
+            const [usage] = await Promise.allSettled([
                 api('/api/usage'),
-                api('/api/usage/quota-map'),
             ]);
-            _usageData = usage.status === 'fulfilled' ? usage.value : null;
+            // `/api/usage` — единственный владелец provider refresh. Карта читает уже
+            // обновлённый кеш, иначе два параллельных GET снова увидят старую точку.
+            const [quotaMap] = await Promise.allSettled([
+                typeof _fetchQuotaMapShared === 'function'
+                    ? _fetchQuotaMapShared()
+                    : api('/api/usage/quota-map'),
+            ]);
             _quotaMapData = quotaMap.status === 'fulfilled' ? quotaMap.value : null;
-            _usageError = usage.status !== 'fulfilled';
+            if (usage.status === 'fulfilled') {
+                _usageData = usage.value;
+                _usageError = false;
+                _usageLastSuccessAt = Date.now();
+                snapshotSave('usage', _usageData);
+            } else {
+                _usageError = true;
+                if (!_usageData) _restoreUsageSnapshot();
+            }
             if (!_usageError && quotaMap.status !== 'fulfilled') {
                 console.error(`quota-map fetch failed: ${quotaMap.reason && quotaMap.reason.message || 'unknown'}`);
             }
             if (_usageError) {
                 const reason = usage.reason || null;
                 const detail = reason instanceof Error
                     ? `${reason.name}: ${reason.message || '(no message)'}`
                     : String(reason);
                 console.error(`Usage fetch failed: ${detail}`);
             }
-            _usageLastSuccessAt = Date.now();
-            snapshotSave('usage', _usageData);
         } catch (error) {
             _usageError = true;
             const detail = error instanceof Error
                 ? `${error.name}: ${error.message || '(no message)'}`
                 : String(error);
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index fba43fb41..f99d707a0 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -84,16 +84,12 @@ def _interactive_page(browser: Browser):
 
 def _settle_usage(page, utilization, *, reject=False):
     page.evaluate(
         """([utilization, reject]) => {
             const pending = usagePending.shift();
-            const quotaPending = usagePending.shift();
             if (reject) {
                 pending.reject(new DOMException('signal timed out', 'TimeoutError'));
-                if (quotaPending) {
-                    quotaPending.reject(new DOMException('signal timed out', 'TimeoutError'));
-                }
                 return;
             }
             const reset = new Date(Date.now() + 4 * 86400000).toISOString();
             pending.resolve({
                 anthropic: {
@@ -104,16 +100,23 @@ def _settle_usage(page, utilization, *, reject=False):
                     primary: {utilization: 22, window_minutes: 10080, resets_at: reset},
                 },
                 grok: null,
                 orchestra: {},
             });
-            if (quotaPending) {
-                quotaPending.resolve({buckets: []});
-            }
         }""",
         [utilization, reject],
     )
+    # Cache-only quota-map starts only after the usage refresh owner settles.
+    page.wait_for_function("() => usagePending.length === 1")
+    page.evaluate(
+        """reject => {
+            const quotaPending = usagePending.shift();
+            if (reject) quotaPending.reject(new DOMException('signal timed out', 'TimeoutError'));
+            else quotaPending.resolve({buckets: []});
+        }""",
+        reject,
+    )
     page.wait_for_function("() => _usageFetchPromise === null")
 
 
 def test_compact_bar_replaces_spark_with_grok(browser):
     page = _page(browser, True)
@@ -423,13 +426,14 @@ def test_usage_refreshes_on_click_and_stale_tab_return_without_request_storm(bro
 
     page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
     page.locator("#usage-bar").click()
     page.locator("#usage-bar").click()
     page.locator("#usage-bar").click()
-    assert page.evaluate("() => usageRequests") == 4
+    assert page.evaluate("() => usageRequests") == 3
     expect(page.locator("#usage-freshness")).to_have_text("обновление…")
     _settle_usage(page, 2)
+    assert page.evaluate("() => usageRequests") == 4
 
     expect(page.locator("#usage-bar")).to_contain_text("2%")
     expect(page.locator("#usage-freshness")).to_have_text("обновлено сейчас")
 
     page.evaluate(
@@ -453,19 +457,22 @@ def test_usage_refreshes_on_click_and_stale_tab_return_without_request_storm(bro
             window.testVisibility = 'visible';
             document.dispatchEvent(new Event('visibilitychange'));
             document.dispatchEvent(new Event('visibilitychange'));
         }"""
     )
-    assert page.evaluate("() => usageRequests") == 6
+    assert page.evaluate("() => usageRequests") == 5
     _settle_usage(page, 3)
+    assert page.evaluate("() => usageRequests") == 6
     expect(page.locator("#usage-bar")).to_contain_text("3%")
 
     page.evaluate("() => { _usageLastFetchStartedAt = 0; }")
     page.locator("#usage-bar").click()
     _settle_usage(page, 0, reject=True)
-    expect(page.locator("#usage-bar")).to_contain_text("Usage unavailable")
-    expect(page.locator("#usage-freshness")).to_have_count(0)
+    expect(page.locator("#usage-bar")).to_contain_text("3%")
+    expect(page.locator("#usage-bar")).not_to_contain_text("Usage unavailable")
+    expect(page.locator("#usage-freshness")).to_contain_text("ошибка обновления")
+    expect(page.locator("#usage-freshness")).to_contain_text("данные от сейчас")
     assert errors == ["Usage fetch failed: TimeoutError: signal timed out"]
     page.close()
 
 
 def test_history_period_requires_two_points(browser):
### 3318068b0 Unify restart and connection status across dashboard

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 258c4b0ed..ca2ec0dd2 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -2,10 +2,19 @@
 
 let _usageData = null;
 let _quotaMapData = null;
 let _usageError = false;
 let _usageCountdownInterval = null;
+
+function _connectionOwnsUsageErrors() {
+    return typeof connectionStatusOwnsTransientErrors === 'function'
+        && connectionStatusOwnsTransientErrors();
+}
+
+function _usageNoDataLabel() {
+    return _connectionOwnsUsageErrors() ? '—' : 'нет данных';
+}
 let _usageFetchPromise = null;
 let _usageLastSuccessAt = 0;
 let _usageLastFetchStartedAt = 0;
 const _USAGE_REFRESH_INTERVAL_MS = 120000;
 const _USAGE_CLICK_DEBOUNCE_MS = 1000;
@@ -133,11 +142,11 @@ function _quotaMapLaneStatusText(windowData, bucketId = null) {
     }
     if (status === 'at_reset') {
         return hasSeconds ? `откроется при сбросе, через ${_releaseDurationFromSeconds(seconds)}` : 'откроется при сбросе';
     }
     if (status === 'no_data') {
-        return 'нет данных';
+        return _connectionOwnsUsageErrors() ? '' : 'нет данных';
     }
     return 'работает';
 }
 
 function _etaToLimit(currentPct, isoStr, windowMs) {
@@ -186,10 +195,11 @@ function _usageProviderWindows(providerId, capacity) {
                 : window,
         }));
 }
 
 function _usageFreshnessHtml() {
+    if (_connectionOwnsUsageErrors()) return '';
     if (_usageFetchPromise) {
         return '<span id="usage-freshness" style="color:#38bdf8">обновление…</span>';
     }
     if (!_usageLastSuccessAt) return '';
     const ageMinutes = Math.floor((Date.now() - _usageLastSuccessAt) / 60000);
@@ -210,10 +220,15 @@ function _renderUsageBarShell(bar, groups) {
 function renderUsageBar() {
     const bar = document.getElementById('usage-bar');
     if (!bar) return;
     if (!_usageData) {
         if (_usageError) {
+            if (_connectionOwnsUsageErrors()) {
+                bar.innerHTML = '';
+                bar.style.display = 'none';
+                return;
+            }
             bar.style.cssText = 'display:flex;align-items:center;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#eab308;flex-shrink:0';
             bar.textContent = '⚠ Usage unavailable';
         } else {
             bar.innerHTML = '';
             bar.style.display = 'none';
@@ -227,11 +242,13 @@ function renderUsageBar() {
     const cx = _usageData.codex || {};
     const gx = _usageData.grok || null;
     const groups = [];
     const claudeParts = [];
 
-    if (_usageError) claudeParts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
+    if (_usageError && !_connectionOwnsUsageErrors()) {
+        claudeParts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
+    }
 
     const fh = a.five_hour;
     if (fh) {
         const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
         const c = _usageColor(fh.utilization, rpNum);
@@ -265,11 +282,11 @@ function renderUsageBar() {
             // #368: недоступный счётчик — явное «нет данных», не ноль: ноль
             // читается как «квота свободна».
             groups.push(
                 `<span class="usage-provider-group" data-usage-compact-provider="openrouter">`
                 + `<span class="usage-provider-title" style="color:${accent};font-weight:600">OpenRouter</span>`
-                + '<span class="usage-provider-values"><span style="color:#64748b">нет данных</span></span>'
+                + `<span class="usage-provider-values"><span style="color:#64748b">${_usageNoDataLabel()}</span></span>`
                 + '</span>',
             );
         } else {
             const d = or.daily || {};
             const m = or.minute || {};
@@ -302,11 +319,11 @@ function renderUsageBar() {
             const providerParts = [];
             if (!provider.windows.length) {
                 groups.push(
                     `<span class="usage-provider-group" data-usage-compact-provider="${provider.id}">`
                     + `<span class="usage-provider-title" style="color:${color};font-weight:600">${provider.compactTitle || meta.compactTitle || meta.title}</span>`
-                    + '<span class="usage-provider-values"><span style="color:#64748b">нет данных</span></span>'
+                    + `<span class="usage-provider-values"><span style="color:#64748b">${_usageNoDataLabel()}</span></span>`
                     + '</span>'
                 );
                 continue;
             }
             for (const item of provider.windows) {
@@ -838,13 +855,17 @@ async function fetchUsage() {
             if (usage.status === 'fulfilled') {
                 _usageData = usage.value;
                 _usageError = false;
                 _usageLastSuccessAt = Date.now();
                 snapshotSave('usage', _usageData);
+                if (typeof _clearStaleNotice === 'function') _clearStaleNotice('usage');
             } else {
                 _usageError = true;
                 if (!_usageData) _restoreUsageSnapshot();
+                if (_usageData && typeof _showStaleNotice === 'function') {
+                    _showStaleNotice('usage', _usageLastSuccessAt);
+                }
             }
             if (!_usageError && quotaMap.status !== 'fulfilled') {
                 console.error(`quota-map fetch failed: ${quotaMap.reason && quotaMap.reason.message || 'unknown'}`);
             }
             if (_usageError) {
@@ -860,10 +881,13 @@ async function fetchUsage() {
                 ? `${error.name}: ${error.message || '(no message)'}`
                 : String(error);
             console.error(`Usage fetch failed: ${detail}`);
             // Своих данных ещё нет — показываем прошлые с меткой возраста вместо пустоты.
             _restoreUsageSnapshot();
+            if (_usageData && typeof _showStaleNotice === 'function') {
+                _showStaleNotice('usage', _usageLastSuccessAt);
+            }
         }
     })();
     renderUsageBar();
     try {
         await _usageFetchPromise;
### 772e3a748 Extract dashboard connection state from app monolith

diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index ca2ec0dd2..9df909782 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -3,17 +3,12 @@
 let _usageData = null;
 let _quotaMapData = null;
 let _usageError = false;
 let _usageCountdownInterval = null;
 
-function _connectionOwnsUsageErrors() {
-    return typeof connectionStatusOwnsTransientErrors === 'function'
-        && connectionStatusOwnsTransientErrors();
-}
-
 function _usageNoDataLabel() {
-    return _connectionOwnsUsageErrors() ? '—' : 'нет данных';
+    return Connection.ownsErrors() ? '—' : 'нет данных';
 }
 let _usageFetchPromise = null;
 let _usageLastSuccessAt = 0;
 let _usageLastFetchStartedAt = 0;
 const _USAGE_REFRESH_INTERVAL_MS = 120000;
@@ -142,11 +137,11 @@ function _quotaMapLaneStatusText(windowData, bucketId = null) {
     }
     if (status === 'at_reset') {
         return hasSeconds ? `откроется при сбросе, через ${_releaseDurationFromSeconds(seconds)}` : 'откроется при сбросе';
     }
     if (status === 'no_data') {
-        return _connectionOwnsUsageErrors() ? '' : 'нет данных';
+        return Connection.ownsErrors() ? '' : 'нет данных';
     }
     return 'работает';
 }
 
 function _etaToLimit(currentPct, isoStr, windowMs) {
@@ -195,11 +190,11 @@ function _usageProviderWindows(providerId, capacity) {
                 : window,
         }));
 }
 
 function _usageFreshnessHtml() {
-    if (_connectionOwnsUsageErrors()) return '';
+    if (Connection.ownsErrors()) return '';
     if (_usageFetchPromise) {
         return '<span id="usage-freshness" style="color:#38bdf8">обновление…</span>';
     }
     if (!_usageLastSuccessAt) return '';
     const ageMinutes = Math.floor((Date.now() - _usageLastSuccessAt) / 60000);
@@ -220,11 +215,11 @@ function _renderUsageBarShell(bar, groups) {
 function renderUsageBar() {
     const bar = document.getElementById('usage-bar');
     if (!bar) return;
     if (!_usageData) {
         if (_usageError) {
-            if (_connectionOwnsUsageErrors()) {
+            if (Connection.ownsErrors()) {
                 bar.innerHTML = '';
                 bar.style.display = 'none';
                 return;
             }
             bar.style.cssText = 'display:flex;align-items:center;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#eab308;flex-shrink:0';
@@ -242,11 +237,11 @@ function renderUsageBar() {
     const cx = _usageData.codex || {};
     const gx = _usageData.grok || null;
     const groups = [];
     const claudeParts = [];
 
-    if (_usageError && !_connectionOwnsUsageErrors()) {
+    if (_usageError && !Connection.ownsErrors()) {
         claudeParts.push('<span style="color:#eab308" title="Using cached data">⚠️</span>');
     }
 
     const fh = a.five_hour;
     if (fh) {
@@ -855,17 +850,15 @@ async function fetchUsage() {
             if (usage.status === 'fulfilled') {
                 _usageData = usage.value;
                 _usageError = false;
                 _usageLastSuccessAt = Date.now();
                 snapshotSave('usage', _usageData);
-                if (typeof _clearStaleNotice === 'function') _clearStaleNotice('usage');
+                Connection.clear('usage');
             } else {
                 _usageError = true;
                 if (!_usageData) _restoreUsageSnapshot();
-                if (_usageData && typeof _showStaleNotice === 'function') {
-                    _showStaleNotice('usage', _usageLastSuccessAt);
-                }
+                if (_usageData) Connection.stale('usage', _usageLastSuccessAt);
             }
             if (!_usageError && quotaMap.status !== 'fulfilled') {
                 console.error(`quota-map fetch failed: ${quotaMap.reason && quotaMap.reason.message || 'unknown'}`);
             }
             if (_usageError) {
@@ -881,13 +874,11 @@ async function fetchUsage() {
                 ? `${error.name}: ${error.message || '(no message)'}`
                 : String(error);
             console.error(`Usage fetch failed: ${detail}`);
             // Своих данных ещё нет — показываем прошлые с меткой возраста вместо пустоты.
             _restoreUsageSnapshot();
-            if (_usageData && typeof _showStaleNotice === 'function') {
-                _showStaleNotice('usage', _usageLastSuccessAt);
-            }
+            if (_usageData) Connection.stale('usage', _usageLastSuccessAt);
         }
     })();
     renderUsageBar();
     try {
         await _usageFetchPromise;
diff --git a/tests/test_grok_usage_frontend.py b/tests/test_grok_usage_frontend.py
index f99d707a0..621d69120 100644
--- a/tests/test_grok_usage_frontend.py
+++ b/tests/test_grok_usage_frontend.py
@@ -4,10 +4,11 @@ import pytest
 from playwright.sync_api import Browser, expect, sync_playwright
 
 
 ROOT = Path(__file__).parent.parent
 UTILS_JS = ROOT / "app/static/js/utils.js"
+CONNECTION_JS = ROOT / "app/static/js/connection.js"
 USAGE_JS = ROOT / "app/static/js/usage.js"
 STYLE_CSS = ROOT / "app/static/css/style.css"
 USAGE_SHOT_DIR = ROOT / "docs/tasks/356"
 
 
@@ -30,10 +31,11 @@ def _page(browser: Browser, grok):
             };
             window.DOMPurify = { addHook() {} };
         }"""
     )
     page.add_script_tag(path=str(UTILS_JS))
+    page.add_script_tag(path=str(CONNECTION_JS))
     page.add_script_tag(path=str(USAGE_JS))
     page.evaluate(
         """grok => {
             const reset = new Date(Date.now() + 4 * 86400000).toISOString();
             _usageData = {
@@ -59,11 +61,11 @@ def _page(browser: Browser, grok):
     return page
 
 
 def _interactive_page(browser: Browser):
     page = browser.new_page(viewport={"width": 1440, "height": 900})
-    page.set_content('<body><div id="usage-bar"></div></body>')
+    page.set_content('<body><div id="connection-banner" class="hidden"></div><div id="usage-bar"></div></body>')
     page.evaluate(
         """() => {