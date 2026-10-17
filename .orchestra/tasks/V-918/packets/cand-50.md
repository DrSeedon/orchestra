# Candidate cand-50

## ORIGIN commit d72bf45cad (2026-09-17): V-589: #V-589: quota-lines.js и usage.js на английском, русский перевод в словарь
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/static/js/i18n.js b/app/static/js/i18n.js
index 095857388..505a7b85c 100644
--- a/app/static/js/i18n.js
+++ b/app/static/js/i18n.js
@@ -433,16 +433,117 @@
         'Orchestra unavailable': 'Orchestra недоступна',
         'Restart failed': 'Рестарт не выполнен',
         'Orchestra restarted · data updated': 'Orchestra перезапустилась · данные обновлены',
         'Connection restored · data updated': 'Связь восстановлена · данные обновлены',
         'Restart did not happen: {reason}': 'Рестарт не состоялся: {reason}',
         'Failed to update: {errors}': 'Не удалось обновить: {errors}',
         'Shown saved:': 'Показано сохранённое:',
 
+// --- quota-lines.js, usage.js ---
+        'Pool quotas': 'Квоты пула',
+        'single scale: window progress share, 0–100%': 'одна шкала: доля пройденного окна, 0–100%',
+        'no data — server did not send rule constants': 'нет данных — сервер не прислал константы правила',
+        'opens in {duration}': 'откроется через {duration}',
+        'opens soon': 'откроется скоро',
+        'opens at reset, in {duration}': 'откроется при сбросе, через {duration}',
+        'opens at reset': 'откроется при сбросе',
+        'no data': 'нет данных',
+        'others': 'прочие',
+        'gate: no data': 'гейт: нет данных',
+        'gate MANUALLY LIFTED — returns in {min} min · ceiling: {ceiling}': 'гейт СНЯТ ВРУЧНУЮ — вернётся через {min} мин · потолок: {ceiling}',
+        'gate LIFTED — diagonal holds no lanes, only ceiling remains: {ceiling}': 'гейт СНЯТ — диагональ не держит ни одну полосу, остаётся только потолок: {ceiling}',
+        'outside gate': 'вне гейта',
+        'gate ON: {held}{tail} · ceiling: {ceiling}': 'гейт ВКЛЮЧЁН: {held}{tail} · потолок: {ceiling}',
+        'window progress share': 'доля пройденного окна',
+        'Sol threshold': 'порог Sol',
+        ' — burning pool early': ' — жжём пул рано',
+        ' — lifted': ' — снят',
+        'Claude threshold': 'порог Claude',
+        'hard {pct}% — stop for lanes without own ceiling': 'жёсткие {pct}% — стоп полос без своего потолка',
+        '{label} — hard {pct}%': '{label} — жёсткие {pct}%',
+        'orchestrator always runs — no limit': 'оркестратор работает всегда — предела нет',
+        '{label}: reset time unknown — only hard {pct}%': '{label}: срок сброса неизвестен — только жёсткие {pct}%',
+        'actual {util}% · expected {expected}%': 'факт {util}% · норма {expected}%',
+        '{head} · diagonal not applied — only hard {pct}%': '{head} · диагональ не применяется — только жёсткие {pct}%',
+        '{head} · no threshold': '{head} · порога нет',
+        '{head} · tolerance {tol} pp · threshold {thr}%': '{head} · допуск {tol} п.п. · порог {thr}%',
+        ' (telemetry stale)': ' (телеметрия устарела)',
+        '{label}: no history for this window': '{label}: истории за это окно нет',
+        'steady burn': 'равномерный расход',
+        'threshold for gated lanes': 'порог гейтящихся полос',
+        'hard {pct}%': 'жёсткие {pct}%',
+        'orchestrator — no limit': 'оркестратор — без предела',
+        'Orchestrator: <b>always runs</b>': 'Оркестратор: <b>всегда работает</b>',
+        'allowance rule': 'правило допуска',
+        'allowance rule — loading…': 'правило допуска — загрузка…',
+        'no data — pool missing from server response': 'нет данных — пул отсутствует в ответе сервера',
+        'no data — server did not send allowance lanes': 'нет данных — сервер не прислал полосы допуска',
+        'no data — no pool telemetry, gate returns unknown': 'нет данных — телеметрии пула нет, гейт отвечает unknown',
+        'no data — some lanes missing telemetry': 'нет данных — часть полос без телеметрии',
+        '{lanes} — blocked': '{lanes} — стоят',
+        '{lanes} — running': '{lanes} — работают',
+        'lift for 30 min': 'снять на 30 мин',
+        'restore gate': 'вернуть гейт',
+        'no data — {error}': 'нет данных — {error}',
+        'server did not send quota map': 'сервер не отдал карту квот',
+        'request failed': 'запрос не выполнен',
+        'Usage does not outpace linear window pace': 'Расход не опережает линейный темп окна',
+        'pace ok': 'темп ok',
+        'Local estimate of outpacing linear pace. Not a separate limit window and not an official provider timer.': 'Локальная оценка опережения линейного темпа. Это не отдельное лимитное окно и не официальный таймер провайдера.',
+        'pace +{label}': 'темп +{label}',
+        '⚡ limit!': '⚡ лимит!',
+        '⏳{label}': '⏳{label}',
+        'updating…': 'обновление…',
+        'just now': 'сейчас',
+        '{min} min ago': '{min} мин назад',
+        'update error · data from {age}': 'ошибка обновления · данные от {age}',
+        'stale': 'устарело',
+        'updated': 'обновлено',
+        'Click to refresh usage data': 'Нажмите, чтобы обновить данные о расходе',
+        'OpenRouter': 'OpenRouter',
+        'daily: {bar} <span style="color:#64748b">{used}/{limit}</span>{cd}': 'сутки: {bar} <span style="color:#64748b">{used}/{limit}</span>{cd}',
+        'minute: <span style="color:{minColor}">{minCount}/{minLimit}</span>': 'минута: <span style="color:{minColor}">{minCount}/{minLimit}</span>',
+        'Used': 'Использовано',
+        'Reset in': 'Сброс через',
+        'Reset (Krasnoyarsk)': 'Сброс (Крск)',
+        'Window progress': 'Прогресс окна',
+        '{label} window': '{label} окно',
+        'Deviation': 'Отклонение',
+        'Limit in': 'Лимит через',
+        'Limit data unavailable': 'Данные лимита недоступны',
+        'OpenRouter (free)': 'OpenRouter (бесплатный)',
+        'Data unavailable': 'Данные недоступны',
+        'Daily': 'Сутки',
+        'Minute': 'Минута',
+        'daily': 'сутки',
+        'minute': 'минута',
+        'Count source': 'Источник счёта',
+        'local': 'локальный',
+        'Yesterday ({day}): provider {provider}, local {local}, Δ {delta}': 'Вчера ({day}): провайдер {provider}, локально {local}, Δ {delta}',
+        'Local attempts yesterday: {parts}': 'Локальные попытки вчера: {parts}',
+        '💰 Cost': '💰 Стоимость',
+        '🎤 Voice': '🎤 Голос',
+        'Subscription': 'Подписка',
+        '📈 Agents: <span style="color:#cbd5e1">{count}</span>': '📈 Агенты: <span style="color:#cbd5e1">{count}</span>',
+        'Sun Mon Tue Wed Thu Fri Sat': 'Вс Пн Вт Ср Чт Пт Сб',
+        ' <i>no diagonal</i>': ' <i>без диагонали</i>',
+        'Error': 'Ошибка',
+        'no message': 'без текста',
+        '{name}: {message}': '{name}: {message}',
+        '{status} {age}': '{status} {age}',
+        'Loading previous period…': 'Загружаю предыдущий период…',
+        'History failed to load — {error}': 'История не загрузилась — {error}',
+        'No snapshots yet: chart appears after two measurements in one window': 'Снимков ещё нет: график появится после двух замеров в одном окне',
+        ' Tracking since {date}.': ' Снимки ведутся с {date}.',
+        'Not enough points: chart needs ≥2 measurements in one window.{since}': 'Мало точек: на график нужно ≥2 замера в одном окне.{since}',
+        'This provider has no history.{since}': 'Этого провайдера в истории нет.{since}',
+        'Previous period failed to load — {error}': 'Предыдущий период не загрузился — {error}',
+        'response without rows: {history}': 'ответ без rows: {history}',
+
         // --- шаблоны: dashboard.html ---
         'Model catalog — availability for dashboard and agents': 'Каталог моделей — доступность для дашборда и для агентов',
         'settings directory (empty = ~/.claude)': 'каталог настроек (пусто = ~/.claude)',
         'Delete Orchestrator': 'Удалить оркестратор',
         'and all its workers?': ' и всех его воркеров?',
         'Also delete associated TG topics': 'Также удалить связанные TG-топики',
         '📁 Change Folder': '📁 Сменить папку',
         'Orchestrator:': 'Оркестратор:',
