/* usage.js — usage bar rendering, sparklines, countdown. Loaded before app.js. */

let _usageData = null;
let _usageError = false;
let _usageCountdownInterval = null;
let _usageFetchPromise = null;
let _usageLastSuccessAt = 0;
let _usageLastFetchStartedAt = 0;
const _USAGE_REFRESH_INTERVAL_MS = 120000;
const _USAGE_CLICK_DEBOUNCE_MS = 1000;

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
    if (ms <= 0) return '';
    const h = Math.floor(ms / 3600000); const m = Math.floor((ms % 3600000) / 60000);
    if (h >= 24) { const d = Math.floor(h / 24); return `${d}d ${h % 24}h ${m}m`; }
    return `${h}h ${m}m`;
}

function _resetPctNum(isoStr, windowMs) {
    if (!isoStr) return null;
    const remaining = new Date(isoStr) - Date.now();
    const elapsed = windowMs - remaining;
    return Math.max(0, Math.min(100, Math.round(elapsed / windowMs * 100)));
}

// Computes how long to wait (or "ok") based on pace vs. ideal linear burn.
// cooldownMin = how many minutes to wait at 0% usage to get back on pace.
function _paceIndicator(currentPct, isoStr, windowMs) {
    if (!isoStr) return '';
    const remainMs = Math.max(0, new Date(isoStr) - Date.now());
    const elapsedMs = windowMs - remainMs;
    const idealPct = (elapsedMs / windowMs) * 100;
    const delta = currentPct - idealPct;
    if (delta <= 5) return '<span style="color:#22c55e" title="Расход не опережает линейный темп окна">темп ok</span>';
    const cooldownMin = Math.round(delta * windowMs / 100 / 60000);
    const color = delta <= 20 ? '#eab308' : '#ef4444';
    let label;
    if (cooldownMin < 60) label = `${cooldownMin}m`;
    else if (cooldownMin < 1440) label = `${Math.floor(cooldownMin/60)}h ${cooldownMin%60}m`;
    else label = `${Math.floor(cooldownMin/1440)}d ${Math.floor((cooldownMin%1440)/60)}h ${cooldownMin%60}m`;
    return `<span style="color:${color}" title="Локальная оценка опережения линейного темпа. Это не отдельное лимитное окно и не официальный таймер провайдера.">темп +${label}</span>`;
}

function _etaToLimit(currentPct, isoStr, windowMs) {
    if (!isoStr || currentPct <= 0) return '';
    const remainMs = Math.max(0, new Date(isoStr) - Date.now());
    const elapsedMs = windowMs - remainMs;
    if (elapsedMs <= 0) return '';
    const rate = currentPct / elapsedMs;
    const pctLeft = 100 - currentPct;
    if (pctLeft <= 0) return '<span style="color:#ef4444">⚡ лимит!</span>';
    const etaMs = pctLeft / rate;
    const etaMin = Math.round(etaMs / 60000);
    const color = etaMin < 30 ? '#ef4444' : etaMin < 120 ? '#eab308' : '#22c55e';
    let label;
    if (etaMin < 60) label = `${etaMin}m`;
    else if (etaMin < 1440) label = `${Math.floor(etaMin/60)}h ${etaMin%60}m`;
    else label = `${Math.floor(etaMin/1440)}d ${Math.floor((etaMin%1440)/60)}h`;
    return `<span style="color:${color}">⏳${label}</span>`;
}

function _miniBar(pct, color) {
    return `<span style="display:inline-flex;align-items:center;gap:4px"><span style="display:inline-block;width:80px;height:6px;border-radius:3px;background:rgba(51,65,85,0.5);overflow:hidden;vertical-align:middle"><span style="display:block;width:${Math.min(pct, 100)}%;height:100%;border-radius:3px;background:${color}"></span></span><span style="color:#e2e8f0;font-weight:600">${pct}%</span></span>`;
}

