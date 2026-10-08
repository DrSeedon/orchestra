window.QuotaPanel = (() => {
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
const _QL_LABEL_STEP = 12;
const _QL_LABEL_TOP_PAD = 8;
const _QL_KR_HOUR_FORMAT = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Krasnoyarsk', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

const _QL_PANELS = [
    {key: 'all', title: T('Pool quotas'), sub: T('single scale: window progress share, 0–100%'),
     buckets: ['codex', 'codex_spark', 'anthropic']},
];

const _QL_NO_RULE = T('no data — server did not send rule constants');

let _quotaLinesData = null;
let _quotaLinesError = '';
let _quotaLinesOpen = false;
let _quotaLinesTimer = null;
// Server withholds subscription quotas outside owner mode: the panel has nothing to
// govern there, and "no data — owner_mode_only" read as a fault to outside users.
let _quotaLinesOwnerOnly = false;

const _qlX = t => _QL_ML + t * _QL_PW;
const _qlY = p => _QL_MT + (1 - p / 100) * _QL_PH;
const _QL_LANE_MARKERS = [
    {dx: 12, dy: -14},
    {dx: -12, dy: -22},
    {dx: 12, dy: 17},
    {dx: -12, dy: 26},
];
const _QL_LANE_COLORS = {sol: '#f472b6', luna: '#38bdf8', spark: '#c084fc', claude: '#fb923c'};

// Форма диагонали допуска между началом и концом окна. Значение В ТЕКУЩЕЙ точке
// берётся из lanes[].limit_pct сервера, а не отсюда, — иначе панель и гейт разойдутся.
// `lane` обязателен для полос с собственной формой: Sol — степенная кривая, Claude — day/night.
// Формула обязана совпадать с `line_limit` в app/quota_gate.py — расхождение здесь означает,
// что юзер видит на графике не тот порог, по которому его воркеров реально блокируют.
function _qlDayHoursBetween(startLocalHour, elapsedHours, dayStartHour) {
    const cumulative = position => {
        const fullDays = Math.floor(position / 24);
        const localHour = position - fullDays * 24;
        const dayLength = 24 - dayStartHour;
        return fullDays * dayLength + Math.min(dayLength, Math.max(0, localHour - dayStartHour));
    };
    return cumulative(startLocalHour + elapsedHours) - cumulative(startLocalHour);
}

function _qlClaudeDayNightLimit(t, rule, hardStop, windowMinutes, windowStartMs) {
    const minutes = Number.isFinite(windowMinutes) && windowMinutes > 0 ? windowMinutes : 10080;
    const spanHours = minutes / 60;
    let startHour = 14;
    if (Number.isFinite(windowStartMs)) {
        const parts = Object.fromEntries(_QL_KR_HOUR_FORMAT.formatToParts(new Date(windowStartMs))
            .map(part => [part.type, part.value]));
        startHour = Number(parts.hour) + Number(parts.minute) / 60;
    }
    const configuredDayStart = Number(rule.claude_day_start_hour);
    const dayStart = Number.isFinite(configuredDayStart)
        ? Math.min(23.999999, Math.max(0, configuredDayStart))
        : 8;
    const progress = Math.min(1, Math.max(0, t));
    const elapsedHours = progress * spanHours;
    const totalDay = _qlDayHoursBetween(startHour, spanHours, dayStart);
    const elapsedDay = _qlDayHoursBetween(startHour, elapsedHours, dayStart);
    const totalNight = spanHours - totalDay;
    const elapsedNight = elapsedHours - elapsedDay;
    const start = Number(rule.tolerance_start_pp);
    const rise = Math.max(0, hardStop - start);
    const nightShare = Math.min(1, Math.max(0, Number(rule.claude_night_quota_share)));
    const dayWeight = totalDay > 0 ? 1 - nightShare : 0;
    const nightWeight = totalNight > 0 ? nightShare : 0;
    const weightTotal = dayWeight + nightWeight;
    if (!weightTotal) return hardStop;
    const dayRate = totalDay ? rise * dayWeight / weightTotal / totalDay : 0;
    const nightRate = totalNight ? rise * nightWeight / weightTotal / totalNight : 0;
    const legacySlope = 100 + Number(rule.tolerance_end_pp) - start;
    const headroom = legacySlope * Number(rule.claude_weekly_shift_hours || 0) / spanHours;
    const limit = start + dayRate * elapsedDay + nightRate * elapsedNight + headroom;
    return Math.min(hardStop, limit);
}

function _qlLimitAt(t, rule, lane, windowMinutes = 10080, windowStartMs = null) {
    const start = Number(rule.tolerance_start_pp), end = Number(rule.tolerance_end_pp);
    const exponent = Number(rule.curve_exponent) || 1;
    const hasDayNightShape = lane === 'claude'
        && rule.claude_night_quota_share != null
        && Number.isFinite(Number(rule.claude_night_quota_share));
    const hardStop = _qlHardStop(rule, lane);
    if (hasDayNightShape) {
        return _qlClaudeDayNightLimit(t, rule, hardStop, windowMinutes, windowStartMs);
    }
    const shiftHours = lane === 'claude' ? Number(rule.claude_weekly_shift_hours) : 0;
    const lineProgress = lane === 'claude' && Number.isFinite(shiftHours) ? t + shiftHours / 168 : t;
    const curved = lane && (rule.curved_lanes || []).includes(lane) && exponent > 1;
    const norm = (curved && lineProgress > 0) ? Math.pow(lineProgress, 1 / exponent) : lineProgress;
    return Math.min(hardStop, norm * 100 + start + (end - start) * lineProgress);
}

function _qlMonotoneLimitAt(t, rule, lane, windowMinutes, windowStartMs, history, atMs) {
    const current = _qlLimitAt(t, rule, lane, windowMinutes, windowStartMs);
    if (lane !== 'claude' || !Array.isArray(history)) return current;
    let limit = current;
    for (const event of history) {
        const effectiveAt = Number(event.effective_from) * 1000;
        const policy = event.policy;
        if (!Number.isFinite(effectiveAt) || effectiveAt > atMs
            || !policy || !(policy.gated_lanes || []).includes('claude')) continue;
        limit = Math.max(limit, _qlLimitAt(t, policy, lane, windowMinutes, windowStartMs));
    }
    return limit;
}

// Жёсткий стоп — свойство ПОЛОСЫ: хвост пула зарезервирован под дешёвую модель,
// поэтому Sol встаёт раньше Luna. Зеркало `QuotaPolicy.hard_stop_for`.
function _qlHardStop(rule, lane) {
    const hard = Number(rule.hard_stop_pct);
    const laneHard = Number((rule.lane_hard_stop_pct || {})[lane]);
    return Number.isFinite(laneHard) ? Math.min(hard, laneHard) : hard;
}

function _qlRuleAt(ts, now, currentRule, history) {
    if (ts >= now || !Array.isArray(history) || history.length === 0) {
        return {policy: currentRule, effectiveFrom: 'current'};
    }
    let activeRule = currentRule;
    let effectiveFrom = 'current';
    for (const event of history) {
        const effectiveAtMs = Number(event.effective_from) * 1000;
        if (!Number.isFinite(effectiveAtMs) || effectiveAtMs > ts) break;
        if (event.policy && typeof event.policy === 'object') {
            activeRule = event.policy;
            effectiveFrom = String(event.effective_from);
        }
    }
    return {policy: activeRule, effectiveFrom};
}

function _qlBucket(bucketId) {
    return (_quotaLinesData?.buckets || []).find(b => b.bucket === bucketId) || null;
}

function _qlDurationFromSeconds(totalSeconds) {
    const rounded = Math.max(0, Math.round(Number(totalSeconds)));
    if (!Number.isFinite(rounded)) return '';
    const minutes = Math.floor((rounded % 3600) / 60);
    const hours = Math.floor((rounded % 86400) / 3600);
    const days = Math.floor(rounded / 86400);
    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function _qlReleaseText(lane) {
    const status = String(lane.release_status || '').trim();
    const seconds = Number(lane.release_in_seconds);
    const hasSeconds = Number.isFinite(seconds);

    if (status === 'opens_in') {
        return hasSeconds ? T('opens in {duration}', {duration: _qlDurationFromSeconds(seconds)}) : T('opens soon');
    }
    if (status === 'at_reset') {
        return hasSeconds
            ? T('opens at reset, in {duration}', {duration: _qlDurationFromSeconds(seconds)})
            : T('opens at reset');
    }
    if (status === 'no_data') {
        return T('no data');
    }
    return T('running');
}

function _qlLaneSummary(lane) {
    return _qlReleaseText(lane);
}

function _qlAllLanes() {
    const lanes = [];
    for (const bucket of (_quotaLinesData?.buckets || [])) {
        for (const lane of (bucket.lanes || [])) lanes.push(lane);
    }
    return lanes;
}

function _qlLaneLabel(laneId) {
    const found = _qlAllLanes().find(lane => lane.lane === laneId);
    return T(found ? (found.label || laneId) : laneId);
}

// Hard-stop ceilings in words: Sol has its own (95%), others share one. Label
// must match the `ql-hard` lines on the chart — both use the same numbers.
function _qlCeilingText(rule) {
    const own = Object.entries(rule.lane_hard_stop_pct || {})
        .filter(([, pct]) => Number.isFinite(Number(pct)))
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([lane, pct]) => `${_qlLaneLabel(lane)} ${_formatPercent(pct)}%`);
    const common = `${_formatPercent(rule.hard_stop_pct)}%`;
    return own.length ? `${own.join(', ')}, ${T('others')} ${common}` : common;
}

// Gate state — first thing readable from the panel (#V-547). Previously the
// diagonal lifted from ALL lanes differed from a working rule only by an italic
// badge note, so two different modes looked identical on the panel.
// Source is server's `rule.gated_lanes`: panel doesn't decide who gets gated.
function _qlGateState() {
    const rule = _quotaLinesData?.rule;
    // While connection is lost, panel verdict is already "—": printing a confident
    // "gate enabled" from a stale response would show outdated as current.
    if (Connection.ownsErrors() || !rule || !Array.isArray(rule.gated_lanes)) {
        return {state: 'nodata', text: T('gate: no data')};
    }
    const ceilings = _qlCeilingText(rule);
    // Manual lift by owner (#V-578) shown SEPARATELY from "rules are such":
    // otherwise temporary lift would silently stretch for three days unnoticed.
    const left = Number(rule.override_seconds_left) || 0;
    if (left > 0) {
        return {
            state: 'override',
            text: T('gate MANUALLY LIFTED — returns in {min} min · ceiling: {ceiling}', {
                min: Math.ceil(left / 60),
                ceiling: ceilings,
            }),
        };
    }
    if (!rule.gated_lanes.length) {
        return {
            state: 'off',
            text: T('gate LIFTED — diagonal holds no lanes, only ceiling remains: {ceiling}', {
                ceiling: ceilings,
            }),
        };
    }
    const held = rule.gated_lanes.map(_qlLaneLabel);
    const free = _qlAllLanes()
        .filter(lane => !rule.gated_lanes.includes(lane.lane))
        .map(lane => T(lane.label || lane.lane));
    const tail = free.length ? ` · ${T('outside gate')}: ${free.join(', ')}` : '';
    return {state: 'on', text: T('gate ON: {held}{tail} · ceiling: {ceiling}', {
        held: held.join(', '),
        tail,
        ceiling: ceilings,
    })};
}

function _qlTrace(bucket) {
    const trace = bucket?.trace;
    const points = trace && Array.isArray(trace.points) ? trace.points : [];
    const cleaned = [];
    for (const point of points) {
        const util = Number(point?.utilization);
        const progress = Number(point?.progress);
        if (!Number.isFinite(util) || !Number.isFinite(progress)) continue;
        cleaned.push({
            util,
            progress: Math.max(0, Math.min(1, progress)),
            x: _qlX(Math.max(0, Math.min(1, progress))),
            y: _qlY(util),
        });
    }
    return cleaned;
}

function _qlTone(verdict) {
    return verdict.nodata ? 'ql-nodata' : verdict.blocked ? 'ql-verdict-blocked' : 'ql-verdict-open';
}

function _qlPlaceY(baseY, usedBands, step = _QL_LABEL_STEP) {
    let y = Math.max(_QL_MT + _QL_LABEL_TOP_PAD, baseY);
    for (let tries = 0; tries < 8; tries++) {
        const top = y - 10;
        const bottom = y + 30;
        const collided = usedBands.some(([from, to]) => !(bottom < from || top > to));
        if (!collided) {
            usedBands.push([top, bottom]);
            return y;
        }
        y += step;
    }
    usedBands.push([y - 10, y + 30]);
    return y;
}

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
        tolerance: Number.isFinite(bucket.tolerance_pp) ? Number(bucket.tolerance_pp) : null,
        fresh: bucket.fresh !== false,
    };
}