diff --git a/app/static/js/quota-lines.js b/app/static/js/quota-lines.js
index 1958c8e69..547274348 100644
--- a/app/static/js/quota-lines.js
+++ b/app/static/js/quota-lines.js
@@ -10,21 +10,21 @@ window.QuotaPanel = (() => {
 
 const _QL_W = 960, _QL_H = 470, _QL_ML = 54, _QL_MR = 20, _QL_MT = 18, _QL_MB = 44;
 const _QL_PW = _QL_W - _QL_ML - _QL_MR, _QL_PH = _QL_H - _QL_MT - _QL_MB;
 const _QL_REFRESH_MS = 120000;
 const _QL_LABEL_STEP = 12;
 const _QL_LABEL_TOP_PAD = 8;
 
 const _QL_PANELS = [
-    {key: 'all', title: 'Квоты пула', sub: 'одна шкала: доля пройденного окна, 0–100%',
+    {key: 'all', title: T('Pool quotas'), sub: T('single scale: window progress share, 0–100%'),
      buckets: ['codex', 'codex_spark', 'anthropic']},
 ];
 
-const _QL_NO_RULE = 'нет данных — сервер не прислал константы правила';
+const _QL_NO_RULE = T('no data — server did not send rule constants');
 
 let _quotaLinesData = null;
 let _quotaLinesError = '';
 let _quotaLinesOpen = false;
 let _quotaLinesTimer = null;
 
 const _qlX = t => _QL_ML + t * _QL_PW;
 const _qlY = p => _QL_MT + (1 - p / 100) * _QL_PH;
@@ -77,27 +77,27 @@ function _qlDurationFromSeconds(totalSeconds) {
 }
 
 function _qlReleaseText(lane) {
     const status = String(lane.release_status || '').trim();
     const seconds = Number(lane.release_in_seconds);
     const hasSeconds = Number.isFinite(seconds);
 
     if (status === 'opens_in') {
-        return hasSeconds ? `откроется через ${_qlDurationFromSeconds(seconds)}` : 'откроется скоро';
+        return hasSeconds ? T('opens in {duration}', {duration: _qlDurationFromSeconds(seconds)}) : T('opens soon');
     }
     if (status === 'at_reset') {
         return hasSeconds
-            ? `откроется при сбросе, через ${_qlDurationFromSeconds(seconds)}`
-            : 'откроется при сбросе';
+            ? T('opens at reset, in {duration}', {duration: _qlDurationFromSeconds(seconds)})
+            : T('opens at reset');
     }
     if (status === 'no_data') {
-        return 'нет данных';
+        return T('no data');
     }
-    return 'работает';
+    return T('running');
 }
 
 function _qlLaneSummary(lane) {
     return _qlReleaseText(lane);
 }
 
 function _qlAllLanes() {
     const lanes = [];
@@ -107,60 +107,69 @@ function _qlAllLanes() {
     return lanes;
 }
 
 function _qlLaneLabel(laneId) {
     const found = _qlAllLanes().find(lane => lane.lane === laneId);
     return found ? (found.label || laneId) : laneId;
 }
 
-// Потолки жёсткого стопа словами: у Sol свой (95%), у остальных общий. Подпись
-// обязана совпадать с линиями `ql-hard` на графике — обе берут одни и те же числа.
+// Hard-stop ceilings in words: Sol has its own (95%), others share one. Label
+// must match the `ql-hard` lines on the chart — both use the same numbers.
 function _qlCeilingText(rule) {
     const own = Object.entries(rule.lane_hard_stop_pct || {})
         .filter(([, pct]) => Number.isFinite(Number(pct)))
         .sort(([a], [b]) => a.localeCompare(b))
         .map(([lane, pct]) => `${_qlLaneLabel(lane)} ${_qlNum(pct)}%`);
     const common = `${_qlNum(rule.hard_stop_pct)}%`;
-    return own.length ? `${own.join(', ')}, прочие ${common}` : common;
+    return own.length ? `${own.join(', ')}, ${T('others')} ${common}` : common;
 }
 
-// Состояние гейта — первое, что должно читаться с панели (#V-547). Раньше снятая со
-// ВСЕХ полос диагональ отличалась от работающего правила только курсивной припиской
-// у бейджа, и по панели два разных режима выглядели одинаково.
-// Источник — `rule.gated_lanes` сервера: панель не решает, кого гейтить.
+// Gate state — first thing readable from the panel (#V-547). Previously the
+// diagonal lifted from ALL lanes differed from a working rule only by an italic
+// badge note, so two different modes looked identical on the panel.
+// Source is server's `rule.gated_lanes`: panel doesn't decide who gets gated.
 function _qlGateState() {
     const rule = _quotaLinesData?.rule;
-    // Пока связь потеряна, вердикт панели уже «—»: печатать рядом уверенное
-    // «гейт включён» по прошлому ответу значит выдать устаревшее за текущее.
+    // While connection is lost, panel verdict is already "—": printing a confident
+    // "gate enabled" from a stale response would show outdated as current.
     if (Connection.ownsErrors() || !rule || !Array.isArray(rule.gated_lanes)) {
-        return {state: 'nodata', text: 'гейт: нет данных'};
+        return {state: 'nodata', text: T('gate: no data')};
     }
     const ceilings = _qlCeilingText(rule);
-    // Снятие рукой владельца (#V-578) показывается ОТДЕЛЬНО от «правила такие»:
-    // иначе временное снятие снова растянется на трое суток незамеченным.
+    // Manual lift by owner (#V-578) shown SEPARATELY from "rules are such":
+    // otherwise temporary lift would silently stretch for three days unnoticed.
     const left = Number(rule.override_seconds_left) || 0;
     if (left > 0) {
         return {
             state: 'override',
-            text: `гейт СНЯТ ВРУЧНУЮ — вернётся через ${Math.ceil(left / 60)} мин · потолок: ${ceilings}`,
+            text: T('gate MANUALLY LIFTED — returns in {min} min · ceiling: {ceiling}', {
+                min: Math.ceil(left / 60),
+                ceiling: ceilings,
+            }),
         };
     }
     if (!rule.gated_lanes.length) {
         return {
             state: 'off',
-            text: `гейт СНЯТ — диагональ не держит ни одну полосу, остаётся только потолок: ${ceilings}`,
+            text: T('gate LIFTED — diagonal holds no lanes, only ceiling remains: {ceiling}', {
+                ceiling: ceilings,
+            }),
         };
     }
     const held = rule.gated_lanes.map(_qlLaneLabel);
     const free = _qlAllLanes()
         .filter(lane => !rule.gated_lanes.includes(lane.lane))
         .map(lane => lane.label || lane.lane);
-    const tail = free.length ? ` · вне гейта: ${free.join(', ')}` : '';
-    return {state: 'on', text: `гейт ВКЛЮЧЁН: ${held.join(', ')}${tail} · потолок: ${ceilings}`};
+    const tail = free.length ? ` · ${T('outside gate')}: ${free.join(', ')}` : '';
+    return {state: 'on', text: T('gate ON: {held}{tail} · ceiling: {ceiling}', {
+        held: held.join(', '),
+        tail,
+        ceiling: ceilings,
+    })};
 }
 
 function _qlTrace(bucket) {
     const trace = bucket?.trace;
     const points = trace && Array.isArray(trace.points) ? trace.points : [];
     const cleaned = [];
     for (const point of points) {
         const util = Number(point?.utilization);
@@ -227,53 +236,54 @@ function _qlChartSvg(panel, rule) {
         p.push(`<line class="ql-grid" x1="${_QL_ML}" y1="${_qlY(pct)}" x2="${_QL_ML + _QL_PW}" y2="${_qlY(pct)}"/>`);
         p.push(`<text class="ql-axis" x="${_QL_ML - 10}" y="${_qlY(pct) + 4}" text-anchor="end">${pct}%</text>`);
     }
     for (let d = 0; d <= 10; d++) {
         const t = d / 10;
         p.push(`<line class="ql-grid" x1="${_qlX(t)}" y1="${_QL_MT}" x2="${_qlX(t)}" y2="${_QL_MT + _QL_PH}"/>`);
         p.push(`<text class="ql-axis" x="${_qlX(t)}" y="${_QL_MT + _QL_PH + 19}" text-anchor="middle">${d * 10}%</text>`);
     }
-    p.push(`<text class="ql-axis" x="${_QL_ML + _QL_PW / 2}" y="${_QL_H - 7}" text-anchor="middle">доля пройденного окна</text>`);
+    p.push(`<text class="ql-axis" x="${_QL_ML + _QL_PW / 2}" y="${_QL_H - 7}" text-anchor="middle">${T('window progress share')}</text>`);
 
-    // Порогов теперь ДВА, потому что Sol идёт по кривой, а Claude по прямой: одна общая
-    // ломаная показывала бы половине воркеров чужой предел. Полосу заливки строим по
-    // прямой — она нижняя из двух и означает «здесь не блокируют никого».
+    // Two thresholds now: Sol follows a curve, Claude a straight line. One shared
+    // polyline would show half the workers a foreign limit. Fill band uses the
+    // straight line — it's the lower one and means "no blocking here".
     const band = [], lineClaude = [], lineSol = [];
     for (let i = 0; i <= 100; i++) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(t * 100)}`); }
     for (let i = 100; i >= 0; i--) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule, 'claude'))}`); }
     for (let i = 0; i <= 100; i++) { const t = i / 100; lineClaude.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule, 'claude'))}`); }
     for (let i = 0; i <= 100; i++) { const t = i / 100; lineSol.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule, 'sol'))}`); }
     p.push(`<polygon class="ql-band" points="${band.join(' ')}"/>`);
     p.push(`<line class="ql-diag" x1="${_qlX(0)}" y1="${_qlY(0)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
-    // Снятая с полосы диагональ рисуется призраком: сплошная линия означала бы порог,
-    // по которому кого-то останавливают, а её на этой полосе сейчас не применяют.
+    // Lifted diagonal drawn as ghost: solid line would imply a threshold that
+    // blocks someone, but on this lane it's not applied right now.
     const gatedLanes = Array.isArray(rule.gated_lanes) ? rule.gated_lanes : [];
     const _ghost = lane => gatedLanes.includes(lane) ? '' : ' ql-gated-off';
-    const _lifted = lane => gatedLanes.includes(lane) ? '' : ' — снят';
     p.push(`<polyline class="ql-gated${_ghost('claude')}" data-ql-threshold="claude" points="${lineClaude.join(' ')}"/>`);
     if ((rule.curved_lanes || []).includes('sol')) {
         p.push(`<polyline class="ql-gated ql-gated-sol${_ghost('sol')}" data-ql-threshold="sol" points="${lineSol.join(' ')}"/>`);
-        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.30)}" y="${_qlY(_qlLimitAt(0.30, rule, 'sol')) - 9}" fill="#f472b6">порог Sol${gatedLanes.includes('sol') ? ' — жжём пул рано' : _lifted('sol')}</text>`);
-        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.62)}" y="${_qlY(_qlLimitAt(0.62, rule, 'claude')) + 17}" fill="#fb923c">порог Claude${_lifted('claude')}</text>`);
+        const solSuffix = gatedLanes.includes('sol') ? T(' — burning pool early') : T(' — lifted');
+        const claudeSuffix = gatedLanes.includes('claude') ? '' : T(' — lifted');
+        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.30)}" y="${_qlY(_qlLimitAt(0.30, rule, 'sol')) - 9}" fill="#f472b6">${T('Sol threshold')}${solSuffix}</text>`);
+        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.62)}" y="${_qlY(_qlLimitAt(0.62, rule, 'claude')) + 17}" fill="#fb923c">${T('Claude threshold')}${claudeSuffix}</text>`);
     }
 
     const hard = Number(rule.hard_stop_pct);
     p.push(`<line class="ql-hard" x1="${_qlX(0)}" y1="${_qlY(hard)}" x2="${_qlX(1)}" y2="${_qlY(hard)}"/>`);
