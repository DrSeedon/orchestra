# Context for item-04

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 160acb49a..9cc1feca3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -8239,63 +8239,69 @@ async function loadProfilesList() {
 /* ============================================================================
  * Правило допуска по квоте — две линии расхода (#344).
  *
  * Панель НЕ считает правило: пороги, допуск и вердикты приходят готовыми из
  * /api/usage/quota-map (#343). Здесь только геометрия — перевод чисел сервера в
  * координаты SVG. Единственная местная формула — форма диагонали между узлами,
  * и она строится на константах rule.* того же ответа, а не на своей копии чисел.
  * ========================================================================== */
 
 const _QL_W = 960, _QL_H = 470, _QL_ML = 54, _QL_MR = 20, _QL_MT = 18, _QL_MB = 44;
 const _QL_PW = _QL_W - _QL_ML - _QL_MR, _QL_PH = _QL_H - _QL_MT - _QL_MB;
 const _QL_REFRESH_MS = 120000;
 
 const _QL_PANELS = [
     {key: 'codex', title: 'Пул Codex', sub: 'окно скользящее — 7 суток от первого использования',
      buckets: ['codex', 'codex_spark']},
     {key: 'claude', title: 'Пул Claude', sub: 'окно фиксированное — сброс во вторник 07:00 UTC',
      buckets: ['anthropic']},
 ];
 
+const _QL_NO_RULE = 'нет данных — сервер не прислал константы правила';
+
 let _quotaLinesData = null;
 let _quotaLinesError = '';
 let _quotaLinesOpen = false;
 let _quotaLinesTimer = null;
 
 const _qlX = t => _QL_ML + t * _QL_PW;
 const _qlY = p => _QL_MT + (1 - p / 100) * _QL_PH;
 
 // Форма диагонали допуска между началом и концом окна. Значение В ТЕКУЩЕЙ точке
 // берётся из bucket.limit_pct сервера, а не отсюда, — иначе панель и гейт разойдутся.
 function _qlLimitAt(t, rule) {
     const start = Number(rule.tolerance_start_pp), end = Number(rule.tolerance_end_pp);
     return Math.min(Number(rule.hard_stop_pct), t * 100 + start + (end - start) * t);
 }
 
 function _qlBucket(bucketId) {
     return (_quotaLinesData?.buckets || []).find(b => b.bucket === bucketId) || null;
 }
 
 function _qlNum(value, digits = 0) {
     return Number(value).toFixed(digits);
 }
 
+function _qlTone(verdict) {
+    return verdict.nodata ? 'ql-nodata' : verdict.blocked ? 'ql-verdict-blocked' : 'ql-verdict-open';
+}
+
 // Точка рисуется, только когда сервер сказал, что данные есть. utilization=0 при
 // data_available=false — это «телеметрии нет», и молчаливый ноль соврал бы «всё чисто».
 function _qlPoint(bucket) {
     if (!bucket || !bucket.data_available || !bucket.window) return null;
     const util = Number(bucket.window.utilization);
     if (!Number.isFinite(util)) return null;
     const progress = bucket.window.progress;
     return {
         util,
         progress: Number.isFinite(progress) ? Number(progress) : null,
         limit: Number.isFinite(bucket.limit_pct) ? Number(bucket.limit_pct) : null,
         tolerance: Number.isFinite(bucket.tolerance_pp) ? Number(bucket.tolerance_pp) : null,
         fresh: bucket.fresh !== false,
     };
 }
 
 function _qlLanes(panel) {
     const lanes = [];
     for (const id of panel.buckets) {
         const bucket = _qlBucket(id);
@@ -8356,111 +8362,122 @@ function _qlChartSvg(panel, rule) {
         const right = point.progress > 0.6, dx = right ? -12 : 12, anchor = right ? 'end' : 'start';
         const high = point.util > 85;
         const y1 = high ? y + (secondary ? 35 : 18) : y - (secondary ? 31 : 13);
         // Порог диагонали печатается только там, где он ДЕЙСТВУЕТ. У пула без
         // гейтящихся полос (Spark) допуск считается, но никого не останавливает —
         // напечатать его значило бы приписать Spark ограничение, которого нет.
         const gatedHere = (bucket.lanes || []).some(lane => lane.gated);
         const head = `факт ${_qlNum(point.util)}% · норма ${_qlNum(point.progress * 100)}%`;
         const detail = !gatedHere
             ? `${head} · диагональ не применяется — только жёсткие ${_qlNum(hard)}%`
             : point.limit === null
             ? `${head} · порога нет`
             : `${head} · допуск ${_qlNum(point.tolerance, 1)} п.п. · порог ${_qlNum(point.limit, 1)}%`;
         p.push(`<text class="ql-halo ql-point-label" data-ql-label="${_escHtml(id)}" x="${x + dx}" y="${y1}" text-anchor="${anchor}" fill="${secondary ? 'var(--accent-alt)' : 'var(--ink)'}">${label}${point.fresh ? '' : ' (телеметрия устарела)'}</text>`);
         p.push(`<text class="ql-axis ql-halo" x="${x + dx}" y="${y1 + (high ? 17 : 17)}" text-anchor="${anchor}">${detail}</text>`);
     });
 
     return `<svg class="ql-chart" data-ql-chart="${_escHtml(panel.key)}" viewBox="0 0 ${_QL_W} ${_QL_H}" preserveAspectRatio="xMidYMid meet">${p.join('')}</svg>`;
 }
 
+// ЕДИНСТВЕННЫЙ владелец вердикта: и сводка в свёрнутой строке, и тело панели
+// печатают текст ОТСЮДА. Разойтись по смыслу они не могут по построению — раньше
+// у сводки была своя ветка, и на ответе без блока `rule` она рисовала «работают»,
+// пока тело честно говорило «нет данных».
 // Подпись обязана прямо говорить, кто работает, а кто стоит, — и не выдумывать
 // «работает», когда сервер сказал data_available=false.
 function _qlVerdict(panel) {
+    if (_quotaLinesError) return {text: _quotaLinesError, nodata: true};
+    if (!_quotaLinesData) return {text: 'правило допуска — загрузка…', nodata: true};
+    // Без констант правила неизвестно само правило: вердикт не считается ни для
+    // кого, включая полосы, у которых сервер прислал готовый `blocked`.
+    if (!_quotaLinesData.rule) return {text: _QL_NO_RULE, nodata: true};
+    if (!panel.buckets.map(_qlBucket).filter(Boolean).length) {
+        return {text: 'нет данных — пул отсутствует в ответе сервера', nodata: true};
+    }
     const lanes = _qlLanes(panel);
     const known = lanes.filter(l => l.bucket?.data_available);
-    if (!lanes.length) return {text: 'нет данных', nodata: true};
+    if (!lanes.length) return {text: 'нет данных — сервер не прислал полосы допуска', nodata: true};
     if (!known.length) return {text: 'нет данных — телеметрии пула нет, гейт отвечает unknown', nodata: true};
     const blocked = known.filter(l => l.blocked).map(l => l.label || l.lane);
     const open = known.filter(l => !l.blocked).map(l => l.label || l.lane);
     const parts = [];
     if (blocked.length) parts.push(`${blocked.join(', ')} — стоят`);
     if (open.length) parts.push(`${open.join(', ')} — работают`);
     const partial = known.length < lanes.length;
     return {
         text: parts.join(' · ') + (partial ? ' · часть полос без данных' : ''),
         nodata: false,
         blocked: blocked.length > 0,
     };
 }
 
-function _qlPanelHtml(panel, rule) {
+function _qlPanelHtml(panel) {
+    const rule = _quotaLinesData?.rule;
+    const verdict = _qlVerdict(panel);
     const buckets = panel.buckets.map(_qlBucket).filter(Boolean);
-    if (!buckets.length) {
+    if (!rule || !buckets.length) {
         return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
             <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
-            <p class="ql-nodata" data-ql-verdict>нет данных — пул отсутствует в ответе сервера</p>
+            <p class="ql-nodata" data-ql-verdict>${_escHtml(verdict.text)}</p>
         </section>`;
     }
-    const verdict = _qlVerdict(panel);
     const lanes = _qlLanes(panel).map(lane => {
         const nodata = !lane.bucket?.data_available;
         const state = nodata ? 'nodata' : lane.blocked ? 'blocked' : 'open';
         const word = nodata ? 'нет данных' : lane.blocked ? (lane.gated ? 'блок' : 'блок (99%)') : 'работает';
         return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : ' <i>без диагонали</i>'}</span>`;
     }).join('');
     const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
         .map(l => `<li><b>${_escHtml(l.label || l.lane)}</b> — ${_escHtml(l.reason)}</li>`).join('');
     return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
         <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
         ${_qlChartSvg(panel, rule)}
         <div class="ql-legend">
             <span><i style="background:#8595ab"></i>равномерный расход</span>
             <span><i style="background:#f472b6"></i>порог гейтящихся полос</span>
             <span><i style="background:#fb923c"></i>жёсткие ${_qlNum(rule.hard_stop_pct)}%</span>
             <span><i style="background:#818cf8"></i>оркестратор — без предела</span>
         </div>
-        <p class="ql-verdict ${verdict.nodata ? 'ql-nodata' : verdict.blocked ? 'ql-verdict-blocked' : 'ql-verdict-open'}" data-ql-verdict>${_escHtml(verdict.text)}</p>
+        <p class="ql-verdict ${_qlTone(verdict)}" data-ql-verdict>${_escHtml(verdict.text)}</p>
         <div class="ql-badges">${lanes}<span class="ql-badge ql-badge-always" data-ql-lane="orchestrator">Оркестратор: <b>всегда работает</b></span></div>
         ${reasons ? `<ul class="ql-reasons">${reasons}</ul>` : ''}
     </section>`;
 }
 
+// Сводка — те же вердикты, только короче. Общий отказ (ошибка, загрузка, нет
+// правила) даёт обоим пулам ОДИН текст: печатать его дважды нечего.
 function _qlSummary() {
-    if (_quotaLinesError) return `<b class="ql-nodata">квоты недоступны</b> · ${_escHtml(_quotaLinesError)}`;
-    if (!_quotaLinesData) return 'правило допуска — загрузка…';
-    return _QL_PANELS.map(panel => {
-        const verdict = _qlVerdict(panel);
-        const tone = verdict.nodata ? 'ql-nodata' : verdict.blocked ? 'ql-verdict-blocked' : 'ql-verdict-open';
-        return `<span class="ql-sum-item"><b>${_escHtml(panel.title)}:</b> <span class="${tone}">${_escHtml(verdict.text)}</span></span>`;
-    }).join('');
+    const items = _QL_PANELS.map(panel => ({panel, verdict: _qlVerdict(panel)}));
+    if (items.every(i => i.verdict.text === items[0].verdict.text)) {
+        const verdict = items[0].verdict;
+        return `<span class="ql-sum-item" data-ql-sum><span class="${_qlTone(verdict)}">${_escHtml(verdict.text)}</span></span>`;
+    }
+    return items.map(({panel, verdict}) =>
+        `<span class="ql-sum-item" data-ql-sum><b>${_escHtml(panel.title)}:</b> <span class="${_qlTone(verdict)}">${_escHtml(verdict.text)}</span></span>`
+    ).join('');
 }
 
 function renderQuotaLines() {
     const root = document.getElementById('quota-lines');
     if (!root) return;
-    const rule = _quotaLinesData?.rule;
-    const body = !_quotaLinesData
-        ? `<p class="ql-nodata" data-ql-verdict>${_escHtml(_quotaLinesError || 'нет данных — ответ сервера не получен')}</p>`
-        : !rule
-        ? '<p class="ql-nodata" data-ql-verdict>нет данных — сервер не прислал константы правила</p>'
-        : _QL_PANELS.map(panel => _qlPanelHtml(panel, rule)).join('');
+    const body = _QL_PANELS.map(_qlPanelHtml).join('');
     root.innerHTML = `
         <div class="ql-bar">
             <button type="button" id="quota-lines-toggle" aria-expanded="${_quotaLinesOpen}">${_quotaLinesOpen ? '▾' : '▸'} правило допуска</button>
             <div class="ql-sum">${_qlSummary()}</div>
         </div>
         <div class="ql-body" ${_quotaLinesOpen ? '' : 'hidden'}>${body}</div>`;
     root.querySelector('#quota-lines-toggle').onclick = () => {
         _quotaLinesOpen = !_quotaLinesOpen;
         renderQuotaLines();
     };
 }
 
 async function fetchQuotaLines() {
     try {
         const data = await api('/api/usage/quota-map', {pollKey: 'quota-lines'});
         if (data && data.data_available === false) {
             _quotaLinesData = null;
             _quotaLinesError = `нет данных — ${data.error || 'сервер не отдал карту квот'}`;
         } else {
             _quotaLinesData = data;
diff --git a/docs/workers/impl-quota-front.md b/docs/workers/impl-quota-front.md
index 9f0c0a000..b15b59b4d 100644
--- a/docs/workers/impl-quota-front.md
+++ b/docs/workers/impl-quota-front.md
@@ -47,20 +47,39 @@
 
 Что удалять, решает не глаз, а счёт: для каждого класса-кандидата
 `grep -c "<класс>" app/static/js/*.js app/templates/*.html` → 0 означает «осиротел».
 
 ## Границу «кто владеет числом» держать явно
 
 Сервер (#343) отдаёт `limit_pct`, `tolerance_pp`, `progress` и вердикты `lanes[].blocked`.
 Фронт владеет ТОЛЬКО геометрией — переводом чисел в координаты. Повтор арифметики правила
 в JS = второй владелец, панель разойдётся с гейтом молча.
 
 Единственная местная формула — форма диагонали МЕЖДУ узлами (`_qlLimitAt`), и она строится
 на константах `rule.*` из того же ответа. Что это не разошлось, проверяется тестом:
 `_qlLimitAt(progress, rule)` обязан совпасть с `bucket.limit_pct` сервера.
 
 ## `utilization = 0` и «телеметрии нет» — разные состояния, и путать их нельзя
 
 На неизвестной квоте гейт пропускает (fail-open), поэтому тихое «работает» — прямая ложь
 оператору. Различать по `data_available` / `progress === null` / `fresh`, а не по значению.
 Отдельный случай: `progress = null` при известном `utilization` — диагонали нет, действуют
 только жёсткие 99%.
+
+## Свёрнутая сводка и раскрытое тело — ОДИН вердикт, а не две ветки
+
+19.08 панель на живом дашборде врала именно так: тело честно печатало «нет данных — сервер
+не прислал константы правила» (в проде `/api/usage/quota-map` отдаёт ответ без блока `rule`
+до мержа #343), а сводка в свёрнутой строке при Codex 100% печатала «Sol, Luna Fast, Spark —
+работают». У `_qlSummary()` была своя ветка `!_quotaLinesData`, и состояние «данные есть, а
+`rule` в них нет» она от нормы не отличала.
+
+Тест `test_old_payload_without_rule_block_says_no_data` это пропускал, потому что искал
+«нет данных» по ВСЕМУ `#quota-lines`: обе строки лежат в одном узле, и правдивая строка тела
+покрывала ложную строку сводки. Проверка на отсутствие смысла обязана целиться в СВОЙ узел
+(`.ql-sum`), а не в контейнер.
+
+Лечение — не «добавить ещё одну проверку в сводку», а убрать второго вычислителя: `_qlVerdict()`
+теперь единственный владелец, включая случаи ошибки, загрузки и отсутствия `rule`; `_qlSummary()`
+и `_qlPanelHtml()` только печатают его текст. Разойтись по смыслу они больше не могут
+по построению. Обе стороны закрыты тестами: без `rule` — «нет данных», с `rule` — сводка
+обязана содержать вердикт тела ДОСЛОВНО.
diff --git a/tests/test_t344_quota_lines_browser.py b/tests/test_t344_quota_lines_browser.py
index 3320dc464..78f52e047 100644
--- a/tests/test_t344_quota_lines_browser.py
+++ b/tests/test_t344_quota_lines_browser.py
@@ -256,26 +256,55 @@ def test_unknown_reset_time_drops_the_diagonal_and_keeps_hard_stop(browser):
     assert page.locator("[data-ql-point='codex']").count() == 0
     # SVG-узел не HTMLElement — inner_text() на нём падает, нужен text_content().
     chart = page.locator("[data-ql-chart='codex']").text_content()
     assert "срок сброса неизвестен" in chart
     page.close()
 
 
 def test_old_payload_without_rule_block_says_no_data(browser):
     """Реальное состояние до мержа #343: роут `/api/usage/quota-map` уже есть,
     а блока `rule` в нём ещё нет. Панель обязана честно сказать «нет данных»,
     а не нарисовать линию по выдуманным константам."""
     payload = _payload()
     del payload["rule"]
     page, _ = _render(browser, payload)
     text = page.locator("#quota-lines").inner_text()
     assert "нет данных" in text
     assert page.locator(".ql-chart").count() == 0
     page.close()
 
 
+def test_summary_without_rule_block_says_no_data_not_works(browser):
+    """Свёрнутая сводка на живом ответе без `rule` (сейчас так отвечает прод).
+
+    Ловится именно расхождение сводки с телом: тело говорило «нет данных», а
+    сводка при Codex 100% печатала «Sol, Luna Fast, Spark — работают», потому что
+    считала вердикт своей веткой. Вердикт один — источник один.
+    """
+    payload = _payload(codex_util=100.0, spark_util=100.0, claude_util=20.0)
+    del payload["rule"]
+    page, _ = _render(browser, payload)
+    summary = page.locator("#quota-lines .ql-sum").inner_text()
+    assert "нет данных" in summary, summary
+    assert "работают" not in summary, summary
+    assert "стоят" not in summary, summary
+    page.close()
+
+
+def test_summary_repeats_the_body_verdict_when_the_rule_arrives(browser):
+    """Обратная сторона того же: `rule` пришёл (состояние после мержа #343) —
+    сводка обязана печатать ДОСЛОВНО вердикт тела, а не свой пересчёт."""
+    page, _ = _render(browser, _payload(codex_util=80.0, codex_progress=0.5, claude_util=20.0))
+    summary = page.locator("#quota-lines .ql-sum").inner_text()
+    for key in ("codex", "claude"):
+        body = page.locator(f"[data-ql-panel='{key}'] [data-ql-verdict]").inner_text()
+        assert body and body in summary, (key, body, summary)
+    assert "Sol" in summary and "стоят" in summary, summary
+    page.close()
+
+
 def test_failed_request_says_no_data_and_does_not_pretend_to_work(browser):
     page, _ = _render(browser, None)
     text = page.locator("#quota-lines").inner_text()
     assert "нет данных" in text
     assert page.locator(".ql-chart").count() == 0
     page.close()


## Later history of the touched files on main (after this commit)

107 later commits touch these paths; the first 40 (oldest first):
e91247c9c 2026-08-19 #353: #353: unify quota panel and add traces
a44feb4bb 2026-08-19 #356: #356: route usage bars to quota release status
24d6308d4 2026-08-20 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера
b68ace219 2026-08-20 #202: бабл веб-поиска показывает запрос и результат
5165bcc02 2026-08-21 чат открывается на последних сообщениях и не ждёт зеркало
5e7163191 2026-08-21 чат держится низа всю начальную загрузку
71532403e 2026-08-21 потолок узлов чата 500 -> 200, и обрезка только когда юзер внизу
3985ef548 2026-08-21 открытие чата: 11 запросов -> 0-2, страница берётся одним запросом
ac08becdd 2026-08-21 чат: одна отрисовка вместо достройки экрана кусками, минус 4 механизма
5c77969b3 2026-08-21 таймаут API 2 с -> 4 с: бюджет сгорал в очереди, а не в ответе
47b28811e 2026-08-21 откат таймаута на 2 с и отказ от опроса скрытой панели файлов
0d8208a77 2026-08-21 опрос дашборда: фазовый сдвиг и 304 на /api/sessions
fa3e993db 2026-08-23 Allow fresh model switches without handoff
a7c1c369d 2026-08-22 #369: #369: render harness tool calls as proper chat bubbles
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)
1f0a526d3 2026-08-23 #225: group chat photo batches into compact galleries
aa33578e2 2026-08-23 #234: #234: add red acceptance tests
9f946a601 2026-08-24 #309: #309: freeze phase2 deletion oracles
e7d521de5 2026-08-24 fix: preserve generated images across chat switches
e26dcde85 2026-08-24 fix: switch Codex models in place
b09118919 2026-08-24 #338: #338: remove unreachable deleteOrchestrator
ebb38764a 2026-08-25 #365: harden free OpenRouter harness
33660cfd5 2026-08-25 #397: add final answer timeline navigation
bf1d013c4 2026-08-25 #365: send dashboard voice asynchronously
e7772a32b 2026-08-25 #364: зеркало логов держит 100 строк на сессию; секреты в своих логах не блокируют работу
00ab036d9 2026-08-25 #364: обрезать чат и при чтении истории — узлы копились без предела
13aceafe3 2026-08-25 рестарт: убрать блокировку ввода и починить сторож без pidfd_open
382bd22e8 2026-08-25 #364: freeze red oracle
46b02836a 2026-08-25 Merge remote-tracking branch 'origin/main'
589528d1a 2026-08-26 Improve Orchestra runtime stability and live status
bdff230b0 2026-08-27 #410: add GLM-5.3-Flash harness route
9d43ceaab 2026-08-27 Revert "#410: add GLM-5.3-Flash harness route"
f77e06cee 2026-08-27 #403: render send_files batches in dashboard
ad76ba42e 2026-08-27 #411: freeze reliable restart oracles
a06fcc500 2026-08-27 #404: add mirror freshness regression oracles
07f97eeff 2026-08-27 Merge remote-tracking branch 'origin/main'
99fa70980 2026-08-27 #405: add upload size and progress oracles
735cf14e5 2026-08-28 чат берётся из сети, зеркало логов в IndexedDB удалено
6de7cb703 2026-08-28 Force live chat snapshots past HTTP caches
16f85b462 2026-08-28 Restore one-shot previous chat history loading

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### e91247c9c #353: #353: unify quota panel and add traces

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 9cc1feca3..5a05026f9 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -8246,16 +8246,16 @@ async function loadProfilesList() {
  * ========================================================================== */
 
 const _QL_W = 960, _QL_H = 470, _QL_ML = 54, _QL_MR = 20, _QL_MT = 18, _QL_MB = 44;
 const _QL_PW = _QL_W - _QL_ML - _QL_MR, _QL_PH = _QL_H - _QL_MT - _QL_MB;
 const _QL_REFRESH_MS = 120000;
+const _QL_LABEL_STEP = 12;
+const _QL_LABEL_TOP_PAD = 8;
 
 const _QL_PANELS = [
-    {key: 'codex', title: 'Пул Codex', sub: 'окно скользящее — 7 суток от первого использования',
-     buckets: ['codex', 'codex_spark']},
-    {key: 'claude', title: 'Пул Claude', sub: 'окно фиксированное — сброс во вторник 07:00 UTC',
-     buckets: ['anthropic']},
+    {key: 'all', title: 'Квоты пула', sub: 'одна шкала: доля пройденного окна, 0–100%',
+     buckets: ['codex', 'codex_spark', 'anthropic']},
 ];
 
 const _QL_NO_RULE = 'нет данных — сервер не прислал константы правила';
 
 let _quotaLinesData = null;
@@ -8263,10 +8263,17 @@ let _quotaLinesError = '';
 let _quotaLinesOpen = false;
 let _quotaLinesTimer = null;
 
 const _qlX = t => _QL_ML + t * _QL_PW;
 const _qlY = p => _QL_MT + (1 - p / 100) * _QL_PH;
+const _QL_LANE_MARKERS = [
+    {dx: 12, dy: -14},
+    {dx: -12, dy: -22},
+    {dx: 12, dy: 17},
+    {dx: -12, dy: 26},
+];
+const _QL_LANE_COLORS = {sol: '#f472b6', luna: '#38bdf8', spark: '#c084fc', claude: '#fb923c'};
 
 // Форма диагонали допуска между началом и концом окна. Значение В ТЕКУЩЕЙ точке
 // берётся из bucket.limit_pct сервера, а не отсюда, — иначе панель и гейт разойдутся.
 function _qlLimitAt(t, rule) {
     const start = Number(rule.tolerance_start_pp), end = Number(rule.tolerance_end_pp);
@@ -8279,14 +8286,48 @@ function _qlBucket(bucketId) {
 
 function _qlNum(value, digits = 0) {
     return Number(value).toFixed(digits);
 }
 
+function _qlTrace(bucket) {
+    const trace = bucket?.trace;
+    const points = trace && Array.isArray(trace.points) ? trace.points : [];
+    const cleaned = [];
+    for (const point of points) {
+        const util = Number(point?.utilization);
+        const progress = Number(point?.progress);
+        if (!Number.isFinite(util) || !Number.isFinite(progress)) continue;
+        cleaned.push({
+            util,
+            progress: Math.max(0, Math.min(1, progress)),
+            x: _qlX(Math.max(0, Math.min(1, progress))),
+            y: _qlY(util),
+        });
+    }
+    return cleaned;
+}
+
 function _qlTone(verdict) {
     return verdict.nodata ? 'ql-nodata' : verdict.blocked ? 'ql-verdict-blocked' : 'ql-verdict-open';
 }
 
+function _qlPlaceY(baseY, usedBands, step = _QL_LABEL_STEP) {
+    let y = Math.max(_QL_MT + _QL_LABEL_TOP_PAD, baseY);
+    for (let tries = 0; tries < 8; tries++) {
+        const top = y - 10;
+        const bottom = y + 30;
+        const collided = usedBands.some(([from, to]) => !(bottom < from || top > to));
+        if (!collided) {
+            usedBands.push([top, bottom]);
+            return y;
+        }
+        y += step;
+    }
+    usedBands.push([y - 10, y + 30]);
+    return y;
+}
+
 // Точка рисуется, только когда сервер сказал, что данные есть. utilization=0 при
 // data_available=false — это «телеметрии нет», и молчаливый ноль соврал бы «всё чисто».
 function _qlPoint(bucket) {
     if (!bucket || !bucket.data_available || !bucket.window) return null;
     const util = Number(bucket.window.utilization);
@@ -8309,23 +8350,20 @@ function _qlLanes(panel) {
     }
     return lanes;
 }
 
 function _qlChartSvg(panel, rule) {
-    const primary = _qlBucket(panel.buckets[0]);
-    const windowMinutes = Number(primary?.window?.window_minutes) || 10080;
-    const days = Math.max(1, Math.min(14, Math.round(windowMinutes / 1440)));
     const p = [];
 
     for (let pct = 0; pct <= 100; pct += 20) {
         p.push(`<line class="ql-grid" x1="${_QL_ML}" y1="${_qlY(pct)}" x2="${_QL_ML + _QL_PW}" y2="${_qlY(pct)}"/>`);
         p.push(`<text class="ql-axis" x="${_QL_ML - 10}" y="${_qlY(pct) + 4}" text-anchor="end">${pct}%</text>`);
     }
-    for (let d = 0; d <= days; d++) {
-        const t = d / days;
+    for (let d = 0; d <= 10; d++) {
+        const t = d / 10;
         p.push(`<line class="ql-grid" x1="${_qlX(t)}" y1="${_QL_MT}" x2="${_qlX(t)}" y2="${_QL_MT + _QL_PH}"/>`);
-        p.push(`<text class="ql-axis" x="${_qlX(t)}" y="${_QL_MT + _QL_PH + 19}" text-anchor="middle">${d} сут</text>`);
+        p.push(`<text class="ql-axis" x="${_qlX(t)}" y="${_QL_MT + _QL_PH + 19}" text-anchor="middle">${d * 10}%</text>`);
     }
     p.push(`<text class="ql-axis" x="${_QL_ML + _QL_PW / 2}" y="${_QL_H - 7}" text-anchor="middle">доля пройденного окна</text>`);
 
     const band = [], line = [];
     for (let i = 0; i <= 100; i++) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(t * 100)}`); }
@@ -8339,46 +8377,90 @@ function _qlChartSvg(panel, rule) {
     p.push(`<line class="ql-hard" x1="${_qlX(0)}" y1="${_qlY(hard)}" x2="${_qlX(1)}" y2="${_qlY(hard)}"/>`);
     p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">жёсткие ${_qlNum(hard)}% — стоп для всех воркеров</text>`);
     p.push(`<line class="ql-orch" x1="${_qlX(0)}" y1="${_qlY(100)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
     p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">оркестратор работает всегда — предела нет</text>`);
 
-    // Каждый пул рисуется своей точкой: Spark считается по СВОЕМУ счётчику и стоит
-    // на своей доле окна, поэтому одной линией с Sol его рисовать нельзя.
-    panel.buckets.forEach((id, index) => {
+    const byBucket = [];
+    for (const id of panel.buckets) {
         const bucket = _qlBucket(id);
+        if (!bucket) continue;
+        byBucket.push(bucket);
+    }
+    const lanes = _qlLanes(panel);
+    const traceNotices = [];
+    const traces = new Set();
+    const usedLabelBands = [];
+    // Пути строим по pool-решению (решающее окно): один пул — одна ломаная.
+    for (const bucket of byBucket) {
+        if (traces.has(bucket.bucket)) continue;
+        traces.add(bucket.bucket);
+        const point = _qlPoint(bucket);
+        const points = _qlTrace(bucket);
+        if (points.length < 2) {
+            traceNotices.push({
+                bucket: bucket.bucket,
+                label: bucket.label || bucket.bucket,
### a44feb4bb #356: #356: route usage bars to quota release status

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 5a05026f9..e1b9b0164 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -8286,10 +8286,44 @@ function _qlBucket(bucketId) {
 
 function _qlNum(value, digits = 0) {
     return Number(value).toFixed(digits);
 }
 
+function _qlDurationFromSeconds(totalSeconds) {
+    const rounded = Math.max(0, Math.round(Number(totalSeconds)));
+    if (!Number.isFinite(rounded)) return '';
+    const minutes = Math.floor((rounded % 3600) / 60);
+    const hours = Math.floor((rounded % 86400) / 3600);
+    const days = Math.floor(rounded / 86400);
+    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
+    if (hours > 0) return `${hours}h ${minutes}m`;
+    return `${minutes}m`;
+}
+
+function _qlReleaseText(lane) {
+    const status = String(lane.release_status || '').trim();
+    const seconds = Number(lane.release_in_seconds);
+    const hasSeconds = Number.isFinite(seconds);
+
+    if (status === 'opens_in') {
+        return hasSeconds ? `откроется через ${_qlDurationFromSeconds(seconds)}` : 'откроется скоро';
+    }
+    if (status === 'at_reset') {
+        return hasSeconds
+            ? `откроется при сбросе, через ${_qlDurationFromSeconds(seconds)}`
+            : 'откроется при сбросе';
+    }
+    if (status === 'no_data') {
+        return 'нет данных';
+    }
+    return 'работает';
+}
+
+function _qlLaneSummary(lane) {
+    return _qlReleaseText(lane);
+}
+
 function _qlTrace(bucket) {
     const trace = bucket?.trace;
     const points = trace && Array.isArray(trace.points) ? trace.points : [];
     const cleaned = [];
     for (const point of points) {
@@ -8507,11 +8541,11 @@ function _qlPanelHtml(panel) {
         </section>`;
     }
     const lanes = _qlLanes(panel).map(lane => {
         const nodata = !lane.bucket?.data_available;
         const state = nodata ? 'nodata' : lane.blocked ? 'blocked' : 'open';
-        const word = nodata ? 'нет данных' : lane.blocked ? (lane.gated ? 'блок' : 'блок (99%)') : 'работает';
+        const word = _qlLaneSummary(lane);
         return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : ' <i>без диагонали</i>'}</span>`;
     }).join('');
     const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
         .map(l => `<li><b>${_escHtml(l.label || l.lane)}</b> — ${_escHtml(l.reason)}</li>`).join('');
     const chart = _qlChartSvg(panel, rule);
### 24d6308d4 #197: #197: кеш последнего успешного ответа, джиттер ретраев, негативный кеш провайдера

diff --git a/app/static/js/app.js b/app/static/js/app.js
index e1b9b0164..0baa02cc2 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1166,28 +1166,40 @@ async function loadMoreLogs() {
     }
 }
 
 
 // === Models ===
+function _renderModels(data) {
+    const models = data.models || [];
+    _MODELS = models.map(m => ({ ...m, label: m.name }));
+    _modelsLoaded = true;
+    const select = $('#orch-model');
+    if (select) {
+        select.innerHTML = '';
+        for (const m of models) {
+            const opt = document.createElement('option');
+            opt.value = m.id;
+            opt.textContent = `${m.name} (${m.id})`;
+            select.appendChild(opt);
+        }
+    }
+    _updateProxyStatus(data.proxy_connected);
+}
+
 async function _loadModelsNow() {
     try {
         const data = await api('/api/models', {pollKey: 'models'});
-        const models = data.models || [];
-        _MODELS = models.map(m => ({ ...m, label: m.name }));
-        _modelsLoaded = true;
-        const select = $('#orch-model');
-        if (select) {
-            select.innerHTML = '';
-            for (const m of models) {
-                const opt = document.createElement('option');
-                opt.value = m.id;
-                opt.textContent = `${m.name} (${m.id})`;
-                select.appendChild(opt);
-            }
-        }
-        _updateProxyStatus(data.proxy_connected);
-    } catch {}
+        _renderModels(data);
+        snapshotSave('models', data);
+    } catch (e) {
+        // Каталог моделей почти статичен — снимок тут не «может пригодиться», а закрывает
+        // дыру целиком: без него пустой селектор не даёт создать оркестратора вовсе.
+        console.warn(`models: ${e.name}: ${e.message}`);
+        if (_modelsLoaded) return;
+        const snapshot = snapshotLoad('models');
+        if (snapshot) _renderModels(snapshot.data);
+    }
 }
 
 function loadModels() {
     return _pollCoalesce('models-request', _loadModelsNow);
 }
@@ -1613,54 +1625,71 @@ async function deleteOrchestrator() {
 
 // === Orchestrator Picker ===
 let orchData = [];
 const _unreadTabs = new Set();
 
+function _renderOrchestrators(allOrchs) {
+    // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
+    orchData = allOrchs.filter(o => !o.parent_name);
+    const picker = $('#orch-picker');
+    picker.innerHTML = '';
+    for (const o of orchData) {
+        const opt = document.createElement('option');
+        opt.value = o.scope;
+        opt.dataset.id = o.id;
+        opt.dataset.name = o.name;
+        opt.textContent = o.name;
+        picker.appendChild(opt);
+    }
+
+    const lastScope = localStorage.getItem('lastOrchScope');
+    const lastName = localStorage.getItem('lastOrchName');
+    const recentRaw = localStorage.getItem('recentOrchs');
+    const recent = recentRaw ? JSON.parse(recentRaw) : [];
+
+    const sorted = [...orchData].sort((a, b) => {
+        const ai = recent.indexOf(a.name);
+        const bi = recent.indexOf(b.name);
+        if (ai >= 0 && bi >= 0) return ai - bi;
+        if (ai >= 0) return -1;
+        if (bi >= 0) return 1;
+        return 0;
+    });
+
+    renderOrchTabs(sorted);
+
+    if (orchData.length > 0 && !currentScope) {
+        const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
+        if (match) {
+            selectOrchestrator(match.name, match.scope);
+        } else {
+            selectOrchestrator(sorted[0].name, sorted[0].scope);
+        }
+    }
+}
+
 async function _loadOrchestratorsNow() {
     try {
         const allOrchs = await api('/api/orchestrators', {pollKey: 'orchestrators'});
         // Данные только что получены. Без этой отметки дроссель в refreshSessions считает
         // их протухшими и через полсекунды тянет тот же список второй раз (#71).
         _orchFreshAt = Date.now();
-        // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
-        orchData = allOrchs.filter(o => !o.parent_name);
-        const picker = $('#orch-picker');
-        picker.innerHTML = '';
-        for (const o of orchData) {
-            const opt = document.createElement('option');
-            opt.value = o.scope;
-            opt.dataset.id = o.id;
-            opt.dataset.name = o.name;
-            opt.textContent = o.name;
-            picker.appendChild(opt);
-        }
-
-        const lastScope = localStorage.getItem('lastOrchScope');
-        const lastName = localStorage.getItem('lastOrchName');
-        const recentRaw = localStorage.getItem('recentOrchs');
-        const recent = recentRaw ? JSON.parse(recentRaw) : [];
-
-        const sorted = [...orchData].sort((a, b) => {
-            const ai = recent.indexOf(a.name);
-            const bi = recent.indexOf(b.name);
-            if (ai >= 0 && bi >= 0) return ai - bi;
-            if (ai >= 0) return -1;
-            if (bi >= 0) return 1;
-            return 0;
-        });
-
-        renderOrchTabs(sorted);
-
-        if (orchData.length > 0 && !currentScope) {
-            const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
-            if (match) {
-                selectOrchestrator(match.name, match.scope);
-            } else {
-                selectOrchestrator(sorted[0].name, sorted[0].scope);
-            }
### b68ace219 #202: бабл веб-поиска показывает запрос и результат

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 0baa02cc2..e2ef50f53 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -5086,14 +5086,12 @@ function addChatEntry(type, content, ts, anchor, payload) {
         if (isWebSearchCall) {
             try {
                 const d = JSON.parse(body);
                 setCodexToolTitle(header, 'Web search', '🌐');
                 header.style.color = '#38bdf8';
-                if (rawName === 'WebSearch') {
-                    div.dataset.isCodexWebSearch = '1';
-                    updateCodexWebSearchActivity(div, codexWebSearchSpec(d));
-                }
+                div.dataset.isCodexWebSearch = '1';
+                updateCodexWebSearchActivity(div, codexWebSearchSpec(d));
                 if (d.model) {
                     const badge = document.createElement('span');
                     badge.textContent = d.model;
                     badge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid #38bdf8;color:#38bdf8;opacity:0.8;vertical-align:middle;margin-left:6px';
                     header.appendChild(badge);
@@ -5721,14 +5719,20 @@ function addChatEntry(type, content, ts, anchor, payload) {
         const preview = _hasMore ? _resultLines.slice(0, _RESULT_PREVIEW).join('\n') : linked;
         const full = _hasMore ? linked : null;
 
         if (lastTool) {
             if (lastTool.dataset.isCodexWebSearch) {
-                updateCodexWebSearchActivity(lastTool, codexWebSearchSpec(content));
-                delete lastTool.dataset.lastTool;
-                addTimestamp(lastTool, ts);
-                return;
+                // Codex шлёт результатом ту же структуру с action/queries — ею обновляем шапку.
+                // Встроенный WebSearch и MCP-поиск отдают ТЕКСТ: spec=null, и его надо
+                // отрисовать обычным телом результата, а не проглотить ранним return.
+                const resultSpec = codexWebSearchSpec(content);
+                if (resultSpec) {
+                    updateCodexWebSearchActivity(lastTool, resultSpec);
+                    delete lastTool.dataset.lastTool;
+                    addTimestamp(lastTool, ts);
+                    return;
+                }
             }
             if (lastTool.dataset.isSpawnWorker) {
                 const hdr = lastTool.querySelector('.flex.items-center');
                 if (hdr) setCodexToolTitle(hdr, `${lastTool.dataset.workerName || 'Worker'} spawned`);
                 delete lastTool.dataset.lastTool;
### 5165bcc02 чат открывается на последних сообщениях и не ждёт зеркало

diff --git a/app/static/js/app.js b/app/static/js/app.js
index e2ef50f53..5579725c3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -491,12 +491,16 @@ function _restoreChatAnchor(key) {
     }
     const divider = document.createElement('div');
     divider.className = 'chat-unread-divider';
     divider.textContent = 'Непрочитанные';
     chat.insertBefore(divider, firstUnread);
-    divider.scrollIntoView({block: 'start'});
-    _chatHasNewBelow = true;
+    // Разделитель — МЕТКА для того, кто листает вверх, а не цель прыжка. Прыжок к нему
+    // открывал чат на сообщениях многодневной давности, и свежие «дорисовывались ниже»
+    // (жалоба юзера 21.08). Открываем внизу, у последнего сообщения; кнопка «вниз»
+    // при этом не нужна — ниже ничего не осталось.
+    _scrollChatToBottom();
+    _chatHasNewBelow = false;
     _syncChatJumpButton();
 }
 
 function _scheduleChatInitialSettle() {
     const key = _chatPositionKey();
@@ -518,10 +522,11 @@ function _scheduleChatInitialSettle() {
 const _sessionIds = {};  // _chatPositionKey() -> session.id, заполняется в renderAgentList и _storeSync
 const _CHAT_PAGE = 100;  // столько строк показываем при заходе — как и раньше при limit=100
 // Столько строк рисуем в ПЕРВОМ кадре; остальное — после него. Двадцать — это ровно то,
 // что раньше лежало в зеркале и давало чат за 871 мс против 1186 мс на сотне строк.
 const _CHAT_FIRST_PAINT = 20;
+const _CHAT_MIRROR_DEADLINE = 250;  // сколько ждём IndexedDB, прежде чем идти в сеть
 // Порция добора истории — И по строкам, И по байтам. Одних строк мало: замер по живой БД
 // дал на 25 строках от 5.2 до 46.6 КБ gzip в разных чатах, потому что размер сообщения
 // гуляет на три порядка. Бюджет 24 КБ content держит худшую порцию в пределах ~10 КБ по
 // проводу у всех проверенных агентов — ниже порога, на котором посредник у юзера рвёт ответ.
 const _CHAT_CHUNK = 25;
@@ -2309,12 +2314,25 @@ async function _showChatFor(name, scope) {
     $('#chat').innerHTML = '';
     chatLogs[name] = {lastId: 0, firstId: null, initialCount: 0};
     scrollAfterLoad = true;
     _chatLoading = true;
     try {
-        const sid = await _storeSessionId(scope, name);
-        let rows = sid ? await _storeRead(sid, _CHAT_PAGE) : [];
+        // Зеркало быстрее сети, но только пока оно свободно: холодная синхронизация
+        // (/api/logs/sync?after_id=0 — 2.23 с на замере 21.08) держит readwrite-транзакцию,
+        // и наши чтения стоят за ней в очереди. Замер того же дня: переключение на агента
+        // без зеркала = 3.08 с пустого чата при том, что /api/sessions/<name>/logs отвечает
+        // за 10–20 мс. Поэтому ждём зеркало ограниченно и уходим в сеть, не дожидаясь.
+        const mirror = (async () => {
+            const id = await _storeSessionId(scope, name);
+            return {id, rows: id ? await _storeRead(id, _CHAT_PAGE) : []};
+        })();
+        const hit = await Promise.race([
+            mirror,
+            new Promise((res) => setTimeout(() => res(null), _CHAT_MIRROR_DEADLINE)),
+        ]);
+        const sid = hit ? hit.id : null;
+        let rows = hit ? hit.rows : [];
         // Обрезанная строка раньше делала всю историю непригодной: пометить её было нечем,
         // и битую картинку показывать нельзя. Теперь у обрезки есть видимый маркер и кнопка
         // «загрузить целиком» (#74), а сервер режет тем же потолком, что и зеркало, — так что
         // обрезка перестала быть поводом перекачивать страницу целиком.
         const fromStore = rows.length > 0;
### 5e7163191 чат держится низа всю начальную загрузку

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 5579725c3..58afc2b67 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -535,10 +535,16 @@ const _CHAT_CHUNK = 25;
 // всей истории каждой сессии, не по последней сотне) — 14.5 КБ, сессий сверх порога ноль.
 const _CHAT_CHUNK_BYTES = 16000;
 // Страховка от бесконечного добора. Двадцать, а не двенадцать: с меньшим бюджетом порций
 // нужно больше, и на двенадцати два самых тяжёлых чата (bizdev, payroll) не добирали сотню.
 const _CHAT_MAX_CHUNKS = 20;
+// Пока идёт НАЧАЛЬНАЯ загрузка чата, низ держим безусловно. История дорисовывается
+// порциями ВВЕРХ (первый кадр 20 строк, потом добор до 100 по 25), и каждая порция
+// меняет scrollHeight; решение «остаться внизу» принималось по _chatAtBottom, а он
+// на промежуточном кадре легко отвечает «нет» — юзер видел, как сообщения сперва
+// появляются сверху, а бабли доезжают ниже (жалоба 21.08, второй заход).
+let _chatInitialLoad = false;
 
 // === Зеркало журнала в IndexedDB (#8) ===
 // Строки logs неизменяемы (в app/db.py ровно один INSERT и оптовый DELETE по возрасту,
 // ни одного UPDATE), поэтому сохранённая строка не может стать неверной — только исчезнуть.
 // Отсюда вся инвалидация сводится к трём правилам: чистим сессии, которых больше нет,
@@ -2259,11 +2265,12 @@ function _prependHistory(name, scope, rows) {
             meta.initialCount++;
         }
     } finally { _replayingHistory = false; }
     // Дорисовка уходит ВВЕРХ. Юзер внизу — держим его внизу; читает выше — компенсируем
     // прирост высоты, чтобы текст под курсором не уехал (иначе добор из #38 сам себе рывок).
-    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
+    // Начальная загрузка — всегда низ: там «выше» ещё некому читать.
+    if (wasAtBottom || _chatInitialLoad) chat.scrollTop = chat.scrollHeight;
     else chat.scrollTop = desiredTop + (chat.scrollHeight - heightBefore);
     updateLoadMoreBtn();
     return rows.length;
 }
 
@@ -2312,10 +2319,11 @@ async function _fetchHistory(name, scope) {
 async function _showChatFor(name, scope) {
     if (!name || !scope) return;
     $('#chat').innerHTML = '';
     chatLogs[name] = {lastId: 0, firstId: null, initialCount: 0};
     scrollAfterLoad = true;
+    _chatInitialLoad = true;
     _chatLoading = true;
     try {
         // Зеркало быстрее сети, но только пока оно свободно: холодная синхронизация
         // (/api/logs/sync?after_id=0 — 2.23 с на замере 21.08) держит readwrite-транзакцию,
         // и наши чтения стоят за ней в очереди. Замер того же дня: переключение на агента
@@ -2347,13 +2355,20 @@ async function _showChatFor(name, scope) {
         const head = rows.length > _CHAT_FIRST_PAINT ? rows.slice(0, -_CHAT_FIRST_PAINT) : [];
         _renderHistory(name, head.length ? rows.slice(-_CHAT_FIRST_PAINT) : rows);
         connectSSE(true);
         // Остаток страницы и добор с сервера идут строго по очереди: и то и другое
         // вставляет НАД первой строкой, а серверные строки старше остатка зеркала.
-        _afterPaint(() => {
+        _afterPaint(async () => {
             _prependHistory(name, scope, head);
-            _completeChatPage(name, scope);   // и после промаха зеркала: _fetchHistory берёт одну порцию
+            await _completeChatPage(name, scope);   // и после промаха зеркала: _fetchHistory берёт одну порцию
+            // Страница добрана — начальная фаза кончилась. Снимаем флаг только здесь:
+            // добор идёт дольше, чем таймер _scheduleChatInitialSettle, и снятие по
+            // таймеру возвращало прыжки на последних порциях.
+            if (name === selectedAgent && scope === currentScope) {
+                _chatInitialLoad = false;
+                if (_chatAtBottom()) $('#chat').scrollTop = $('#chat').scrollHeight;
+            }
         });
         return fromStore;
     } finally {
         // Обязательно снимаем даже на раннем выходе: иначе восстановительный connectSSE
         // окажется заблокирован навсегда и умерший поток никто не поднимет.
### 71532403e потолок узлов чата 500 -> 200, и обрезка только когда юзер внизу

diff --git a/app/static/js/app.js b/app/static/js/app.js
index 58afc2b67..e16d7d011 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -1,7 +1,12 @@
 // Cap DOM nodes to avoid memory growth during long agent sessions
-const MAX_CHAT_NODES = 500;
+// Потолок узлов в живой вкладке. 500 держалось «на глаз» и для чата оркестратора значит
+// ≈109 000 px: замер 21.08 — 100 сообщений его журнала это 21 861 px, а за 12 часов
+// набегает 554 строки, то есть вкладка упирается в потолок за полдня и дальше тормозит
+// на каждом кадре. 200 узлов ≈ 44 000 px при той же странице входа в 100 сообщений;
+// старшее уходит из DOM, но не из истории — оно возвращается кнопкой «загрузить ещё».
+const MAX_CHAT_NODES = 200;
 function fmtCost(v) { v = Number(v) || 0; if (v === 0) return MODEL_COST_CURRENCY + '0.00'; if (v < 0.01) return MODEL_COST_CURRENCY + v.toFixed(4); return MODEL_COST_CURRENCY + v.toFixed(2); }
 const _MODEL_COLORS = {
     'claude-opus-5[1m]': '#d8b4fe',
     'claude-sonnet-5[1m]': '#38bdf8', 'claude-haiku-4-5': '#4ade80',
     'claude-fable-5[1m]': '#fb923c', 'gpt-5.5': '#f472b6', 'gpt-5.4': '#f472b6',
@@ -222,10 +227,18 @@ let _followPinRaf = null;
 // Поднимается обработчиками ввода и означает «следующее событие scroll — от юзера».
 let _userScrolled = false;
 function _pinChatBottom(chat) {
     chat.scrollTop = chat.scrollHeight;
 }
+
+// Срезать самые старые узлы. Режем ТОЛЬКО когда юзер внизу и следует за потоком:
+// иначе кнопка «загрузить ещё» бессмысленна — добранная история исчезала бы от первого
+// же нового сообщения, и текст под курсором прыгал бы вверх на высоту срезанного.
+function _trimChatNodes(chat) {
+    if (!chat || !_chatFollow) return;
+    while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
+}
 function _keepPinnedIfFollowing() {
     if (!_chatFollow || _followPinRaf) return;
     _followPinRaf = requestAnimationFrame(() => {
         _followPinRaf = null;
         const chat = $('#chat');
@@ -4630,11 +4643,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
         }
         const line = buildCompactToolLine(type, content, ts, payload);
         const wasAtBottom = _chatAtBottom(chat);
         _insert(line);
         // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
-        while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
+        _trimChatNodes(chat);
         if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
         if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
         return;
     }
 
@@ -6769,11 +6782,11 @@ function addChatEntry(type, content, ts, anchor, payload) {
 
     addCopyBtn(div, content);
     addTimestamp(div, ts);
     const wasAtBottom = _chatAtBottom(chat);
     _insert(div);
-    while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
+    _trimChatNodes(chat);
     if (type === 'tool') _adoptOrphanResults(chat, div.dataset.toolUseId);
     if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
 }
 
 
### 3985ef548 открытие чата: 11 запросов -> 0-2, страница берётся одним запросом

diff --git a/app/static/js/app.js b/app/static/js/app.js
index e16d7d011..75940b8d3 100644
--- a/app/static/js/app.js
+++ b/app/static/js/app.js
@@ -545,13 +545,18 @@ const _CHAT_MIRROR_DEADLINE = 250;  // сколько ждём IndexedDB, пре
 const _CHAT_CHUNK = 25;
 // 16 000 Б, а не 24 000: base64 не сжимается вообще, и порция из обрезанных блобов на 24 КБ
 // сырых даёт 19 КБ по проводу — выше порога. С 16 000 худшая порция ВО ВСЕЙ БД (прогон по
 // всей истории каждой сессии, не по последней сотне) — 14.5 КБ, сессий сверх порога ноль.
 const _CHAT_CHUNK_BYTES = 16000;
-// Страховка от бесконечного добора. Двадцать, а не двенадцать: с меньшим бюджетом порций
-// нужно больше, и на двенадцати два самых тяжёлых чата (bizdev, payroll) не добирали сотню.
-const _CHAT_MAX_CHUNKS = 20;
+// Сколько ДОБОРНЫХ запросов допустимо после первого. Каждый стоит круга по сети, а у юзера
+// канал в другую страну: прежние 20 проходов по 25 строк давали 11 запросов на открытие и
+// 2.40 с при латентности 200 мс (замер 21.08). Теперь запрашиваем сразу _CHAT_PAGE, и
+// сервер отдаёт столько, сколько влезает в _CHAT_CHUNK_BYTES — на живом журнале это 35
+// строк за проход, то есть сотня набирается за три. Тяжёлый чат наберёт меньше сотни;
+// это осознанный размен: остаток доступен кнопкой «загрузить ещё», а секунды ожидания при
+// каждом открытии — нет.
+const _CHAT_REFILL_PASSES = 3;
 // Пока идёт НАЧАЛЬНАЯ загрузка чата, низ держим безусловно. История дорисовывается
 // порциями ВВЕРХ (первый кадр 20 строк, потом добор до 100 по 25), и каждая порция
 // меняет scrollHeight; решение «остаться внизу» принималось по _chatAtBottom, а он
 // на промежуточном кадре легко отвечает «нет» — юзер видел, как сообщения сперва
 // появляются сверху, а бабли доезжают ниже (жалоба 21.08, второй заход).
@@ -2221,23 +2226,30 @@ function _renderHistory(agent, rows) {
     $('#chat').scrollTop = $('#chat').scrollHeight;
     _scheduleChatInitialSettle();
     _syncChatJumpButton();
 }
 
-// Добор страницы до _CHAT_PAGE порциями по _CHAT_CHUNK и запись добранного в зеркало:
-// следующий заход к этому же агенту снова бесплатный. Порции последовательные — каждая
-// следующая опирается на firstId предыдущей. Сотню строк одним ответом не берём: это
-// 27.1 КБ, а канал юзера рвёт крупные ответы (#70, #72).
+// Добор страницы до _CHAT_PAGE и запись добранного в зеркало: следующий заход к этому же
+// агенту снова бесплатный.
+//
+// НЕДОСТАЮЩЕЕ БЕРЁТСЯ ОДНИМ ЗАПРОСОМ, а не порциями по _CHAT_CHUNK. Прежнее «сотню строк
+// одним ответом не берём: это 27.1 КБ» (#70, #72) не подтвердилось замером 21.08: сервер
+// режет каждое сообщение по max_bytes, поэтому 100 строк весят 6 063 байта после gzip
+// против 16 598 сырых у 25 — четыре порции не экономят ничего, а стоят четырёх RTT.
+// Настоящая цена была видна только на канале юзера: частичное попадание в зеркало
+// запускало цепочку из ОДИННАДЦАТИ запросов подряд, и открытие чата занимало 2.40 с при
+// латентности 200 мс. Цикл оставлен на два прохода: ответ может оказаться короче
+// запрошенного из-за бюджета байт, и тогда второй проход добирает остаток.
 // Предзагружать зеркало на все сессии вместо этого нельзя: инкрементальная синхронизация
 // (after_id > 0) tail ИГНОРИРУЕТ, дозаполнить уже заведённое зеркало она не может, а
 // холодная предзагрузка стоила 145.5 КБ по проводу ради строк, из которых рисуется ~5%.
 async function _completeChatPage(name, scope) {
     let added = 0;
-    for (let i = 0; i < _CHAT_MAX_CHUNKS; i++) {
+    for (let i = 0; i < _CHAT_REFILL_PASSES; i++) {
         const meta = chatLogs[name];
         if (!meta || !meta.firstId) return added;
-        const need = Math.min(_CHAT_PAGE - (meta.initialCount || 0), _CHAT_CHUNK);
+        const need = _CHAT_PAGE - (meta.initialCount || 0);
         if (need <= 0) return added;
         let older;
         try {
             const q = new URLSearchParams({scope, before_id: String(meta.firstId), limit: String(need),
                                            max_bytes: String(_CHAT_CHUNK_BYTES), cap: String(_STORE_CAP)});
@@ -2252,11 +2264,10 @@ async function _completeChatPage(name, scope) {
         if (!Array.isArray(older) || !older.length) return added;
         if (!_prependHistory(name, scope, older)) return added;     // юзер ушёл к другому агенту
         _storePut(older);
         added += older.length;
     }
-    console.warn(`[chat] добор истории ${name} остановлен на ${_CHAT_MAX_CHUNKS} порциях — добрано ${added} строк`);
     return added;
 }
 
 // Дорисовать старые строки НАД уже показанными. Один владелец на два случая: остаток
 // страницы из зеркала (первый кадр рисует только хвост) и добор с сервера.
@@ -2307,13 +2318,20 @@ async function _storePut(rows) {
     } catch (e) { _storeDisable('не пишется в IndexedDB', e); }
 }
 
 // Промах зеркала: тянем историю обычным маршрутом. Он отдаёт application/json, который
 // nginx жмёт, — те же 100 сообщений едут в 5 раз меньшим объёмом, чем через SSE (D1).
+//
+// СТРАНИЦА БЕРЁТСЯ ОДНИМ ЗАПРОСОМ. Раньше здесь стоял _CHAT_CHUNK (25), а остальные три
+// четверти добирал _completeChatPage — то есть открытие чата стоило ЧЕТЫРЁХ круговых
+// задержек подряд. Локально это незаметно (6 мс на порцию), а у юзера канал до сервера в
+// другой стране, и цена открытия равна 4×RTT. Замер 21.08 на живом журнале: limit=100 —
+// 22 мс и 6 063 байта после gzip, limit=25 — 16 598 байт сырых, потому что max_bytes режет
+// каждое сообщение и четыре порции почти не экономят трафик. Один запрос строго лучше.
 async function _fetchHistory(name, scope) {
     try {
-        const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: String(_CHAT_CHUNK),
+        const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: String(_CHAT_PAGE),
                                        max_bytes: String(_CHAT_CHUNK_BYTES), cap: String(_STORE_CAP)});
         const rows = await api(`/api/sessions/${encodeURIComponent(name)}/logs?${q}`);
         if (!Array.isArray(rows)) return [];
         // Обязательно в зеркало: эти строки СТАРШЕ watermark, инкремент их уже не принесёт
         // никогда. Без этой записи в зеркале осталась бы дыра ровно на самом свежем куске
@@ -2370,11 +2388,15 @@ async function _showChatFor(name, scope) {
         connectSSE(true);
         // Остаток страницы и добор с сервера идут строго по очереди: и то и другое
         // вставляет НАД первой строкой, а серверные строки старше остатка зеркала.
         _afterPaint(async () => {
             _prependHistory(name, scope, head);
-            await _completeChatPage(name, scope);   // и после промаха зеркала: _fetchHistory берёт одну порцию
+            // Добираем ТОЛЬКО когда страница действительно неполная: зеркало отдало меньше
+            // _CHAT_PAGE. После сетевого пути добирать нечего — _fetchHistory уже привёз
+            // всю страницу одним запросом, а лишний вызов стоил ещё одного круга по сети
+            // и всегда возвращал пустоту в конце журнала.
+            if (rows.length < _CHAT_PAGE) await _completeChatPage(name, scope);
             // Страница добрана — начальная фаза кончилась. Снимаем флаг только здесь:
             // добор идёт дольше, чем таймер _scheduleChatInitialSettle, и снятие по
             // таймеру возвращало прыжки на последних порциях.
             if (name === selectedAgent && scope === currentScope) {
                 _chatInitialLoad = false;