function _qlLanes(panel) {
    const lanes = [];
    for (const id of panel.buckets) {
        const bucket = _qlBucket(id);
        for (const lane of (bucket?.lanes || [])) lanes.push({...lane, bucketId: id, bucket});
    }
    return lanes;
}

function _qlTimelineSvg(panel, rule) {
    const now = Date.parse(_quotaLinesData?.generated_at) || Date.now();
    const half = 84 * 60 * 60 * 1000;
    const from = now - half, to = now + half;
    const x = ts => _QL_ML + (ts - from) / (to - from) * _QL_PW;
    const y = _qlY;
    const p = [];
    const day = 86400000, zoneOffset = 7 * 3600000;
    const firstLocalDay = Math.floor((from + zoneOffset) / day) * day - zoneOffset;
    for (let start = firstLocalDay; start < to; start += day) {
        const nightStart = start;
        const nightEnd = start + 8 * 3600000;
        const left = Math.max(from, nightStart), right = Math.min(to, nightEnd);
        if (right > left) p.push(`<rect class="ql-night" x="${x(left)}" y="${_QL_MT}" width="${x(right)-x(left)}" height="${_QL_PH}"/>`);
    }
    for (let pct = 0; pct <= 100; pct += 20) {
        p.push(`<line class="ql-grid" x1="${_QL_ML}" y1="${y(pct)}" x2="${_QL_ML + _QL_PW}" y2="${y(pct)}"/>`);
        p.push(`<text class="ql-axis" x="${_QL_ML - 10}" y="${y(pct) + 4}" text-anchor="end">${pct}%</text>`);
    }
    const locale = typeof orchLang === 'function' && orchLang() === 'ru' ? 'ru-RU' : 'en-US';
    const tickFormat = new Intl.DateTimeFormat(locale, {timeZone: 'Asia/Krasnoyarsk', weekday: 'short', hour: '2-digit', hourCycle: 'h23'});
    const twoHours = 2 * 3600000;
    const firstTick = Math.ceil((from + zoneOffset) / twoHours) * twoHours - zoneOffset;
    for (let tick = firstTick; tick <= to; tick += twoHours) {
        const tx = x(tick), parts = Object.fromEntries(tickFormat.formatToParts(new Date(tick)).map(part => [part.type, part.value]));
        const hour = Number(parts.hour);
        const nightBoundary = hour === 0 || hour === 8;
        p.push(`<line class="ql-grid" data-ql-time-tick="${hour}" x1="${tx}" y1="${_QL_MT}" x2="${tx}" y2="${_QL_MT + _QL_PH}"/>`);
        if (nightBoundary) {
            p.push(`<text class="ql-axis ql-time-boundary" data-ql-time-boundary="${hour}" x="${tx}" y="${_QL_MT + _QL_PH + 8}" text-anchor="middle"><tspan x="${tx}">${_escHtml(parts.weekday)}</tspan><tspan x="${tx}" dy="12">${_escHtml(parts.hour)}:00</tspan></text>`);
        } else if (hour % 4 === 0) {
            p.push(`<text class="ql-axis" data-ql-time-label="${hour}" x="${tx}" y="${_QL_MT + _QL_PH + 34}" text-anchor="middle">${_escHtml(parts.hour)}</text>`);
        }
    }

    // Quota policy curves restart at each provider window boundary. Historical
    // intervals also split at the time each rule snapshot became effective.
    for (const bucket of panel.buckets.map(_qlBucket).filter(Boolean)) {
        const window = bucket.window;
        const reset = Date.parse(window?.resets_at);
        const duration = Number(window?.window_minutes) * 60000;
        if (!Number.isFinite(reset) || !(duration > 0)) continue;
        const cycles = [];
        for (let end = reset; end - duration < to; end += duration) cycles.push({end, span: duration});
        for (let end = reset - duration; end > from; end -= duration) cycles.push({end, span: duration});
        for (const {end, span} of cycles) {
            const start = end - span;
            const left = Math.max(from, start), right = Math.min(to, end);
            if (right <= left) continue;
            const progressAt = ts => Math.max(0, Math.min(1, (ts - start) / span));
            const baseline = [];
            for (let i = 0; i <= 50; i++) {
                const ts = left + (right - left) * i / 50, progress = progressAt(ts);
                baseline.push(`${x(ts)},${y(progress * 100)}`);
            }
            p.push(`<polyline class="ql-timeline-burn" points="${baseline.join(' ')}"/>`);
            const events = (_quotaLinesData?.rule_history || [])
                .map(event => Number(event.effective_from) * 1000)
                .filter(ts => Number.isFinite(ts) && ts > left && ts < right)
                .sort((a, b) => a - b);
            const cuts = [left, ...events, right];
            const lanes = new Set((bucket.lanes || []).map(lane => lane.lane));
            for (const event of (_quotaLinesData?.rule_history || [])) {
                for (const lane of (event.policy?.gated_lanes || [])) lanes.add(lane);
            }
            for (const lane of lanes) {
                for (let segment = 0; segment < cuts.length - 1; segment++) {
                    const segmentLeft = cuts[segment], segmentRight = cuts[segment + 1];
                    const active = _qlRuleAt((segmentLeft + segmentRight) / 2, now, rule,
                        _quotaLinesData?.rule_history);
                    const segmentRule = active.policy;
                    const gated = (segmentRule.gated_lanes || []).includes(lane);
                    if (gated) {
                        const coords = [];
                        for (let i = 0; i <= 50; i++) {
                            const ts = segmentLeft + (segmentRight - segmentLeft) * i / 50;
                            coords.push(`${x(ts)},${y(_qlMonotoneLimitAt(
                                progressAt(ts), segmentRule, lane, span / 60000, start,
                                _quotaLinesData?.rule_history, ts,
                            ))}`);
                        }
                        const colorClass = lane === 'sol' ? 'ql-gated-sol' : '';
                        p.push(`<polyline class="ql-gated ${colorClass}" data-ql-timeline-threshold="${_escHtml(lane)}" data-ql-policy-from="${_escHtml(active.effectiveFrom)}" data-ql-window-end="${end / 1000}" points="${coords.join(' ')}"/>`);
                    }
                    const stop = _qlHardStop(segmentRule, lane);
                    p.push(`<line class="ql-hard" data-ql-timeline-hard="${_escHtml(lane)}" data-ql-policy-from="${_escHtml(active.effectiveFrom)}" x1="${x(segmentLeft)}" y1="${y(stop)}" x2="${x(segmentRight)}" y2="${y(stop)}"/>`);
                }
            }
        }
    }
    // Facts stop at now. Add a current sample there; the right half is policy only.
    let pointIndex = 0;
    for (const lane of _qlLanes(panel)) {
        const point = _qlPoint(lane.bucket);
        if (!point) continue;
        const color = _QL_LANE_COLORS[lane.lane] || 'var(--ink)';
        p.push(`<circle data-ql-timeline-point="${_escHtml(lane.lane)}" cx="${x(now)}" cy="${y(point.util)}" r="${5.5 + pointIndex * 2}" fill="none" stroke="${color}" stroke-width="2.5"><title>${_escHtml(T(lane.label || lane.lane))}: ${_formatPercent(point.util)}%</title></circle>`);
        pointIndex++;
    }
    p.push(`<line class="ql-now" x1="${x(now)}" y1="${_QL_MT}" x2="${x(now)}" y2="${_QL_MT + _QL_PH}"/>`);
    const histories = new Set();
    for (const bucket of panel.buckets.map(_qlBucket).filter(Boolean)) {
        if (histories.has(bucket.bucket)) continue;
        histories.add(bucket.bucket);
        const points = bucket.timeline?.points || [];
        const coords = points.map(point => [Number(point.ts) * 1000, Number(point.utilization)])
            .filter(([ts, util]) => Number.isFinite(ts) && Number.isFinite(util) && ts >= from && ts <= now)
            .map(([ts, util]) => `${x(ts)},${y(util)}`);
        const current = _qlPoint(bucket);
        if (current) coords.push(`${x(now)},${y(current.util)}`);
        if (coords.length > 1) p.push(`<polyline class="ql-trace ql-trace-${bucket.bucket.replace('_', '-') }" data-ql-timeline-history="${_escHtml(bucket.bucket)}" points="${coords.join(' ')}"/>`);
    }
    return `<svg class="ql-chart" data-ql-timeline="${_escHtml(panel.key)}" viewBox="0 0 ${_QL_W} ${_QL_H}" preserveAspectRatio="xMidYMid meet">${p.join('')}</svg>`;
}