-    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">жёсткие ${_qlNum(hard)}% — стоп полос без своего потолка</text>`);
-    // Своя линия у полосы с более низким потолком: одна общая соврала бы, что дорогая
-    // полоса работает до последнего процента пула.
+    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">${T('hard {pct}% — stop for lanes without own ceiling', {pct: _qlNum(hard)})}</text>`);
+    // Lane-specific line for lane with lower ceiling: one common line would lie
+    // that the expensive lane runs to the last pool percent.
     for (const lane of _qlLanes(panel)) {
         const stop = _qlHardStop(rule, lane.lane);
         if (!(stop < hard)) continue;
         p.push(`<line class="ql-hard" data-ql-hard-lane="${_escHtml(lane.lane)}" x1="${_qlX(0)}" y1="${_qlY(stop)}" x2="${_qlX(1)}" y2="${_qlY(stop)}"/>`);
-        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${_escHtml(lane.label || lane.lane)} — жёсткие ${_qlNum(stop)}%</text>`);
+        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${T('{label} — hard {pct}%', {label: _escHtml(lane.label || lane.lane), pct: _qlNum(stop)})}</text>`);
     }
     p.push(`<line class="ql-orch" x1="${_qlX(0)}" y1="${_qlY(100)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
-    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">оркестратор работает всегда — предела нет</text>`);
+    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">${T('orchestrator always runs — no limit')}</text>`);
 
     const byBucket = [];
     for (const id of panel.buckets) {
         const bucket = _qlBucket(id);
         if (!bucket) continue;
         byBucket.push(bucket);
     }
     const lanes = _qlLanes(panel);
@@ -306,17 +316,17 @@ function _qlChartSvg(panel, rule) {
 
     for (let i = 0; i < lanes.length; i++) {
         const lane = lanes[i];
         const bucket = lane.bucket;
         const point = _qlPoint(bucket);
         if (!point) continue;
         if (point.progress === null) {
             if (i === 0) {
-                p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(point.util) - 8}" fill="#e2e8f0">${_escHtml(bucket.label || bucket.bucket)}: срок сброса неизвестен — только жёсткие ${_qlNum(_qlHardStop(rule, lane.lane))}%</text>`);
+                p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(point.util) - 8}" fill="#e2e8f0">${T('{label}: reset time unknown — only hard {pct}%', {label: _escHtml(bucket.label || bucket.bucket), pct: _qlNum(_qlHardStop(rule, lane.lane))})}</text>`);
             }
             continue;
         }
         const x = _qlX(point.progress), y = _qlY(point.util);
         p.push(`<line class="ql-cursor" x1="${x}" y1="${_QL_MT}" x2="${x}" y2="${_QL_MT + _QL_PH}"/>`);
         const offset = _QL_LANE_MARKERS[i] || _QL_LANE_MARKERS[0];
         const right = point.progress > 0.6;
         const dx = right ? -Math.abs(offset.dx) : offset.dx;
@@ -327,67 +337,67 @@ function _qlChartSvg(panel, rule) {
         const anchor = right ? 'end' : 'start';
         const hardY = _qlY(hard);
         const baseY = _qlY(point.util + 0);
         const rawLabelY = y + dy;
         const avoidHardY = Math.abs(baseY - hardY) < 8 || Math.abs(rawLabelY - hardY) < 28;
         const stackedLabelY = _qlPlaceY(avoidHardY ? hardY + 22 : rawLabelY, usedLabelBands);
         const stackedDetailY = _qlPlaceY(stackedLabelY + 15, usedLabelBands);
         p.push(`<circle data-ql-point="${_escHtml(lane.lane)}" class="${markerClass}" cx="${x}" cy="${y}" r="5.5" fill="none" stroke="${color}" stroke-width="2.5"/>`);
-        // Порог — свойство ПОЛОСЫ, а не бакета: Sol идёт по кривой, Claude по прямой, а
-        // Luna и Spark не гейтятся вовсе. Печатать бакетную прямую рядом с кривой полосой
-        // значит показать юзеру не тот предел, по которому его воркеров блокируют.
+        // Threshold is a LANE property, not bucket: Sol follows curve, Claude straight,
+        // Luna and Spark not gated at all. Printing bucket straight next to lane curve
+        // would show user the wrong limit their workers get blocked by.
         const laneLimit = Number.isFinite(lane.limit_pct) ? Number(lane.limit_pct) : null;
-        const head = `факт ${_qlNum(point.util)}% · норма ${_qlNum(point.progress * 100)}%`;
+        const head = T('actual {util}% · expected {expected}%', {util: _qlNum(point.util), expected: _qlNum(point.progress * 100)});
         const detail = !lane.gated
-            ? `${head} · диагональ не применяется — только жёсткие ${_qlNum(_qlHardStop(rule, lane.lane))}%`
+            ? T('{head} · diagonal not applied — only hard {pct}%', {head, pct: _qlNum(_qlHardStop(rule, lane.lane))})
             : laneLimit === null
-            ? `${head} · порога нет`
-            : `${head} · допуск ${_qlNum(point.tolerance, 1)} п.п. · порог ${_qlNum(laneLimit, 1)}%`;
-        p.push(`<text class="ql-halo ql-point-label" data-ql-label="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedLabelY}" text-anchor="${anchor}" fill="${color}">${label}${point.fresh ? '' : ' (телеметрия устарела)'}</text>`);
+            ? T('{head} · no threshold', {head})
+            : T('{head} · tolerance {tol} pp · threshold {thr}%', {head, tol: _qlNum(point.tolerance, 1), thr: _qlNum(laneLimit, 1)});
+        p.push(`<text class="ql-halo ql-point-label" data-ql-label="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedLabelY}" text-anchor="${anchor}" fill="${color}">${label}${point.fresh ? '' : T(' (telemetry stale)')}</text>`);
         p.push(`<text class="ql-axis ql-halo" data-ql-detail="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedDetailY}" text-anchor="${anchor}">${detail}</text>`);
     }
 
     return {
         svg: `<svg class="ql-chart" data-ql-chart="${_escHtml(panel.key)}" viewBox="0 0 ${_QL_W} ${_QL_H}" preserveAspectRatio="xMidYMid meet">${p.join('')}</svg>`,
         traceNotices,
     };
 }
 
-// ЕДИНСТВЕННЫЙ владелец вердикта: и сводка в свёрнутой строке, и тело панели
-// печатают текст ОТСЮДА. Разойтись по смыслу они не могут по построению — раньше
-// у сводки была своя ветка, и на ответе без блока `rule` она рисовала «работают»,
-// пока тело честно говорило «нет данных».
-// Подпись обязана прямо говорить, кто работает, а кто стоит, — и не выдумывать
-// «работает», когда сервер сказал data_available=false.
+// SINGLE verdict owner: both collapsed summary and panel body print text
+// FROM HERE. They cannot diverge by construction — previously summary had
+// its own branch and on response without `rule` block it drew "running"
+// while body honestly said "no data".
+// Label must directly state who runs and who stands — and not invent
+// "running" when server said data_available=false.
 function _qlVerdict(panel) {
     if (Connection.ownsErrors()) return {text: '—', nodata: true};
     if (_quotaLinesError) return {text: _quotaLinesError, nodata: true};
-    if (!_quotaLinesData) return {text: 'правило допуска — загрузка…', nodata: true};
-    // Без констант правила неизвестно само правило: вердикт не считается ни для
-    // кого, включая полосы, у которых сервер прислал готовый `blocked`.
+    if (!_quotaLinesData) return {text: T('allowance rule — loading…'), nodata: true};
+    // Without rule constants the rule itself is unknown: verdict not computed
+    // for anyone, including lanes where server sent ready `blocked`.
     if (!_quotaLinesData.rule) return {text: _QL_NO_RULE, nodata: true};
     if (!panel.buckets.map(_qlBucket).filter(Boolean).length) {
-        return {text: 'нет данных — пул отсутствует в ответе сервера', nodata: true};
+        return {text: T('no data — pool missing from server response'), nodata: true};
     }
     const lanes = _qlLanes(panel);
     const known = lanes.filter(l => l.bucket?.data_available
         && l.bucket.fresh !== false
         && l.release_status !== 'no_data');
-    if (!lanes.length) return {text: 'нет данных — сервер не прислал полосы допуска', nodata: true};
-    if (!known.length) return {text: 'нет данных — телеметрии пула нет, гейт отвечает unknown', nodata: true};
+    if (!lanes.length) return {text: T('no data — server did not send allowance lanes'), nodata: true};
+    if (!known.length) return {text: T('no data — no pool telemetry, gate returns unknown'), nodata: true};
     const partial = known.length < lanes.length;
     if (partial) {
-        return {text: 'нет данных — часть полос без телеметрии', nodata: true, blocked: false};
+        return {text: T('no data — some lanes missing telemetry'), nodata: true, blocked: false};
     }
     const blocked = known.filter(l => l.blocked).map(l => l.label || l.lane);
     const open = known.filter(l => !l.blocked).map(l => l.label || l.lane);
     const parts = [];
-    if (blocked.length) parts.push(`${blocked.join(', ')} — стоят`);
-    if (open.length) parts.push(`${open.join(', ')} — работают`);
+    if (blocked.length) parts.push(T('{lanes} — blocked', {lanes: blocked.join(', ')}));
+    if (open.length) parts.push(T('{lanes} — running', {lanes: open.join(', ')}));
     return {
         text: parts.join(' · '),
         nodata: false,
         blocked: blocked.length > 0,
     };
 }
 
 function _qlPanelHtml(panel) {
@@ -401,42 +411,42 @@ function _qlPanelHtml(panel) {
         </section>`;
     }
     const lanes = _qlLanes(panel).map(lane => {
         const nodata = !lane.bucket?.data_available
             || lane.bucket.fresh === false
             || lane.release_status === 'no_data';
         const state = nodata ? 'nodata' : lane.blocked ? 'blocked' : 'open';
         const word = _qlLaneSummary(lane);
-        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : ' <i>без диагонали</i>'}</span>`;
+        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : T(' <i>no diagonal</i>')}</span>`;
     }).join('');
     const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
         .map(l => `<li><b>${_escHtml(l.label || l.lane)}</b> — ${_escHtml(l.reason)}</li>`).join('');
     const chart = _qlChartSvg(panel, rule);
     const traceNotices = (chart.traceNotices || [])
-        .map(item => `<div class="ql-trace-msg" data-ql-trace-msg="${_escHtml(item.bucket)}">${_escHtml(item.label)}: истории за это окно нет</div>`)
+        .map(item => `<div class="ql-trace-msg" data-ql-trace-msg="${_escHtml(item.bucket)}">${T('{label}: no history for this window', {label: _escHtml(item.label)})}</div>`)
         .join('');
     return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
         <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
         ${chart.svg}
         <div class="ql-legend">
-            <span><i style="background:#8595ab"></i>равномерный расход</span>
-            <span><i style="background:#f472b6"></i>порог гейтящихся полос</span>
-            <span><i style="background:#fb923c"></i>жёсткие ${_qlNum(rule.hard_stop_pct)}%</span>
-            <span><i style="background:#818cf8"></i>оркестратор — без предела</span>
+            <span><i style="background:#8595ab"></i>${T('steady burn')}</span>
+            <span><i style="background:#f472b6"></i>${T('threshold for gated lanes')}</span>
+            <span><i style="background:#fb923c"></i>${T('hard {pct}%', {pct: _qlNum(rule.hard_stop_pct)})}</span>
+            <span><i style="background:#818cf8"></i>${T('orchestrator — no limit')}</span>
         </div>
         ${traceNotices ? `<div class="ql-trace-notices">${traceNotices}</div>` : ''}
         <p class="ql-verdict ${_qlTone(verdict)}" data-ql-verdict>${_escHtml(verdict.text)}</p>
-        <div class="ql-badges">${lanes}<span class="ql-badge ql-badge-always" data-ql-lane="orchestrator">Оркестратор: <b>всегда работает</b></span></div>
+        <div class="ql-badges">${lanes}<span class="ql-badge ql-badge-always" data-ql-lane="orchestrator">${T('Orchestrator: <b>always runs</b>')}</span></div>
         ${reasons ? `<ul class="ql-reasons">${reasons}</ul>` : ''}
     </section>`;
 }
 
