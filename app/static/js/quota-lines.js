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

const _QL_PANELS = [
    {key: 'all', title: 'Квоты пула', sub: 'одна шкала: доля пройденного окна, 0–100%',
     buckets: ['codex', 'codex_spark', 'anthropic']},
];

const _QL_NO_RULE = 'нет данных — сервер не прислал константы правила';

let _quotaLinesData = null;
let _quotaLinesError = '';
let _quotaLinesOpen = false;
let _quotaLinesTimer = null;

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
// берётся из bucket.limit_pct сервера, а не отсюда, — иначе панель и гейт разойдутся.
// `lane` обязателен для полос с кривой: Sol идёт по `t ** (1/exponent)`, Claude по прямой.
// Формула обязана совпадать с `line_limit` в app/quota_gate.py — расхождение здесь означает,
// что юзер видит на графике не тот порог, по которому его воркеров реально блокируют.
function _qlLimitAt(t, rule, lane) {
    const start = Number(rule.tolerance_start_pp), end = Number(rule.tolerance_end_pp);
    const exponent = Number(rule.curve_exponent) || 1;
    const curved = lane && (rule.curved_lanes || []).includes(lane) && exponent > 1;
    const norm = (curved && t > 0) ? Math.pow(t, 1 / exponent) : t;
    return Math.min(Number(rule.hard_stop_pct), norm * 100 + start + (end - start) * t);
}

function _qlBucket(bucketId) {
    return (_quotaLinesData?.buckets || []).find(b => b.bucket === bucketId) || null;
}

function _qlNum(value, digits = 0) {
    return Number(value).toFixed(digits);
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
        return hasSeconds ? `откроется через ${_qlDurationFromSeconds(seconds)}` : 'откроется скоро';
    }
    if (status === 'at_reset') {
        return hasSeconds
            ? `откроется при сбросе, через ${_qlDurationFromSeconds(seconds)}`
            : 'откроется при сбросе';
    }
    if (status === 'no_data') {
        return 'нет данных';
    }
    return 'работает';
}

