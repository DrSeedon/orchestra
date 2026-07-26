/* usage.js — usage bar rendering, sparklines, countdown. Loaded before app.js. */

let _usageData = null;
let _usageError = false;
let _usageCountdownInterval = null;

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

function renderUsageBar() {
    const bar = document.getElementById('usage-bar');
    if (!bar) return;
    if (!_usageData) {
        bar.innerHTML = '';
        bar.style.display = 'none';
        return;
    }
    bar.style.cssText = 'display:flex;align-items:center;gap:14px;padding:0 12px;height:28px;background:#0f172a;border-bottom:1px solid rgba(30,41,59,0.5);font-size:11px;color:#94a3b8;flex-shrink:0;overflow:hidden;white-space:nowrap';

    const a = _usageData.anthropic || {};
    const cx = _usageData.codex || {};
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

    const codexProviders = [
        {label:'Codex', color:'#22c55e', windows:[cx.primary, cx.secondary].filter(Boolean)},
        {label:'Spark', color:'#f59e0b', windows:[cx.spark?.primary, cx.spark?.secondary].filter(Boolean)},
    ].filter(provider => provider.windows.length);
    if (codexProviders.length) {
        parts.push('<span style="height:14px;border-left:1px solid rgba(71,85,105,0.6)"></span>');
        for (const provider of codexProviders) {
            parts.push(`<span style="color:${provider.color};font-weight:600">${provider.label}</span>`);
            for (const window of provider.windows) {
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
                const _o = _usageData?.orchestra || {};
                const fh = _a.five_hour;
                const sd = _a.seven_day;
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
                let claudeHtml = '<section style="min-width:0;padding-right:2px">';
                claudeHtml += '<div style="color:#38bdf8;font-weight:700;margin-bottom:7px">☕ Claude Max</div>';
                if (fh) {
                    claudeHtml += _windowBlock({...fh, window_minutes:300}, '5h', '#38bdf8');
                }
                if (sd) {
                    claudeHtml += _windowBlock({...sd, window_minutes:10080}, '7d', '#38bdf8');
                }
                claudeHtml += '<div data-usage-history="anthropic"></div></section>';

                const codexProviders = [
                    {title:'✦ Codex Pro', accent:'#22c55e', windowAccent:'#86efac', windows:[_c.primary, _c.secondary].filter(Boolean)},
                    {title:'⚡ GPT-5.3-Codex-Spark', accent:'#f59e0b', windowAccent:'#fcd34d', windows:[_c.spark?.primary, _c.spark?.secondary].filter(Boolean)},
                ].filter(provider => provider.windows.length);
                let codexHtml = '<section style="min-width:0;border-left:1px solid rgba(51,65,85,0.65);padding-left:14px">';
                for (const provider of codexProviders) {
                    codexHtml += '<div style="border-bottom:1px solid rgba(51,65,85,0.45);padding-bottom:4px;margin-bottom:7px">';
                    codexHtml += `<div style="color:${provider.accent};font-weight:700;margin-bottom:5px">${provider.title}</div>`;
                    for (const window of provider.windows) {
                        codexHtml += _windowBlock(window, _codexWindowLabel(window.window_minutes), provider.windowAccent);
                    }
                    codexHtml += '</div>';
                }
                codexHtml += '<div data-usage-history="codex,codex_spark"></div></section>';

                let h = '<div style="color:#e2e8f0;font-weight:700;margin-bottom:10px">📊 Usage control</div>';
                h += '<div id="usage-sparkline-slot" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px">';
                h += claudeHtml + codexHtml + '</div>';
                if (typeof _o.total_cost_usd === 'number') {
                    h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
                    h += _row('💰 Стоимость', `${MODEL_COST_CURRENCY}${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                    if (typeof _usageData.voice_cost_usd === 'number') {
                        h += `<div style="font-size:10px">${_row('🎤 Voice', `${MODEL_COST_CURRENCY}${_usageData.voice_cost_usd.toFixed(2)}`, '#94a3b8')}</div>`;
                    }
                    h += _row('Подписка', `${MODEL_COST_CURRENCY}100+${MODEL_COST_CURRENCY}100/мес`, '#64748b');
                    h += '</div>';
                }
                if (typeof _o.agents_count === 'number') {
                    h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 Агенты: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
                }
                tip = document.createElement('div');
                tip.style.cssText = 'position:fixed;z-index:9999;background:rgba(15,23,42,0.97);border:1px solid rgba(71,85,105,0.5);border-radius:12px;padding:16px;width:min(680px,calc(100vw - 24px));max-height:calc(100vh - 52px);overflow:auto;overscroll-behavior:contain;backdrop-filter:blur(12px);box-shadow:0 12px 36px rgba(0,0,0,0.5);font-size:12px;line-height:1.6;color:#94a3b8';
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

let _sparkData = null, _sparkDataTs = 0, _sparkPeriodIdx = {};
// Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
async function _loadSparkline(tipEl) {
    const slots = [...tipEl.querySelectorAll('[data-usage-history]')];
    if (!slots.length) return;
    const now = Date.now();
    if (!_sparkData || now - _sparkDataTs >= 300000) {
        try {
            _sparkData = await api('/api/usage/history?hours=8760');
            _sparkDataTs = now;
        } catch { _sparkData = null; }
    }
    if (!Array.isArray(_sparkData) || _sparkData.length < 1) {
        slots.forEach(slot => {
            slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic">Collecting data...</div>';
        });
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
    }).filter(period => period.length);
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
    };

    const mkSvg = (pts, idealPts, color, guides) => {
        const allV = [...pts.map(p=>p.v), ...idealPts.map(p=>p.v)];
        let yMin = Math.floor(Math.min(...allV)), yMax = Math.ceil(Math.max(...allV));
        if (yMax - yMin < 5) { yMin = Math.max(0, yMin - 3); yMax = yMin + 6; }
        const yRange = yMax - yMin || 1;
        const toStr = (arr) => arr.map(p => {
            const x = PL + p.t * gw;
            const y = gh - ((Math.min(p.v, 100) - yMin) / yRange) * gh;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
        const totalH = H + 12;
        let s = `<svg width="${W}" height="${totalH}" viewBox="0 0 ${W} ${totalH}" style="display:block">`;
        s += `<text x="${PL - 3}" y="8" text-anchor="end" fill="#64748b" font-size="9">${yMax}%</text>`;
        s += `<text x="${PL - 3}" y="${gh - 1}" text-anchor="end" fill="#64748b" font-size="9">${yMin}%</text>`;
        for (const guide of guides) {
            const mx = PL + guide.t * gw;
            s += `<line x1="${mx}" y1="0" x2="${mx}" y2="${gh}" stroke="rgba(100,116,139,0.3)" stroke-width="0.5"/>`;
            s += `<text x="${mx}" y="${H + 11}" text-anchor="middle" fill="#64748b" font-size="8">${guide.label}</text>`;
        }
        if (idealPts.length >= 2) s += `<polyline points="${toStr(idealPts)}" fill="none" stroke="#475569" stroke-width="1" stroke-dasharray="4 3" stroke-linejoin="round" opacity="0.6"/>`;
        if (pts.length >= 2) s += `<polyline points="${toStr(pts)}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
        else if (pts.length === 1) { const px = PL + pts[0].t * gw, py = gh - ((Math.min(pts[0].v, 100) - yMin) / yRange) * gh; s += `<circle cx="${px}" cy="${py}" r="3" fill="${color}"/>`; }
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

    const mkPts = (slice) => {
        if (!slice.length) return { pts: [], ideal: [] };
        const t0 = new Date(slice[0].ts).getTime(), tN = new Date(slice[slice.length-1].ts).getTime();
        const range = tN - t0 || 1;
        const pts = [], ideal = [];
        for (const point of slice) {
            const t = (new Date(point.ts).getTime() - t0) / range;
            pts.push({t, v:point.utilization});
            if (!point.resets_at) { ideal.push({t, v:0}); continue; }
            const windowMs = point.window_minutes * 60000;
            const remain = new Date(point.resets_at) - new Date(point.ts);
            ideal.push({t, v:Math.max(0, Math.min(100, (windowMs - remain) / windowMs * 100))});
        }
        return { pts, ideal };
    };

    const grouped = new Map();
    for (const series of _usageHistorySeries(data)) {
        if (!grouped.has(series.providerId)) grouped.set(series.providerId, []);
        grouped.get(series.providerId).push(series);
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
        const periodIdx = Math.max(0, Math.min(_sparkPeriodIdx[anchorSeries.key] || 0, periods.length - 1));
        _sparkPeriodIdx[anchorSeries.key] = periodIdx;
        const anchorPeriod = periods[periods.length - 1 - periodIdx];
        const hasOlder = periodIdx < periods.length - 1;
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
                ? `<span data-spark-nav="older" data-spark-key="${series.key}" style="cursor:pointer;color:#64748b">◀</span>`
                : isAnchor ? '<span style="color:#1e293b">◀</span>' : '';
            const newer = isAnchor && hasNewer
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
    try {
        _usageData = await api('/api/usage');
        _usageError = false;
    } catch {
        _usageError = true;
    }
    renderUsageBar();
}

function initUsageBar() {
    fetchUsage();
    // Full data refresh every 2 minutes; countdown rerender every minute (no API call)
    setInterval(fetchUsage, 120000);
    _usageCountdownInterval = setInterval(() => {
        if (_usageData) renderUsageBar();
    }, 60000);
}
