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
    if (delta <= 5) return '<span style="color:#22c55e">ok</span>';
    const cooldownMin = Math.round(delta * windowMs / 100 / 60000);
    const color = delta <= 20 ? '#eab308' : '#ef4444';
    let label;
    if (cooldownMin < 60) label = `${cooldownMin}m`;
    else if (cooldownMin < 1440) label = `${Math.floor(cooldownMin/60)}h ${cooldownMin%60}m`;
    else label = `${Math.floor(cooldownMin/1440)}d ${Math.floor((cooldownMin%1440)/60)}h ${cooldownMin%60}m`;
    return `<span style="color:${color}">⏸${label}</span>`;
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

    parts.push('<span style="flex:1"></span>');

    if (typeof o.total_cost_usd === 'number') {
        parts.push(`<span style="color:#22c55e">$${o.total_cost_usd.toFixed(0)}</span>`);
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
                const _o = _usageData?.orchestra || {};
                const fh = _a.five_hour;
                const sd = _a.seven_day;
                const _row = (label, val, color) => `<div style="display:flex;justify-content:space-between"><span>${label}</span><span style="color:${color || '#cbd5e1'}">${val}</span></div>`;
                let h = '<div style="color:#e2e8f0;font-weight:600;margin-bottom:10px">📊 Claude Max · $200/мес</div>';
                if (fh) {
                    const cd = _resetCountdown(fh.resets_at);
                    const pace = _paceIndicator(fh.utilization, fh.resets_at, 5 * 3600000);
                    const eta = _etaToLimit(fh.utilization, fh.resets_at, 5 * 3600000);
                    const rpNum = _resetPctNum(fh.resets_at, 5 * 3600000);
                    h += `<div style="margin-bottom:8px"><div style="color:#38bdf8;font-weight:600;margin-bottom:2px">5h окно</div>`;
                    h += _row('Использовано', `${fh.utilization}%`, fh.utilization >= 80 ? '#ef4444' : fh.utilization >= 50 ? '#eab308' : '#22c55e');
                    if (cd) h += _row('Сброс через', cd, '#64748b');
                    if (rpNum != null) h += _row('Прогресс окна', `${rpNum}%`, '#64748b');
                    h += _row('Темп', pace, null);
                    if (eta) h += _row('Лимит через', eta, null);
                    h += '</div>';
                }
                if (sd) {
                    const cd = _resetCountdown(sd.resets_at);
                    const pace = _paceIndicator(sd.utilization, sd.resets_at, 7 * 86400000);
                    const eta = _etaToLimit(sd.utilization, sd.resets_at, 7 * 86400000);
                    const rpNum = _resetPctNum(sd.resets_at, 7 * 86400000);
                    h += `<div style="margin-bottom:8px"><div style="color:#38bdf8;font-weight:600;margin-bottom:2px">7d окно</div>`;
                    h += _row('Использовано', `${sd.utilization}%`, sd.utilization >= 80 ? '#ef4444' : sd.utilization >= 50 ? '#eab308' : '#22c55e');
                    if (cd) h += _row('Сброс через', cd, '#64748b');
                    if (rpNum != null) h += _row('Прогресс окна', `${rpNum}%`, '#64748b');
                    h += _row('Темп', pace, null);
                    if (eta) h += _row('Лимит через', eta, null);
                    h += '</div>';
                }
                h += '<div id="usage-sparkline-slot" style="margin:8px 0"></div>';
                if (typeof _o.total_cost_usd === 'number') {
                    h += '<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">';
                    h += _row('💰 Стоимость', `$${_o.total_cost_usd.toFixed(0)}`, '#22c55e');
                    h += _row('Подписка', '$200/мес', '#64748b');
                    h += '</div>';
                }
                if (typeof _o.agents_count === 'number') {
                    h += `<div style="border-top:1px solid rgba(51,65,85,0.5);padding-top:6px;margin-top:4px">📈 Агенты: <span style="color:#cbd5e1">${_o.agents_count}</span></div>`;
                }
                tip = document.createElement('div');
                tip.style.cssText = 'position:fixed;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:12px;padding:16px;max-width:320px;min-width:240px;backdrop-filter:blur(12px);box-shadow:0 8px 24px rgba(0,0,0,0.4);font-size:12px;line-height:1.6;color:#94a3b8';
                tip.innerHTML = h;
                const rect = infoBtn.getBoundingClientRect();
                tip.style.left = Math.min(rect.left, window.innerWidth - 336) + 'px';
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

let _sparkData = null, _sparkDataTs = 0, _spark7dWeekIdx = 0;
// Cache sparkline data for 5 minutes — tooltip opens frequently, avoid hammering /api/usage/history
async function _loadSparkline(tipEl) {
    const slot = tipEl.querySelector('#usage-sparkline-slot');
    if (!slot) return;
    const now = Date.now();
    if (!_sparkData || now - _sparkDataTs >= 300000) {
        try {
            _sparkData = await api('/api/usage/history?hours=336');
            _sparkDataTs = now;
        } catch { _sparkData = null; }
    }
    if (!Array.isArray(_sparkData) || _sparkData.length < 3) {
        slot.innerHTML = '<div style="font-size:10px;color:#475569;font-style:italic">Collecting data...</div>';
        return;
    }
    _spark7dWeekIdx = 0;
    _renderSparklines(slot);
}

function _renderSparklines(slot) {
    const data = _sparkData;
    if (!data || data.length < 3) return;
    const PL = 28, W = 280, H = 50, gw = W - PL, gh = H;
    const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

    const mkSvg = (pts, idealPts, color, xLabels, midnights) => {
        const allV = [...pts.map(p=>p.v), ...idealPts.map(p=>p.v)];
        let yMin = Math.floor(Math.min(...allV)), yMax = Math.ceil(Math.max(...allV));
        if (yMax - yMin < 5) { yMin = Math.max(0, yMin - 3); yMax = yMin + 6; }
        const yRange = yMax - yMin || 1;
        const toStr = (arr) => arr.map(p => {
            const x = PL + p.t * gw;
            const y = gh - ((Math.min(p.v, 100) - yMin) / yRange) * gh;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
        const totalH = xLabels ? H + 12 : H;
        let s = `<svg width="${W}" height="${totalH}" viewBox="0 0 ${W} ${totalH}" style="display:block">`;
        s += `<text x="${PL - 3}" y="8" text-anchor="end" fill="#64748b" font-size="9">${yMax}%</text>`;
        s += `<text x="${PL - 3}" y="${gh - 1}" text-anchor="end" fill="#64748b" font-size="9">${yMin}%</text>`;
        for (const m of midnights) {
            const mx = PL + m.t * gw;
            s += `<line x1="${mx}" y1="0" x2="${mx}" y2="${gh}" stroke="rgba(100,116,139,0.3)" stroke-width="0.5"/>`;
            if (xLabels) s += `<text x="${mx}" y="${H + 11}" text-anchor="middle" fill="#64748b" font-size="8">${m.label}</text>`;
        }
        if (idealPts.length >= 2) s += `<polyline points="${toStr(idealPts)}" fill="none" stroke="#475569" stroke-width="1" stroke-dasharray="4 3" stroke-linejoin="round" opacity="0.6"/>`;
        if (pts.length >= 2) s += `<polyline points="${toStr(pts)}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
        else if (pts.length === 1) { const px = PL + pts[0].t * gw, py = gh - ((Math.min(pts[0].v, 100) - yMin) / yRange) * gh; s += `<circle cx="${px}" cy="${py}" r="3" fill="${color}"/>`; }
        s += '</svg>';
        return s;
    };

    const getMidnights = (slice) => {
        if (slice.length < 2) return [];
        const t0 = new Date(slice[0].ts).getTime(), tN = new Date(slice[slice.length-1].ts).getTime();
        const range = tN - t0 || 1;
        const mids = [];
        const first = new Date(slice[0].ts); first.setHours(0,0,0,0); first.setDate(first.getDate()+1);
        for (let d = first.getTime(); d < tN; d += 86400000) {
            mids.push({ t: (d - t0) / range, label: DAYS[new Date(d).getDay()] });
        }
        return mids;
    };

    const mkPts = (slice, key, resetKey, windowMs) => {
        if (!slice.length) return { pts: [], ideal: [] };
        const t0 = new Date(slice[0].ts).getTime(), tN = new Date(slice[slice.length-1].ts).getTime();
        const range = tN - t0 || 1;
        const pts = [], ideal = [];
        for (const d of slice) {
            const t = (new Date(d.ts).getTime() - t0) / range;
            pts.push({ t, v: d[key] || 0 });
            const ra = d[resetKey]; if (!ra) { ideal.push({ t, v: 0 }); continue; }
            const remain = new Date(ra) - new Date(d.ts);
            const elapsed = windowMs - remain;
            ideal.push({ t, v: Math.max(0, Math.min(100, elapsed / windowMs * 100)) });
        }
        return { pts, ideal };
    };

    // Split history into 7-day billing periods by detecting when resets_at changes.
    // 1h gap threshold avoids false splits from clock skew or API flakiness.
    const rawWeeks = []; let curWeek = [data[0]];
    for (let i = 1; i < data.length; i++) {
        const prev = data[i-1], cur = data[i];
        const prevReset = prev.seven_day_resets_at, curReset = cur.seven_day_resets_at;
        const isNewPeriod = prevReset && curReset && prevReset !== curReset &&
            new Date(curReset) - new Date(prevReset) > 3600000;
        if (isNewPeriod) {
            rawWeeks.push(curWeek);
            curWeek = [];
        }
        curWeek.push(data[i]);
    }
    if (curWeek.length > 0) rawWeeks.push(curWeek);
    const weeks = rawWeeks.map(w => {
        const resetAt = w[w.length - 1]?.seven_day_resets_at;
        if (!resetAt) return w;
        const periodStart = new Date(resetAt).getTime() - 7 * 86400000;
        return w.filter(d => new Date(d.ts).getTime() >= periodStart);
    }).filter(w => w.length > 0);

    const wi = Math.max(0, Math.min(_spark7dWeekIdx, weeks.length - 1));
    const weekData = weeks[weeks.length - 1 - wi];
    const hasPrev = wi < weeks.length - 1;
    const hasNext = wi > 0;
    const sd = mkPts(weekData, 'seven_day_pct', 'seven_day_resets_at', 7*86400000);
    const sdMids = getMidnights(weekData);
    const fh = mkPts(weekData, 'five_hour_pct', 'five_hour_resets_at', 5*3600000);
    const fhMids = getMidnights(weekData);
    const fhCur = weekData[weekData.length-1]?.five_hour_pct || 0;
    let html = `<div style="margin-bottom:4px"><div style="font-size:10px;color:#38bdf8;margin-bottom:1px;font-weight:600">5h <span style="color:#64748b;font-weight:normal">${fhCur}%</span></div><div style="font-size:8px;color:#475569;margin-bottom:2px">━ usage &nbsp;┈ ideal pace</div>${mkSvg(fh.pts, fh.ideal, '#38bdf8', true, fhMids)}</div>`;

    const sdCur = weekData[weekData.length-1]?.seven_day_pct || 0;
    const navLeft = hasPrev ? `<span id="spark-7d-prev" style="cursor:pointer;color:#64748b;hover:color:#94a3b8">◀</span> ` : '<span style="color:#1e293b">◀</span> ';
    const navRight = hasNext ? ` <span id="spark-7d-next" style="cursor:pointer;color:#64748b">▶</span>` : ` <span style="color:#1e293b">▶</span>`;
    const weekLabel = wi === 0 ? 'current' : `${wi}w ago`;
    html += `<div style="margin-bottom:4px"><div style="font-size:10px;margin-bottom:1px;display:flex;align-items:center;gap:4px">${navLeft}<span style="color:#f97316;font-weight:600">7d</span> <span style="color:#64748b;font-weight:normal">${sdCur}% · ${weekLabel}</span>${navRight}</div><div style="font-size:8px;color:#475569;margin-bottom:2px">━ usage &nbsp;┈ ideal pace</div>${sd.pts.length >= 1 ? mkSvg(sd.pts, sd.ideal, '#f97316', true, sdMids) : '<div style="font-size:10px;color:#475569;font-style:italic">Not enough data</div>'}</div>`;

    slot.innerHTML = html;

    const prevBtn = slot.querySelector('#spark-7d-prev');
    const nextBtn = slot.querySelector('#spark-7d-next');
    if (prevBtn) prevBtn.addEventListener('click', (e) => { e.stopPropagation(); _spark7dWeekIdx++; _renderSparklines(slot); });
    if (nextBtn) nextBtn.addEventListener('click', (e) => { e.stopPropagation(); _spark7dWeekIdx--; _renderSparklines(slot); });
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