function _qlLaneSummary(lane) {
    return _qlReleaseText(lane);
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
        limit: Number.isFinite(bucket.limit_pct) ? Number(bucket.limit_pct) : null,
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

function _qlChartSvg(panel, rule) {
    const p = [];

    for (let pct = 0; pct <= 100; pct += 20) {
        p.push(`<line class="ql-grid" x1="${_QL_ML}" y1="${_qlY(pct)}" x2="${_QL_ML + _QL_PW}" y2="${_qlY(pct)}"/>`);
        p.push(`<text class="ql-axis" x="${_QL_ML - 10}" y="${_qlY(pct) + 4}" text-anchor="end">${pct}%</text>`);
    }
    for (let d = 0; d <= 10; d++) {
        const t = d / 10;
        p.push(`<line class="ql-grid" x1="${_qlX(t)}" y1="${_QL_MT}" x2="${_qlX(t)}" y2="${_QL_MT + _QL_PH}"/>`);
        p.push(`<text class="ql-axis" x="${_qlX(t)}" y="${_QL_MT + _QL_PH + 19}" text-anchor="middle">${d * 10}%</text>`);
    }
    p.push(`<text class="ql-axis" x="${_QL_ML + _QL_PW / 2}" y="${_QL_H - 7}" text-anchor="middle">доля пройденного окна</text>`);

    // Порогов теперь ДВА, потому что Sol идёт по кривой, а Claude по прямой: одна общая
    // ломаная показывала бы половине воркеров чужой предел. Полосу заливки строим по
    // прямой — она нижняя из двух и означает «здесь не блокируют никого».
    const band = [], lineClaude = [], lineSol = [];
    for (let i = 0; i <= 100; i++) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(t * 100)}`); }
    for (let i = 100; i >= 0; i--) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule, 'claude'))}`); }
    for (let i = 0; i <= 100; i++) { const t = i / 100; lineClaude.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule, 'claude'))}`); }
    for (let i = 0; i <= 100; i++) { const t = i / 100; lineSol.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule, 'sol'))}`); }
    p.push(`<polygon class="ql-band" points="${band.join(' ')}"/>`);
    p.push(`<line class="ql-diag" x1="${_qlX(0)}" y1="${_qlY(0)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
    p.push(`<polyline class="ql-gated" points="${lineClaude.join(' ')}"/>`);
    if ((rule.curved_lanes || []).includes('sol')) {
        p.push(`<polyline class="ql-gated ql-gated-sol" points="${lineSol.join(' ')}"/>`);
        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.30)}" y="${_qlY(_qlLimitAt(0.30, rule, 'sol')) - 9}" fill="#f472b6">порог Sol — жжём пул рано</text>`);
        p.push(`<text class="ql-axis ql-halo" x="${_qlX(0.62)}" y="${_qlY(_qlLimitAt(0.62, rule, 'claude')) + 17}" fill="#fb923c">порог Claude</text>`);
    }

    const hard = Number(rule.hard_stop_pct);
    p.push(`<line class="ql-hard" x1="${_qlX(0)}" y1="${_qlY(hard)}" x2="${_qlX(1)}" y2="${_qlY(hard)}"/>`);
    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + _QL_PW - 4}" y="${_qlY(hard) - 7}" text-anchor="end" fill="#fdba74">жёсткие ${_qlNum(hard)}% — стоп для всех воркеров</text>`);
    p.push(`<line class="ql-orch" x1="${_qlX(0)}" y1="${_qlY(100)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
    p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(100) + 15}" fill="#c7d2fe">оркестратор работает всегда — предела нет</text>`);

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
                p.push(`<text class="ql-axis ql-halo" x="${_QL_ML + 6}" y="${_qlY(point.util) - 8}" fill="#e2e8f0">${_escHtml(bucket.label || bucket.bucket)}: срок сброса неизвестен — только жёсткие ${_qlNum(hard)}%</text>`);
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
        const label = _escHtml(String(lane.label || lane.lane));
        const markerClass = `ql-point-${lane.lane || 'lane'}`;
        const anchor = right ? 'end' : 'start';
        const hardY = _qlY(hard);
        const baseY = _qlY(point.util + 0);
        const rawLabelY = y + dy;
        const avoidHardY = Math.abs(baseY - hardY) < 8 || Math.abs(rawLabelY - hardY) < 28;
        const stackedLabelY = _qlPlaceY(avoidHardY ? hardY + 22 : rawLabelY, usedLabelBands);
        const stackedDetailY = _qlPlaceY(stackedLabelY + 15, usedLabelBands);
        p.push(`<circle data-ql-point="${_escHtml(lane.lane)}" class="${markerClass}" cx="${x}" cy="${y}" r="5.5" fill="none" stroke="${color}" stroke-width="2.5"/>`);
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
        p.push(`<text class="ql-halo ql-point-label" data-ql-label="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedLabelY}" text-anchor="${anchor}" fill="${color}">${label}${point.fresh ? '' : ' (телеметрия устарела)'}</text>`);
        p.push(`<text class="ql-axis ql-halo" data-ql-detail="${_escHtml(lane.lane)}" x="${x + dx}" y="${stackedDetailY}" text-anchor="${anchor}">${detail}</text>`);
    }

    return {
        svg: `<svg class="ql-chart" data-ql-chart="${_escHtml(panel.key)}" viewBox="0 0 ${_QL_W} ${_QL_H}" preserveAspectRatio="xMidYMid meet">${p.join('')}</svg>`,
        traceNotices,
    };
}