function _codexWindowLabel(windowMinutes) {
    if (windowMinutes === 300) return '5h';
    if (windowMinutes === 10080) return '7d';
    if (windowMinutes % 1440 === 0) return `${windowMinutes / 1440}d`;
    if (windowMinutes % 60 === 0) return `${windowMinutes / 60}h`;
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

function _usageFreshnessHtml() {
    if (_usageFetchPromise) {
        return '<span id="usage-freshness" style="color:#38bdf8">обновление…</span>';
    }
    if (!_usageLastSuccessAt) return '';
    const ageMinutes = Math.floor((Date.now() - _usageLastSuccessAt) / 60000);
    const age = ageMinutes < 1 ? 'сейчас' : `${ageMinutes} мин назад`;
    if (_usageError) {
        return `<span id="usage-freshness" style="color:#eab308">ошибка обновления · данные от ${age}</span>`;
    }
    const stale = Date.now() - _usageLastSuccessAt >= _USAGE_REFRESH_INTERVAL_MS;
    return `<span id="usage-freshness" style="color:${stale ? '#eab308' : '#64748b'}">${stale ? 'устарело' : 'обновлено'} ${age}</span>`;
}

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
    bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap;cursor:pointer';
    bar.title = 'Нажмите, чтобы обновить usage';

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
        const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
        const c = _usageColor(sd.utilization, rpNum);
        const rp = rpNum != null ? ` <span style="color:#64748b">(${rpNum}%)</span>` : '';
        const cd = _resetCountdown(sd.resets_at);
        const pace = _paceIndicator(sd.utilization, sd.resets_at, 7 * 86400000);
        parts.push(`<span style="display:inline-flex;align-items:center;gap:3px">7d: ${_miniBar(sd.utilization, c)}${rp}${cd ? ` <span style="color:#64748b">${cd}</span>` : ''}${pace ? ` <span style="font-size:10px">·</span> ${pace}` : ''}</span>`);
    }

    const compactProviders = [
        {id:'codex', windows:_usageProviderWindows('codex', cx)},
        {id:'grok', windows:_usageProviderWindows('grok', gx), showUnavailable:true},
    ].filter(provider => provider.windows.length || provider.showUnavailable);
    if (compactProviders.length) {
        parts.push('<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>');
        for (const provider of compactProviders) {
            const meta = _PROVIDER_META[provider.id];
            const color = _usageProviderAccent(provider.id);
            parts.push(`<span style="color:${color};font-weight:600">${meta.compactTitle || meta.title}</span>`);
            if (!provider.windows.length) {
                parts.push('<span style="color:#64748b">: нет данных</span>');
                continue;
            }
            for (const item of provider.windows) {
                const window = item.window;
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
    const freshness = _usageFreshnessHtml();
    if (freshness) parts.push(freshness);
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
            infoBtn.style.color = '#94a3b8';
            showTimer = setTimeout(async () => {
                if (tip) return;
                const _a = _usageData?.anthropic || {};
                const _c = _usageData?.codex || {};
                const _g = _usageData?.grok || null;
                const _o = _usageData?.orchestra || {};
                const _row = (label, val, color) => `<div style="display:flex;justify-content:space-between"><span>${label}</span><span style="color:${color || '#cbd5e1'}">${val}</span></div>`;
                const _windowBlock = (window, label, accent) => {
                    const windowMs = window.window_minutes * 60000;
                    const cd = _resetCountdown(window.resets_at);
                    const pace = _paceIndicator(window.utilization, window.resets_at, windowMs);
                    const eta = _etaToLimit(window.utilization, window.resets_at, windowMs);
                    const rpNum = _resetPctNum(window.resets_at, windowMs);
                    let html = `<div style="margin-bottom:9px"><div style="color:${accent};font-weight:600;margin-bottom:2px">${label} окно</div>`;
                    html += _row('Использовано', `${window.utilization}%`, window.utilization >= 80 ? '#ef4444' : window.utilization >= 50 ? '#eab308' : '#22c55e');
                    if (cd) html += _row('Сброс через', cd, '#64748b');
                    if (rpNum != null) html += _row('Прогресс окна', `${rpNum}%`, '#64748b');
                    html += _row('Отклонение', pace, null);
                    if (eta) html += _row('Лимит через', eta, null);
                    return html + '</div>';
                };
                const claudeMeta = _PROVIDER_META.claude;
                let claudeHtml = '<section data-usage-provider="claude" style="min-width:0;padding-right:2px">';
                claudeHtml += `<div style="color:${_usageProviderAccent('claude')};font-weight:700;margin-bottom:7px">${claudeMeta.usageTitle}</div>`;
                for (const item of _usageProviderWindows('claude', _a)) {
                    claudeHtml += _windowBlock(item.window, item.label, claudeMeta.windowAccent);
                }
                claudeHtml += `<div data-usage-history="${claudeMeta.historyProviders.join(',')}"></div></section>`;

                const codexMeta = _PROVIDER_META.codex;
                const codexProviders = [
                    {title:codexMeta.usageTitle, accent:_usageProviderAccent('codex'), windowAccent:codexMeta.windowAccent, windows:_usageProviderWindows('codex', _c).map(item => item.window)},
                    {title:'⚡ GPT-5.3-Codex-Spark', accent:'#f59e0b', windowAccent:'#fcd34d', windows:_usageProviderWindows('codex', _c.spark).map(item => item.window)},
                ].filter(provider => provider.windows.length);
                let codexHtml = '<section data-usage-provider="codex" style="min-width:0;border-left:1px solid rgba(51,65,85,0.65);padding-left:14px">';
                for (const provider of codexProviders) {
                    codexHtml += '<div style="border-bottom:1px solid rgba(51,65,85,0.45);padding-bottom:4px;margin-bottom:7px">';
                    codexHtml += `<div style="color:${provider.accent};font-weight:700;margin-bottom:5px">${provider.title}</div>`;
                    for (const window of provider.windows) {
                        codexHtml += _windowBlock(window, _codexWindowLabel(window.window_minutes), provider.windowAccent);
                    }
                    codexHtml += '</div>';
                }
                codexHtml += `<div data-usage-history="${codexMeta.historyProviders.join(',')}"></div></section>`;

                const grokMeta = _PROVIDER_META.grok;
                const grokWindows = _usageProviderWindows('grok', _g);
                let grokHtml = '<section data-usage-provider="grok" style="min-width:0;border-left:1px solid rgba(51,65,85,0.65);padding-left:14px">';
                grokHtml += `<div style="color:${_usageProviderAccent('grok')};font-weight:700;margin-bottom:7px">${grokMeta.usageTitle}</div>`;
                if (grokWindows.length) {
                    for (const item of grokWindows) {
                        grokHtml += _windowBlock(item.window, _codexWindowLabel(item.window.window_minutes), grokMeta.windowAccent);
                    }
                    grokHtml += `<div data-usage-history="${grokMeta.historyProviders.join(',')}"></div>`;
                } else {
                    grokHtml += '<div style="color:#64748b;font-style:italic">Данные лимита недоступны</div>';
                }
                grokHtml += '</section>';

                let h = '<div style="color:#e2e8f0;font-weight:700;margin-bottom:10px">📊 Usage control</div>';
                h += '<div id="usage-sparkline-slot" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px">';
                h += claudeHtml + codexHtml + grokHtml + '</div>';
                if (typeof _o.total_cost_usd === 'number') {
                    h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
                    h += _row('💰 Стоимость', `${MODEL_COST_CURRENCY}${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                    if (typeof _usageData.voice_cost_usd === 'number') {
                        h += `<div style="font-size:10px">${_row('🎤 Voice', `${MODEL_COST_CURRENCY}${_usageData.voice_cost_usd.toFixed(2)}`, '#94a3b8')}</div>`;
                    }
                    // Цена подписки приходит из SUBSCRIPTION_COST (.env). Не задана — строки
                    // нет: захардкоженная константа уже провисела неверной, а рядом стоят
                    // посчитанные числа, и выдуманное среди них неотличимо от настоящего.
                    if (_usageData.subscription_cost) {
                        h += _row('Подписка', escHtml(_usageData.subscription_cost), '#64748b');
                    }
                    h += '</div>';
                }
                if (typeof _o.agents_count === 'number') {
                    h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 Агенты: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
                }
                tip = document.createElement('div');
                tip.style.cssText = 'position:fixed;z-index:9999;background:rgba(15,23,42,0.97);border:1px solid rgba(71,85,105,0.5);border-radius:12px;padding:16px;width:min(940px,calc(100vw - 24px));max-height:calc(100vh - 52px);overflow:auto;overscroll-behavior:contain;backdrop-filter:blur(12px);box-shadow:0 12px 36px rgba(0,0,0,0.5);font-size:12px;line-height:1.6;color:#94a3b8';
                tip.innerHTML = h;
                const rect = infoBtn.getBoundingClientRect();
                tip.style.right = '12px';
                tip.style.top = (rect.bottom + 6) + 'px';
                tip.addEventListener('mouseenter', () => clearTimeout(hideTimer));
                tip.addEventListener('mouseleave', () => { delayedHide(); });
                document.body.appendChild(tip);
                _loadSparkline(tip);
            }, 200);
        });
        infoBtn.addEventListener('mouseleave', () => { infoBtn.style.color = '#475569'; delayedHide(); });
    }
}

let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {}, _sparkError = '', _sparkStepMin = 5;
let _sparkOldestTs = '';
// Грузим ровно то, что рисуем: график показывает один период якорного окна, а самое
// длинное окно у провайдеров — 7 суток. История растёт вечно, и тянуть её целиком
// значит вернуться к тому же таймауту через пару лет. Остальное приезжает по клику ◀.
const _SPARK_VIEW_HOURS = 168;

function _sparkMessage(slot, text, isError) {
    slot.innerHTML = `<div style="font-size:10px;color:${isError ? '#eab308' : '#475569'};font-style:italic"></div>`;
    slot.firstChild.textContent = text;
}

// Имя с префиксом _spark: app.js уже держит глобальный _fetchHistory(name, scope)
// и грузится ПОСЛЕ usage.js, поэтому его объявление перекрывало это.
async function _sparkFetch(until) {
    // Общий таймаут api() = 5 с выбран для мелких ответов и обрывался раньше этого
    // запроса (год в 5-минутной сетке — 4.36 МБ), а падение пряталось за пустым catch.
    const query = until
        ? `hours=${_SPARK_VIEW_HOURS}&until=${encodeURIComponent(until)}`
        : `hours=${_SPARK_VIEW_HOURS}`;
    const history = await api(`/api/usage/history?${query}`,
                              { signal: AbortSignal.timeout(30000) });
    if (!Array.isArray(history?.rows)) {
        throw new Error(`ответ без rows: ${JSON.stringify(history).slice(0, 80)}`);
    }
    _sparkStepMin = Number(history.step_minutes) || 5;
    _sparkOldestTs = history.oldest_ts || '';
    return history.rows;
}

// Есть ли на сервере снимки старше самого старого загруженного.
function _sparkHasOlder() {
    if (!_sparkOldestTs || !_sparkData?.length) return false;
    // Через Date, а не сравнением строк: смешать «+00:00» и «Z» достаточно, чтобы
    // лексикографический порядок соврал, а стрелка исчезла или зациклилась.
    return new Date(_sparkData[0].ts) > new Date(_sparkOldestTs);
}

// Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
async function _loadSparkline(tipEl) {
    const slots = [...tipEl.querySelectorAll('[data-usage-history]')];
    if (!slots.length) return;
    const now = Date.now();
    if (!_sparkData || now - _sparkDataTs >= 300000) {
        try {
            _sparkData = await _sparkFetch('');
            _sparkDataTs = now;
            _sparkError = '';
        } catch (e) {
            _sparkData = null;
            _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
            console.error(`usage history fetch failed: ${_sparkError}`);
        }
    }
    if (!Array.isArray(_sparkData) || _sparkData.length < 1) {
        // Раньше здесь во всех случаях висело «Collecting data...» — и когда сбор
        // действительно не начался, и когда запрос упал. Это разные вещи.
        const why = _sparkError
            ? `История не загрузилась — ${_sparkError}`
            : 'Снимков ещё нет: график появится после двух замеров в одном окне';
        slots.forEach(slot => _sparkMessage(slot, why, Boolean(_sparkError)));
        return;
    }
    _sparkPeriodIdx = {};
    slots.forEach(slot => {
        const providerFilter = new Set(slot.dataset.usageHistory.split(','));
        _renderSparklines(slot, providerFilter);
    });
}

function _historyProviders(row) {
    if (row?.providers && typeof row.providers === 'object') return row.providers;
    const windows = [];
    if (row?.five_hour_resets_at || Number(row?.five_hour_pct)) {
        windows.push({id:'five_hour', label:'5h', utilization:Number(row.five_hour_pct) || 0,
            window_minutes:300, resets_at:row.five_hour_resets_at || null});
    }
    if (row?.seven_day_resets_at || Number(row?.seven_day_pct)) {
        windows.push({id:'seven_day', label:'7d', utilization:Number(row.seven_day_pct) || 0,
            window_minutes:10080, resets_at:row.seven_day_resets_at || null});
    }
    return windows.length ? {anthropic:{label:'Claude', windows}} : {};
}

function _usageHistorySeries(data) {
    const series = new Map();
    for (const row of data) {
        for (const [providerId, provider] of Object.entries(_historyProviders(row))) {
            for (const window of provider.windows || []) {
                if (!Number.isFinite(Number(window.utilization)) || !Number(window.window_minutes)) continue;
                const key = `${providerId}:${window.id}`;
                if (!series.has(key)) {
                    series.set(key, {
                        key, providerId, providerLabel: provider.label || providerId,
                        windowId: window.id, windowLabel: window.label || _codexWindowLabel(window.window_minutes),
                        points: [],
                    });
                }
                series.get(key).points.push({
                    ts: row.ts,
                    utilization: Number(window.utilization),
                    resets_at: window.resets_at || null,
                    window_minutes: Number(window.window_minutes),
                });
            }
        }
    }
    return [...series.values()];
}

function _usagePeriods(series) {
    const raw = [];
    let current = [];
    for (const point of series.points) {
        const prev = current[current.length - 1];
        const resetChanged = prev?.resets_at && point.resets_at &&
            Math.abs(new Date(point.resets_at) - new Date(prev.resets_at)) > 3600000;
        const durationChanged = prev && prev.window_minutes !== point.window_minutes;
        if (current.length && (resetChanged || durationChanged)) {
            raw.push(current);
            current = [];
        }
        current.push(point);
    }
    if (current.length) raw.push(current);
    return raw.map(period => {
        const latest = period[period.length - 1];
        if (!latest?.resets_at) return period;
        const start = new Date(latest.resets_at).getTime() - latest.window_minutes * 60000;
        return period.filter(point => new Date(point.ts).getTime() >= start);
    }).filter(period => period.length >= 2);
}

function _seriesPointsForPeriod(series, anchorPeriod) {
    if (!anchorPeriod?.length) return [];
    const start = new Date(anchorPeriod[0].ts).getTime();
    const end = new Date(anchorPeriod[anchorPeriod.length - 1].ts).getTime();
    return series.points.filter(point => {
        const ts = new Date(point.ts).getTime();
        return ts >= start && ts <= end;
    });
}

function _renderSparklines(slot, providerFilter = null) {
    const data = _sparkData;
    if (!data || data.length < 1) return;
    const PL = 28, W = 280, H = 50, gw = W - PL, gh = H;
    const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    const providerColors = {
        anthropic: ['#38bdf8', '#f97316'],
        codex: ['#22c55e', '#a3e635'],
        codex_spark: ['#f59e0b', '#fcd34d'],
        grok: [_PROVIDER_COLORS['x-ai'], '#94a3b8'],
    };

    const mkSvg = (pts, idealPts, color, guides) => {
        const allV = [...pts.map(p=>p.v), ...idealPts.map(p=>p.v)];
        let yMin = Math.floor(Math.min(...allV)), yMax = Math.ceil(Math.max(...allV));
        if (yMax - yMin < 5) { yMin = Math.max(0, yMin - 3); yMax = yMin + 6; }
        const yRange = yMax - yMin || 1;
        const yOf = (p) => gh - ((Math.min(p.v, 100) - yMin) / yRange) * gh;
        const toStr = (arr) => arr.map(p => `${(PL + p.t * gw).toFixed(1)},${yOf(p).toFixed(1)}`).join(' ');
        // Точка с gap открывает новый отрезок: между ней и предыдущей снимков не
        // было, и одна полилиния через дырку нарисовала бы выдуманные данные.
        const segments = (arr) => {
            const out = [];
            for (const p of arr) {
                if (p.gap || !out.length) out.push([]);
                out[out.length - 1].push(p);
            }
            return out;
        };
        const totalH = H + 12;
        let s = `<svg width="${W}" height="${totalH}" viewBox="0 0 ${W} ${totalH}" style="display:block">`;
        s += `<text x="${PL - 3}" y="8" text-anchor="end" fill="#64748b" font-size="9">${yMax}%</text>`;
        s += `<text x="${PL - 3}" y="${gh - 1}" text-anchor="end" fill="#64748b" font-size="9">${yMin}%</text>`;
        for (const guide of guides) {
            const mx = PL + guide.t * gw;
            s += `<line x1="${mx}" y1="0" x2="${mx}" y2="${gh}" stroke="rgba(100,116,139,0.3)" stroke-width="0.5"/>`;
            s += `<text x="${mx}" y="${H + 11}" text-anchor="middle" fill="#64748b" font-size="8">${guide.label}</text>`;
        }
        for (const seg of segments(idealPts)) {
            if (seg.length >= 2) s += `<polyline points="${toStr(seg)}" fill="none" stroke="#475569" stroke-width="1" stroke-dasharray="4 3" stroke-linejoin="round" opacity="0.6"/>`;
        }
        for (const seg of segments(pts)) {
            if (seg.length >= 2) s += `<polyline points="${toStr(seg)}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
            else s += `<circle cx="${(PL + seg[0].t * gw).toFixed(1)}" cy="${yOf(seg[0]).toFixed(1)}" r="${pts.length === 1 ? 3 : 1.5}" fill="${color}"/>`;
        }
        s += '</svg>';
        return s;
    };

    const getGuides = (slice) => {
        if (slice.length < 2) return [];
        const t0 = new Date(slice[0].ts).getTime(), tN = new Date(slice[slice.length-1].ts).getTime();
        const range = tN - t0 || 1;
        const step = range > 36 * 3600000 ? 86400000 : range > 8 * 3600000 ? 6 * 3600000 : 3600000;
        const guides = [];
        for (let at = Math.ceil(t0 / step) * step; at < tN; at += step) {
            const date = new Date(at);
            const label = step === 86400000
                ? DAYS[date.getDay()]
                : `${String(date.getHours()).padStart(2, '0')}:00`;
            guides.push({t:(at - t0) / range, label});
        }
        return guides;
    };

    // Сервер отдаёт сетку с известным шагом и не выдаёт точку там, где снимков
    // не было. Значит соседи дальше шага = провал в данных, а не редкая выборка.
    const gapMs = _sparkStepMin * 1.5 * 60000;

    const mkPts = (slice) => {
        if (!slice.length) return { pts: [], ideal: [] };
        const t0 = new Date(slice[0].ts).getTime(), tN = new Date(slice[slice.length-1].ts).getTime();
        const range = tN - t0 || 1;
        const pts = [], ideal = [];
        let prevMs = null;
        for (const point of slice) {
            const ms = new Date(point.ts).getTime();
            const t = (ms - t0) / range;
            const gap = prevMs !== null && ms - prevMs > gapMs;
            prevMs = ms;
            pts.push({t, v:point.utilization, gap});
            if (!point.resets_at) { ideal.push({t, v:0, gap}); continue; }
            const windowMs = point.window_minutes * 60000;
            const remain = new Date(point.resets_at) - new Date(point.ts);
            ideal.push({t, v:Math.max(0, Math.min(100, (windowMs - remain) / windowMs * 100)), gap});
        }
        return { pts, ideal };
    };

    const grouped = new Map();
    for (const series of _usageHistorySeries(data)) {
        if (!grouped.has(series.providerId)) grouped.set(series.providerId, []);
        grouped.get(series.providerId).push(series);
    }
    // Порядок серий задаёт цвет из палитры. Без сортировки он зависел от того, какое
    // окно попалось в первой строке данных: подгрузили старый кусок, где 5h ещё не
    // было, — и 5h с 7d менялись местами и цветами прямо под курсором.
    for (const providerSeries of grouped.values()) {
        providerSeries.sort((a, b) =>
            (a.points[0]?.window_minutes || 0) - (b.points[0]?.window_minutes || 0));
    }
    let html = '';
    for (const [providerId, providerSeries] of grouped) {
        if (providerFilter && !providerFilter.has(providerId)) continue;
        const palette = providerColors[providerId] || ['#c084fc', '#f0abfc'];
        // The longest window owns period navigation. Shorter windows use the
        // same time slice, so Claude 5h and 7d always describe one selected week.
        const anchorSeries = providerSeries.reduce((longest, series) =>
            series.points[0]?.window_minutes > longest.points[0]?.window_minutes ? series : longest
        );
        const periods = _usagePeriods(anchorSeries);
        if (!periods.length) continue;
        const periodIdx = Math.max(0, Math.min(_sparkPeriodIdx[anchorSeries.key] || 0, periods.length - 1));
        _sparkPeriodIdx[anchorSeries.key] = periodIdx;
        const anchorPeriod = periods[periods.length - 1 - periodIdx];
        // Стрелка живёт, даже когда загруженные периоды кончились: следующий приедет
        // по клику. Иначе ленивая загрузка выглядела бы как потеря истории.
        const hasOlder = periodIdx < periods.length - 1 || _sparkHasOlder();
        const hasNewer = periodIdx > 0;
        const anchorMinutes = anchorSeries.points[0]?.window_minutes || 0;
        const periodLabel = periodIdx === 0
            ? 'current'
            : anchorMinutes >= 10080
                ? `${periodIdx}w ago`
                : `${periodIdx} period${periodIdx === 1 ? '' : 's'} ago`;
        html += `<div style="border-top:1px solid rgba(51,65,85,0.45);padding-top:7px;margin-top:7px">`;
        html += `<div style="font-size:10px;color:${palette[0]};font-weight:700;letter-spacing:.04em;margin-bottom:4px">${providerSeries[0].providerLabel} history</div>`;
        providerSeries.forEach((series, index) => {
            const period = _seriesPointsForPeriod(series, anchorPeriod);
            if (!period?.length) return;
            const isAnchor = series.key === anchorSeries.key;
            const color = palette[index % palette.length];
            const current = period[period.length - 1].utilization;
            const points = mkPts(period);
            const older = isAnchor && hasOlder
                ? `<span data-spark-nav="older" data-spark-key="${series.key}" data-spark-periods="${periods.length}" style="cursor:pointer;color:#64748b">◀</span>`
                : isAnchor ? '<span style="color:#1e293b">◀</span>' : '';
            const newer = isAnchor && hasNewer
                ? `<span data-spark-nav="newer" data-spark-key="${series.key}" style="cursor:pointer;color:#64748b">▶</span>`
                : isAnchor ? '<span style="color:#1e293b">▶</span>' : '';
            html += `<div data-usage-series="${series.key}" style="margin-bottom:5px"><div style="font-size:10px;display:flex;align-items:center;gap:4px">${older}<span style="color:${color};font-weight:600">${series.windowLabel}</span><span style="color:#64748b">${current}% · ${periodLabel}</span>${newer}</div>`;
            html += `<div style="font-size:8px;color:#475569;margin-bottom:2px">━ usage &nbsp;┈ ideal pace</div>${mkSvg(points.pts, points.ideal, color, getGuides(period))}</div>`;
        });
        html += '</div>';
    }
    if (!html) {
        // Строки есть, но по ЭТОМУ провайдеру графика не выходит. Раньше тут стояло
        // то же «Collecting data...», что и при полном отсутствии данных, — из-за чего
        // «данных нет вообще» и «нет данных по Codex» выглядели одинаково.
        const hasPoints = [...grouped.keys()].some(id => !providerFilter || providerFilter.has(id));
        // Именно первый снимок ВООБЩЕ, а не первый загруженный: с ленивой подгрузкой
        // data[0] — это граница текущего куска, и «снимки ведутся с» врало бы.
        const since0 = _sparkOldestTs || data[0]?.ts;
        const firstTs = since0 ? new Date(since0) : null;
        const since = firstTs && !isNaN(firstTs)
            ? ` Снимки ведутся с ${firstTs.toLocaleDateString()}.`
            : '';
        slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic"></div>';
        slot.firstChild.textContent = hasPoints
            ? `Мало точек: на график нужно ≥2 замера в одном окне.${since}`
            : `Этого провайдера в истории нет.${since}`;
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
                _sparkMessage(slot, 'Загружаю предыдущий период…', false);
                try {
                    _sparkData = (await _sparkFetch(_sparkData[0].ts)).concat(_sparkData);
                } catch (e) {
                    _sparkError = `${e?.name || 'Error'}: ${e?.message || 'без текста'}`;
                    console.error(`usage history chunk failed: ${_sparkError}`);
                    _sparkMessage(slot, `Предыдущий период не загрузился — ${_sparkError}`, true);
                    return;
                }
            }
            _renderSparklines(slot, providerFilter);
        });
    });
}