function _qlChartSvg(panel, rule) {
    const p = [];
    const claudeWindow = _qlBucket('anthropic')?.window;
    const claudeWindowMinutes = Number(claudeWindow?.window_minutes);
    const claudeReset = Date.parse(claudeWindow?.resets_at);
    const claudeWindowStart = Number.isFinite(claudeReset)
        && Number.isFinite(claudeWindowMinutes) && claudeWindowMinutes > 0
        ? claudeReset - claudeWindowMinutes * 60000
        : null;
    const limitAt = (t, lane) => _qlMonotoneLimitAt(
        t, rule, lane,
        lane === 'claude' ? claudeWindowMinutes : undefined,
        lane === 'claude' ? claudeWindowStart : null,
        _quotaLinesData?.rule_history,
        Number.isFinite(claudeWindowStart) ? claudeWindowStart + t * claudeWindowMinutes * 60000 : Date.now(),
    );

    for (let pct = 0; pct <= 100; pct += 20) {
        p.push(`<line class="ql-grid" x1="${_QL_ML}" y1="${_qlY(pct)}" x2="${_QL_ML + _QL_PW}" y2="${_qlY(pct)}"/>`);
        p.push(`<text class="ql-axis" x="${_QL_ML - 10}" y="${_qlY(pct) + 4}" text-anchor="end">${pct}%</text>`);
    }
    for (let d = 0; d <= 10; d++) {
        const t = d / 10;
        p.push(`<line class="ql-grid" x1="${_qlX(t)}" y1="${_QL_MT}" x2="${_qlX(t)}" y2="${_QL_MT + _QL_PH}"/>`);
        p.push(`<text class="ql-axis" x="${_qlX(t)}" y="${_QL_MT + _QL_PH + 19}" text-anchor="middle">${d * 10}%</text>`);
    }
    p.push(`<text class="ql-axis" x="${_QL_ML + _QL_PW / 2}" y="${_QL_H - 7}" text-anchor="middle">${T('window progress share')}</text>`);

    // Separate thresholds keep each lane's curve, cap and day/night profile accurate.
    const band = [], lineClaude = [], lineSol = [];
    for (let i = 0; i <= 100; i++) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(t * 100)}`); }
    for (let i = 100; i >= 0; i--) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(limitAt(t, 'claude'))}`); }
    for (let i = 0; i <= 100; i++) { const t = i / 100; lineClaude.push(`${_qlX(t)},${_qlY(limitAt(t, 'claude'))}`); }
    for (let i = 0; i <= 100; i++) { const t = i / 100; lineSol.push(`${_qlX(t)},${_qlY(limitAt(t, 'sol'))}`); }
    p.push(`<polygon class="ql-band" points="${band.join(' ')}"/>`);
    p.push(`<line class="ql-diag" x1="${_qlX(0)}" y1="${_qlY(0)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
    // Lifted diagonal drawn as ghost: solid line would imply a threshold that
    // blocks someone, but on this lane it's not applied right now.
    const gatedLanes = Array.isArray(rule.gated_lanes) ? rule.gated_lanes : [];
    const _ghost = lane => gatedLanes.includes(lane) ? '' : ' ql-gated-off';
    p.push(`<polyline class="ql-gated${_ghost('claude')}" data-ql-threshold="claude" points="${lineClaude.join(' ')}"/>`);
    if ((rule.curved_lanes || []).includes('sol')) {
        p.push(`<polyline class="ql-gated ql-gated-sol${_ghost('sol')}" data-ql-threshold="sol" points="${lineSol.join(' ')}"/>`);
        const solSuffix = gatedLanes.includes('sol') ? T(' — burning pool early') : T(' — lifted');
        const claudeSuffix = gatedLanes.includes('claude') ? '' : T(' — lifted');
        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.30)}" y="${_qlY(limitAt(0.30, 'sol')) - 9}" fill="#f472b6">${T('Sol threshold')}${solSuffix}</text>`);
        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.62)}" y="${_qlY(limitAt(0.62, 'claude')) + 17}" fill="#fb923c">${T('Claude threshold')}${claudeSuffix}</text>`);
    }

    const hard = Number(rule.hard_stop_pct);
    p.push(`<line class="ql-hard" x1="${_qlX(0)}" y1="${_qlY(hard)}" x2="${_qlX(1)}" y2="${_qlY(hard)}"/>`);
    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">${T('hard {pct}% — stop for lanes without own ceiling', {pct: _formatPercent(hard)})}</text>`);
    // Lane-specific line for lane with lower ceiling: one common line would lie
    // that the expensive lane runs to the last pool percent.
    for (const lane of _qlLanes(panel)) {
        const stop = _qlHardStop(rule, lane.lane);
        if (!(stop < hard)) continue;
        p.push(`<line class="ql-hard" data-ql-hard-lane="${_escHtml(lane.lane)}" x1="${_qlX(0)}" y1="${_qlY(stop)}" x2="${_qlX(1)}" y2="${_qlY(stop)}"/>`);
        p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(stop) - 7}" text-anchor="end" fill="#fdba74">${T('{label} — hard {pct}%', {label: _escHtml(T(lane.label || lane.lane)), pct: _formatPercent(stop)})}</text>`);
    }
    p.push(`<line class="ql-orch" x1="${_qlX(0)}" y1="${_qlY(100)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">${T('orchestrator always runs — no limit')}</text>`);

    const byBucket = [];
    for (const id of panel.buckets) {
        const bucket = _qlBucket(id);
        if (!bucket) continue;
        byBucket.push(bucket);
    }
    const lanes = _qlLanes(panel);
    const traceNotices = [];
    const traces = new Set();
    const usedLabelBands = [];
    // Пути строим по pool-решению (решающее окно): один пул — одна ломаная.
    for (const bucket of byBucket) {
        if (traces.has(bucket.bucket)) continue;
        traces.add(bucket.bucket);
        const point = _qlPoint(bucket);
        const points = _qlTrace(bucket);
        if (points.length < 2) {
            traceNotices.push({
                bucket: bucket.bucket,
                label: bucket.label || bucket.bucket,
            });
            if (point && point.progress === null) {
                p.push(`<line class="ql-noprogress" data-ql-flat="${_escHtml(bucket.bucket)}" x1="${_qlX(0)}" y1="${_qlY(point.util)}" x2="${_qlX(1)}" y2="${_qlY(point.util)}"/>`);
            }
            continue;
        }
        const traceClass = `ql-trace ql-trace-${bucket.bucket.replace('_', '-')}`;
        const tracePoints = points.map(item => `${item.x},${item.y}`).join(' ');
        p.push(`<polyline class="${traceClass}" points="${tracePoints}"/>`);
        if (point && point.progress === null) {
            p.push(`<line class="ql-noprogress" data-ql-flat="${_escHtml(bucket.bucket)}" x1="${_qlX(0)}" y1="${_qlY(point.util)}" x2="${_qlX(1)}" y2="${_qlY(point.util)}"/>`);
        }
    }

    for (let i = 0; i < lanes.length; i++) {
        const lane = lanes[i];
        const bucket = lane.bucket;
        const point = _qlPoint(bucket);
        if (!point) continue;
        if (point.progress === null) {
            if (i === 0) {
                p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(point.util) - 8}" fill="#e2e8f0">${T('{label}: reset time unknown — only hard {pct}%', {label: _escHtml(bucket.label || bucket.bucket), pct: _formatPercent(_qlHardStop(rule, lane.lane))})}</text>`);
            }
            continue;
        }
        const x = _qlX(point.progress), y = _qlY(point.util);
        p.push(`<line class="ql-cursor" x1="${x}" y1="${_QL_MT}" x2="${x}" y2="${_QL_MT + _QL_PH}"/>`);
        const offset = _QL_LANE_MARKERS[i] || _QL_LANE_MARKERS[0];
        const right = point.progress > 0.6;
        const dx = right ? -Math.abs(offset.dx) : offset.dx;
        const dy = offset.dy;
        const color = _QL_LANE_COLORS[lane.lane] || 'var(--ink)';
        const label = _escHtml(String(T(lane.label || lane.lane)));
        const markerClass = `ql-point-${lane.lane || 'lane'}`;
        const anchor = right ? 'end' : 'start';
        const hardY = _qlY(hard);
        const baseY = _qlY(point.util + 0);
        const rawLabelY = y + dy;
        const avoidHardY = Math.abs(baseY - hardY) < 8 || Math.abs(rawLabelY - hardY) < 28;
        const stackedLabelY = _qlPlaceY(avoidHardY ? hardY + 22 : rawLabelY, usedLabelBands);
        const stackedDetailY = _qlPlaceY(stackedLabelY + 15, usedLabelBands);
        p.push(`<circle data-ql-point="${_escHtml(lane.lane)}" class="${markerClass}" cx="${x}" cy="${y}" r="5.5" fill="none" stroke="${color}" stroke-width="2.5"/>`);
        // Threshold is a LANE property, not bucket: Sol follows curve, Claude straight,
        // Luna and Spark not gated at all. Printing bucket straight next to lane curve
        // would show user the wrong limit their workers get blocked by.
        const laneLimit = Number.isFinite(lane.limit_pct) ? Number(lane.limit_pct) : null;
        const head = T('actual {util}% · expected {expected}%', {util: _formatPercent(point.util), expected: _formatPercent(point.progress * 100)});
        const detail = !lane.gated
            ? T('{head} · diagonal not applied — only hard {pct}%', {head, pct: _formatPercent(_qlHardStop(rule, lane.lane))})
            : laneLimit === null
            ? T('{head} · no threshold', {head})
            : T('{head} · tolerance {tol} pp · threshold {thr}%', {head, tol: _formatPercent(point.tolerance, 1), thr: _formatPercent(laneLimit, 1)});
        p.push(`<text class="ql-halo ql-point-label" data-ql-label="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedLabelY}" text-anchor="${anchor}" fill="${color}">${label}${point.fresh ? '' : T(' (telemetry stale)')}</text>`);
        p.push(`<text class="ql-axis ql-halo" data-ql-detail="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedDetailY}" text-anchor="${anchor}">${detail}</text>`);
    }

    return {
        svg: `<svg class="ql-chart" data-ql-chart="${_escHtml(panel.key)}" viewBox="0 0 ${_QL_W} ${_QL_H}" preserveAspectRatio="xMidYMid meet">${p.join('')}</svg>`,
        traceNotices,
    };
}