-// Сводка — те же вердикты, только короче. Общий отказ (ошибка, загрузка, нет
-// правила) даёт обоим пулам ОДИН текст: печатать его дважды нечего.
+// Summary — same verdicts, only shorter. Common failure (error, loading, no
+// rule) gives both pools ONE text: no point printing it twice.
 function _qlSummary() {
     const items = _QL_PANELS.map(panel => ({panel, verdict: _qlVerdict(panel)}));
     if (items.every(i => i.verdict.text === items[0].verdict.text)) {
         const verdict = items[0].verdict;
         return `<span class="ql-sum-item" data-ql-sum><span class="${_qlTone(verdict)}">${_escHtml(verdict.text)}</span></span>`;
     }
     return items.map(({panel, verdict}) =>
         `<span class="ql-sum-item" data-ql-sum><b>${_escHtml(panel.title)}:</b> <span class="${_qlTone(verdict)}">${_escHtml(verdict.text)}</span></span>`
@@ -444,23 +454,23 @@ function _qlSummary() {
 }
 
 function renderQuotaLines() {
     const root = document.getElementById('quota-lines');
     if (!root) return;
     const body = _QL_PANELS.map(_qlPanelHtml).join('');
     const gate = _qlGateState();
     const overrideOn = gate.state === 'override';
-    // Кнопка есть всегда, кроме потери связи: нажимать её вслепую, не зная состояния
-    // гейта, значит снимать правило наугад.
+    // Button always present except on connection loss: pressing it blindly,
+    // not knowing gate state, means lifting rule at random.
     const button = gate.state === 'nodata' ? '' :
-        `<button type="button" id="quota-gate-override" class="ql-gate-btn">${overrideOn ? 'вернуть гейт' : 'снять на 30 мин'}</button>`;
+        `<button type="button" id="quota-gate-override" class="ql-gate-btn">${overrideOn ? T('restore gate') : T('lift for 30 min')}</button>`;
     root.innerHTML = `
         <div class="ql-bar">
-            <button type="button" id="quota-lines-toggle" aria-expanded="${_quotaLinesOpen}">${_quotaLinesOpen ? '▾' : '▸'} правило допуска</button>
+            <button type="button" id="quota-lines-toggle" aria-expanded="${_quotaLinesOpen}">${_quotaLinesOpen ? '▾' : '▸'} ${T('allowance rule')}</button>
             <span class="ql-gate ql-gate-${gate.state}" data-ql-gate="${gate.state}">${_escHtml(gate.text)}</span>
             ${button}
             <div class="ql-sum">${_qlSummary()}</div>
         </div>
         <div class="ql-body" ${_quotaLinesOpen ? '' : 'hidden'}>${body}</div>`;
     root.querySelector('#quota-lines-toggle').onclick = () => {
         _quotaLinesOpen = !_quotaLinesOpen;
         renderQuotaLines();
@@ -471,17 +481,17 @@ function renderQuotaLines() {
             overrideButton.disabled = true;
             try {
                 await api('/api/usage/quota-override', {
                     method: 'POST',
                     headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify({minutes: overrideOn ? 0 : 30}),
                 });
             } finally {
-                // Состояние перерисовывается из ответа сервера, а не из нашего намерения.
+                // State redraws from server response, not from our intent.
                 _quotaMapData = null;
                 await fetchQuotaLines();
             }
         };
     }
 }
 
 async function fetchQuotaLines() {
@@ -495,24 +505,24 @@ async function fetchQuotaLines() {
             if (!_quotaMapData) throw new Error('quota-map request failed');
             dataRaw = _quotaMapData;
         } else {
             dataRaw = await _fetchQuotaMapShared();
         }
         const data = typeof dataRaw === 'string' ? JSON.parse(dataRaw) : dataRaw;
         if (data && data.data_available === false) {
             _quotaLinesData = null;
-            _quotaLinesError = `нет данных — ${data.error || 'сервер не отдал карту квот'}`;
+            _quotaLinesError = T('no data — {error}', {error: data.error || T('server did not send quota map')});
         } else {
             _quotaLinesData = data;
             _quotaLinesError = '';
         }
     } catch (e) {
         _quotaLinesData = null;
-        _quotaLinesError = `нет данных — ${e && e.message ? e.message : 'запрос не выполнен'}`;
+        _quotaLinesError = T('no data — {error}', {error: e && e.message ? e.message : T('request failed')});
     }
     renderQuotaLines();
 }
 
 function initQuotaLines() {
     const bar = document.getElementById('usage-bar');
     if (!bar || document.getElementById('quota-lines')) return;
     const root = document.createElement('div');
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 6c4cae960..2df5950d3 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -1,17 +1,17 @@
 /* usage.js — usage bar rendering, sparklines, countdown. Loaded before app.js. */
 
 let _usageData = null;
 let _quotaMapData = null;
 let _usageError = false;
 let _usageCountdownInterval = null;
 
 function _usageNoDataLabel() {
-    return Connection.ownsErrors() ? '—' : 'нет данных';
+    return Connection.ownsErrors() ? '—' : T('no data');
 }
 let _usageFetchPromise = null;
 let _usageLastSuccessAt = 0;
 let _usageLastFetchStartedAt = 0;
 const _USAGE_REFRESH_INTERVAL_MS = 120000;
 const _USAGE_CLICK_DEBOUNCE_MS = 1000;
 
 // Color encodes pace vs. ideal burn rate: green = under budget, red = over,
@@ -66,24 +66,24 @@ function _resetPctText(pct) {
 // Computes how long to wait (or "ok") based on pace vs. ideal linear burn.
 // cooldownMin = how many minutes to wait at 0% usage to get back on pace.
 function _paceIndicator(currentPct, isoStr, windowMs) {
     if (!isoStr) return '';
     const remainMs = Math.max(0, new Date(isoStr) - Date.now());
     const elapsedMs = windowMs - remainMs;
     const idealPct = (elapsedMs / windowMs) * 100;
     const delta = currentPct - idealPct;
-    if (delta <= 5) return '<span style="color:#22c55e" title="Расход не опережает линейный темп окна">темп ok</span>';
+    if (delta <= 5) return `<span style="color:#22c55e" title="${T('Usage does not outpace linear window pace')}">${T('pace ok')}</span>`;
     const cooldownMin = Math.round(delta * windowMs / 100 / 60000);
     const color = delta <= 20 ? '#eab308' : '#ef4444';
     let label;
     if (cooldownMin < 60) label = `${cooldownMin}m`;
     else if (cooldownMin < 1440) label = `${Math.floor(cooldownMin/60)}h ${cooldownMin%60}m`;
     else label = `${Math.floor(cooldownMin/1440)}d ${Math.floor((cooldownMin%1440)/60)}h ${cooldownMin%60}m`;
-    return `<span style="color:${color}" title="Локальная оценка опережения линейного темпа. Это не отдельное лимитное окно и не официальный таймер провайдера.">темп +${label}</span>`;
+    return `<span style="color:${color}" title="${T('Local estimate of outpacing linear pace. Not a separate limit window and not an official provider timer.')}">${T('pace +{label}', {label})}</span>`;
 }
 
 function _releaseDurationFromSeconds(totalSeconds) {
     const rounded = Math.max(0, Math.round(Number(totalSeconds)));
     if (!Number.isFinite(rounded)) return '';
     if (rounded < 60) return `${rounded}m`;
     const minutes = Math.floor((rounded % 3600) / 60);
     const hours = Math.floor((rounded % 86400) / 3600);
@@ -148,25 +148,25 @@ function _quotaMapLaneRelease(windowData, bucketId = null) {
     return laneRelease(bucket);
 }
 
 function _quotaMapLaneStatusText(windowData, bucketId = null) {
     const {status, release_in_seconds} = _quotaMapLaneRelease(windowData, bucketId);
     const seconds = Number(release_in_seconds);
     const hasSeconds = Number.isFinite(seconds);
     if (status === 'opens_in') {
-        return hasSeconds ? `откроется через ${_releaseDurationFromSeconds(seconds)}` : 'откроется скоро';
+        return hasSeconds ? T('opens in {duration}', {duration: _releaseDurationFromSeconds(seconds)}) : T('opens soon');
     }
     if (status === 'at_reset') {
-        return hasSeconds ? `откроется при сбросе, через ${_releaseDurationFromSeconds(seconds)}` : 'откроется при сбросе';
+        return hasSeconds ? T('opens at reset, in {duration}', {duration: _releaseDurationFromSeconds(seconds)}) : T('opens at reset');
     }
     if (status === 'no_data') {
-        return Connection.ownsErrors() ? '' : 'нет данных';
+        return Connection.ownsErrors() ? '' : T('no data');
     }
-    return 'работает';
+    return T('running');
 }
 
 function _quotaMapLaneHeadroomText(windowData, bucketId = null) {
     if (!_quotaMapData || !Array.isArray(_quotaMapData.buckets) || !windowData) return '';
     const bucket = _quotaMapData.buckets.find(item =>
         (!bucketId || item.bucket === bucketId)
         && item.data_available
         && item.fresh !== false
@@ -193,25 +193,25 @@ function _quotaMapLaneHeadroomText(windowData, bucketId = null) {
 
 function _etaToLimit(currentPct, isoStr, windowMs) {
     if (!isoStr || currentPct <= 0) return '';
     const remainMs = Math.max(0, new Date(isoStr) - Date.now());
     const elapsedMs = windowMs - remainMs;
     if (elapsedMs <= 0) return '';
     const rate = currentPct / elapsedMs;
     const pctLeft = 100 - currentPct;
-    if (pctLeft <= 0) return '<span style="color:#ef4444">⚡ лимит!</span>';
+    if (pctLeft <= 0) return `<span style="color:#ef4444">${T('⚡ limit!')}</span>`;
     const etaMs = pctLeft / rate;
     const etaMin = Math.round(etaMs / 60000);
     const color = etaMin < 30 ? '#ef4444' : etaMin < 120 ? '#eab308' : '#22c55e';
     let label;
     if (etaMin < 60) label = `${etaMin}m`;
     else if (etaMin < 1440) label = `${Math.floor(etaMin/60)}h ${etaMin%60}m`;
     else label = `${Math.floor(etaMin/1440)}d ${Math.floor((etaMin%1440)/60)}h`;
-    return `<span style="color:${color}">⏳${label}</span>`;
+    return `<span style="color:${color}">${T('⏳{label}', {label})}</span>`;
 }
 
 function _miniBar(pct, color) {
     return `<span style="display:inline-flex;align-items:center;gap:4px"><span style="position:relative;display:inline-block;width:80px;height:6px;border-radius:3px;background:rgba(51,65,85,0.5);overflow:hidden;vertical-align:middle"><span style="display:block;width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${color}"></span></span><span style="color:#e2e8f0;font-weight:600">${pct}%</span></span>`;
 }
 
 function _usageProviderAccent(providerId) {
     const meta = _PROVIDER_META[providerId] || {};
@@ -228,26 +228,26 @@ function _usageProviderWindows(providerId, capacity) {
                 ? {...window, window_minutes:defaultMinutes}
                 : window,
         }));
 }
 
 function _usageFreshnessHtml() {
     if (Connection.ownsErrors()) return '';
     if (_usageFetchPromise) {
-        return '<span id="usage-freshness" style="color:#38bdf8">обновление…</span>';
+        return `<span id="usage-freshness" style="color:#38bdf8">${T('updating…')}</span>`;
     }
     if (!_usageLastSuccessAt) return '';
     const ageMinutes = Math.floor((Date.now() - _usageLastSuccessAt) / 60000);
-    const age = ageMinutes < 1 ? 'сейчас' : `${ageMinutes} мин назад`;
+    const age = ageMinutes < 1 ? T('just now') : T('{min} min ago', {min: ageMinutes});
     if (_usageError) {
-        return `<span id="usage-freshness" style="color:#eab308">ошибка обновления · данные от ${age}</span>`;
+        return `<span id="usage-freshness" style="color:#eab308">${T('update error · data from {age}', {age})}</span>`;
     }
     const stale = Date.now() - _usageLastSuccessAt >= _USAGE_REFRESH_INTERVAL_MS;
-    return `<span id="usage-freshness" style="color:${stale ? '#eab308' : '#64748b'}">${stale ? 'устарело' : 'обновлено'} ${age}</span>`;
+    return `<span id="usage-freshness" style="color:${stale ? '#eab308' : '#64748b'}">${T('{status} {age}', {status: stale ? T('stale') : T('updated'), age})}</span>`;
 }
 
 function _renderUsageBarShell(bar, groups) {
     bar.innerHTML = `<div class="usage-limits">${groups.join('')}</div>`
         + `<div class="usage-actions">${_usageFreshnessHtml()}`
         + `<span id="usage-info-btn" title="${T('Usage details and history')}">ⓘ</span></div>`;
 }
 
@@ -265,17 +265,17 @@ function renderUsageBar() {
             bar.textContent = T('⚠ Usage unavailable');
         } else {
             bar.innerHTML = '';
             bar.style.display = 'none';
         }
         return;
     }
     bar.style.cssText = 'display:flex;align-items:flex-start;gap:10px;padding:4px 12px;min-height:28px;height:auto;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:visible;white-space:nowrap;cursor:pointer';
-    bar.title = 'Нажмите, чтобы обновить данные о расходе';
+    bar.title = T('Click to refresh usage data');
 
     const a = _usageData.anthropic || {};
     const cx = _usageData.codex || {};
     const gx = _usageData.grok || null;
     const groups = [];
     const claudeParts = [];
 
     if (_usageError && !Connection.ownsErrors()) {
@@ -329,19 +329,18 @@ function renderUsageBar() {
             const minuteLimit = m.limit || 20;
             const used = Math.max(d.count || 0, 0);
             const util = Math.round(used / dailyLimit * 1000) / 10;
             const c = _usageColor(util, null);
             const resetIso = new Date(Date.now() + 86400000).toISOString().slice(0, 13) + ':00:00Z';
             const cd = _resetCountdown(resetIso);
             groups.push(
                 `<span class="usage-provider-group" data-usage-compact-provider="openrouter">`
-                + `<span class="usage-provider-title" style="color:${accent};font-weight:600">OpenRouter</span>`
-                + `<span class="usage-provider-values"><span style="display:inline-flex;align-items:center;gap:3px">сутки: ${_miniBar(util, c)} <span style="color:#64748b">${used}/${dailyLimit}</span>${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}</span>`
-                + ` <span style="display:inline-flex;align-items:center;gap:3px">минута: <span style="color:${(m.count || 0) >= minuteLimit ? '#f87171' : '#94a3b8'}">${m.count || 0}/${minuteLimit}</span></span></span>`
+                + `<span class="usage-provider-title" style="color:${accent};font-weight:600">${T('OpenRouter')}</span>`
+                + `<span class="usage-provider-values"><span style="display:inline-flex;align-items:center;gap:3px">${T('daily')}: ${_miniBar(util, c)} <span style="color:#64748b">${used}/${dailyLimit}</span>${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}</span> <span style="display:inline-flex;align-items:center;gap:3px">${T('minute')}: <span style="color:${(m.count || 0) >= minuteLimit ? '#f87171' : '#94a3b8'}">${m.count || 0}/${minuteLimit}</span></span></span>`
                 + '</span>',
             );
         }
     }
 
     const compactProviders = [
         {id:'codex', bucketId:'codex', windows:_usageProviderWindows('codex', cx)},
         {id:'codex-spark', bucketId:'codex_spark', windows:_usageProviderWindows('codex', cx.spark), compactTitle:'Codex Spark'},
@@ -409,27 +408,27 @@ function renderUsageBar() {
                 const _o = _usageData?.orchestra || {};
                 const _row = (label, val, color) => `<div style="display:flex;justify-content:space-between"><span>${label}</span><span style="color:${color || '#cbd5e1'}">${val}</span></div>`;
                 const _windowBlock = (window, label, accent) => {
                     const windowMs = window.window_minutes * 60000;
                     const cd = _resetCountdown(window.resets_at);
                     const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
                     const eta = _etaToLimit(window.utilization, window.resets_at, windowMs);
                     const rpNum = _resetPctNum(window.resets_at, windowMs);
-                    let html = `<div style="margin-bottom:9px"><div style="color:${accent};font-weight:600;margin-bottom:2px">${label} окно</div>`;
-                    html += _row('Использовано', `${window.utilization}%`, window.utilization >= 80 ? '#ef4444' : window.utilization >= 50 ? '#eab308' : '#22c55e');
-                    if (cd) html += _row('Сброс через', cd, '#64748b');
-                    // Недельное окно живёт днями — «через 3d 21h» не читается как момент времени.
+                    let html = `<div style="margin-bottom:9px"><div style="color:${accent};font-weight:600;margin-bottom:2px">${T('{label} window', {label})}</div>`;
+                    html += _row(T('Used'), `${window.utilization}%`, window.utilization >= 80 ? '#ef4444' : window.utilization >= 50 ? '#eab308' : '#22c55e');
+                    if (cd) html += _row(T('Reset in'), cd, '#64748b');
+                    // Weekly window lives in days — "in 3d 21h" doesn't read as a moment in time.
                     if (window.window_minutes >= 1440) {
                         const krsk = _krskReset(window.resets_at);
-                        if (krsk) html += _row('Сброс (Крск)', krsk, '#64748b');
+                        if (krsk) html += _row(T('Reset (Krasnoyarsk)'), krsk, '#64748b');
                     }
-                    if (rpNum != null) html += _row('Прогресс окна', `${_resetPctText(rpNum)}%`, '#64748b');
-                    html += _row('Отклонение', pace, null);
-                    if (eta) html += _row('Лимит через', eta, null);
+                    if (rpNum != null) html += _row(T('Window progress'), `${_resetPctText(rpNum)}%`, '#64748b');
+                    html += _row(T('Deviation'), pace, null);
+                    if (eta) html += _row(T('Limit in'), eta, null);
                     return html + '</div>';
                 };
                 let h = '';
                 const claudeMeta = _PROVIDER_META.claude;
                 let claudeHtml = '<section data-usage-provider="claude" style="min-width:0;padding-right:2px">';
                 claudeHtml += `<div style="color:${_usageProviderAccent('claude')};font-weight:700;margin-bottom:7px">${T(claudeMeta.usageTitle)}</div>`;
                 for (const item of _usageProviderWindows('claude', _a)) {
                     claudeHtml += _windowBlock(item.window, T(item.label), claudeMeta.windowAccent);
@@ -457,61 +456,61 @@ function renderUsageBar() {
                 let grokHtml = '<section data-usage-provider="grok" style="min-width:0;border-left:1px solid rgba(51,65,85,0.65);padding-left:14px">';
                 grokHtml += `<div style="color:${_usageProviderAccent('grok')};font-weight:700;margin-bottom:7px">${T(grokMeta.usageTitle)}</div>`;
                 if (grokWindows.length) {
                     for (const item of grokWindows) {
                         grokHtml += _windowBlock(item.window, T(windowLabel(item.window.window_minutes)), grokMeta.windowAccent);
                     }
                     grokHtml += `<div data-usage-history="${grokMeta.historyProviders.join(',')}"></div>`;
                 } else {
-                    grokHtml += '<div style="color:#64748b;font-style:italic">Данные лимита недоступны</div>';
+                    grokHtml += `<div style="color:#64748b;font-style:italic">${T('Limit data unavailable')}</div>`;
                 }
                 grokHtml += '</section>';
 
                 const orMeta = _usageData?.openrouter || null;
                 let orHtml = '';
                 if (orMeta) {
                     orHtml = '<section data-usage-provider="openrouter" style="min-width:0;border-left:1px solid rgba(51,65,85,0.65);padding-left:14px">';
-                    orHtml += '<div style="color:#a78bfa;font-weight:700;margin-bottom:7px">OpenRouter (бесплатный)</div>';
+                    orHtml += `<div style="color:#a78bfa;font-weight:700;margin-bottom:7px">${T('OpenRouter (free)')}</div>`;
                     if (!orMeta.available) {
-                        orHtml += `<div style="color:#64748b;font-style:italic">${escHtml(orMeta.reason || 'Данные недоступны')}</div>`;
+                        orHtml += `<div style="color:#64748b;font-style:italic">${escHtml(orMeta.reason || T('Data unavailable'))}</div>`;
                     } else {
                         const d = orMeta.daily || {}, m = orMeta.minute || {};
-                        orHtml += _row('Сутки', `${d.count}/${d.limit}`, '#cbd5e1');
-                        orHtml += _row('Минута', `${m.count}/${m.limit}`, '#cbd5e1');
-                        orHtml += _row('Источник счёта', 'локальный', '#64748b');
+                        orHtml += _row(T('Daily'), `${d.count}/${d.limit}`, '#cbd5e1');
+                        orHtml += _row(T('Minute'), `${m.count}/${m.limit}`, '#cbd5e1');
+                        orHtml += _row(T('Count source'), T('local'), '#64748b');
                         const rec = orMeta.reconciliation;
                         if (rec) {
-                            orHtml += `<div style="margin-top:4px;color:#94a3b8">Вчера (${escHtml(rec.day)}): провайдер ${rec.provider_requests}, локально ${rec.local_requests}, Δ ${rec.delta}</div>`;
+                            orHtml += `<div style="margin-top:4px;color:#94a3b8">${T('Yesterday ({day}): provider {provider}, local {local}, Δ {delta}', {day: escHtml(rec.day), provider: rec.provider_requests, local: rec.local_requests, delta: rec.delta})}</div>`;
                             const bs = rec.local_by_status || {};
                             const parts = Object.keys(bs).map(k => `${k}×${bs[k]}`).join(', ');
-                            if (parts) orHtml += `<div style="color:#64748b;font-size:10px">Локальные попытки вчера: ${escHtml(parts)}</div>`;
+                            if (parts) orHtml += `<div style="color:#64748b;font-size:10px">${T('Local attempts yesterday: {parts}', {parts: escHtml(parts)})}</div>`;
                         }
                     }
                     orHtml += '</section>';
                 }
 
                 h += '<div id="usage-sparkline-slot" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px">';
                 h += claudeHtml + codexHtml + grokHtml + orHtml + '</div>';
                 if (typeof _o.total_cost_usd === 'number') {
                     h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
-                    h += _row('💰 Стоимость', `${MODEL_COST_CURRENCY}${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
+                    h += _row(T('💰 Cost'), `${MODEL_COST_CURRENCY}${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                     if (typeof _usageData.voice_cost_usd === 'number') {
-                        h += `<div style="font-size:10px">${_row('🎤 Голос', `${MODEL_COST_CURRENCY}${_usageData.voice_cost_usd.toFixed(2)}`, '#94a3b8')}</div>`;
+                        h += `<div style="font-size:10px">${_row(T('🎤 Voice'), `${MODEL_COST_CURRENCY}${_usageData.voice_cost_usd.toFixed(2)}`, '#94a3b8')}</div>`;
                     }
-                    // Цена подписки приходит из SUBSCRIPTION_COST (.env). Не задана — строки
-                    // нет: захардкоженная константа уже провисела неверной, а рядом стоят
-                    // посчитанные числа, и выдуманное среди них неотличимо от настоящего.
+                    // Subscription price comes from SUBSCRIPTION_COST (.env). Not set — no row:
+                    // hardcoded constant was already wrong, and among calculated numbers a fake
+                    // one is indistinguishable from real.
                     if (_usageData.subscription_cost) {
-                        h += _row('Подписка', escHtml(_usageData.subscription_cost), '#64748b');
+                        h += _row(T('Subscription'), escHtml(_usageData.subscription_cost), '#64748b');
                     }
                     h += '</div>';
                 }
                 if (typeof _o.agents_count === 'number') {
-                    h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 Агенты: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
+                    h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 ${T('Agents')}: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
                 }
                 tip = document.createElement('div');
                 tip.style.cssText = 'position:fixed;z-index:9999;background:rgba(15,23,42,0.97);border:1px solid rgba(71,85,105,0.5);border-radius:12px;padding:16px;width:min(940px,calc(100vw - 24px));max-height:calc(100vh - 52px);overflow:auto;overscroll-behavior:contain;backdrop-filter:blur(12px);box-shadow:0 12px 36px rgba(0,0,0,0.5);font-size:12px;line-height:1.6;color:#94a3b8';
                 tip.innerHTML = h;
                 const rect = infoBtn.getBoundingClientRect();
                 tip.style.right = '12px';
                 tip.style.top = (rect.bottom + 6) + 'px';
                 tip.addEventListener('mouseenter', () => clearTimeout(hideTimer));
@@ -547,17 +546,17 @@ function _sparkMessage(slot, text, isError) {
 async function _sparkFetch(until) {
     // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался раньше этого
     // запроса (год в 5-минутной сетке — 4.36 МБ), а падение пряталось за пустым catch.
     const query = until
         ? `hours=${_SPARK_VIEW_HOURS}&until=${encodeURIComponent(until)}`
         : `hours=${_SPARK_VIEW_HOURS}`;
     const history = await api(`/api/usage/history?${query}`, { timeoutMs: 30000 });
     if (!Array.isArray(history?.rows)) {
-        throw new Error(`ответ без rows: ${JSON.stringify(history).slice(0, 80)}`);
+        throw new Error(T('response without rows: {history}', {history: JSON.stringify(history).slice(0, 80)}));
     }
     _sparkStepMin = Number(history.step_minutes) || 5;
     _sparkOldestTs = history.oldest_ts || '';
     return history.rows;
 }
 
 // Есть ли на сервере снимки старше самого старого загруженного.
 function _sparkHasOlder() {
@@ -574,26 +573,26 @@ async function _loadSparkline(tipEl) {
     const now = Date.now();
     if (!_sparkData || now - _sparkDataTs >= 300000) {
         try {
             _sparkData = await _sparkFetch('');
             _sparkDataTs = now;
             _sparkError = '';
         } catch (e) {
             _sparkData = null;
-            _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
+            _sparkError = T('{name}: {message}', {name: e?.name || T('Error'), message: e?.message || T('no message')});
             console.error(`usage history fetch failed: ${_sparkError}`);
         }
     }
     if (!Array.isArray(_sparkData) || _sparkData.length < 1) {
-        // Раньше здесь во всех случаях висело «Collecting data...» — и когда сбор
-        // действительно не начался, и когда запрос упал. Это разные вещи.
+        // Previously "Collecting data..." hung in all cases — both when collection
+        // hadn't started and when the request failed. These are different things.
         const why = _sparkError
-            ? `История не загрузилась — ${_sparkError}`
-            : 'Снимков ещё нет: график появится после двух замеров в одном окне';
+            ? T('History failed to load — {error}', {error: _sparkError})
+            : T('No snapshots yet: chart appears after two measurements in one window');
         slots.forEach(slot => _sparkMessage(slot, why, Boolean(_sparkError)));
         return;
     }
     _sparkPeriodIdx = {};
     slots.forEach(slot => {
         const providerFilter = new Set(slot.dataset.usageHistory.split(','));
         _renderSparklines(slot, providerFilter);
     });
@@ -677,17 +676,17 @@ function _seriesPointsForPeriod(series, anchorPeriod) {
         return ts >= start && ts <= end;
     });
 }
 
 function _renderSparklines(slot, providerFilter = null) {
     const data = _sparkData;
     if (!data || data.length < 1) return;
     const PL = 28, W = 280, H = 50, gw = W - PL, gh = H;
-    const DAYS = ['вс','пн','вт','ср','чт','пт','сб'];
+    const DAYS = T('Sun Mon Tue Wed Thu Fri Sat').split(' ');
     const providerColors = {
         anthropic: ['#38bdf8', '#f97316'],
         codex: ['#22c55e', '#a3e635'],
         codex_spark: ['#f59e0b', '#fcd34d'],
         grok: [_PROVIDER_COLORS['x-ai'], '#94a3b8'],
     };
 
     const mkSvg = (pts, idealPts, color, guides) => {
@@ -819,50 +818,50 @@ function _renderSparklines(slot, providerFilter = null) {
                 ? `<span data-spark-nav="newer" data-spark-key="${series.key}" style="cursor:pointer;color:#64748b">▶</span>`
                 : isAnchor ? '<span style="color:#1e293b">▶</span>' : '';
             html += `<div data-usage-series="${series.key}" style="margin-bottom:5px"><div style="font-size:10px;display:flex;align-items:center;gap:4px">${older}<span style="color:${color};font-weight:600">${T(series.windowLabel)}</span><span style="color:#64748b">${current}% · ${periodLabel}</span>${newer}</div>`;
             html += `<div style="font-size:8px;color:#475569;margin-bottom:2px">${T('━ usage ┈ ideal pace')}</div>${mkSvg(points.pts, points.ideal, color, getGuides(period))}</div>`;
         });
         html += '</div>';
     }
     if (!html) {
-        // Строки есть, но по ЭТОМУ провайдеру графика не выходит. Раньше тут стояло
-        // то же «Collecting data...», что и при полном отсутствии данных, — из-за чего
-        // «данных нет вообще» и «нет данных по Codex» выглядели одинаково.
+        // Data exists but no chart for THIS provider. Previously the same
+        // "Collecting data..." was shown for both no-data-at-all and no-data-for-Codex,
+        // making them indistinguishable.
         const hasPoints = [...grouped.keys()].some(id => !providerFilter || providerFilter.has(id));
-        // Именно первый снимок ВООБЩЕ, а не первый загруженный: с ленивой подгрузкой
-        // data[0] — это граница текущего куска, и «снимки ведутся с» врало бы.
+        // Exactly the FIRST snapshot OVERALL, not the first loaded: with lazy loading
+        // data[0] is the current chunk boundary, so "tracking since" would be a lie.
         const since0 = _sparkOldestTs || data[0]?.ts;
         const firstTs = since0 ? new Date(since0) : null;
         const since = firstTs && !isNaN(firstTs)
-            ? ` Снимки ведутся с ${firstTs.toLocaleDateString()}.`
+            ? T(' Tracking since {date}.', {date: firstTs.toLocaleDateString()})
             : '';
         slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic"></div>';
         slot.firstChild.textContent = hasPoints
-            ? `Мало точек: на график нужно ≥2 замера в одном окне.${since}`
-            : `Этого провайдера в истории нет.${since}`;
+            ? T('Not enough points: chart needs ≥2 measurements in one window.{since}', {since})
+            : T('This provider has no history.{since}', {since});
         return;
     }
     slot.innerHTML = html;
     slot.querySelectorAll('[data-spark-nav]').forEach(button => {
         button.addEventListener('click', async event => {
             event.stopPropagation();
             const key = button.dataset.sparkKey;
             const delta = button.dataset.sparkNav === 'older' ? 1 : -1;
             const idx = Math.max(0, (_sparkPeriodIdx[key] || 0) + delta);
             _sparkPeriodIdx[key] = idx;
             const loaded = Number(button.dataset.sparkPeriods) || 1;
             if (delta > 0 && idx >= loaded - 1 && _sparkHasOlder()) {
-                _sparkMessage(slot, 'Загружаю предыдущий период…', false);
+                _sparkMessage(slot, T('Loading previous period…'), false);
                 try {
                     _sparkData = (await _sparkFetch(_sparkData[0].ts)).concat(_sparkData);
                 } catch (e) {
-                    _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
+                    _sparkError = T('{name}: {message}', {name: e?.name || T('Error'), message: e?.message || T('no message')});
                     console.error(`usage history chunk failed: ${_sparkError}`);
-                    _sparkMessage(slot, `Предыдущий период не загрузился — ${_sparkError}`, true);
+                    _sparkMessage(slot, T('Previous period failed to load — {error}', {error: _sparkError}), true);
                     return;
                 }
             }
             _renderSparklines(slot, providerFilter);
         });
     });
 }
 


## LATER FIX 8dd91d5e11 (17.7 days later): V-700: #V-700: fix dashboard CI and i18n issues
lines of origin it changed/deleted: 2
(code only, capped 400 lines)

V-700: #V-700: fix dashboard CI and i18n issues

Orchestra-Operation: 135686ca-629c-47d3-b6b6-7d67924f8061


diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 6335cc983..87456a56e 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -28,20 +28,20 @@ jobs:
       fail-fast: false
       matrix:
         shard: [0, 1, 2, 3, 4, 5]
     steps:
       # Часть тестов сравнивает рабочее дерево с `main` и ходит к родительским
       # коммитам. По умолчанию checkout берёт ОДИН коммит ОДНОЙ ветки, и такой
       # тест падает не по существу: `git show main:app/static/js/app.js` отвечает
       # `exit 128`. `fetch-depth: 0` даёт полную историю и все ветки.
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@v5
         with:
           fetch-depth: 0
-      - uses: astral-sh/setup-uv@v4
+      - uses: astral-sh/setup-uv@v7
       - run: uv sync --dev
       # На образе ubuntu-latest ffmpeg не предустановлен, а тест длительности
       # аудио обязан звать НАСТОЯЩИЙ ffprobe — подменять бинарь значило бы
       # проверять заглушку вместо разбора контейнера.
       - run: sudo apt-get update && sudo apt-get install -y ffmpeg
       # `uv sync` ставит пакет playwright, но не бинарники браузеров. Без этого
       # шага все браузерные тесты молча скипались бы, и CI был бы зелёным, ничего
       # про фронт не проверив.
@@ -77,18 +77,18 @@ jobs:
     # из гейта, не убиваем»), поэтому джоба помечена `continue-on-error` — она остаётся
     # СИГНАЛОМ, видимым в списке проверок, но не решает судьбу прогона. Гоняются те же
     # 167 узлов, что снимает с себя merge-гейт: состав закреплён
     # `tests/test_merge_test_gate.py::test_browser_inventory_is_explicit`.
     runs-on: ubuntu-latest
     continue-on-error: true
     timeout-minutes: 20
     steps:
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@v5
         with:
           fetch-depth: 0
-      - uses: astral-sh/setup-uv@v4
+      - uses: astral-sh/setup-uv@v7
       - run: uv sync --dev
       - run: uv run playwright install --with-deps chromium
       - name: pytest browser
         run: |
           PYTHONUNBUFFERED=1 /usr/bin/time -v uv run pytest -v -rf --timeout=30 \
             -m "browser" tests/
diff --git a/app/db.py b/app/db.py
index 0672cd3c6..fafad79cf 100644
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
-    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct):
+    if fh_pct is not None and (row.get("five_hour_resets_at") or fh_pct == 0):
         windows.append({
             "id": "five_hour", "label": "5h",
             "utilization": fh_pct,
             "window_minutes": 300,
             "resets_at": row.get("five_hour_resets_at") or None,
         })
-    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct):
+    if sd_pct is not None and (row.get("seven_day_resets_at") or sd_pct == 0):
         windows.append({
             "id": "seven_day", "label": "7d",
             "utilization": sd_pct,
             "window_minutes": 10080,
             "resets_at": row.get("seven_day_resets_at") or None,
         })
     return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}
 
diff --git a/app/quota_gate.py b/app/quota_gate.py
index 71c3f0793..cfbe175e1 100644
--- a/app/quota_gate.py
+++ b/app/quota_gate.py
@@ -265,17 +265,17 @@ SPARK_MODEL = "gpt-5.3-codex-spark"
 LUNA_MODEL = "gpt-5.6-luna"
 
 # Полосы, которым диагональ применяется. Всё, чего здесь нет, ограничено только
 # жёстким стопом.
 GATED_LANES = _env_gated_lanes("QUOTA_GATED_LANES", _ENV_GATED_LANES_DEFAULT)
 CURVED_LANES = _env_gated_lanes("QUOTA_CURVED_LANES", _ENV_CURVED_LANES_DEFAULT)
 
 LANE_LABELS = {
-    "claude": "Claude-воркеры",
+    "claude": "Claude workers",
     "sol": "Sol",
     "luna": "Luna",
     "spark": "Spark",
 }
 
 # Временное снятие гейта владельцем (#V-578). Снимается ТОЛЬКО наша дополнительная
 # осторожность — диагональ и потолок отдельной полосы; общий жёсткий стоп остаётся,
 # потому что за ним стоит предел провайдера, а не наше правило: пропустив туда, мы
diff --git a/app/static/js/analytics.js b/app/static/js/analytics.js
index 00675e456..d9c659508 100644
--- a/app/static/js/analytics.js
+++ b/app/static/js/analytics.js
@@ -644,28 +644,31 @@ function _analyticsCapacity(provider) {
 
 function _analyticsKpi(label, value, detail) {
     return `<article><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>`;
 }
 
 function _analyticsMoney(value) {
     if (value == null || Number.isNaN(Number(value))) return '—';
     const amount = Number(value);
-    return `${MODEL_COST_CURRENCY}${amount.toLocaleString('ru-RU', { minimumFractionDigits: amount < 100 ? 2 : 0, maximumFractionDigits: 2 })}`;
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return `${MODEL_COST_CURRENCY}${amount.toLocaleString(locale, { minimumFractionDigits: amount < 100 ? 2 : 0, maximumFractionDigits: 2 })}`;
 }
 
 function _analyticsNumber(value) {
-    return Number(value || 0).toLocaleString('ru-RU');
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return Number(value || 0).toLocaleString(locale);
 }
 
 function _analyticsDateTime(value) {
     if (!value) return '—';
     const date = new Date(value);
     if (Number.isNaN(date.getTime())) return _analyticsEsc(String(value));
-    return date.toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return date.toLocaleString(locale, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
 }
 
 function _analyticsDuration(seconds) {
     const total = Number(seconds || 0);
     if (total < 60) return T('{sec} sec', {sec: Math.round(total)});
     return T('{min} min {sec} sec', {min: Math.floor(total / 60), sec: Math.round(total % 60)});
 }
 
diff --git a/app/static/js/i18n.js b/app/static/js/i18n.js
index 4ebaf5fc9..1b1b8edb5 100644
--- a/app/static/js/i18n.js
+++ b/app/static/js/i18n.js
@@ -122,16 +122,17 @@
     'In progress': 'Идёт',
     'Ready': 'Готово',
     'Result': 'Результат',
     'Rolled back': 'Откат',
     'Tool': 'Инструмент',
     'Output shortened for display ({n} source bytes)': 'Показана часть вывода (исходный размер: {n} байт)',
     'Created': 'Создано',
     'Created:': 'Создана:',
+    'Claude workers': 'Claude-воркеры',
     'Creating...': 'Создание…',
     'Critical': 'Критический',
     'Current turn': 'Текущий ход',
     'DESCRIPTION': 'ОПИСАНИЕ',
     'DONE': 'ГОТОВО',
     'Daily': 'Сутки',
     'Data unavailable': 'Данные недоступны',
     'Delegation': 'Делегирование',
diff --git a/app/static/js/quota-lines.js b/app/static/js/quota-lines.js
index e2317f9f9..455af7756 100644
--- a/app/static/js/quota-lines.js
+++ b/app/static/js/quota-lines.js
@@ -107,17 +107,17 @@ function _qlAllLanes() {
     for (const bucket of (_quotaLinesData?.buckets || [])) {
         for (const lane of (bucket.lanes || [])) lanes.push(lane);
     }
     return lanes;
 }
 
 function _qlLaneLabel(laneId) {
     const found = _qlAllLanes().find(lane => lane.lane === laneId);
-    return found ? (found.label || laneId) : laneId;
+    return T(found ? (found.label || laneId) : laneId);
 }
 
 // Hard-stop ceilings in words: Sol has its own (95%), others share one. Label
 // must match the `ql-hard` lines on the chart — both use the same numbers.
 function _qlCeilingText(rule) {
     const own = Object.entries(rule.lane_hard_stop_pct || {})
         .filter(([, pct]) => Number.isFinite(Number(pct)))
         .sort(([a], [b]) => a.localeCompare(b))
@@ -156,17 +156,17 @@ function _qlGateState() {
             text: T('gate LIFTED — diagonal holds no lanes, only ceiling remains: {ceiling}', {
                 ceiling: ceilings,
             }),
         };
     }
     const held = rule.gated_lanes.map(_qlLaneLabel);
     const free = _qlAllLanes()
         .filter(lane => !rule.gated_lanes.includes(lane.lane))
-        .map(lane => lane.label || lane.lane);
+        .map(lane => T(lane.label || lane.lane));
     const tail = free.length ? ` · ${T('outside gate')}: ${free.join(', ')}` : '';
     return {state: 'on', text: T('gate ON: {held}{tail} · ceiling: {ceiling}', {
         held: held.join(', '),
         tail,
         ceiling: ceilings,
     })};
 }
 
@@ -304,17 +304,17 @@ function _qlTimelineSvg(panel, rule) {
         }
     }
     // Facts stop at now. Add a current sample there; the right half is policy only.
     let pointIndex = 0;
     for (const lane of _qlLanes(panel)) {
         const point = _qlPoint(lane.bucket);
         if (!point) continue;
         const color = _QL_LANE_COLORS[lane.lane] || 'var(--ink)';
-        p.push(`<circle data-ql-timeline-point="${_escHtml(lane.lane)}" cx="${x(now)}" cy="${y(point.util)}" r="${5.5 + pointIndex * 2}" fill="none" stroke="${color}" stroke-width="2.5"><title>${_escHtml(lane.label || lane.lane)}: ${_qlNum(point.util)}%</title></circle>`);
+        p.push(`<circle data-ql-timeline-point="${_escHtml(lane.lane)}" cx="${x(now)}" cy="${y(point.util)}" r="${5.5 + pointIndex * 2}" fill="none" stroke="${color}" stroke-width="2.5"><title>${_escHtml(T(lane.label || lane.lane))}: ${_qlNum(point.util)}%</title></circle>`);
         pointIndex++;
     }
     p.push(`<line class="ql-now" x1="${x(now)}" y1="${_QL_MT}" x2="${x(now)}" y2="${_QL_MT + _QL_PH}"/>`);
     const histories = new Set();
     for (const bucket of panel.buckets.map(_qlBucket).filter(Boolean)) {
         if (histories.has(bucket.bucket)) continue;
         histories.add(bucket.bucket);
         const points = bucket.timeline?.points || [];
@@ -369,17 +369,17 @@ function _qlChartSvg(panel, rule) {
     p.push(`<line class="ql-hard" x1="${_qlX(0)}" y1="${_qlY(hard)}" x2="${_qlX(1)}" y2="${_qlY(hard)}"/>`);
     p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">${T('hard {pct}% — stop for lanes without own ceiling', {pct: _qlNum(hard)})}</text>`);
     // Lane-specific line for lane with lower ceiling: one common line would lie
     // that the expensive lane runs to the last pool percent.
     for (const lane of _qlLanes(panel)) {
         const stop = _qlHardStop(rule, lane.lane);
         if (!(stop < hard)) continue;
         p.push(`<line class="ql-hard" data-ql-hard-lane="${_escHtml(lane.lane)}" x1="${_qlX(0)}" y1="${_qlY(stop)}" x2="${_qlX(1)}" y2="${_qlY(stop)}"/>`);
-        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${T('{label} — hard {pct}%', {label: _escHtml(lane.label || lane.lane), pct: _qlNum(stop)})}</text>`);
+        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${T('{label} — hard {pct}%', {label: _escHtml(T(lane.label || lane.lane)), pct: _qlNum(stop)})}</text>`);
     }
     p.push(`<line class="ql-orch" x1="${_qlX(0)}" y1="${_qlY(100)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
     p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">${T('orchestrator always runs — no limit')}</text>`);
 
     const byBucket = [];
     for (const id of panel.buckets) {
         const bucket = _qlBucket(id);
         if (!bucket) continue;
@@ -426,17 +426,17 @@ function _qlChartSvg(panel, rule) {
         }
         const x = _qlX(point.progress), y = _qlY(point.util);
         p.push(`<line class="ql-cursor" x1="${x}" y1="${_QL_MT}" x2="${x}" y2="${_QL_MT + _QL_PH}"/>`);
         const offset = _QL_LANE_MARKERS[i] || _QL_LANE_MARKERS[0];
         const right = point.progress > 0.6;
         const dx = right ? -Math.abs(offset.dx) : offset.dx;
         const dy = offset.dy;
         const color = _QL_LANE_COLORS[lane.lane] || 'var(--ink)';
-        const label = _escHtml(String(lane.label || lane.lane));
+        const label = _escHtml(String(T(lane.label || lane.lane)));
         const markerClass = `ql-point-${lane.lane || 'lane'}`;
         const anchor = right ? 'end' : 'start';
         const hardY = _qlY(hard);
         const baseY = _qlY(point.util + 0);
         const rawLabelY = y + dy;
         const avoidHardY = Math.abs(baseY - hardY) < 8 || Math.abs(rawLabelY - hardY) < 28;
         const stackedLabelY = _qlPlaceY(avoidHardY ? hardY + 22 : rawLabelY, usedLabelBands);
         const stackedDetailY = _qlPlaceY(stackedLabelY + 15, usedLabelBands);
@@ -482,18 +482,18 @@ function _qlVerdict(panel) {
         && l.bucket.fresh !== false
         && l.release_status !== 'no_data');
     if (!lanes.length) return {text: T('no data — server did not send allowance lanes'), nodata: true};
     if (!known.length) return {text: T('no data — no pool telemetry, gate returns unknown'), nodata: true};
     const partial = known.length < lanes.length;
     if (partial) {
         return {text: T('no data — some lanes missing telemetry'), nodata: true, blocked: false};
     }
-    const blocked = known.filter(l => l.blocked).map(l => l.label || l.lane);
-    const open = known.filter(l => !l.blocked).map(l => l.label || l.lane);
+    const blocked = known.filter(l => l.blocked).map(l => T(l.label || l.lane));
+    const open = known.filter(l => !l.blocked).map(l => T(l.label || l.lane));
     const parts = [];
     if (blocked.length) parts.push(T('{lanes} — blocked', {lanes: blocked.join(', ')}));
     if (open.length) parts.push(T('{lanes} — running', {lanes: open.join(', ')}));
     return {
         text: parts.join(' · '),
         nodata: false,
         blocked: blocked.length > 0,
     };
@@ -510,20 +510,20 @@ function _qlPanelHtml(panel) {
         </section>`;
     }
     const lanes = _qlLanes(panel).map(lane => {
         const nodata = !lane.bucket?.data_available
             || lane.bucket.fresh === false
             || lane.release_status === 'no_data';
         const state = nodata ? 'nodata' : lane.blocked ? 'blocked' : 'open';
         const word = _qlLaneSummary(lane);
-        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : T(' <i>no diagonal</i>')}</span>`;
+        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(T(lane.label || lane.lane))}: <b>${word}</b>${lane.gated ? '' : T(' <i>no diagonal</i>')}</span>`;
     }).join('');
     const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
-        .map(l => `<li><b>${_escHtml(l.label || l.lane)}</b> — ${_escHtml(l.reason)}</li>`).join('');
+        .map(l => `<li><b>${_escHtml(T(l.label || l.lane))}</b> — ${_escHtml(l.reason)}</li>`).join('');
     const chart = _qlChartSvg(panel, rule);
     const traceNotices = (chart.traceNotices || [])
         .map(item => `<div class="ql-trace-msg" data-ql-trace-msg="${_escHtml(item.bucket)}">${T('{label}: no history for this window', {label: _escHtml(item.label)})}</div>`)
         .join('');
     return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
         <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
         <div class="ql-head ql-timeline-head"><h4>${T('Quota timeline')}</h4><span>${T('±3.5 days · current time centered · Krasnoyarsk')}</span></div>
         ${_qlTimelineSvg(panel, rule)}
diff --git a/app/static/js/usage.js b/app/static/js/usage.js
index 2df5950d3..48f4b5262 100644
--- a/app/static/js/usage.js
+++ b/app/static/js/usage.js
@@ -38,17 +38,18 @@ function _resetCountdown(isoStr) {
     if (h >= 24) { const d = Math.floor(h / 24); return `${d}d ${h % 24}h ${m}m`; }
     return `${h}h ${m}m`;
 }
 
 function _krskReset(isoStr) {
     if (!isoStr) return '';
     const at = new Date(isoStr);
     if (Number.isNaN(at.getTime())) return '';
-    return new Intl.DateTimeFormat('ru-RU', {
+    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
+    return new Intl.DateTimeFormat(locale, {
         timeZone: 'Asia/Krasnoyarsk',
         weekday: 'short', day: 'numeric', month: 'short',
         hour: '2-digit', minute: '2-digit',
     }).format(at);
 }
 
 function _resetPctNum(isoStr, windowMs) {
     if (!isoStr) return null;
@@ -602,21 +603,21 @@ function _historyProviders(row) {
     if (row?.providers && typeof row.providers === 'object') return row.providers;
     const windows = [];
     // null в колонке = источник не ответил (#150). `Number(null)` даёт 0, и окно
     // с нулём нарисовало бы провал в пол там, где данных нет вовсе
     const pct = value => (value == null || value === '' || !Number.isFinite(Number(value)))
         ? null : Number(value);
     const fiveHour = pct(row?.five_hour_pct);
     const sevenDay = pct(row?.seven_day_pct);
-    if (fiveHour !== null && (row.five_hour_resets_at || fiveHour)) {
+    if (fiveHour !== null && (row.five_hour_resets_at || fiveHour === 0)) {
         windows.push({id:'five_hour', label:'5h', utilization:fiveHour,
             window_minutes:300, resets_at:row.five_hour_resets_at || null});
     }
-    if (sevenDay !== null && (row.seven_day_resets_at || sevenDay)) {
+    if (sevenDay !== null && (row.seven_day_resets_at || sevenDay === 0)) {
         windows.push({id:'seven_day', label:'7d', utilization:sevenDay,
             window_minutes:10080, resets_at:row.seven_day_resets_at || null});
     }
     return windows.length ? {anthropic:{label:'Claude', windows}} : {};
 }
 
 function _usageHistorySeries(data) {
     const series = new Map();
diff --git a/tests/test_dashboard_i18n_formatting.py b/tests/test_dashboard_i18n_formatting.py
new file mode 100644
index 000000000..7aaa7d427
--- /dev/null
+++ b/tests/test_dashboard_i18n_formatting.py
@@ -0,0 +1,57 @@
+from pathlib import Path
+
+import pytest
+from playwright.sync_api import sync_playwright
+
+from app.quota_gate import LANE_LABELS
+
+ROOT = Path(__file__).parent.parent
+
+
+@pytest.fixture(scope="module")
+def browser():
+    with sync_playwright() as playwright:
+        instance = playwright.chromium.launch(headless=True)
+        yield instance
+        instance.close()
+
+
+def _formatting_page(browser, language):
+    context = browser.new_context()
+    context.add_init_script(f"localStorage.setItem('orch_lang', '{language}')")
+    page = context.new_page()
+    page.route("http://harness.local/**", lambda route: route.fulfill(
+        status=200, content_type="text/html", body="<body></body>"))
+    page.goto("http://harness.local/")
+    page.add_script_tag(path=str(ROOT / "app/static/js/utils.js"))
+    page.add_script_tag(path=str(ROOT / "app/static/js/i18n.js"))
+    page.add_script_tag(path=str(ROOT / "app/static/js/usage.js"))
+    page.add_script_tag(path=str(ROOT / "app/static/js/analytics.js"))
+    return context, page
+
+
+def test_dashboard_numbers_and_dates_follow_the_selected_language(browser):
+    assert LANE_LABELS["claude"] == "Claude workers"
+    values = {}