async function fetchUsage() {
    if (_usageFetchPromise) return _usageFetchPromise;
    _usageLastFetchStartedAt = Date.now();
    _usageFetchPromise = (async () => {
        try {
            _usageData = await api('/api/usage');
            _usageError = false;
            _usageLastSuccessAt = Date.now();
        } catch (error) {
            _usageError = true;
            const detail = error instanceof Error
                ? `${error.name}: ${error.message || '(no message)'}`
                : String(error);
            console.error(`Usage fetch failed: ${detail}`);
        }
    })();
    renderUsageBar();
    try {
        await _usageFetchPromise;
    } finally {
        _usageFetchPromise = null;
        renderUsageBar();
    }
}

function initUsageBar() {
    fetchUsage();
    const bar = document.getElementById('usage-bar');
    if (bar) {
        bar.addEventListener('click', () => {
            if (_usageFetchPromise) return;
            if (Date.now() - _usageLastFetchStartedAt < _USAGE_CLICK_DEBOUNCE_MS) return;
            fetchUsage();
        });
    }
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return;
        const lastRefresh = Math.max(_usageLastSuccessAt, _usageLastFetchStartedAt);
        if (Date.now() - lastRefresh >= _USAGE_REFRESH_INTERVAL_MS) fetchUsage();
    });
    // Full data refresh every 2 minutes; countdown rerender every minute (no API call)
    setInterval(fetchUsage, _USAGE_REFRESH_INTERVAL_MS);
    _usageCountdownInterval = setInterval(() => {
        if (_usageData) renderUsageBar();
    }, 60000);
}