// SINGLE verdict owner: both collapsed summary and panel body print text
// FROM HERE. They cannot diverge by construction — previously summary had
// its own branch and on response without `rule` block it drew "running"
// while body honestly said "no data".
// Label must directly state who runs and who stands — and not invent
// "running" when server said data_available=false.
function _qlVerdict(panel) {
    if (Connection.ownsErrors()) return {text: '—', nodata: true};
    if (_quotaLinesError) return {text: _quotaLinesError, nodata: true};
    if (!_quotaLinesData) return {text: T('allowance rule — loading…'), nodata: true};
    // Without rule constants the rule itself is unknown: verdict not computed
    // for anyone, including lanes where server sent ready `blocked`.
    if (!_quotaLinesData.rule) return {text: _QL_NO_RULE, nodata: true};
    if (!panel.buckets.map(_qlBucket).filter(Boolean).length) {
        return {text: T('no data — pool missing from server response'), nodata: true};
    }
    const lanes = _qlLanes(panel);
    const known = lanes.filter(l => l.bucket?.data_available
        && l.bucket.fresh !== false
        && l.release_status !== 'no_data');
    if (!lanes.length) return {text: T('no data — server did not send allowance lanes'), nodata: true};
    if (!known.length) return {text: T('no data — no pool telemetry, gate returns unknown'), nodata: true};
    const partial = known.length < lanes.length;
    if (partial) {
        return {text: T('no data — some lanes missing telemetry'), nodata: true, blocked: false};
    }
    const blocked = known.filter(l => l.blocked).map(l => T(l.label || l.lane));
    const open = known.filter(l => !l.blocked).map(l => T(l.label || l.lane));
    const parts = [];
    if (blocked.length) parts.push(T('{lanes} — blocked', {lanes: blocked.join(', ')}));
    if (open.length) parts.push(T('{lanes} — running', {lanes: open.join(', ')}));
    return {
        text: parts.join(' · '),
        nodata: false,
        blocked: blocked.length > 0,
    };
}

