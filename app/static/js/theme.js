/* theme.js — дизайн-система в JS (V-876). Загружается до utils.js.
 *
 * Цвета здесь НЕ определяются: их единственный источник — токены в css/design-system.css.
 * Этот файл только отвечает «какой токен у этой модели / статуса / поставщика».
 * Для DOM отдаём `var(--token)` — браузер подставит значение сам; для canvas и
 * SVG-атрибутов, где var() не работает, — cssToken() с уже вычисленным значением.
 * Брендбук: docs/design-system.md.
 */

// Семейство модели по id, псевдониму или подписи: 'claude-opus-5-5[1m]', 'opus', 'Opus 5.5'.
// Spark раньше luna/sol: его id 'gpt-5.3-codex-spark' содержит «codex», а это псевдоним Sol.
const _MODEL_FAMILY_RULES = [
    ['spark', /spark/i],
    ['opus', /opus/i],
    ['sonnet', /sonnet/i],
    ['haiku', /haiku/i],
    ['fable', /fable|mythos/i],
    ['luna', /luna/i],
    ['astra', /astra/i],
    ['sol', /sol(?![a-z])|^codex$/i],
    ['grok', /grok/i],
];
// Каждый поставщик моделей обязан иметь токен --provider-<id> (tests/test_usage_analytics_frontend.py).
const _PROVIDER_COLORS = {
    anthropic: 'var(--provider-anthropic)', openai: 'var(--provider-openai)', 'x-ai': 'var(--provider-x-ai)',
    openrouter: 'var(--provider-openrouter)', gigachat: 'var(--provider-gigachat)', deepseek: 'var(--provider-deepseek)',
    multicode: 'var(--provider-multicode)', unknown: 'var(--provider-unknown)',
};

function modelFamily(id) {
    const text = String(id || '');
    for (const [family, rule] of _MODEL_FAMILY_RULES) {
        if (rule.test(text)) return family;
    }
    return null;
}

function _themeModelMeta(id) {
    return typeof _MODELS !== 'undefined' && Array.isArray(_MODELS) ? _MODELS.find(m => m.id === id) || null : null;
}

function providerColorVar(provider) {
    return _PROVIDER_COLORS[provider] || _PROVIDER_COLORS.unknown;
}

// Цвет модели для DOM: var(--model-<семейство>), иначе цвет её поставщика.
function modelColorVar(id, provider) {
    const meta = _themeModelMeta(id);
    const family = modelFamily(id) || modelFamily(meta?.label || meta?.name);
    return family ? `var(--model-${family})` : providerColorVar(provider || meta?.provider);
}

const _cssTokenCache = new Map();
// Вычисленное значение токена: '--model-opus' → '#fb923c'. Для canvas, Chart.js, SVG-атрибутов.
function cssToken(name, fallback = '') {
    if (!_cssTokenCache.has(name)) {
        const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        if (!value) return fallback;  // стили ещё не загружены — не кешировать пустоту
        _cssTokenCache.set(name, value);
    }
    return _cssTokenCache.get(name);
}

function _resolveVar(value) {
    const match = /^var\((--[\w-]+)\)$/.exec(value);
    return match ? cssToken(match[1], '#94a3b8') : value;
}

// Вычисленный цвет модели — там, где var() не подставится (canvas, SVG-атрибуты).
function modelColor(id, provider) {
    return _resolveVar(modelColorVar(id, provider));
}

function providerColor(provider) {
    return _resolveVar(providerColorVar(provider));
}

// Подпись модели: label из /api/models, иначе id без служебных хвостов.
function modelShortLabel(id) {
    const meta = _themeModelMeta(id);
    return meta?.label || String(id || '').replace('claude-', '').replace('[1m]', '').replace('-1m', '') || '?';
}

// Бейдж модели — один компонент для списка агентов, «Инфо», чата и вкладок.
function modelBadge(id, {label, pill = false, className = ''} = {}) {
    const badge = document.createElement('span');
    badge.className = `ds-model${pill ? ' ds-pill' : ''}${className ? ' ' + className : ''}`;
    badge.style.setProperty('--ds-c', modelColorVar(id));
    badge.textContent = label || modelShortLabel(id);
    badge.title = id || '';
    badge.dataset.modelFamily = modelFamily(id) || 'other';
    badge.dataset.i18nSkip = '1';  // имя модели — данные, не надпись
    return badge;
}

// Hub workers are sessions whose model id starts with `hub-` (MultiCode hub pool).
function isHubModel(id) {
    return typeof id === 'string' && id.startsWith('hub-');
}

function hubBadge() {
    const badge = document.createElement('span');
    badge.className = 'ds-model ds-pill';
    badge.style.setProperty('--ds-c', 'var(--provider-multicode)');
    badge.textContent = 'Hub';
    badge.title = 'MultiCode Hub';
    badge.dataset.hubBadge = '1';
    badge.dataset.i18nSkip = '1';
    return badge;
}

function modelBadgeHtml(id, opts = {}) {
    return modelBadge(id, opts).outerHTML;
}

// Один словарь статусов на весь дашборд — бейджи списка, вкладки оркестраторов, «Инфо», чат.
// Иконка несёт состояние, цвет его дублирует (idle/waiting по одному оттенку не различить).
const _STATUS_ICON = {running: '⚡', idle: '☕️', waiting: '📆', broken: '⛔'};
// broken красный, а не серый: это не «нет данных», а «задачу слать бесполезно».
// error/stopped/starting приходят только в выводе инструментов.
const _STATUS_COLOR = Object.fromEntries(
    ['running', 'idle', 'waiting', 'broken', 'error', 'stopped', 'starting']
        .map(status => [status, `var(--status-${status})`]),
);
const _STATUS_BG = Object.fromEntries(
    ['running', 'idle', 'waiting', 'broken'].map(status => [status, `var(--status-${status}-bg)`]),
);
// Геттеры: перевод берётся в момент показа, а theme.js может загрузиться раньше i18n.js.
const _STATUS_TITLE = {
    get running() { return T('running — agent is working on a task'); },
    get waiting() { return T('waiting — agent is waiting for a background task or confirmation'); },
    get idle() { return T('idle — agent is free'); },
    get broken() { return T('broken — agent worktree does not exist: sending tasks is useless, needs respawn'); },
};

function statusColor(status) {
    return _STATUS_COLOR[status] || _STATUS_COLOR.stopped;
}