// ЕДИНСТВЕННЫЙ владелец вердикта: и сводка в свёрнутой строке, и тело панели
// печатают текст ОТСЮДА. Разойтись по смыслу они не могут по построению — раньше
// у сводки была своя ветка, и на ответе без блока `rule` она рисовала «работают»,
// пока тело честно говорило «нет данных».
// Подпись обязана прямо говорить, кто работает, а кто стоит, — и не выдумывать
// «работает», когда сервер сказал data_available=false.
function _qlVerdict(panel) {
    if (Connection.ownsErrors()) return {text: '—', nodata: true};
    if (_quotaLinesError) return {text: _quotaLinesError, nodata: true};
    if (!_quotaLinesData) return {text: 'правило допуска — загрузка…', nodata: true};
    // Без констант правила неизвестно само правило: вердикт не считается ни для
    // кого, включая полосы, у которых сервер прислал готовый `blocked`.
    if (!_quotaLinesData.rule) return {text: _QL_NO_RULE, nodata: true};
    if (!panel.buckets.map(_qlBucket).filter(Boolean).length) {
        return {text: 'нет данных — пул отсутствует в ответе сервера', nodata: true};
    }
    const lanes = _qlLanes(panel);
    const known = lanes.filter(l => l.bucket?.data_available
        && l.bucket.fresh !== false
        && l.release_status !== 'no_data');
    if (!lanes.length) return {text: 'нет данных — сервер не прислал полосы допуска', nodata: true};
    if (!known.length) return {text: 'нет данных — телеметрии пула нет, гейт отвечает unknown', nodata: true};
    const partial = known.length < lanes.length;
    if (partial) {
        return {text: 'нет данных — часть полос без телеметрии', nodata: true, blocked: false};
    }
    const blocked = known.filter(l => l.blocked).map(l => l.label || l.lane);
    const open = known.filter(l => !l.blocked).map(l => l.label || l.lane);
    const parts = [];
    if (blocked.length) parts.push(`${blocked.join(', ')} — стоят`);
    if (open.length) parts.push(`${open.join(', ')} — работают`);
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
        return `<span class="ql-badge ql-badge-${state}" data-ql-lane="${_escHtml(lane.lane)}">${_escHtml(lane.label || lane.lane)}: <b>${word}</b>${lane.gated ? '' : ' <i>без диагонали</i>'}</span>`;
    }).join('');
    const reasons = _qlLanes(panel).filter(l => l.blocked && l.reason)
        .map(l => `<li><b>${_escHtml(l.label || l.lane)}</b> — ${_escHtml(l.reason)}</li>`).join('');
    const chart = _qlChartSvg(panel, rule);
    const traceNotices = (chart.traceNotices || [])
        .map(item => `<div class="ql-trace-msg" data-ql-trace-msg="${_escHtml(item.bucket)}">${_escHtml(item.label)}: истории за это окно нет</div>`)
        .join('');
    return `<section class="ql-panel" data-ql-panel="${_escHtml(panel.key)}">
        <div class="ql-head"><h3>${_escHtml(panel.title)}</h3><span>${_escHtml(panel.sub)}</span></div>
        ${chart.svg}
        <div class="ql-legend">
            <span><i style="background:#8595ab"></i>равномерный расход</span>
            <span><i style="background:#f472b6"></i>порог гейтящихся полос</span>
            <span><i style="background:#fb923c"></i>жёсткие ${_qlNum(rule.hard_stop_pct)}%</span>
            <span><i style="background:#818cf8"></i>оркестратор — без предела</span>
        </div>
        ${traceNotices ? `<div class="ql-trace-notices">${traceNotices}</div>` : ''}
        <p class="ql-verdict ${_qlTone(verdict)}" data-ql-verdict>${_escHtml(verdict.text)}</p>
        <div class="ql-badges">${lanes}<span class="ql-badge ql-badge-always" data-ql-lane="orchestrator">Оркестратор: <b>всегда работает</b></span></div>
        ${reasons ? `<ul class="ql-reasons">${reasons}</ul>` : ''}
    </section>`;
}

// Сводка — те же вердикты, только короче. Общий отказ (ошибка, загрузка, нет
// правила) даёт обоим пулам ОДИН текст: печатать его дважды нечего.
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
    const body = _QL_PANELS.map(_qlPanelHtml).join('');
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
        if (data && data.data_available === false) {
            _quotaLinesData = null;
            _quotaLinesError = `нет данных — ${data.error || 'сервер не отдал карту квот'}`;
        } else {
            _quotaLinesData = data;
            _quotaLinesError = '';
        }
    } catch (e) {
        _quotaLinesData = null;
        _quotaLinesError = `нет данных — ${e && e.message ? e.message : 'запрос не выполнен'}`;
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
        setErrorForTest(value) { _quotaLinesError = value || ''; renderQuotaLines(); },
    };
})();