function _qlPanelHtml(panel) {
    const rule = _quotaLinesData?.rule;
    const verdict = _qlVerdict(panel);
    const buckets = panel.buckets.map(_qlBucket).filter(Boolean);
    if (!rule || !buckets.length) {
        return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
            <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
            <p class="ql-nodata" data-ql-verdict>${_escHtml(verdict.text)}</p>
        </section>`;
    }
    const lanes = _qlLanes(panel).map(lane => {
        const nodata = !lane.bucket?.data_available
            || lane.bucket.fresh === false
            || lane.release_status === 'no_data';
        const state = nodata ? 'nodata' : lane.blocked ? 'blocked' : 'open';
        const word = _qlLaneSummary(lane);
        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(T(lane.label || lane.lane))}: <b>${word}</b>${lane.gated ? '' : T(' <i>no diagonal</i>')}</span>`;
    }).join('');
    const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
        .map(l => `<li><b>${_escHtml(T(l.label || l.lane))}</b> — ${_escHtml(l.reason)}</li>`).join('');
    const chart = _qlChartSvg(panel, rule);
    const traceNotices = (chart.traceNotices || [])
        .map(item => `<div class="ql-trace-msg" data-ql-trace-msg="${_escHtml(item.bucket)}">${T('{label}: no history for this window', {label: _escHtml(item.label)})}</div>`)
        .join('');
    return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
        <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
        <div class="ql-head ql-timeline-head"><h4>${T('Quota timeline')}</h4><span>${T('±3.5 days · current time centered · Krasnoyarsk')}</span></div>
        ${_qlTimelineSvg(panel, rule)}
        ${chart.svg}
        <div class="ql-legend">
            <span><i style="background:#8595ab"></i>${T('steady burn')}</span>
            <span><i style="background:#f472b6"></i>${T('threshold for gated lanes')}</span>
            <span><i style="background:#fb923c"></i>${T('hard {pct}%', {pct: _formatPercent(rule.hard_stop_pct)})}</span>
            <span><i style="background:#818cf8"></i>${T('orchestrator — no limit')}</span>
        </div>
        ${traceNotices ? `<div class="ql-trace-notices">${traceNotices}</div>` : ''}
        <p class="ql-verdict ${_qlTone(verdict)}" data-ql-verdict>${_escHtml(verdict.text)}</p>
        <div class="ql-badges">${lanes}<span class="ql-badge ql-badge-always" data-ql-lane="orchestrator">${T('Orchestrator: <b>always runs</b>')}</span></div>
        ${reasons ? `<ul class="ql-reasons">${reasons}</ul>` : ''}
    </section>`;
}

// Summary — same verdicts, only shorter. Common failure (error, loading, no
// rule) gives both pools ONE text: no point printing it twice.
function _qlSummary() {
    const items = _QL_PANELS.map(panel => ({panel, verdict: _qlVerdict(panel)}));
    if (items.every(i => i.verdict.text === items[0].verdict.text)) {
        const verdict = items[0].verdict;
        return `<span class="ql-sum-item" data-ql-sum><span class="${_qlTone(verdict)}">${_escHtml(verdict.text)}</span></span>`;
    }
    return items.map(({panel, verdict}) =>
        `<span class="ql-sum-item" data-ql-sum><b>${_escHtml(panel.title)}:</b> <span class="${_qlTone(verdict)}">${_escHtml(verdict.text)}</span></span>`
    ).join('');
}

function renderQuotaLines() {
    const root = document.getElementById('quota-lines');
    if (!root) return;
    root.hidden = _quotaLinesOwnerOnly;
    const body = _QL_PANELS.map(_qlPanelHtml).join('');
    const gate = _qlGateState();
    const overrideOn = gate.state === 'override';
    // Button always present except on connection loss: pressing it blindly,
    // not knowing gate state, means lifting rule at random.
    const button = gate.state === 'nodata' ? '' :
        `<button type="button" id="quota-gate-override" class="ql-gate-btn">${overrideOn ? T('restore gate') : T('lift for 2 h')}</button>`;
    root.innerHTML = `
        <div class="ql-bar">
            <button type="button" id="quota-lines-toggle" aria-expanded="${_quotaLinesOpen}">${_quotaLinesOpen ? '▾' : '▸'} ${T('allowance rule')}</button>
            <span class="ql-gate ql-gate-${gate.state}" data-ql-gate="${gate.state}">${_escHtml(gate.text)}</span>
            ${button}
            <div class="ql-sum">${_qlSummary()}</div>
        </div>
        <div class="ql-body" ${_quotaLinesOpen ? '' : 'hidden'}>${body}</div>`;
    root.querySelector('#quota-lines-toggle').onclick = () => {
        _quotaLinesOpen = !_quotaLinesOpen;
        renderQuotaLines();
    };
    const overrideButton = root.querySelector('#quota-gate-override');
    if (overrideButton) {
        overrideButton.onclick = async () => {
            overrideButton.disabled = true;
            try {
                await api('/api/usage/quota-override', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({minutes: overrideOn ? 0 : 120}),
                });
            } finally {
                // State redraws from server response, not from our intent.
                _quotaMapData = null;
                await fetchQuotaLines();
            }
        };
    }
}

async function fetchQuotaLines() {
    try {
        const usageInFlight = typeof _usageFetchPromise !== 'undefined'
            ? _usageFetchPromise
            : null;
        let dataRaw;
        if (usageInFlight) {
            await usageInFlight;
            if (!_quotaMapData) throw new Error('quota-map request failed');
            dataRaw = _quotaMapData;
        } else {
            dataRaw = await _fetchQuotaMapShared();
        }
        const data = typeof dataRaw === 'string' ? JSON.parse(dataRaw) : dataRaw;
        _quotaLinesOwnerOnly = !!data && data.data_available === false && data.error === 'owner_mode_only';
        if (data && data.data_available === false) {
            _quotaLinesData = null;
            _quotaLinesError = T('no data — {error}', {error: data.error || T('server did not send quota map')});
        } else {
            _quotaLinesData = data;
            _quotaLinesError = '';
        }
    } catch (e) {
        _quotaLinesData = null;
        _quotaLinesError = T('no data — {error}', {error: e && e.message ? e.message : T('request failed')});
    }
    renderQuotaLines();
}

function initQuotaLines() {
    const bar = document.getElementById('usage-bar');
    if (!bar || document.getElementById('quota-lines')) return;
    const root = document.createElement('div');
    root.id = 'quota-lines';
    bar.insertAdjacentElement('afterend', root);
    renderQuotaLines();
    fetchQuotaLines();
    if (_quotaLinesTimer) clearInterval(_quotaLinesTimer);
    _quotaLinesTimer = setInterval(fetchQuotaLines, _QL_REFRESH_MS);
}



    return {
        init: initQuotaLines,
        fetch: fetchQuotaLines,
        render: renderQuotaLines,
        limitAt: _qlLimitAt,
        monotoneLimitAt: _qlMonotoneLimitAt,
        setErrorForTest(value) { _quotaLinesError = value || ''; renderQuotaLines(); },
    };
})();
