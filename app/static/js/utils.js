/* utils.js — pure helpers, marked setup, autolink. Loaded before app.js. */

// Client task/payment amounts use the configured billing currency; model costs are stored in USD.
const CUR = document.body.dataset.currency || '₽';
const MODEL_COST_CURRENCY = '$';
const $ = (s) => document.querySelector(s);
const taskNum = (par) => String(par || '').replace(/^[A-Z]+-/, '');

const _PROVIDER_COLORS = {
    anthropic: '#fb923c', openai: '#22c55e', 'x-ai': '#e2e8f0',
    openrouter: '#a78bfa', deepseek: '#60a5fa', opencode: '#a78bfa',
    unknown: '#94a3b8',
};

// === Кеш последнего успешного ответа (#197) ===
// Канал юзера теряет ~17% TLS-хендшейков. Провал в середине сессии переживают те панели,
// что держат данные в памяти, а вот ЗАГРУЗКА страницы не переживает ничего: память пуста,
// и первый же недошедший запрос даёт «нет данных» вместо интерфейса. Поэтому снимок
// последнего успеха живёт в localStorage — он и есть то, что рисуется, пока сеть молчит.
// Возраст снимка показывается всегда: тихо подсунуть вчерашние цифры хуже, чем не подсунуть.
const _SNAPSHOT_PREFIX = 'orchestra_snapshot:';
// Старше суток не показываем даже с меткой: за сутки меняется всё, включая состав агентов.
const _SNAPSHOT_MAX_AGE_MS = 86400000;

function snapshotSave(key, data) {
    try {
        localStorage.setItem(_SNAPSHOT_PREFIX + key, JSON.stringify({ts: Date.now(), data}));
    } catch (e) {
        // Переполнение квоты localStorage — не повод ронять обновление интерфейса,
        // но и молчать нельзя: кеш просто перестал бы работать без единого слова.
        console.warn(`snapshot ${key}: не сохранён — ${e.name}: ${e.message}`);
    }
}

// null = снимка нет или он протух. Иначе {data, ts, ageMs}.
function snapshotLoad(key) {
    let raw;
    try {
        raw = localStorage.getItem(_SNAPSHOT_PREFIX + key);
    } catch (e) {
        console.warn(`snapshot ${key}: не прочитан — ${e.name}: ${e.message}`);
        return null;
    }
    if (!raw) return null;
    let parsed;
    try {
        parsed = JSON.parse(raw);
    } catch (e) {
        console.warn(`snapshot ${key}: битый JSON — ${e.name}`);
        return null;
    }
    const ts = Number(parsed?.ts);
    if (!ts || parsed?.data === undefined) return null;
    const ageMs = Date.now() - ts;
    if (ageMs < 0 || ageMs > _SNAPSHOT_MAX_AGE_MS) return null;
    return {data: parsed.data, ts, ageMs};
}

// «данные от 14:32» — метка времени, а не относительный возраст: юзер и так знает,
// который час, а «5 минут назад» надо держать в голове и пересчитывать.
function snapshotAgeLabel(ts) {
    const when = new Date(ts);
    const hh = String(when.getHours()).padStart(2, '0');
    const mm = String(when.getMinutes()).padStart(2, '0');
    return `данные от ${hh}:${mm}`;
}

// One table owns provider labels, capacity routing and window shapes for every usage view.
const _PROVIDER_META = {
    claude: {
        title: 'Claude Max', usageTitle: '☕ Claude Max', runtime: 'Opus · orchestrators',
        provider: 'anthropic', capacityKey: 'anthropic', tone: 'violet',
        usageAccent: '#38bdf8', windowAccent: '#38bdf8',
        historyProviders: ['anthropic'],
        windows: c => [['5h', c.five_hour, 300], ['7d', c.seven_day, 10080]],
    },
    codex: {
        title: 'Codex Pro', usageTitle: '✦ Codex Pro', compactTitle: 'Codex',
        runtime: 'Sol · workers', provider: 'openai', capacityKey: 'codex',
        tone: 'cyan', windowAccent: '#86efac',
        historyProviders: ['codex', 'codex_spark'],
        windows: c => [['Основной', c.primary], ['Вторичный', c.secondary]],
    },
    grok: {
        title: 'Grok', usageTitle: '𝕏 Grok', compactTitle: 'Grok',
        runtime: 'Grok 4.5 · workers', provider: 'x-ai', capacityKey: 'grok',
        tone: 'slate', windowAccent: '#cbd5e1',
        historyProviders: ['grok'],
        windows: c => [['7d', c.primary]],
    },
    opencode: {
        title: 'OpenCode', usageTitle: 'OpenCode',
        runtime: 'Explicit proxy models', provider: 'openrouter', capacityKey: null,
        tone: 'violet', windowAccent: '#a78bfa',
        historyProviders: ['openrouter', 'deepseek'],
        windows: () => [],
    },
    harness: {
        title: 'OpenRouter', usageTitle: 'OpenRouter',
        runtime: 'Own agent loop · free models', provider: 'openrouter', capacityKey: null,
        tone: 'violet', windowAccent: '#a78bfa',
        historyProviders: ['openrouter'],
        // Quota here is a REQUEST count per UTC day, not a rolling token window —
        // the openrouter bar in usage.js owns it (#368), so no window rows.
        windows: () => [],
    },
    unknown: {
        title: 'Unknown', usageTitle: 'Unknown runtime',
        runtime: 'Unclassified historical rows', provider: 'unknown', capacityKey: null,
        tone: 'slate', windowAccent: '#94a3b8',
        historyProviders: ['unknown'],
        windows: () => [],
    },
};
const _PROVIDER_CAPACITY_KEY = Object.fromEntries(
    Object.entries(_PROVIDER_META).map(([id, meta]) => [id, meta.capacityKey])
);

function _escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
// DOM-based escaping is safer than regex — handles all edge cases without a lookup table
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// Claude injects XML-style tags (e.g. <thinking>) — strip them before markdown render to avoid display noise
function _stripXmlTags(text) {
    return text.replace(/<\/?[a-z][a-z0-9_-]*(?:\s[^>]*)?\s*>/gi, '');
}

// Форматируем ТЕКСТ файла, а не разобранный объект: JSON.parse превращает целые больше
// 2^53 в ближайший double (19-значный id показывался как ...200 вместо ...147), и значение,
// скопированное из окна просмотра, было неверным. Числа и строки переносятся посимвольно,
// добавляются только отступы — раскладка та же, что у JSON.stringify(x, null, 2).
function _prettyJsonText(raw) {
    let out = '', depth = 0, inStr = false;
    for (let i = 0; i < raw.length; i++) {
        const ch = raw[i];
        if (inStr) {
            out += ch;
            if (ch === '\\') out += raw[++i];
            else if (ch === '"') inStr = false;
            continue;
        }
        if (ch === '"') { inStr = true; out += ch; continue; }
        if (ch === ' ' || ch === '\n' || ch === '\r' || ch === '\t') continue;
        if (ch === '{' || ch === '[') {
            const close = ch === '{' ? '}' : ']';
            let j = i + 1;
            while (j < raw.length && ' \n\r\t'.includes(raw[j])) j++;
            if (raw[j] === close) { out += ch + close; i = j; continue; }
            out += ch + '\n' + '  '.repeat(++depth);
        } else if (ch === '}' || ch === ']') {
            out += '\n' + '  '.repeat(--depth) + ch;
        } else if (ch === ',') {
            out += ',\n' + '  '.repeat(depth);
        } else if (ch === ':') {
            out += ': ';
        } else {
            out += ch;
        }
    }
    return out;
}

marked.setOptions({ breaks: true, gfm: true });

// Remove structural tags DOMPurify would leave as text nodes — they'd break layout if injected via agent output
DOMPurify.addHook('uponSanitizeElement', (node) => {
    if (['STYLE', 'HTML', 'HEAD', 'BODY', 'META', 'LINK', 'TITLE', 'SCRIPT'].includes(node.tagName)) node.remove();
});

const _autolinkRe = /(?<!\w)((?:https?:\/\/|ftp:\/\/)[^\s<>\]\)]+|(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:\/[^\s<>\]\)]*)?)(?!\w)/g;
// Walk only text nodes — skipping A/PRE/CODE avoids double-linking already-linked content and mangling code blocks
function autolinkText(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const walk = (node) => {
        if (node.nodeType === 3) {
            const t = node.textContent;
            if (!_autolinkRe.test(t)) return;
            // Reset lastIndex after test() — regex with /g retains state between calls
            _autolinkRe.lastIndex = 0;
            const frag = document.createDocumentFragment();
            let last = 0, m;
            while ((m = _autolinkRe.exec(t)) !== null) {
                if (m.index > last) frag.appendChild(document.createTextNode(t.slice(last, m.index)));
                const a = document.createElement('a');
                const href = m[0].match(/^https?:\/\/|^ftp:\/\//) ? m[0] : 'http://' + m[0];
                a.href = href;
                a.target = '_blank';
                a.rel = 'noopener';
                a.textContent = m[0];
                frag.appendChild(a);
                last = m.index + m[0].length;
            }
            if (last < t.length) frag.appendChild(document.createTextNode(t.slice(last)));
            node.parentNode.replaceChild(frag, node);
        } else if (node.nodeType === 1 && !['A', 'PRE', 'CODE', 'SCRIPT', 'STYLE'].includes(node.tagName)) {
            [...node.childNodes].forEach(walk);
        }
    };
    [...tmp.childNodes].forEach(walk);
    return tmp.innerHTML;
}

const _origMarkedParse = marked.parse.bind(marked);
// Patch marked.parse to: (1) escape lone ~ so marked doesn't misinterpret as strikethrough,
// (2) autolink bare URLs that marked leaves as plain text
marked.parse = (src, ...args) => {
    const escaped = src.replace(/(?<!\~)\~(?!\~)/g, '\\~');
    const html = _origMarkedParse(escaped, ...args);
    return autolinkText(html);
};

// Global click handler: inline code in markdown acts as a copy button,
// but if the content looks like a URL it opens in a new tab instead
document.addEventListener('click', (e) => {
    if (e.target.closest('a')) return;
    const code = e.target.closest('.markdown-body code');
    if (!code || code.closest('pre')) return;
    const text = code.textContent.trim();
    if (/^(https?:\/\/|ftp:\/\/)/.test(text) || /^(\d{1,3}\.){3}\d{1,3}(:\d+)?(\/\S*)?$/.test(text)) {
        const url = /^https?:\/\/|^ftp:\/\//.test(text) ? text : 'http://' + text;
        window.open(url, '_blank', 'noopener');
        return;
    }
    navigator.clipboard.writeText(text).then(() => {
        code.classList.add('code-copied');
        const toast = document.createElement('div');
        toast.className = 'copy-toast';
        toast.textContent = `Copied: ${text.length > 50 ? text.slice(0, 50) + '…' : text}`;
        document.body.appendChild(toast);
        setTimeout(() => { code.classList.remove('code-copied'); toast.remove(); }, 1200);
    });
});
