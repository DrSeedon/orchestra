// Cap DOM nodes to avoid memory growth during long agent sessions
// Потолок узлов в живой вкладке. 500 держалось «на глаз» и для чата оркестратора значит
// ≈109 000 px: замер 21.08 — 100 сообщений его журнала это 21 861 px, а за 12 часов
// набегает 554 строки, то есть вкладка упирается в потолок за полдня и дальше тормозит
// на каждом кадре. 200 узлов ≈ 44 000 px при той же странице входа в 100 сообщений;
// старшее уходит из DOM, но не из истории — оно возвращается кнопкой «загрузить ещё».
const MAX_CHAT_NODES = 200;
function fmtCost(v) { v = Number(v) || 0; if (v === 0) return MODEL_COST_CURRENCY + '0.00'; if (v < 0.01) return MODEL_COST_CURRENCY + v.toFixed(4); return MODEL_COST_CURRENCY + v.toFixed(2); }
const _MODEL_COLORS = {
    'claude-opus-5[1m]': '#d8b4fe',
    'claude-sonnet-5[1m]': '#38bdf8', 'claude-haiku-4-5': '#4ade80',
    'claude-fable-5[1m]': '#fb923c', 'gpt-5.5': '#f472b6', 'gpt-5.4': '#f472b6',
};
function _modelMeta(id) {
    return _MODELS.find(m => m.id === id) || null;
}
function _modelLabel(id) {
    const meta = _modelMeta(id);
    return meta?.label || id || '?';
}
function _modelColor(id) {
    const meta = _modelMeta(id);
    return _MODEL_COLORS[id] || _PROVIDER_COLORS[meta?.provider || 'unknown'] || '#94a3b8';
}
let currentScope = null;
let selectedAgent = null;
let chatLogs = {};
let currentSessions = [];

function _newChatLogState() {
    return {
        lastId: 0,
        firstId: null,
        canLoadOlder: false,
        olderPageLoaded: false,
    };
}
// localMessages tracks messages sent from this tab so SSE echo doesn't create duplicates
let localMessages = new Set();
let refreshController = null;
// UI debounce: rapid-fire messages from the user are batched into one send before the timer fires
const UI_DEBOUNCE_MS = 2500;
let scrollAfterLoad = true;
// Следуем ли за новыми сообщениями. Правило как в мессенджерах: внизу — следуем,
// ушёл читать выше — не трогаем вообще. Снимается в обработчике scroll.
let _chatFollow = true;
let _replayingHistory = false;
let _chatTrimLimit = MAX_CHAT_NODES;
let drafts = {};

const _CHAT_BOTTOM_GAP = 80;
const _CHAT_READ_RECEIPTS_KEY = 'orchestraChatReadReceipts';
let _pendingChatRestore = null;
let _chatHasNewBelow = false;
let _chatReadCaptureRaf = null;

function _chatPositionKey(scope = currentScope, agent = selectedAgent) {
    return scope && agent ? `${scope}\u0000${agent}` : '';
}

// Чтение scrollHeight/scrollTop/clientHeight заставляет браузер посчитать раскладку
// СИНХРОННО. На вставке сообщений это делалось на каждый узел (замер аудита: 6.9 мс на
// узел, 405 мс на пачку). В пределах одного кадра ответ измениться не может — юзер за
// кадр никуда не уехал, — поэтому меряем один раз и переиспользуем. Кеш живёт до конца
// кадра и сбрасывается любым скроллом: только он двигает положение по-настоящему.
let _atBottomCache = null;
function _chatAtBottom(chat = $('#chat')) {
    if (_atBottomCache !== null) return _atBottomCache;
    _atBottomCache = !chat || chat.scrollHeight - chat.scrollTop - chat.clientHeight < _CHAT_BOTTOM_GAP;
    requestAnimationFrame(() => { _atBottomCache = null; });
    return _atBottomCache;
}

function _chatReadReceipts() {
    try {
        const receipts = JSON.parse(sessionStorage.getItem(_CHAT_READ_RECEIPTS_KEY) || '{}');
        return receipts && typeof receipts === 'object' && !Array.isArray(receipts) ? receipts : {};
    } catch (e) {
        console.warn('Chat read receipts unavailable:', e.name, e.message);
        return {};
    }
}

function _chatReadReceipt(key) {
    const id = Number(_chatReadReceipts()[key]);
    return Number.isFinite(id) && id > 0 ? id : null;
}

function _saveChatReadReceipt(key, id) {
    if (!key || !Number.isFinite(id) || id <= 0) return;
    try {
        const receipts = _chatReadReceipts();
        if (Number(receipts[key]) >= id) return;
        receipts[key] = id;
        sessionStorage.setItem(_CHAT_READ_RECEIPTS_KEY, JSON.stringify(receipts));
    } catch (e) {
        console.warn('Chat read receipt save failed:', e.name, e.message);
    }
}

function _stampChatLogNode(node, payload) {
    const id = Number(payload?.id);
    if (!node || !Number.isFinite(id)) return;
    node.dataset.chatLogId = String(Math.max(id, Number(node.dataset.chatLogId) || 0));
}

// Обрезанное сообщение не должно выглядеть законченным. Маркер вешается в _insert —
// единственной воронке, через которую узлы попадают в чат, поэтому он один на все ветки
// отрисовки (текст, инструмент, картинка).
function _fmtKb(bytes) {
    return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} МБ` : `${Math.round(bytes / 1024)} КБ`;
}

function _toolResultImageSrc(content) {
    const data = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{100,})['"]/);
    if (!data) return '';
    const media = content.match(/['"]?media_type['"]?\s*[:=]\s*['"]([^'"]+)['"]/);
    return `data:${media?.[1] || 'image/png'};base64,${data[1].replace(/\s/g, '')}`;
}

function _loadImageSrc(img, src) {
    if (!src) return Promise.resolve(false);
    return new Promise(resolve => {
        const done = ok => {
            img.onload = null;
            img.onerror = null;
            resolve(ok);
        };
        img.onload = () => done(true);
        img.onerror = () => done(false);
        img.src = src;
    });
}

async function _restoreToolResultImage(img, payload) {
    if (!payload?.id) return false;
    try {
        const full = await api(`/api/logs/${payload.id}`);
        const src = _toolResultImageSrc(full.content || '');
        return _loadImageSrc(img, src);
    } catch (e) {
        console.warn(`Image result ${payload.id} unavailable: ${e.name}: ${e.message}`);
        return false;
    }
}

async function _loadToolResultImage(img, origPath, inlineSrc, payload) {
    if (origPath) {
        const rawSrc = `/api/files/raw?path=${encodeURIComponent(origPath)}&t=${Date.now()}`;
        if (await _loadImageSrc(img, rawSrc)) return true;
    }
    if (await _loadImageSrc(img, inlineSrc)) return true;
    return _restoreToolResultImage(img, payload);
}

const SEND_FILES_VISIBLE_LIMIT = 8;

function _sendFileName(path) {
    return String(path || '').split('/').pop() || '?';
}

function _sendFileRawUrl(path, download = false, preview = false) {
    return `/api/files/raw?path=${encodeURIComponent(path)}${download ? '&download=1' : preview ? '&preview=640' : ''}`;
}

// Форматы, которые браузер ОТКРЫВАЕТ, а не предлагает сохранить. Картинки сюда не входят:
// у них уже есть превью и лайтбокс по клику, вторая кнопка была бы дублем.
const _SEND_FILE_OPENABLE = /\.(html?|pdf|txt|md|json|csv|log|xml|ya?ml)$/i;

function _openSendFile(path) {
    // `download=1` НЕ ставим: именно этот флаг заставляет браузер сохранять вместо показа.
    window.open(_sendFileRawUrl(path), '_blank', 'noopener');
}

function _downloadSendFile(path) {
    const link = document.createElement('a');
    link.href = _sendFileRawUrl(path, true);
    link.download = _sendFileName(path);
    link.target = '_blank';
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
}

function _sendFileButton(label, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.style.cssText = 'padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid rgba(99,102,241,0.3);background:rgba(15,23,42,0.95);color:#a5b4fc;cursor:pointer;transition:all 0.15s;backdrop-filter:blur(8px)';
    button.onmouseenter = () => { button.style.borderColor = 'rgba(99,102,241,0.6)'; button.style.color = '#c7d2fe'; };
    button.onmouseleave = () => { button.style.borderColor = 'rgba(99,102,241,0.3)'; button.style.color = '#a5b4fc'; };
    button.onclick = onClick;
    return button;
}

function _sendFilePaths(node) {
    try {
        const paths = JSON.parse(node?.dataset.filePaths || '[]');
        return Array.isArray(paths) ? paths.filter(path => typeof path === 'string' && path) : [];
    } catch {
        return [];
    }
}

function renderSendFilesToolCard(node, paths, {downloads = false} = {}) {
    if (!node || !Array.isArray(paths)) return;
    const list = document.createElement('div');
    list.className = 'sf-file-list';
    list.style.cssText = 'display:flex;flex-direction:column;gap:5px;margin-top:5px';
    const rows = [];
    paths.forEach((path, index) => {
        const row = document.createElement('div');
        row.className = 'sf-file-item';
        row.style.cssText = 'display:flex;align-items:flex-start;gap:7px;flex-wrap:wrap;padding:3px 0';
        if (index >= SEND_FILES_VISIBLE_LIMIT) row.style.display = 'none';

        if (downloads && /\.(png|jpe?g|gif|webp|svg)$/i.test(path)) {
            const rawUrl = _sendFileRawUrl(path);
            const previewUrl = `${_sendFileRawUrl(path, false, true)}&t=${Date.now()}`;
            const img = document.createElement('img');
            img.className = 'sf-thumb';
            img.src = previewUrl;
            img.loading = 'lazy';
            img.decoding = 'async';
            img.alt = _sendFileName(path);
            img.style.cssText = 'display:block;width:44px;height:44px;object-fit:cover;border-radius:6px;cursor:pointer;border:1px solid rgba(99,102,241,0.2)';
            img.addEventListener('click', () => openImageLightbox(rawUrl));
            img.onerror = () => img.remove();
            row.appendChild(img);
        }

        const details = document.createElement('div');
        details.style.cssText = 'min-width:0;flex:1;overflow:hidden';
        const name = document.createElement('div');
        name.textContent = _sendFileName(path);
        name.style.cssText = 'font-size:11px;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        name.title = path;
        const pathEl = document.createElement('div');
        pathEl.textContent = path;
        pathEl.title = path;
        pathEl.style.cssText = 'font-size:10px;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        details.append(name, pathEl);
        row.appendChild(details);
        if (downloads && _SEND_FILE_OPENABLE.test(path)) {
            row.appendChild(_sendFileButton('🔗 Открыть', () => _openSendFile(path)));
        }
        if (downloads) row.appendChild(_sendFileButton('📥 Download', () => _downloadSendFile(path)));
        list.appendChild(row);
        rows.push(row);
    });

    if (paths.length > SEND_FILES_VISIBLE_LIMIT) {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'sf-list-toggle';
        toggle.textContent = `▼ Show all ${paths.length} files`;
        toggle.style.cssText = 'align-self:flex-start;padding:2px 8px;font-size:11px;border:0;background:transparent;color:#a5b4fc;cursor:pointer';
        let expanded = false;
        toggle.onclick = () => {
            expanded = !expanded;
            rows.slice(SEND_FILES_VISIBLE_LIMIT).forEach(row => { row.style.display = expanded ? 'flex' : 'none'; });
            toggle.textContent = expanded ? '▲ Show fewer files' : `▼ Show all ${paths.length} files`;
        };
        list.appendChild(toggle);
    }
    node.appendChild(list);
    if (downloads) {
        const actions = document.createElement('div');
        actions.className = 'sf-actions';
        actions.style.cssText = 'margin-top:4px;display:flex;gap:6px;flex-wrap:wrap';
        actions.appendChild(_sendFileButton('📥 Download all / Скачать все', () => paths.forEach(_downloadSendFile)));
        node.appendChild(actions);
    }
}

function _sendFilesResultInfo(content, fallbackCount = 0) {
    let parsed = null;
    try { parsed = JSON.parse(content); } catch {}
    const body = parsed && typeof parsed === 'object' && parsed.result !== undefined ? parsed.result : parsed;
    const text = typeof body === 'string' ? body : content;
    const hasError = Boolean(parsed && typeof parsed === 'object' && (parsed.error || parsed.ok === false))
        || /\b(error|failed|rejected|unknown)\b/i.test(text || '');
    let count = null;
    if (body && typeof body === 'object') {
        if (Array.isArray(body.files)) count = body.files.length;
        else for (const key of ['accepted_count', 'accepted', 'count']) {
            if (typeof body[key] !== 'boolean' && Number.isFinite(Number(body[key]))) {
                count = Number(body[key]);
                break;
            }
        }
    }
    const countMatch = String(text || '').match(/(\d+)\s+(?:files?|файл(?:а|ов)?)\b/i);
    if (count === null && countMatch) count = Number(countMatch[1]);
    if (count === null) count = hasError ? 0 : fallbackCount;
    return {hasError, count: Math.max(0, count)};
}

function _attachTruncNotice(node, row, type, ts) {
    const shown = new TextEncoder().encode(row.content || '').length;
    const notice = document.createElement('div');
    notice.className = 'trunc-notice';
    const text = document.createElement('span');
    text.textContent = `✂️ показано ${_fmtKb(shown)} из ${_fmtKb(row.trunc)}`;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'trunc-load';
    btn.textContent = 'загрузить целиком';
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'гружу…';
        let full;
        try {
            full = await api(`/api/logs/${row.id}`);
        } catch (e) {
            // Молчать нельзя: юзер нажал и должен увидеть, что именно не вышло.
            btn.disabled = false;
            btn.textContent = `не вышло (${e.name}) — ещё раз`;
            return;
        }
        // Рисуем заново той же функцией, что и всё остальное: одна отрисовка на все случаи.
        addChatEntry(type, full.content, ts, node, {...full, trunc: 0});
        node.remove();
    });
    notice.append(text, btn);
    node.appendChild(notice);
}

function _captureChatReadFrontier() {
    if (scrollAfterLoad) return;
    const chat = $('#chat');
    const key = _chatPositionKey();
    if (!chat || !key) return;
    const bounds = chat.getBoundingClientRect();
    let lastVisibleId = null;
    for (const node of chat.querySelectorAll(':scope > [data-chat-log-id]')) {
        const rect = node.getBoundingClientRect();
        if (rect.top < bounds.bottom - 1 && rect.bottom > bounds.top + 1) {
            lastVisibleId = Math.max(lastVisibleId || 0, Number(node.dataset.chatLogId));
        }
    }
    if (lastVisibleId) _saveChatReadReceipt(key, lastVisibleId);
}

function _scheduleChatReadCapture() {
    if (_chatReadCaptureRaf) cancelAnimationFrame(_chatReadCaptureRaf);
    _chatReadCaptureRaf = requestAnimationFrame(() => {
        _chatReadCaptureRaf = null;
        _captureChatReadFrontier();
    });
}

function _syncChatJumpButton() {
    const chat = $('#chat');
    const button = $('#chat-jump-latest');
    if (!chat || !button) return;
    if (chat.scrollHeight <= chat.clientHeight + 1 || _chatAtBottom(chat)) {
        _chatHasNewBelow = false;
        button.classList.add('hidden');
        return;
    }
    button.textContent = _chatHasNewBelow ? '↓ Новые ниже' : '↓ В конец';
    button.title = _chatHasNewBelow ? 'Ниже есть сообщения — перейти в конец' : 'Перейти в конец чата';
    button.classList.remove('hidden');
}

function _markChatHasNewBelow() {
    if (scrollAfterLoad || _chatAtBottom()) return;
    _chatHasNewBelow = true;
    _syncChatJumpButton();
}

// Держим низ, пока юзер внизу. Спрашивать _chatAtBottom() в момент вызова нельзя:
// содержимое уже выросло, и мы формально «не внизу» — решает состояние _chatFollow,
// снятое обработчиком scroll ДО роста. Склейка через rAF: поток дописывает текст
// десятками мутаций подряд, а прижать достаточно один раз за кадр.
let _followPinRaf = null;
// Поднимается обработчиками ввода и означает «следующее событие scroll — от юзера».
let _userScrolled = false;
function _pinChatBottom(chat) {
    chat.scrollTop = chat.scrollHeight;
}

// Срезать самые старые узлы. Режем ТОЛЬКО когда юзер внизу и следует за потоком:
// иначе кнопка «загрузить ещё» бессмысленна — добранная история исчезала бы от первого
// же нового сообщения, и текст под курсором прыгал бы вверх на высоту срезанного.
// Прокрутка вверх раньше выключала обрезку ЦЕЛИКОМ, и при чтении истории узлы копились
// без предела — отсюда лаги на длинных диалогах. Режем всегда, меняется только КОНЕЦ:
// следуешь за потоком — уходит самое старое; читаешь историю — уходит хвост снизу,
// который сейчас не на экране. Обе стороны сохраняют узел под курсором на месте.
const MAX_CHAT_NODES_DETACHED = 300;
function _trimChatNodes(chat) {
    if (!chat || _replayingHistory) return;
    if (_chatFollow) {
        while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
        return;
    }
    const limit = Math.max(MAX_CHAT_NODES_DETACHED, _chatTrimLimit);
    while (chat.children.length > limit) chat.removeChild(chat.lastChild);
}

function _collapseLoadedArchiveAtBottom(chat) {
    if (!_chatFollow || typeof _chatTrimLimit === 'undefined'
        || _chatTrimLimit === MAX_CHAT_NODES) return;
    _chatTrimLimit = MAX_CHAT_NODES;
    _trimChatNodes(chat);
}
function _keepPinnedIfFollowing() {
    if (!_chatFollow || _followPinRaf) return;
    _followPinRaf = requestAnimationFrame(() => {
        _followPinRaf = null;
        const chat = $('#chat');
        if (_chatFollow && chat) _pinChatBottom(chat);
    });
}

function _scrollChatToBottom(behavior = 'auto') {
    const chat = $('#chat');
    if (!chat) return;
    _chatHasNewBelow = false;
    _chatFollow = true;
    _collapseLoadedArchiveAtBottom(chat);
    chat.scrollTo({top: chat.scrollHeight, behavior});
    _syncChatJumpButton();
}

let _chatTimelineObserver = null;
let _chatTimelineSizeObserver = null;
let _chatTimelineHeightRaf = 0;
// Ниже метка перестаёт быть кликабельной мишенью; на длинной ленте пол ужимается
// пропорционально, потому что сумма полов не может превысить дорожку.
const CHAT_MARKER_MIN_PX = 3;

const NOTIFY_USER_TOOL = 'mcp__orchestra__notify_user';
const SILENT_TURN_MARKER = '[[ORCHESTRA:SILENT_TURN]]';
const FINAL_AGENT_TEXT_MIN_LENGTH = 200;  // ≈200 visible chars: useful turn summary, not short chatter

function _isSilentTurnMarker(type, content) {
    return type === 'text' && content === SILENT_TURN_MARKER;
}

// Оркестратор зовёт юзера ТОЛЬКО этим вызовом (#241), поэтому таких строк мало и они
// и есть «свежее», ради которого юзер иначе пролистывал бы весь поток.
function _isNotifyUserNode(node) {
    return (node?.dataset.toolRawName || node?.dataset.toolRaw) === NOTIFY_USER_TOOL;
}

function _notifyUserReason(node) {
    const content = node?.dataset.toolContent || '';
    const colonIdx = content.indexOf(':');
    if (colonIdx < 0) return '';
    try { return JSON.parse(content.slice(colonIdx + 1)).reason || ''; } catch { return ''; }
}

// Строку разбираем ДО отрисовки: про уведомление решает живой поток, а не готовый узел.
function _callRowReason(row) {
    if (row?.type !== 'tool') return null;
    const content = typeof row.content === 'string' ? row.content : '';
    const colonIdx = content.indexOf(':');
    if (colonIdx < 0) return null;
    if (canonicalToolName(content.slice(0, colonIdx).trim()) !== NOTIFY_USER_TOOL) return null;
    try { return JSON.parse(content.slice(colonIdx + 1)).reason || ''; } catch { return ''; }
}

// Один зов — одно уведомление: поток переподключается, история дорисовывается сверху, и
// одна и та же строка приходит не раз. Ключ — id строки журнала, он глобальный.
const _notifiedCallIds = new Set();
let _notifyLiveArmed = false;
let _notifyArmTimer = null;

function _armCallNotifications(lastId) {
    clearTimeout(_notifyArmTimer);
    // История уже на экране → поток отдаёт только строки новее неё, всё пришедшее настоящее.
    _notifyLiveArmed = lastId > 0;
    // Запасной режим (истории нет, её везёт сам поток): пачка приходит сразу за подключением,
    // поэтому взводимся после неё, а не молчим до следующего реконнекта.
    if (!_notifyLiveArmed) _notifyArmTimer = setTimeout(() => { _notifyLiveArmed = true; }, 2000);
}

function _maybeNotifyCall(row, agent) {
    const reason = _callRowReason(row);
    if (reason === null || !_notifyLiveArmed) return null;
    const id = Number(row.id);
    if (!Number.isFinite(id) || _notifiedCallIds.has(id)) return null;
    _notifiedCallIds.add(id);
    if (!('Notification' in window) || Notification.permission !== 'granted') return null;
    const notification = new Notification(`🔔 ${agent || 'Оркестратор'} зовёт`, {
        body: reason || 'без пояснения',
        tag: `orchestra-call-${id}`,   // вторая защита от дубля, уже на стороне ОС
        requireInteraction: true,      // юзера нет у экрана — зов не должен успеть исчезнуть
    });
    notification.onclick = () => {
        window.focus();
        const node = $('#chat')?.querySelector(`[data-chat-log-id="${id}"]`);
        if (node) _jumpChatTimelineNode(node, node._chatTimelineMarker);
        notification.close();
    };
    return notification;
}

// Разрешение просим ТОЛЬКО по клику: запрос, всплывший на загрузке, юзер отклонит один раз —
// и канал потерян навсегда, второй раз браузер не спросит.
function _addNotifyPermissionBtn() {
    const timeline = $('#chat-timeline');
    if (!timeline || $('#chat-notify-permission')) return;
    if (!('Notification' in window) || Notification.permission !== 'default') return;
    const btn = document.createElement('button');
    btn.id = 'chat-notify-permission';
    btn.type = 'button';
    btn.className = 'chat-notify-permission';
    btn.textContent = '🔔';
    btn.title = 'Включить уведомления браузера о зовах оркестратора';
    btn.setAttribute('aria-label', btn.title);
    btn.addEventListener('click', async () => {
        try { await Notification.requestPermission(); } catch (e) { console.warn('Notification permission:', e.name, e.message); }
        btn.remove();   // решение принято — второй раз браузер всё равно не спросит
    });
    timeline.prepend(btn);
}

function _chatTimelineKind(type, node) {
    if (type === 'user_message') return node.dataset.from ? 'worker' : 'user';
    if (type === 'tool' && _isNotifyUserNode(node)) return 'notify';
    if (type === 'tool' || type === 'tool_result') return 'tool';
    if (type === 'error') return 'error';
    if (type.includes('subagent') || type.includes('background')) return 'worker';
    if (type === 'system' || type === 'notification' || type === 'status') return 'status';
    return 'agent';
}

function _chatTimelineText(node) {
    const copy = node.cloneNode(true);
    copy.querySelectorAll('.chat-time, .copy-btn, .typing-cursor, .trunc-notice').forEach(el => el.remove());
    return copy.textContent.trim();
}

function _isChatTimelineAgentText(node) {
    return ['text', 'assistant', 'stream'].includes(node?.dataset.chatTimelineType)
        && !node.dataset.chatTimelineService;
}

function _chatTimelineLabel(node, kind) {
    const labels = {user: 'Моё сообщение', worker: 'Сообщение воркера', tool: 'Инструмент',
                    error: 'Ошибка', status: 'Статус', agent: 'Ответ агента',
                    final: 'Итоговый ответ', notify: 'Оркестратор зовёт'};
    const reason = kind === 'notify' ? _notifyUserReason(node) : '';
    return reason
        ? `${labels[kind]}: ${reason}${node.dataset.chatNavTime || ''}`
        : `${labels[kind]}${node.dataset.chatNavTime || ''}`;
}

function _setChatTimelineNodeKind(node, kind) {
    if (!node?.dataset.chatNavKind) return;
    node.dataset.chatNavKind = kind;
    const marker = node._chatTimelineMarker;
    if (!marker) return;
    marker.className = `chat-timeline-marker is-${kind}`;
    const label = _chatTimelineLabel(node, kind);
    node.dataset.chatNavLabel = label;
    marker.title = label;
    marker.setAttribute('aria-label', label);
}

// Keep one final candidate per user/worker-delimited turn; a later text replaces it.
// This also handles history prepends.
function _recomputeChatTimelineFinals() {
    const chat = $('#chat');
    if (!chat) return;
    const finalNodes = new Set();
    let latestText = null;
    for (const node of chat.children) {
        if (node.dataset.chatTimelineType === 'user_message') {
            if (latestText) finalNodes.add(latestText);
            latestText = null;
        } else if (_isChatTimelineAgentText(node)) {
            latestText = node;
        }
    }
    if (latestText) finalNodes.add(latestText);
    for (const node of chat.children) {
        if (node.dataset.chatNavBaseKind) {
            const final = finalNodes.has(node)
                && _chatTimelineText(node).length >= FINAL_AGENT_TEXT_MIN_LENGTH;
            _setChatTimelineNodeKind(node, final ? 'final' : node.dataset.chatNavBaseKind);
        }
    }
}

function _tagChatTimelineNode(node, type, ts) {
    if (!node || node.dataset.chatNavKind) return;
    const kind = _chatTimelineKind(type, node);
    let time = '';
    if (ts) {
        const date = new Date(ts);
        if (!Number.isNaN(date.getTime())) time = `, ${date.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'})}`;
    }
    node.dataset.chatTimelineType = type;
    node.dataset.chatNavBaseKind = kind;
    node.dataset.chatNavTime = time;
    node.dataset.chatNavKind = kind;
    node.dataset.chatNavLabel = _chatTimelineLabel(node, kind);
}

function _addChatTimelineMarker(node) {
    const track = $('#chat-timeline-track');
    if (!track || !node?.dataset.chatNavKind || node._chatTimelineMarker) return;
    const marker = document.createElement('button');
    const kind = node.dataset.chatNavKind;
    marker.type = 'button';
    marker.className = `chat-timeline-marker is-${kind}`;
    marker.title = node.dataset.chatNavLabel;
    marker.setAttribute('aria-label', node.dataset.chatNavLabel);
    marker.addEventListener('click', () => _jumpChatTimelineNode(node, marker));

    let previous = node.previousElementSibling;
    while (previous && !previous._chatTimelineMarker) previous = previous.previousElementSibling;
    if (previous?._chatTimelineMarker) {
        track.insertBefore(marker, previous._chatTimelineMarker.nextSibling);
    } else {
        track.prepend(marker);
    }
    node._chatTimelineMarker = marker;
    _chatTimelineSizeObserver?.observe(node);
}

function _removeChatTimelineMarker(node) {
    const marker = node?._chatTimelineMarker;
    if (!marker) return;
    _chatTimelineSizeObserver?.unobserve(node);
    marker.remove();
    node._chatTimelineMarker = null;
}

// Полоса — миникарта ленты: доля метки равна доле высоты её сообщения. Вес берём с
// ОТРИСОВАННОГО узла, а не с длины текста — таблица и картинка занимают экран, а
// символов в них мало. Раздаёт доли сам флексбокс, нам довольно выставить grow.
function _syncChatTimelineHeights() {
    const chat = $('#chat');
    const track = $('#chat-timeline-track');
    if (!chat || !track) return;
    const sized = [];
    let total = 0;
    for (const node of chat.children) {          // сперва читаем все высоты,
        const marker = node._chatTimelineMarker; // потом пишем — иначе layout thrashing
        if (!marker) continue;
        const height = node.offsetHeight;
        sized.push([marker, height]);
        total += height;
    }
    if (!sized.length) return;
    const trackHeight = track.clientHeight;
    if (trackHeight > 0) {
        track.style.setProperty('--chat-marker-min',
            `${Math.min(CHAT_MARKER_MIN_PX, trackHeight / sized.length).toFixed(2)}px`);
    }
    for (const [marker, height] of sized) {
        // Лента скрыта (все высоты нули) — раздаём поровну, иначе полоса схлопнется в полы.
        // Доли не нормируем: при сумме grow < 1 флексбокс раздал бы лишь её часть дорожки.
        marker.style.flexGrow = total > 0 ? height : 1;
    }
}

function _scheduleChatTimelineHeights() {
    if (_chatTimelineHeightRaf) return;
    _chatTimelineHeightRaf = requestAnimationFrame(() => {
        _chatTimelineHeightRaf = 0;
        _syncChatTimelineHeights();
    });
}

// Счёт берём из самой дорожки, а не из отдельных счётчиков: пара «инкремент при вставке /
// декремент при удалении» — вторая копия истины, которая расходится с нарисованным.
function _syncChatTimelineControls() {
    const track = $('#chat-timeline-track');
    for (const [cls, countId, prevId, nextId, label] of [
        ['is-user', '#chat-user-count', '#chat-user-prev', '#chat-user-next', 'Я'],
        ['is-notify', '#chat-notify-count', '#chat-notify-prev', '#chat-notify-next', '🔔'],
        ['is-final', '#chat-final-count', '#chat-final-prev', '#chat-final-next', '🏁'],
    ]) {
        const total = track ? track.querySelectorAll(`.${cls}`).length : 0;
        const count = $(countId);
        if (count) count.textContent = `${label} ${total}`;
        for (const id of [prevId, nextId]) {
            const button = $(id);
            if (button) button.disabled = total === 0;
        }
    }
    const notifyNav = $('#chat-notify-nav');
    // Зовов нет — полосу навигации не показываем вовсе, чтобы не занимала место впустую.
    if (notifyNav) notifyNav.classList.toggle('hidden', !track?.querySelector('.is-notify'));
    const finalNav = $('#chat-final-nav');
    if (finalNav) finalNav.classList.toggle('hidden', !track?.querySelector('.is-final'));
}

function _jumpChatTimelineNode(node, marker) {
    if (!node?.isConnected) return;
    clearTimeout(window._scrollResetTimer);
    scrollAfterLoad = false;
    _pendingChatRestore = null;
    _chatFollow = false;
    $('#chat-timeline-track')?.querySelector('.is-active')?.classList.remove('is-active');
    marker?.classList.add('is-active');
    node.scrollIntoView({block: 'center', behavior: 'smooth'});
    _syncChatJumpButton();
}

function _jumpChatTimelineKind(markerClass, direction) {
    const markers = [...document.querySelectorAll(`#chat-timeline-track .${markerClass}`)];
    if (!markers.length) return;
    const active = markers.findIndex(marker => marker.classList.contains('is-active'));
    const index = active < 0
        ? (direction < 0 ? markers.length - 1 : 0)
        : (active + direction + markers.length) % markers.length;
    const marker = markers[index];
    const node = [...$('#chat').children].find(child => child._chatTimelineMarker === marker);
    _jumpChatTimelineNode(node, marker);
}

// Полосу зовов строим здесь, а не в шаблоне: так вся фича живёт в одном файле и доезжает
// до юзера без рестарта, как и остальная статика.
function _addNotifyNav() {
    const timeline = $('#chat-timeline');
    if (!timeline || $('#chat-notify-nav')) return;
    const nav = document.createElement('div');
    nav.id = 'chat-notify-nav';
    nav.className = 'chat-timeline-user-nav is-notify-nav hidden';
    nav.innerHTML = `
        <button id="chat-notify-prev" type="button" title="Предыдущий зов оркестратора" aria-label="Предыдущий зов оркестратора">↑</button>
        <span id="chat-notify-count">🔔 0</span>
        <button id="chat-notify-next" type="button" title="Следующий зов оркестратора" aria-label="Следующий зов оркестратора">↓</button>`;
    timeline.prepend(nav);
}

function _addFinalNav() {
    const timeline = $('#chat-timeline');
    if (!timeline || $('#chat-final-nav')) return;
    const nav = document.createElement('div');
    nav.id = 'chat-final-nav';
    nav.className = 'chat-timeline-user-nav is-final-nav hidden';
    nav.innerHTML = `
        <button id="chat-final-prev" type="button" title="Предыдущий итоговый ответ" aria-label="Предыдущий итоговый ответ">↑</button>
        <span id="chat-final-count">🏁 0</span>
        <button id="chat-final-next" type="button" title="Следующий итоговый ответ" aria-label="Следующий итоговый ответ">↓</button>`;
    timeline.prepend(nav);
}

function initChatTimeline() {
    const chat = $('#chat');
    if (!chat || _chatTimelineObserver) return;
    _addNotifyPermissionBtn();
    _addNotifyNav();
    _addFinalNav();
    // Заводим ДО первого прохода по детям, иначе уже существующие узлы останутся без наблюдения.
    // Ловит и раскрытие/сворачивание, и догрузку картинки, и перенос текста при смене ширины.
    _chatTimelineSizeObserver = new ResizeObserver(_scheduleChatTimelineHeights);
    for (const node of chat.children) _addChatTimelineMarker(node);
    _recomputeChatTimelineFinals();
    _syncChatTimelineControls();
    _scheduleChatTimelineHeights();
    _chatTimelineObserver = new MutationObserver(records => {
        for (const record of records) {
            for (const node of record.removedNodes) if (node.nodeType === Node.ELEMENT_NODE) _removeChatTimelineMarker(node);
            for (const node of record.addedNodes) if (node.nodeType === Node.ELEMENT_NODE) _addChatTimelineMarker(node);
        }
        _recomputeChatTimelineFinals();
        _syncChatTimelineControls();
        _scheduleChatTimelineHeights();
    });
    _chatTimelineObserver.observe(chat, {childList: true});
    $('#chat-user-prev')?.addEventListener('click', () => _jumpChatTimelineKind('is-user', -1));
    $('#chat-user-next')?.addEventListener('click', () => _jumpChatTimelineKind('is-user', 1));
    $('#chat-notify-prev')?.addEventListener('click', () => _jumpChatTimelineKind('is-notify', -1));
    $('#chat-notify-next')?.addEventListener('click', () => _jumpChatTimelineKind('is-notify', 1));
    $('#chat-final-prev')?.addEventListener('click', () => _jumpChatTimelineKind('is-final', -1));
    $('#chat-final-next')?.addEventListener('click', () => _jumpChatTimelineKind('is-final', 1));
}

function _prepareChatAnchorRestore(hasUnread) {
    clearTimeout(window._scrollResetTimer);
    const key = _chatPositionKey();
    const afterId = hasUnread ? _chatReadReceipt(key) : null;
    _pendingChatRestore = afterId ? {key, afterId} : null;
    _chatHasNewBelow = false;
    $('#chat-jump-latest')?.classList.add('hidden');
}

function _restoreChatAnchor(key) {
    if (!key || key !== _pendingChatRestore?.key || key !== _chatPositionKey()) return;
    const {afterId} = _pendingChatRestore;
    _pendingChatRestore = null;
    const chat = $('#chat');
    if (!chat) return;
    const firstUnread = [...chat.querySelectorAll(':scope > [data-chat-log-id]')]
        .find(node => Number(node.dataset.chatLogId) > afterId);
    if (!firstUnread) {
        _scrollChatToBottom();
        return;
    }
    const divider = document.createElement('div');
    divider.className = 'chat-unread-divider';
    divider.textContent = 'Непрочитанные';
    chat.insertBefore(divider, firstUnread);
    // Разделитель — МЕТКА для того, кто листает вверх, а не цель прыжка. Прыжок к нему
    // открывал чат на сообщениях многодневной давности, и свежие «дорисовывались ниже»
    // (жалоба юзера 21.08). Открываем внизу, у последнего сообщения; кнопка «вниз»
    // при этом не нужна — ниже ничего не осталось.
    _scrollChatToBottom();
    _chatHasNewBelow = false;
    _syncChatJumpButton();
}

function _scheduleChatInitialSettle() {
    const key = _chatPositionKey();
    clearTimeout(window._scrollResetTimer);
    window._scrollResetTimer = setTimeout(() => {
        if (key !== _chatPositionKey()) return;
        scrollAfterLoad = false;
        _restoreChatAnchor(key);
        _syncChatJumpButton();
    }, 500);
}

// === Актуальный snapshot истории чата ===
// Единственный первый источник — серверный tail. Локальный кеш не может доказать, что
// после его watermark ничего не появилось, и поэтому непригоден для live-чата.
const _sessionIds = {};  // _chatPositionKey() -> session.id, сверяется с handshake SSE
// При первом открытии всегда просим последние 100 строк. Суммарный byte-budget здесь
// нарушал этот контракт и останавливал страницу на 35–70 строках. От одиночного blob
// по-прежнему защищает per-row cap; старшая история грузится отдельно по кнопке.
const _CHAT_PAGE = 100;
const _CHAT_ROW_CAP = 16384;

function initChatPositionMemory() {
    const chat = $('#chat');
    const button = $('#chat-jump-latest');
    if (!chat || !button || chat.dataset.positionReady === '1') return;
    chat.dataset.positionReady = '1';
    chat.addEventListener('scroll', () => {
        _atBottomCache = null;   // положение изменилось — кеш кадра больше не годится
        // Состояние следования меняет ТОЛЬКО ввод юзера (см. _userScrolled ниже).
        // По любому событию scroll его пересчитывать нельзя: браузерный scroll
        // anchoring сам подкручивает позицию при изменении высоты над вьюпортом и шлёт
        // такое же событие. Замер: высота +1326 px, scrollTop уехал +328 САМ, и
        // следование выключалось на ровном месте. Кнопку и отметку прочтения обновляем
        // в любом случае.
        if (_userScrolled) {
            _userScrolled = false;
            _chatFollow = _chatAtBottom(chat);
            _collapseLoadedArchiveAtBottom(chat);
        }
        _syncChatJumpButton();
        _scheduleChatReadCapture();
    }, {passive: true});
    // Ввод, которым юзер двигает чат: колесо, тач, клавиши, перетаскивание полосы.
    // Отпускание кнопки/пальца тоже считаем вводом — иначе после перетаскивания
    // полосы вниз состояние осталось бы от первого события середины жеста.
    for (const type of ['wheel', 'touchmove', 'touchend', 'keydown', 'pointerdown', 'pointerup']) {
        chat.addEventListener(type, () => {
            _userScrolled = true;
            // pointerup/touchend приходят ПОСЛЕ последнего scroll — пересчитываем сразу,
            // иначе состояние осталось бы от середины жеста.
            if (type === 'pointerup' || type === 'touchend') {
                _userScrolled = false;
                _chatFollow = _chatAtBottom(chat);
                _collapseLoadedArchiveAtBottom(chat);
                _syncChatJumpButton();
            }
        }, {passive: true});
    }
    // Высота растёт не только от новых узлов: поток дописывает текст в УЖЕ вставленный
    // блок инструмента, картинки и подсветка кода дорастают после вставки. На таких
    // изменениях никто не прижимал низ — замер на живом потоке: 44 строки, высота
    // 13583 → 14691, а вид уехал на 716 px от низа (то же самое и в main, это не
    // регрессия #59, а вторая половина той же задачи).
    new MutationObserver(_keepPinnedIfFollowing)
        .observe(chat, {childList: true, subtree: true, characterData: true});
    // Событие load не всплывает — отсюда capture.
    chat.addEventListener('load', _keepPinnedIfFollowing, true);
    button.addEventListener('click', () => _scrollChatToBottom('smooth'));
}

window.compactMode = localStorage.getItem('compactToolMode') === 'true';

function saveDraft() {
    if (selectedAgent) drafts[selectedAgent] = { text: $('#chat-input').value, images: [...pastedImages] };
}
function restoreDraft() {
    const d = drafts[selectedAgent] || {};
    $('#chat-input').value = d.text || '';
    clearPastePreview();
    if (d.images && d.images.length) {
        pastedImages = [...d.images];
        d.images.forEach(url => showImagePreview(url));
    }
}


document.addEventListener('DOMContentLoaded', () => {
    $('#send-btn').addEventListener('click', sendChat);
    $('#stop-btn').addEventListener('click', stopAgent);
    $('#chat-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    $('#chat-input').addEventListener('paste', handlePaste);
    $('#chat-input').addEventListener('input', () => {
        const text = $('#chat-input').value;
        const container = $('#paste-preview');
        if (!container) return;
        for (const w of [...container.querySelectorAll('[data-url]')]) {
            const fp = w.dataset.filePath || w.dataset.url;
            if (!text.includes(fp)) {
                w.remove();
                pastedImages = pastedImages.filter(u => u !== w.dataset.url);
            }
        }
        if (!container.children.length) container.remove();
    });
    const _rh = $('#input-resize-handle');
    if (_rh) {
        const _ta = $('#chat-input');
        let _ry, _rh0;
        _rh.addEventListener('mousedown', (e) => {
            _ry = e.clientY;
            _rh0 = _ta.offsetHeight;
            const onMove = (e) => { _ta.style.height = Math.max(40, Math.min(300, _rh0 + (_ry - e.clientY))) + 'px'; };
            const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
            e.preventDefault();
        });
    }
    $('#orch-picker').addEventListener('change', onOrchestratorChange);
    $('#new-orch-btn').addEventListener('click', () => {
        $('#new-orch-modal').classList.remove('hidden');
        $('#new-orch-modal').classList.add('flex');
        $('#project-picker').classList.add('hidden');
        loadProfilesDropdown();
        loadPipelinesDropdown();
        $('#orch-cwd').focus();
    });
    $('#orch-pipeline').addEventListener('change', populateRoleDropdown);
    $('#modal-close').addEventListener('click', closeModal);
    $('#new-orch-modal').addEventListener('click', (e) => {
        if (e.target === $('#new-orch-modal')) closeModal();
    });
    $('#create-orch-btn').addEventListener('click', createOrchestrator);
    $('#orch-cwd').addEventListener('input', () => {
        const path = $('#orch-cwd').value.trim();
        if (path && !$('#orch-name').value.trim()) {
            $('#orch-name').value = autoNameFromPath(path);
        }
    });
    $('#orch-cwd').addEventListener('change', () => {
        const path = $('#orch-cwd').value.trim();
        if (path) $('#orch-name').value = autoNameFromPath(path);
    });
    $('#browse-btn')?.addEventListener('click', showProjectPicker);
    initTabContextMenu();
    initHiddenTabsBtn();
    initChatDrop();
    initVoiceInput();
    initChatPositionMemory();
    initChatTimeline();
    $('#restart-btn').addEventListener('click', restartServer);
    // Client modal (available with auth)
    const clientBtn = document.getElementById('client-btn');
    if (clientBtn) clientBtn.addEventListener('click', openClientModal);
    const clientClose = document.getElementById('client-modal-close');
    if (clientClose) clientClose.addEventListener('click', closeClientModal);
    const clientModal = document.getElementById('client-modal');
    if (clientModal) clientModal.addEventListener('click', (e) => { if (e.target === clientModal) closeClientModal(); });
    initProfilesManager();
    $('#orch-name')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') createOrchestrator(); });
    $('#orch-cwd')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { if (!$('#orch-name').value.trim()) $('#orch-name').value = autoNameFromPath($('#orch-cwd').value); $('#orch-name').focus(); }});
    $('#view-prompt-btn').addEventListener('click', openPromptModal);
    $('#compact-btn').addEventListener('click', compactAgent);
    $('#restart-cli-btn').addEventListener('click', restartCli);
    $('#clear-session-btn')?.addEventListener('click', clearSession);
    $('#prompt-modal-close').addEventListener('click', closePromptModal);
    $('#prompt-modal').addEventListener('click', (e) => { if (e.target === $('#prompt-modal')) closePromptModal(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePromptModal(); closeFilePreview(); closeModal(); closeClientModal(); } });
    const compactBtn = $('#compact-toggle-btn');
    if (compactBtn) {
        const syncCompactButton = () => {
            compactBtn.textContent = window.compactMode ? '📋 Compact' : '📄 Normal';
            compactBtn.title = window.compactMode
                ? 'Tool view: compact. Switch to normal view'
                : 'Tool view: normal. Switch to compact view';
            compactBtn.setAttribute('aria-pressed', String(window.compactMode));
        };
        syncCompactButton();
        compactBtn.addEventListener('click', () => {
            window.compactMode = !window.compactMode;
            localStorage.setItem('compactToolMode', window.compactMode);
            syncCompactButton();
            _prepareChatAnchorRestore(false);
            _showChatFor(selectedAgent, currentScope);  // перерисовать всё в новом режиме
        });
    }
    const openFolderBtn = $('#open-folder-btn');
    if (openFolderBtn) {
        openFolderBtn.addEventListener('click', () => {
            if (currentScope) fetch('/api/open-folder', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: currentScope}) });
        });
    }
    loadModels();
    loadOrchestrators();
    _initPollingVisibility();
    scheduleRefresh();
    initFilePreviewModal();
    initUsageBar();
    QuotaPanel.init();
    PortfolioPanel.init();
    Connection.init();
    _startCacheCountdown();
});

let eventSource = null;

const _POLL_MAX_BACKOFF_MS = 120000;
// Ширина разведения фаз. Меньше самого частого интервала (3 с), чтобы сдвиг не
// превращался в заметную задержку обновления.
const _POLL_PHASE_SPREAD_MS = 900;
const _pollers = new Map();
const _pollTimers = new Map();
const _pollInFlight = new Map();
const _pollFailures = new Map();

function _pollCanRun() {
    return !document.hidden && navigator.onLine !== false;
}

// Фазовый сдвиг: у поллеров базы кратны друг другу (3000/5000/8000/10000/15000/60000),
// поэтому они регулярно совпадают и бьют пачкой в шесть соединений браузера, одно из
// которых навсегда держит SSE. Сдвиг детерминирован по имени ключа — он не «размазывает
// случайностью», а разводит поллеры по постоянным фазам, так что совпадение перестаёт
// быть периодическим. Замер 21.08: сам туннель прогоняет 20 параллельных запросов за
// 0.43 с, то есть узкое место — одновременность, а не канал.
function _pollPhase(key) {
    let h = 0;
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
    return Math.abs(h) % _POLL_PHASE_SPREAD_MS;
}

function _pollDelay(key, base) {
    const failures = _pollFailures.get(key) || 0;
    if (failures) return Math.min(base * (2 ** failures), _POLL_MAX_BACKOFF_MS);
    return base + _pollPhase(key);
}

function _pollNoteFailure(key, error) {
    if (!key || !error) return;
    const transient = navigator.onLine === false
        || ['TimeoutError', 'TypeError', 'AbortError'].includes(error.name)
        || (Number(error.status) >= 500 && Number(error.status) < 600);
    if (transient) _pollFailures.set(key, Math.min((_pollFailures.get(key) || 0) + 1, 8));
}

function _pollNoteSuccess(key) {
    if (key) _pollFailures.delete(key);
}

function _pollCoalesce(key, fn) {
    if (_pollInFlight.has(key)) return _pollInFlight.get(key);
    const request = Promise.resolve().then(fn).finally(() => _pollInFlight.delete(key));
    _pollInFlight.set(key, request);
    return request;
}

function _pollStop(key) {
    const timer = _pollTimers.get(key);
    if (timer) clearTimeout(timer);
    _pollTimers.delete(key);
    _pollers.delete(key);
}

function _pollSchedule(key, immediate = false) {
    const poller = _pollers.get(key);
    const requestKey = `poller:${key}`;
    if (!poller || !_pollCanRun() || _pollTimers.has(key) || _pollInFlight.has(requestKey)) return;
    const delay = immediate ? 0 : _pollDelay(key, poller.base);
    _pollTimers.set(key, setTimeout(async () => {
        _pollTimers.delete(key);
        if (!_pollCanRun()) return;
        try { await _pollCoalesce(requestKey, poller.fn); } catch (e) { _pollNoteFailure(key, e); }
        _pollSchedule(key);
    }, delay));
}

function _pollWake(key) {
    const timer = _pollTimers.get(key);
    if (timer) clearTimeout(timer);
    _pollTimers.delete(key);
    _pollSchedule(key, true);
}

function _pollRegister(key, fn, base, immediate = true) {
    _pollers.set(key, {fn, base});
    _pollSchedule(key, immediate);
}

function _pollWakeAll() {
    if (!_pollCanRun()) return;
    for (const key of _pollers.keys()) _pollWake(key);
    if (selectedAgent && currentScope && !eventSource) connectSSE();
}

function _initPollingVisibility() {
    const pause = () => {
        for (const timer of _pollTimers.values()) clearTimeout(timer);
        _pollTimers.clear();
    };
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) pause();
        else _pollWakeAll();
    });
    window.addEventListener('offline', pause);
    window.addEventListener('online', _pollWakeAll);
}

function scheduleRefresh() {
    _pollRegister('sessions', refreshSessions, 3000);
}

// Чей журнал сейчас в #chat. Сверяется с тем, что называет поток: сервер разрешает
// name+scope в session_id сам, и только он знает правду. Раньше здесь была проверка
// против _sessionIds, но она зависела от того, успел ли вернуться фоновый опрос
// (при TTFB до 4 с он в полёте почти всегда) — гонку выиграть нельзя, можно только
// перестать от неё зависеть.
let _chatSessionId = null;

// Поток говорит, что показываем чужую сессию: агента убили и подняли заново, или наша
// карта устарела. Стираем чат и грузим историю правильной сессии — молчать тут нельзя,
// иначе к старой истории допишется чужой хвост.
function _onForeignSession(agent, realId) {
    console.warn(`[chat] поток отдаёт сессию ${realId}, а показана ${_chatSessionId} — перезагружаю ${agent}`);
    if (eventSource) { eventSource.close(); eventSource = null; }
    _sessionIds[_chatPositionKey(currentScope, agent)] = realId;
    _chatSessionId = realId;
    _showChatFor(agent, currentScope);
}

// Пока история едет, eventSource намеренно null. Восстановительные вызовы connectSSE
// (фоновый опрос в refreshSessions, переподключение по ошибке) в этот момент открыли бы
// поток с after_id=0 — сервер выслал бы всю историю ещё раз, вторым несжатым потоком.
// Ловилось не всегда: зависит от того, попал ли трёхсекундный опрос в эту паузу.
let _chatLoading = false;

// SSE reconnects on error — server may restart mid-session, don't lose the log stream
function connectSSE(fromHistoryLoad) {
    if (_chatLoading && !fromHistoryLoad) return;
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (!selectedAgent || !currentScope || !_chatSnapshotReady) return;
    const targetAgent = selectedAgent;
    const targetScope = currentScope;
    const targetGeneration = _chatLoadGeneration;
    const lastId = chatLogs[selectedAgent]?.lastId || 0;
    // Пустая подтверждённая история — валидный snapshot. limit остаётся страховкой от
    // сообщения, вставленного между SELECT snapshot и подключением потока.
    const limitParam = lastId === 0 ? `&limit=${_CHAT_PAGE}` : '';
    _armCallNotifications(lastId);
    const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
    const source = new EventSource(url);
    eventSource = source;
    source.onmessage = (event) => {
        if (eventSource !== source
            || selectedAgent !== targetAgent
            || currentScope !== targetScope
            || targetGeneration !== _chatLoadGeneration) return;
        try {
            const l = JSON.parse(event.data);
            // Живые куски стрима идут без session_id — их пропускаем, их финал придёт
            // строкой журнала, и вот она уже будет подписана.
            if (l.session_id) {
                if (_chatSessionId && l.session_id !== _chatSessionId) return _onForeignSession(targetAgent, l.session_id);
                if (!_chatSessionId) _chatSessionId = l.session_id;
            }
            if (l.agent_status) _applyLiveAgentStatus(targetAgent, l.agent_status);
            else if (Number.isFinite(l.id)) _wakeStatusRefreshFromStream();
            if (l.type === '__session') return;  // рукопожатие: сессию уже сверили выше
            if (l.type === 'user_message' && localMessages.size > 0) {
                const isLocal = localMessages.has(l.content) ||
                    [...localMessages].some(m => l.content.endsWith(m)) ||
                    [...localMessages].some(m => l.content.includes(m));
                if (isLocal) {
                    for (const m of localMessages) {
                        if (l.content === m || l.content.endsWith(m) || l.content.includes(m)) {
                            localMessages.delete(m);
                            break;
                        }
                    }
                } else {
                    addChatEntry(l.type, l.content, l.ts, null, l);
                }
            } else {
                addChatEntry(l.type, l.content, l.ts, null, l);
            }
            _maybeNotifyCall(l, targetAgent);
            if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = _newChatLogState();
            // Live stream partials carry no id — skip id bookkeeping for them
            if (Number.isFinite(l.id)) {
                if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
                if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                    chatLogs[selectedAgent].firstId = l.id;
                }
            }
            // Следуем за новыми сообщениями ТОЛЬКО если юзер внизу — правило одно для
            // всех путей вставки. Раньше здесь стоял безусловный прыжок под флагом
            // scrollAfterLoad, а _scheduleChatInitialSettle перевзводил его таймер на
            // КАЖДОМ сообщении: у болтливого агента флаг не сбрасывался никогда, и чат
            // утаскивало вниз, даже когда юзер читал в 11 632 px от низа (замер #59).
            if (_chatAtBottom()) $('#chat').scrollTop = $('#chat').scrollHeight;
            if (scrollAfterLoad) _scheduleChatInitialSettle();
        } catch (e) { console.warn('SSE parse:', e); }
    };
    source.onerror = () => {
        source.close();
        // Закрытый старый EventSource иногда успевает прислать onerror уже после A→B.
        // Он не имеет права закрыть новый поток через глобальную переменную.
        if (eventSource !== source) return;
        eventSource = null;
        Connection.fail(`/api/sessions/${encodeURIComponent(targetAgent)}/stream`, new TypeError('SSE disconnected'));
        setTimeout(() => {
            if (selectedAgent === targetAgent
                && currentScope === targetScope
                && targetGeneration === _chatLoadGeneration) connectSSE();
        }, 2000);
    };
}

function _addLoadMoreBtn() {
    if ($('#load-more-btn')) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'load-more-btn';
    btn.className = 'w-full text-xs text-slate-500 hover:text-indigo-300 py-2 text-center cursor-pointer select-none';
    btn.textContent = '▲ Дозагрузить предыдущие 500';
    btn.addEventListener('click', loadMoreLogs);
    $('#chat').prepend(btn);
}
function updateLoadMoreBtn() {
    const meta = chatLogs[selectedAgent];
    const canLoadOlder = meta?.canLoadOlder ?? Boolean(meta?.firstId);
    if (!meta?.firstId || !canLoadOlder || meta.olderPageLoaded) {
        const existing = $('#load-more-btn');
        if (existing) existing.remove();
        return;
    }
    _addLoadMoreBtn();
}

async function loadMoreLogs() {
    if (!selectedAgent || !currentScope) return;
    const targetAgent = selectedAgent;
    const targetScope = currentScope;
    const targetGeneration = _chatLoadGeneration;
    const firstId = chatLogs[targetAgent]?.firstId;
    if (!firstId) return;
    const btn = $('#load-more-btn');
    if (btn) { btn.textContent = '⏳ Загружаю предыдущие сообщения…'; btn.disabled = true; }
    try {
        const q = new URLSearchParams({
            scope: targetScope,
            before_id: String(firstId),
            limit: '500',
            cap: String(_CHAT_ROW_CAP),
        });
        const logs = await api(
            `/api/sessions/${encodeURIComponent(targetAgent)}/logs?${q}`,
            {
                signal: _chatLoadController?.signal,
                priority: 'critical',
                cache: 'no-store',
            },
        );
        if (!_chatLoadIsCurrent(targetGeneration, targetAgent, targetScope)) return;
        if (!Array.isArray(logs)) throw new TypeError('older chat history response is not an array');
        chatLogs[targetAgent].olderPageLoaded = true;
        if (logs.length === 0) {
            if (btn) btn.remove();
            return;
        }
        const chat = $('#chat');
        const oldHeight = chat.scrollHeight;
        if (btn) btn.remove();
        // Пока юзер читает загруженный архив, нельзя возвращать обычный потолок: ветка
        // detached режет lastChild, то есть именно текущий хвост и новые SSE-сообщения.
        // Держим архив + прежний хвост + запас на 200 живых карточек. Когда юзер вернётся
        // вниз, _collapseLoadedArchiveAtBottom срежет старое СВЕРХУ до обычного лимита.
        _chatTrimLimit = Math.max(
            _chatTrimLimit,
            chat.children.length + logs.length + MAX_CHAT_NODES,
        );
        // prepend в правильном порядке (logs уже ASC из db)
        // фиксируем anchor = текущий firstChild, вставляем все перед ним по порядку
        const anchor = chat.firstChild;
        _replayingHistory = true;
        try {
            for (const l of logs) {
                addChatEntry(l.type, l.content, l.ts, anchor, l);
                if (!chatLogs[targetAgent]) chatLogs[targetAgent] = _newChatLogState();
                if (chatLogs[targetAgent].firstId === null || l.id < chatLogs[targetAgent].firstId) {
                    chatLogs[targetAgent].firstId = l.id;
                }
            }
        } finally {
            _replayingHistory = false;
        }
        chat.scrollTop = chat.scrollHeight - oldHeight;
    } catch (e) {
        if (!_chatLoadIsCurrent(targetGeneration, targetAgent, targetScope)) return;
        if (btn) { btn.textContent = '▲ Дозагрузить предыдущие 500'; btn.disabled = false; }
        console.warn('loadMoreLogs error:', e);
    }
}


// === Models ===
function _renderModels(data) {
    const models = data.models || [];
    _MODELS = models.map(m => ({ ...m, label: m.name }));
    _modelsLoaded = true;
    const select = $('#orch-model');
    if (select) {
        select.innerHTML = '';
        for (const m of models) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = `${m.name} (${m.id})`;
            select.appendChild(opt);
        }
    }
    _updateProxyStatus(data.proxy_connected);
}

async function _loadModelsNow() {
    try {
        const data = await api('/api/models', {pollKey: 'models'});
        _renderModels(data);
        snapshotSave('models', data);
    } catch (e) {
        // Каталог моделей почти статичен — снимок тут не «может пригодиться», а закрывает
        // дыру целиком: без него пустой селектор не даёт создать оркестратора вовсе.
        console.warn(`models: ${e.name}: ${e.message}`);
        if (_modelsLoaded) return;
        const snapshot = snapshotLoad('models');
        if (snapshot) _renderModels(snapshot.data);
    }
}

function loadModels() {
    return _pollCoalesce('models-request', _loadModelsNow);
}

// === Profile / Pipeline / Role dropdowns (модалка создания корня) ===
let _pipelineRoles = {};  // карта pipeline-name → [roles]

async function loadProfilesDropdown() {
    try {
        const profiles = await api('/api/profiles');
        const select = $('#orch-profile');
        select.innerHTML = '';
        for (const p of profiles) {
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = `${p.name} (${p.config_dir || 'env процесса'})`;
            select.appendChild(opt);
        }
        // API sorts by name (ORDER BY name), so first entry ≠ 'personal'.
        // Prefer 'personal' explicitly; fall back to whatever comes first.
        const def = profiles.find(p => p.name === 'personal') || profiles[0];
        if (def) select.value = def.name;
    } catch {}
}

async function loadPipelinesDropdown() {
    try {
        const pipelines = await api('/api/pipelines');
        const select = $('#orch-pipeline');
        select.innerHTML = '';
        _pipelineRoles = {};
        for (const p of pipelines) {
            _pipelineRoles[p.name] = p.roles || [];
            const opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = p.name;
            select.appendChild(opt);
        }
        populateRoleDropdown();
    } catch {}
}

function populateRoleDropdown() {
    const select = $('#orch-role');
    select.innerHTML = '';
    const roles = _pipelineRoles[$('#orch-pipeline').value] || [];
    for (const r of roles) {
        const opt = document.createElement('option');
        opt.value = r;
        opt.textContent = r;
        select.appendChild(opt);
    }
}

// === Modal ===
function closeModal() {
    $('#new-orch-modal').classList.add('hidden');
    $('#new-orch-modal').classList.remove('flex');
    $('#orch-error').classList.add('hidden');
}

function closePromptModal() {
    $('#prompt-modal').classList.add('hidden');
    $('#prompt-modal').classList.remove('flex');
}

async function compactAgent() {
    if (!selectedAgent || !currentScope) return;
    const btn = $('#compact-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        const res = await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/compact`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scope: currentScope}),
        });
        if (res.error) throw new Error(res.error);
        delete contextCache[`${currentScope}:${selectedAgent}`];
        await fetchAgentContext(selectedAgent);
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '🗜'; btn.disabled = false; }, 1500);
    } catch (e) {
        btn.textContent = '❌';
        setTimeout(() => { btn.textContent = '🗜'; btn.disabled = false; }, 2000);
    }
}

async function restartCli() {
    if (!selectedAgent || !currentScope) return;
    const targetName = selectedAgent;
    const targetScope = currentScope;
    const btn = $('#restart-cli-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        const result = await api(`/api/sessions/${encodeURIComponent(targetName)}/restart-cli`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scope: targetScope}),
        });
        if (result.unreconciled_deliveries) {
            alert(`${targetName}: очередь освобождена. Доставок с неизвестным исходом: ${result.unreconciled_deliveries}. Они НЕ отправлены повторно; проверь историю перед повторной отправкой.`);
        }
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 1500);
    } catch (e) {
        btn.textContent = '❌';
        alert(`${targetName}: CLI не перезапущен — ${e.message || String(e)}`);
        setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 2000);
    }
}

async function clearSession() {
    if (!selectedAgent || !currentScope) return;
    if (!confirm(`Очистить сессию «${selectedAgent}»?\n\nАгент забудет весь разговор и начнёт с чистого листа.\nWorktree, ветка и промпт не пострадают.`)) return;
    const btn = $('#clear-session-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/clear-session`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scope: currentScope}),
        });
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '🧹'; btn.disabled = false; }, 1500);
    } catch (e) {
        btn.textContent = '❌';
        setTimeout(() => { btn.textContent = '🧹'; btn.disabled = false; }, 2000);
    }
}

async function openPromptModal() {
    if (!selectedAgent || !currentScope) return;
    const modal = $('#prompt-modal');
    const body = $('#prompt-modal-body');
    $('#prompt-modal-name').textContent = selectedAgent;
    body.innerHTML = '<span class="text-slate-500 text-xs">Loading...</span>';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    try {
        const blocks = await api(`/api/sessions/${selectedAgent}/prompt-blocks?scope=${encodeURIComponent(currentScope)}`);
        if (!Array.isArray(blocks) || blocks.length === 0) {
            body.innerHTML = '<span class="text-slate-500 italic text-xs">No system prompt</span>';
            return;
        }
        _renderPromptBlocks(body, blocks, true);
    } catch (e) {
        body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
    }
}

function _renderPromptBlocks(container, blocks) {
    const TYPE_COLORS = { file: '#3b82f6', module: '#a78bfa', dynamic: '#f59e0b', skill: '#22c55e' };
    const counts = {};
    for (const b of blocks) counts[b.type] = (counts[b.type] || 0) + 1;
    const totalChars = blocks.reduce((s, b) => s + (b.size || 0), 0);
    const totalTokens = Math.round(totalChars / 4);

    let html = `<div class="pb-summary">
        <span class="pb-stat"><b>${blocks.length}</b> blocks</span>
        ${counts.file ? `<span class="pb-stat" style="color:#3b82f6"><b>${counts.file}</b> files</span>` : ''}
        ${counts.module ? `<span class="pb-stat" style="color:#a78bfa"><b>${counts.module}</b> modules</span>` : ''}
        ${counts.dynamic ? `<span class="pb-stat" style="color:#f59e0b"><b>${counts.dynamic}</b> dynamic</span>` : ''}
        ${counts.skill ? `<span class="pb-stat" style="color:#22c55e"><b>${counts.skill}</b> skills</span>` : ''}
        <span class="pb-stat"><b>~${totalTokens >= 1000 ? (totalTokens/1000).toFixed(1)+'k' : totalTokens}</b> tokens</span>
    </div>`;

    blocks.forEach((b, i) => {
        const color = TYPE_COLORS[b.type] || '#64748b';
        const tokens = Math.round((b.size || 0) / 4);
        const tokStr = tokens >= 1000 ? (tokens/1000).toFixed(1)+'k' : tokens;
        html += `<div class="pb-block pb-open" style="border-left-color:${color}" data-pb-idx="${i}">
            <div class="pb-header" onclick="this.parentElement.classList.toggle('pb-open')">
                <span class="pb-chevron">▸</span>
                <span class="pb-tag" style="background:${color}22;color:${color}">${b.type}</span>
                <span class="pb-title">${escHtml(b.title)}</span>
                <span class="pb-meta">${tokStr} tok</span>
                ${b.source ? `<span class="pb-source">${escHtml(b.source)}</span>` : ''}
            </div>
            <div class="pb-body"></div>
        </div>`;
    });
    container.innerHTML = html;

    container.querySelectorAll('.pb-block').forEach((el, i) => {
        const b = blocks[i];
        const bodyEl = el.querySelector('.pb-body');
        if (b.content) {
            bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
            bodyEl.dataset.loaded = '1';
        }
        el.querySelector('.pb-header').addEventListener('click', () => {
            if (!bodyEl.dataset.loaded && b.content) {
                bodyEl.innerHTML = `<div class="markdown-body text-xs">${DOMPurify.sanitize(marked.parse(_stripXmlTags(b.content)))}</div>`;
                bodyEl.dataset.loaded = '1';
            }
        });
    });
}

function openImageLightbox(src) {
    const overlay = document.createElement('div');
    overlay.className = 'img-lightbox';
    const img = document.createElement('img');
    img.src = src;
    img.style.cssText = 'max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,0.6);object-fit:contain';
    overlay.appendChild(img);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target !== img) overlay.remove(); });
    img.addEventListener('click', (e) => { e.stopPropagation(); window.open(src, '_blank'); });
    const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
}

async function openFilePreview(path) {
    const modal = $('#file-preview-modal');
    const pathEl = $('#file-preview-path');
    const contentEl = $('#file-preview-content');
    const openBtn = $('#file-preview-open');
    const dlBtn = $('#file-preview-download');
    pathEl.textContent = path;
    contentEl.textContent = 'Loading…';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    const rawUrl = `/api/files/raw?path=${encodeURIComponent(path)}`;
    const fileName = path.split('/').pop() || 'file';
    dlBtn.href = rawUrl;
    dlBtn.download = fileName;
    dlBtn.classList.remove('hidden');
    if (/\.html?$/i.test(path)) {
        openBtn.href = rawUrl;
        openBtn.classList.remove('hidden');
        contentEl.className = 'flex-1 p-0';
        contentEl.style.cssText = 'overflow:hidden;max-height:calc(80vh - 48px)';
        contentEl.innerHTML = `<iframe src="${rawUrl}" style="width:100%;height:100%;border:none;border-radius:0 0 12px 12px;min-height:60vh" sandbox="allow-scripts"></iframe>`;
        return;
    }
    openBtn.classList.add('hidden');
    try {
        const res = await fetch(`/api/files/content?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (data.error) {
            const sizeStr = data.size ? ` (${(data.size / 1024).toFixed(1)} KB)` : '';
            if (data.error === 'binary file' && /\.(png|jpg|jpeg|gif|webp|bmp|ico|svg)$/i.test(path)) {
                contentEl.innerHTML = `<img src="/api/files/raw?path=${encodeURIComponent(path)}&t=${Date.now()}" style="max-width:100%;max-height:70vh;border-radius:8px">`;
            } else {
                contentEl.textContent = `⚠ ${data.error}${sizeStr}`;
            }
        } else if (/\.md$/i.test(path)) {
            contentEl.className = 'flex-1 text-xs text-slate-300 markdown-body p-4';
            contentEl.style.cssText = 'overflow-y:auto;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;white-space:normal;max-height:calc(80vh - 48px)';
            const dir = path.substring(0, path.lastIndexOf('/'));
            const renderer = new marked.Renderer();
            renderer.image = (token) => {
                const h = typeof token === 'object' ? (token.href || '') : (token || '');
                const t = typeof token === 'object' ? (token.title || '') : '';
                const a = typeof token === 'object' ? (token.text || '') : '';
                const src = (h && !h.startsWith('http') && !h.startsWith('/api/'))
                    ? `/api/files/raw?path=${encodeURIComponent(dir + '/' + h)}`
                    : h;
                return `<img src="${src}"${a ? ` alt="${a}"` : ''}${t ? ` title="${t}"` : ''} loading="lazy" style="max-width:100%;border-radius:6px;margin:4px 0;cursor:pointer" onclick="openFilePreview('${h}')">`;
            };
            // Strip prompt-style XML tags (<platform>, <rules>) — they make marked treat
            // wrapped markdown as raw HTML, so ## headings / - lists never render.
            contentEl.innerHTML = DOMPurify.sanitize(marked.parse(_stripXmlTags(data.content), { renderer }), { ADD_ATTR: ['loading'] });
        } else if (/\.svg$/i.test(path)) {
            contentEl.innerHTML = `<img src="/api/files/raw?path=${encodeURIComponent(path)}&t=${Date.now()}" style="max-width:100%;max-height:70vh;border-radius:8px">`;
        } else {
            const ext = (path.match(/\.(\w+)$/)?.[1] || '').toLowerCase();
            const LANG_MAP = {
                py:'python',js:'javascript',ts:'typescript',jsx:'javascript',tsx:'typescript',
                html:'xml',css:'css',json:'json',xml:'xml',yaml:'yaml',yml:'yaml',
                sh:'bash',bash:'bash',sql:'sql',go:'go',rs:'rust',php:'php',
                rb:'ruby',java:'java',kt:'kotlin',swift:'swift',c:'c',cpp:'cpp',
                toml:'ini',ini:'ini',dockerfile:'dockerfile',
            };
            const raw = data.content.replace(/^\s*\d+\t/gm, '');

            if ((ext === 'csv' || ext === 'tsv') && raw.trim()) {
                const sep = ext === 'tsv' ? '\t' : ',';
                const rows = raw.trim().split('\n').map(r => r.split(sep));
                contentEl.className = 'flex-1 text-xs p-4 markdown-body';
                contentEl.style.cssText = 'overflow:auto;max-height:calc(80vh - 48px)';
                let html = '<table><thead><tr>';
                for (const h of (rows[0] || [])) html += `<th>${DOMPurify.sanitize(h.trim())}</th>`;
                html += '</tr></thead><tbody>';
                for (const row of rows.slice(1)) {
                    html += '<tr>';
                    for (const cell of row) html += `<td>${DOMPurify.sanitize(cell.trim())}</td>`;
                    html += '</tr>';
                }
                html += '</tbody></table>';
                contentEl.innerHTML = html;
            } else if (ext === 'json') {
                let pretty = raw;
                try { JSON.parse(raw); pretty = _prettyJsonText(raw); } catch {}
                contentEl.className = 'flex-1 text-xs p-4';
                contentEl.style.cssText = 'overflow-y:auto;overflow-x:hidden;max-height:calc(80vh - 48px)';
                const pre = document.createElement('pre');
                pre.style.cssText = 'margin:0;background:transparent;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word';
                const code = document.createElement('code');
                code.className = 'language-json';
                code.textContent = pretty;
                pre.appendChild(code);
                contentEl.innerHTML = '';
                contentEl.appendChild(pre);
                if (window.hljs) hljs.highlightElement(code);
            } else if (LANG_MAP[ext] && window.hljs) {
                contentEl.className = 'flex-1 text-xs p-4';
                contentEl.style.cssText = 'overflow-y:auto;overflow-x:hidden;max-height:calc(80vh - 48px)';
                const pre = document.createElement('pre');
                pre.style.cssText = 'margin:0;background:transparent;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word';
                const code = document.createElement('code');
                code.className = `language-${LANG_MAP[ext]}`;
                code.textContent = raw;
                pre.appendChild(code);
                contentEl.innerHTML = '';
                contentEl.appendChild(pre);
                hljs.highlightElement(code);
            } else {
                contentEl.className = 'flex-1 text-xs p-4 text-slate-300';
                contentEl.style.cssText = 'overflow-y:auto;overflow-x:hidden;max-height:calc(80vh - 48px);white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word';
                contentEl.textContent = raw;
            }
        }
    } catch (e) {
        contentEl.textContent = `Error: ${e.message}`;
    }
}

function closeFilePreview() {
    const modal = $('#file-preview-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    const openBtn = $('#file-preview-open');
    if (openBtn) openBtn.classList.add('hidden');
    const dlBtn = $('#file-preview-download');
    if (dlBtn) dlBtn.classList.add('hidden');
    const contentEl = $('#file-preview-content');
    if (contentEl) contentEl.innerHTML = '';
}

function initFilePreviewModal() {
    const modal = $('#file-preview-modal');
    if (!modal) return;
    $('#file-preview-close').addEventListener('click', closeFilePreview);
}

async function showProjectPicker() {
    const picker = $('#project-picker');
    picker.innerHTML = '<div class="p-2 text-xs text-slate-500">Loading...</div>';
    picker.classList.remove('hidden');
    try {
        const projects = await api('/api/projects');
        picker.innerHTML = '';
        for (const p of projects) {
            const item = document.createElement('div');
            item.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-slate-800 border-b border-slate-800/50';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'text-white font-medium';
            nameSpan.textContent = p.name;
            const pathSpan = document.createElement('span');
            pathSpan.className = 'text-slate-500 text-xs';
            pathSpan.textContent = ' ' + p.path;
            item.append(nameSpan, pathSpan);
            item.addEventListener('click', () => {
                $('#orch-cwd').value = p.path;
                $('#orch-name').value = p.name + '-orchestrator';
                picker.classList.add('hidden');
            });
            picker.appendChild(item);
        }
    } catch { picker.innerHTML = '<div class="p-2 text-xs text-red-400">Failed to load</div>'; }
}

function autoNameFromPath(path) {
    const parts = path.replace(/\/+$/, '').split('/');
    const folder = parts[parts.length - 1] || '';
    return folder + '-orchestrator';
}

async function createOrchestrator() {
    const name = $('#orch-name').value.trim();
    const cwd = $('#orch-cwd').value.trim();
    const model = $('#orch-model').value;
    const profile = 'personal';
    const pipeline = 'default';
    const role = 'orchestrator';
    const errEl = $('#orch-error');
    if (!name || !cwd) { errEl.textContent = 'Name and project path required'; errEl.classList.remove('hidden'); return; }
    const btn = $('#create-orch-btn');
    btn.disabled = true; btn.textContent = 'Creating...'; errEl.classList.add('hidden');
    try {
        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
        closeModal(); $('#orch-name').value = ''; $('#orch-cwd').value = '';
        currentScope = null;
        await loadOrchestrators();
        selectOrchestrator(name, cwd.replace(/\/+$/, ''));
    } catch (e) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
    finally { btn.disabled = false; btn.textContent = 'Create Orchestrator'; }
}

async function restartServer() {
    const btn = $('#restart-btn');
    btn.disabled = true; btn.textContent = '⏳';
    try {
        const result = await api('/api/restart', { method: 'POST', timeoutMs: 200000 });
        if (result.journal_loss) {
            Connection.restartAttempt(
                `Рестарт состоится, но журнал потерян: ${result.journal_loss.reason || 'причина не указана'}`,
                true,
            );
        } else {
            const waited = Number(result.waited_s || 0).toFixed(1);
            Connection.restartAttempt(`Рестарт подготовлен за ${waited} с`, false);
        }
    } catch (error) {
        Connection.restartAttempt(`Рестарт не состоялся: ${error.message || error}`, true);
        btn.disabled = false;
        btn.textContent = '⟳';
    }
    // Перезагрузки здесь больше нет: она стояла на 3 с, а старт сервиса занимает 4.3-13.9 с
    // (замер по journalctl, .orchestra/tasks/15/research.md) — то есть страница почти всегда
    // перезагружалась в мёртвый сервер и юзер получал 502 от nginx вместо дашборда.
    // Возврат ловит heartbeat и восстанавливает состояние на месте.
}

// === Orchestrator Picker ===
let orchData = [];
const _unreadTabs = new Set();

function _renderOrchestrators(allOrchs) {
    // Sub-orchestrators (have parent) get TG topics but don't show in top tab bar
    orchData = allOrchs.filter(o => !o.parent_name);
    const picker = $('#orch-picker');
    picker.innerHTML = '';
    for (const o of orchData) {
        const opt = document.createElement('option');
        opt.value = o.scope;
        opt.dataset.id = o.id;
        opt.dataset.name = o.name;
        opt.textContent = o.name;
        picker.appendChild(opt);
    }

    const lastScope = localStorage.getItem('lastOrchScope');
    const lastName = localStorage.getItem('lastOrchName');
    const recentRaw = localStorage.getItem('recentOrchs');
    const recent = recentRaw ? JSON.parse(recentRaw) : [];

    const sorted = [...orchData].sort((a, b) => {
        const ai = recent.indexOf(a.name);
        const bi = recent.indexOf(b.name);
        if (ai >= 0 && bi >= 0) return ai - bi;
        if (ai >= 0) return -1;
        if (bi >= 0) return 1;
        return 0;
    });

    renderOrchTabs(sorted);

    if (orchData.length > 0 && !currentScope) {
        const match = orchData.find(o => o.scope === lastScope && o.name === lastName);
        if (match) {
            selectOrchestrator(match.name, match.scope);
        } else {
            selectOrchestrator(sorted[0].name, sorted[0].scope);
        }
    }
}

async function _loadOrchestratorsNow() {
    try {
        const allOrchs = await api('/api/orchestrators', {
            pollKey: 'orchestrators',
            priority: 'critical',
        });
        // Данные только что получены. Без этой отметки дроссель в refreshSessions считает
        // их протухшими и через полсекунды тянет тот же список второй раз (#71).
        _orchFreshAt = Date.now();
        _renderOrchestrators(allOrchs);
        snapshotSave('orchestrators', allOrchs);
        Connection.clear('orchestrators');
    } catch (e) {
        // Пустые вкладки без причины — это то, на что юзер и жалуется. Молчать нельзя:
        // без вкладок дашборд не выбирает scope, и не работает ВООБЩЕ ничего.
        console.warn(`orchestrators: ${e.name}: ${e.message}`);
        const snapshot = orchData.length ? null : snapshotLoad('orchestrators');
        if (snapshot) {
            _renderOrchestrators(snapshot.data);
            Connection.stale('orchestrators', snapshot.ts);
        } else if (!orchData.length) {
            Connection.fail('/api/orchestrators', e);
        }
    }
}

function loadOrchestrators() {
    return _pollCoalesce('orchestrators-request', _loadOrchestratorsNow);
}

function _applyTabOrder(list) {
    const saved = JSON.parse(localStorage.getItem('tabOrder') || '[]');
    if (!saved.length) return list;
    return [...list].sort((a, b) => {
        const ai = saved.indexOf(a.name);
        const bi = saved.indexOf(b.name);
        if (ai >= 0 && bi >= 0) return ai - bi;
        if (ai >= 0) return -1;
        if (bi >= 0) return 1;
        return 0;
    });
}

function _saveTabOrder() {
    const tabs = $('#orch-tabs');
    const order = [...tabs.querySelectorAll('.orch-tab')].map(t => t.dataset.orchName);
    localStorage.setItem('tabOrder', JSON.stringify(order));
}

function _getHiddenTabs() {
    try { return new Set(JSON.parse(localStorage.getItem('orchestra_hidden_tabs') || '[]')); } catch { return new Set(); }
}
function _setHiddenTabs(set) {
    localStorage.setItem('orchestra_hidden_tabs', JSON.stringify([...set]));
}

// One status vocabulary for the whole dashboard — sidebar badges and orch tabs.
// Icon carries the state, so it no longer rides on hue alone (idle/waiting were
// indistinguishable as plain yellow vs orange dots).
const _STATUS_ICON = {running: '⚡', idle: '☕️', waiting: '⏳', broken: '⛔'};
// broken красный, а не серый: это не «нет данных», а «задачу слать бесполезно».
// error/stopped/starting приходят только в выводе инструментов (см. _STATUS_COLOR ниже).
const _STATUS_COLOR = {running: '#22c55e', idle: '#eab308', waiting: '#f59e0b', broken: '#ef4444',
                       error: '#ef4444', stopped: '#6b7280', starting: '#f97316'};
const _STATUS_BG = {running: 'rgba(34,197,94,0.15)', idle: 'rgba(234,179,8,0.12)', waiting: 'rgba(245,158,11,0.15)',
                    broken: 'rgba(239,68,68,0.15)'};
const _STATUS_TITLE = {
    running: 'running — агент выполняет задачу',
    waiting: 'waiting — агент ждёт фоновую задачу или подтверждение',
    idle: 'idle — агент простаивает',
    broken: 'broken — worktree агента не существует: задачу слать бесполезно, нужен спавн заново',
};

function _orchState(o) {
    // broken важнее занятости: у сломанного worktree «running» не значит ничего.
    if (o.status === 'broken') return 'broken';
    if (o.status === 'running' || o.any_running) return 'running';
    if (o.any_waiting) return 'waiting';
    return 'idle';
}

function _paintStatusDot(dot, o) {
    const state = _orchState(o);
    dot.style.color = state === 'broken' ? _STATUS_COLOR.broken : '';
    dot.textContent = _STATUS_ICON[state];
    dot.style.backgroundColor = _STATUS_BG[state];
    dot.title = _STATUS_TITLE[state];
}

function _orchestratorTurnFinished(previous, current) {
    return previous.status === 'running' && current.status !== 'running';
}

function _syncUnreadDot(tab, scope) {
    const existing = tab.querySelector('.tab-unread');
    if (_unreadTabs.has(scope) && !existing) {
        const unread = document.createElement('span');
        unread.className = 'tab-unread';
        unread.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#ef4444;border-radius:50%;box-shadow:0 0 4px rgba(239,68,68,0.6)';
        tab.appendChild(unread);
    } else if (!_unreadTabs.has(scope) && existing) {
        existing.remove();
    }
}

function renderOrchTabs(sorted) {
    const tabs = $('#orch-tabs');
    tabs.innerHTML = '';
    const ordered = _applyTabOrder(sorted);
    const hidden = _getHiddenTabs();
    let dragTab = null;
    _updateHiddenBtn();
    for (const o of ordered) {
        if (hidden.has(o.name)) continue;
        const tab = document.createElement('button');
        tab.className = `orch-tab ${o.name === selectedAgent && o.scope === currentScope ? 'active' : ''}`;
        tab.dataset.orchName = o.name;
        tab.draggable = true;
        const dot = document.createElement('span');
        dot.className = 'tab-dot';
        _paintStatusDot(dot, o);
        const label = document.createElement('span');
        const shortName = o.name.replace(/-orchestrator$/, '');
        label.textContent = shortName;
        tab.append(dot, label);
        // Cache indicator on orch tab — reuse _cachePill / _renderCachePill so countdown ticks them
        const orchPill = _cachePill(o);
        if (orchPill) {
            orchPill.style.fontSize = '9px';
            orchPill.style.marginLeft = '3px';
            orchPill.style.verticalAlign = 'middle';
            orchPill.dataset.hideCold = '1';
            if (orchPill.dataset.tier === 'cold') orchPill.style.display = 'none';
            tab.appendChild(orchPill);
        }
        tab.title = o.scope;
        tab.style.position = 'relative';
        _syncUnreadDot(tab, o.scope);
        tab.addEventListener('click', () => selectOrchestrator(o.name, o.scope));
        tab.addEventListener('dragstart', (e) => {
            dragTab = tab;
            tab.style.opacity = '0.4';
            e.dataTransfer.effectAllowed = 'move';
        });
        tab.addEventListener('dragend', () => {
            tab.style.opacity = '';
            dragTab = null;
            tabs.querySelectorAll('.orch-tab').forEach(t => t.style.borderLeft = '');
        });
        tab.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (!dragTab || dragTab === tab) return;
            const rect = tab.getBoundingClientRect();
            const mid = rect.left + rect.width / 2;
            tabs.querySelectorAll('.orch-tab').forEach(t => t.style.borderLeft = '');
            if (e.clientX < mid) {
                tab.style.borderLeft = '2px solid #6366f1';
            } else {
                const next = tab.nextElementSibling;
                if (next) next.style.borderLeft = '2px solid #6366f1';
            }
        });
        tab.addEventListener('drop', (e) => {
            e.preventDefault();
            if (!dragTab || dragTab === tab) return;
            const rect = tab.getBoundingClientRect();
            const mid = rect.left + rect.width / 2;
            if (e.clientX < mid) {
                tabs.insertBefore(dragTab, tab);
            } else {
                tabs.insertBefore(dragTab, tab.nextSibling);
            }
            tabs.querySelectorAll('.orch-tab').forEach(t => t.style.borderLeft = '');
            _saveTabOrder();
        });
        tabs.appendChild(tab);
    }
}

let _dropDragCounter = 0;
function _hideDropHint() {
    _dropDragCounter = 0;
    const input = $('#chat-input');
    if (!input) return;
    if ('origPlaceholder' in input.dataset) {
        input.placeholder = input.dataset.origPlaceholder;
        delete input.dataset.origPlaceholder;
    }
    input.classList.remove('border-indigo-400');
}

function _showDropHint(input) {
    if (!('origPlaceholder' in input.dataset)) input.dataset.origPlaceholder = input.placeholder;
    input.placeholder = '📎 Drop files here';
    input.classList.add('border-indigo-400');
}

function _showChatDropError(message) {
    const existing = $('#chat-drop-error');
    if (!message) {
        existing?.remove();
        return;
    }
    const error = existing || document.createElement('div');
    if (!existing) {
        error.id = 'chat-drop-error';
        error.className = 'text-xs text-red-400 px-1 pb-1';
        error.setAttribute('role', 'alert');
        const inputRow = $('#chat-input').parentElement;
        inputRow.parentElement.insertBefore(error, inputRow);
    }
    error.textContent = message;
}

function _insertPathAtCaret(input, path, url, showPreview = true) {
    // Путь встаёт туда, где каретка (заменяя выделение): юзер в этот момент печатает,
    // и дописывание в конец уводило бы его текст ЗА путь
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    const before = input.value.slice(0, start);
    const after = input.value.slice(end);
    const prefix = before && !before.endsWith('\n') ? '\n' : '';
    const suffix = after && !after.startsWith('\n') ? '\n' : '';
    input.value = before + prefix + path + suffix + after;
    const caret = before.length + prefix.length + path.length;
    input.focus();
    input.setSelectionRange(caret, caret);
    pastedImages.push(url);
    if (showPreview) showImagePreview(url, path);
}

async function _handleChatDrop(input, dataTransfer) {
    _showChatDropError('');
    const files = [...(dataTransfer?.files || [])];
    if (files.length) {
        for (const file of files) await _trackUpload(_uploadToChat(file, file.name));
        input.focus();
        return;
    }
    const path = dataTransfer?.getData('text/plain');
    if (!path) return;
    const url = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(path)
        ? `/api/files/raw?path=${encodeURIComponent(path)}` : path;
    _insertPathAtCaret(input, path, url);
}

function _hasDropType(dataTransfer, type) {
    return [...(dataTransfer?.types || [])].includes(type);
}

function _isChatDrop(dataTransfer) {
    return _hasDropType(dataTransfer, 'Files') || _hasDropType(dataTransfer, 'text/plain');
}

function initChatDrop() {
    document.addEventListener('dragenter', (e) => {
        const input = e.target.closest?.('#chat-input');
        if (!input || !_isChatDrop(e.dataTransfer)) return;
        _dropDragCounter++;
        _showDropHint(input);
    });
    document.addEventListener('dragleave', (e) => {
        if (!e.target.closest?.('#chat-input')) return;
        _dropDragCounter--;
        if (_dropDragCounter <= 0) _hideDropHint();
    });
    document.addEventListener('dragover', (e) => {
        const input = e.target.closest?.('#chat-input');
        if (input && _isChatDrop(e.dataTransfer)) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        } else if (_hasDropType(e.dataTransfer, 'Files')) {
            e.preventDefault();
        }
    });
    document.addEventListener('drop', (e) => {
        const input = e.target.closest?.('#chat-input');
        if (_hasDropType(e.dataTransfer, 'Files')) e.preventDefault();
        _hideDropHint();
        if (!input || !_isChatDrop(e.dataTransfer)) return;
        e.preventDefault();
        _handleChatDrop(input, e.dataTransfer)
            .catch(error => _showChatDropError(`Drop failed — ${error.message}`));
    });
}

function initTabContextMenu() {
    let menu = null;
    const close = () => { if (menu) { menu.remove(); menu = null; } };
    document.addEventListener('click', close);
    document.addEventListener('contextmenu', (e) => {
        const tab = e.target.closest('.orch-tab');
        if (!tab) { close(); return; }
        e.preventDefault();
        close();
        const name = tab.dataset.orchName;
        const scope = tab.title;
        menu = document.createElement('div');
        menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:120px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
        const mkItem = (label, color, fn) => {
            const item = document.createElement('div');
            item.style.cssText = `padding:6px 14px;font-size:12px;color:${color};cursor:pointer;white-space:nowrap`;
            item.textContent = label;
            item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
            item.addEventListener('mouseleave', () => item.style.background = '');
            item.addEventListener('click', (ev) => { ev.stopPropagation(); close(); fn(); });
            return item;
        };
        menu.appendChild(mkItem('👁 Скрыть', '#94a3b8', () => {
            const h = _getHiddenTabs(); h.add(name); _setHiddenTabs(h);
            renderOrchTabs(orchData);
        }));
        menu.appendChild(mkItem('📁 Сменить папку', '#60a5fa', () => {
            changeOrchScope(name, scope);
        }));
        menu.appendChild(mkItem('🗑 Удалить', '#ef4444', () => {
            openDeleteOrchModal(name, scope);
        }));
        document.body.appendChild(menu);
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
        if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
    });
}

function openDeleteOrchModal(name, scope) {
    const modal = $('#delete-orch-modal');
    if (!modal) {
        if (!confirm(`Delete "${name}" and all its workers?`)) return;
        api(`/api/orchestrators/${name}?scope=${encodeURIComponent(scope)}`, { method: 'DELETE' })
            .then(() => loadOrchestrators())
            .catch(e => alert(`Delete failed: ${e.message}`));
        return;
    }
    $('#delete-orch-name').textContent = `"${name}"`;
    $('#delete-tg-topics').checked = false;
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    const close = () => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    };

    $('#delete-orch-confirm').onclick = async () => {
        const deleteTopics = $('#delete-tg-topics').checked;
        close();
        try {
            const url = `/api/orchestrators/${name}?scope=${encodeURIComponent(scope)}&delete_tg_topics=${deleteTopics}`;
            await api(url, { method: 'DELETE' });
            loadOrchestrators();
        } catch (e) {
            alert(`Delete failed: ${e.message}`);
        }
    };
    $('#delete-orch-cancel').onclick = close;
    $('#delete-orch-modal-close').onclick = close;
    modal.onclick = (e) => { if (e.target === modal) close(); };
}

function changeOrchScope(name, oldScope) {
    const modal = $('#change-scope-modal');
    if (!modal) return;
    const pathInput = $('#change-scope-path');
    const errorEl = $('#change-scope-error');
    const picker = $('#change-scope-picker');
    $('#change-scope-name').textContent = name;
    pathInput.value = oldScope;
    errorEl.classList.add('hidden');
    picker.classList.add('hidden');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    pathInput.focus();
    pathInput.select();

    const close = () => { modal.classList.remove('flex'); modal.classList.add('hidden'); };

    const doMove = async () => {
        const ns = pathInput.value.trim().replace(/\/+$/, '');
        if (!ns || ns === oldScope) { close(); return; }
        errorEl.classList.add('hidden');
        try {
            const res = await api(`/api/orchestrators/${name}/change-scope`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ old_scope: oldScope, new_scope: ns }),
            });
            close();
            await loadOrchestrators();
            selectOrchestrator(name, res.scope || ns);
        } catch (e) {
            errorEl.textContent = e.message;
            errorEl.classList.remove('hidden');
        }
    };

    const browseBtn = $('#change-scope-browse');
    const onBrowse = async () => {
        picker.innerHTML = '<div class="p-2 text-xs text-slate-500">Loading...</div>';
        picker.classList.remove('hidden');
        try {
            const projects = await api('/api/projects');
            picker.innerHTML = '';
            for (const p of projects) {
                const item = document.createElement('div');
                item.className = 'px-3 py-2 text-sm cursor-pointer hover:bg-slate-800 border-b border-slate-800/50';
                item.innerHTML = `<span class="text-white font-medium">${escHtml(p.name)}</span> <span class="text-slate-500 text-xs">${escHtml(p.path)}</span>`;
                item.addEventListener('click', () => { pathInput.value = p.path; picker.classList.add('hidden'); });
                picker.appendChild(item);
            }
        } catch { picker.innerHTML = '<div class="p-2 text-xs text-red-400">Failed to load</div>'; }
    };

    const cleanup = () => {
        document.removeEventListener('keydown', onKey);
        $('#change-scope-close').removeEventListener('click', closeHandler);
        $('#change-scope-cancel').removeEventListener('click', closeHandler);
        $('#change-scope-confirm').removeEventListener('click', confirmHandler);
        browseBtn.removeEventListener('click', onBrowse);
    };
    const closeHandler = () => { close(); cleanup(); };
    // doMove is async — cleanup only after successful close, not on error
    const confirmHandler = async () => { await doMove(); if (modal.classList.contains('hidden')) cleanup(); };
    const onKey = (e) => { if (e.key === 'Escape') { closeHandler(); } else if (e.key === 'Enter') { confirmHandler(); } };

    document.addEventListener('keydown', onKey);
    $('#change-scope-close').addEventListener('click', closeHandler);
    $('#change-scope-cancel').addEventListener('click', closeHandler);
    $('#change-scope-confirm').addEventListener('click', confirmHandler);
    browseBtn.addEventListener('click', onBrowse);
    modal.addEventListener('click', (e) => { if (e.target === modal) { close(); cleanup(); } }, { once: true });
}

function _updateHiddenBtn() {
    const btn = $('#hidden-tabs-btn');
    if (!btn) return;
    const hidden = _getHiddenTabs();
    const hasHidden = [...hidden].some(n => orchData.find(o => o.name === n));
    btn.classList.toggle('hidden', !hasHidden);
    if (hasHidden) btn.textContent = `👁 ${[...hidden].filter(n => orchData.find(o => o.name === n)).length}`;
}

function initHiddenTabsBtn() {
    const btn = $('#hidden-tabs-btn');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const existing = document.getElementById('hidden-tabs-dropdown');
        if (existing) { existing.remove(); return; }
        const hidden = _getHiddenTabs();
        const items = [...hidden].filter(n => orchData.find(o => o.name === n));
        if (!items.length) return;
        const dd = document.createElement('div');
        dd.id = 'hidden-tabs-dropdown';
        const rect = btn.getBoundingClientRect();
        dd.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.bottom + 4}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:140px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
        for (const name of items) {
            const item = document.createElement('div');
            item.style.cssText = 'padding:6px 14px;font-size:12px;color:#94a3b8;cursor:pointer;white-space:nowrap';
            item.textContent = `👁 ${name.replace(/-orchestrator$/, '')}`;
            item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
            item.addEventListener('mouseleave', () => item.style.background = '');
            item.addEventListener('click', () => {
                const h = _getHiddenTabs(); h.delete(name); _setHiddenTabs(h);
                dd.remove();
                renderOrchTabs(orchData);
            });
            dd.appendChild(item);
        }
        document.body.appendChild(dd);
        const closeDd = (ev) => { if (!dd.contains(ev.target) && ev.target !== btn) { dd.remove(); document.removeEventListener('click', closeDd); } };
        setTimeout(() => document.addEventListener('click', closeDd), 0);
    });
    const tabsEl = $('#orch-tabs');
    if (tabsEl) {
        tabsEl.addEventListener('wheel', (e) => {
            e.preventDefault();
            tabsEl.scrollLeft += e.deltaY;
        }, { passive: false });
    }
}

function updateOrchTabDots() {
    const tabs = document.querySelectorAll('#orch-tabs .orch-tab');
    tabs.forEach(tab => {
        const scope = tab.title;
        const o = orchData.find(x => x.scope === scope);
        if (!o) return;
        const dot = tab.querySelector('.tab-dot');
        if (dot) _paintStatusDot(dot, o);
        _syncUnreadDot(tab, scope);
    });
}

function selectOrchestrator(name, scope) {
    const picker = $('#orch-picker');
    picker.value = scope;
    const opt = [...picker.options].find(o => o.dataset.name === name);
    if (opt) picker.selectedIndex = opt.index;

    // Keep last 10 recently used orchestrators — used to sort tabs on next load
    const recent = JSON.parse(localStorage.getItem('recentOrchs') || '[]');
    const filtered = recent.filter(n => n !== name);
    filtered.unshift(name);
    localStorage.setItem('recentOrchs', JSON.stringify(filtered.slice(0, 10)));

    onOrchestratorChange();
    renderOrchTabs(orchData);
}

// Отрисовать готовые строки журнала и выставить отметки, от которых пляшет connectSSE.
// Отличает проигрывание истории от живой строки: часть отрисовки имеет побочные эффекты
// (обновить панель задач), и в прошлом они не нужны. Флаг, а не параметр, потому что
// addChatEntry зовут из десятка мест и протаскивать признак через все — шум.
// NB: объявлен выше, рядом с _chatFollow — _trimChatNodes читает его раньше этой строки,
// а `let` не поднимается: обращение до инициализации бросило бы ReferenceError.

function _renderHistory(agent, rows) {
    _chatTrimLimit = MAX_CHAT_NODES;
    const meta = chatLogs[agent] = _newChatLogState();
    const chat = $('#chat');
    // Страница рисуется ЦЕЛИКОМ и показывается один раз. Пока идёт цикл, контейнер скрыт:
    // сотня узлов вставляется десятками мутаций, браузер успевает показать промежуточные
    // кадры, и юзер видит, как чат достраивается сверху вниз (жалоба 21.08). Скрытый
    // контейнер занимает то же место — раскладка не прыгает, просто не показываем черновик.
    if (chat) chat.style.visibility = 'hidden';
    _replayingHistory = true;
    try {
    for (const l of rows) {
        addChatEntry(l.type, l.content, l.ts, null, l);
        if (!Number.isFinite(l.id)) continue;
        if (l.id > meta.lastId) meta.lastId = l.id;
        if (meta.firstId === null || l.id < meta.firstId) meta.firstId = l.id;
    }
    } finally {
        _replayingHistory = false;
        if (chat) { chat.scrollTop = chat.scrollHeight; chat.style.visibility = ''; }
    }
    meta.canLoadOlder = rows.length > 0;
    updateLoadMoreBtn();
    $('#chat').scrollTop = $('#chat').scrollHeight;
    _scheduleChatInitialSettle();
    _syncChatJumpButton();
}

function _afterPaint(fn) {
    if (typeof requestAnimationFrame !== 'function') return setTimeout(fn, 0);
    requestAnimationFrame(() => requestAnimationFrame(fn));
}

async function _fetchHistory(name, scope, signal) {
    const q = new URLSearchParams({
        scope,
        before_id: String(2 ** 31 - 1),
        limit: String(_CHAT_PAGE),
        cap: String(_CHAT_ROW_CAP),
    });
    const rows = await api(`/api/sessions/${encodeURIComponent(name)}/logs?${q}`, {
        signal,
        priority: 'critical',
        pollKey: 'chat',
        cache: 'no-store',
    });
    if (!Array.isArray(rows)) throw new TypeError('chat history response is not an array');
    return rows;
}

let _chatLoadController = null;
let _chatLoadGeneration = 0;
let _chatSnapshotReady = false;

function _chatLoadIsCurrent(generation, name, scope) {
    return generation === _chatLoadGeneration
        && name === selectedAgent
        && scope === currentScope;
}

function _renderChatLoadState(name, error = null) {
    const chat = $('#chat');
    if (!chat) return;
    const connectionOwns = Boolean(
        error && Connection.ownsErrors()
    );
    const localError = error && !connectionOwns;
    chat.replaceChildren();
    chat.setAttribute('aria-busy', String(!localError));
    chat.dataset.agent = name || '';
    const state = document.createElement('div');
    state.className = `chat-load-state${localError ? ' chat-load-error' : ''}`;
    const marker = document.createElement('span');
    marker.className = 'chat-load-marker';
    marker.textContent = localError ? '!' : '';
    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = localError
        ? 'Актуальные сообщения не загрузились'
        : connectionOwns ? 'Ожидаю восстановления Orchestra' : 'Загружаю актуальные сообщения';
    const detail = document.createElement('span');
    detail.textContent = localError
        ? `${error.name || 'Error'}: ${error.message || 'без текста'}`
        : connectionOwns ? 'Причина и восстановление показаны в единой полосе сверху'
        : `${name} · покажу историю одним кадром`;
    copy.append(title, detail);
    state.append(marker, copy);
    if (localError) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = 'Повторить';
        retry.addEventListener('click', () => _showChatFor(name, currentScope));
        state.appendChild(retry);
    }
    chat.appendChild(state);
}

// Чат — network-first snapshot. IndexedDB не может доказать свежесть без обращения к
// серверу: его watermark обновляется тем же фоновым poll, который может опоздать. Поэтому
// кешированный хвост нельзя показывать как актуальный даже на один кадр. Один маленький
// JSON snapshot приходит целиком, рисуется атомарно, затем SSE продолжает строго после
// последнего id. При смене агента предыдущий snapshot отменяется и не занимает сетевой слот.
async function _showChatFor(name, scope) {
    if (!name || !scope) return false;
    if (_chatLoadController) _chatLoadController.abort();
    const controller = new AbortController();
    const generation = ++_chatLoadGeneration;
    _chatLoadController = controller;
    _chatSnapshotReady = false;
    _chatSessionId = null;
    chatLogs[name] = _newChatLogState();
    scrollAfterLoad = true;
    _chatLoading = true;
    _renderChatLoadState(name);
    try {
        const rows = await _fetchHistory(name, scope, controller.signal);
        if (!_chatLoadIsCurrent(generation, name, scope)) return false;
        _chatSessionId = rows.length ? rows[0].session_id : null;
        $('#chat').replaceChildren();
        _renderHistory(name, rows);
        $('#chat').setAttribute('aria-busy', 'false');
        _chatSnapshotReady = true;
        _chatLoading = false;
        connectSSE(true);
        _afterPaint(() => {
            if (_chatLoadIsCurrent(generation, name, scope) && _chatAtBottom()) {
                $('#chat').scrollTop = $('#chat').scrollHeight;
            }
        });
        return true;
    } catch (error) {
        if (controller.signal.aborted || !_chatLoadIsCurrent(generation, name, scope)) return false;
        console.warn(`[chat] история ${name} не пришла — ${error.name}: ${error.message}`);
        _pollNoteFailure('chat', error);
        _renderChatLoadState(name, error);
        return false;
    } finally {
        if (_chatLoadIsCurrent(generation, name, scope)) _chatLoading = false;
    }
}

async function onOrchestratorChange() {
    saveDraft();
    _captureChatReadFrontier();
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (_chatLoadController) _chatLoadController.abort();
    _chatSnapshotReady = false;
    const picker = $('#orch-picker');
    const opt = picker.selectedOptions[0];
    currentScope = picker.value || null;
    const restoreUnreadAnchor = _unreadTabs.delete(currentScope);
    chatLogs = {};
    currentSessions = [];
    resetChatTransientState();
    selectedAgent = opt?.dataset?.name || null;
    if (currentScope && selectedAgent) {
        localStorage.setItem('lastOrchScope', currentScope);
        localStorage.setItem('lastOrchName', selectedAgent);
    }
    $('#chat').innerHTML = '';
    $('#agent-list')?.replaceChildren();
    _prepareChatAnchorRestore(restoreUnreadAnchor);
    updateAgentInfo(null);
    updateInputState();
    restoreDraft();
    // История и поток идут первыми и не ждут refreshSessions: тому нужно два круга
    // (sessions+stats, затем orchestrators), а нам для показа чата не нужно ни одного (D2).
    _showChatFor(selectedAgent, currentScope);
    refreshSessions();
    initFilePanel();
    if (_tasksTabActive) loadTasks();
    if (_portfolioTabActive) PortfolioPanel.load();
    if (_jobsTabActive) loadJobs();
}

// === Agent Selection ===
async function selectAgent(name) {
    if (name === selectedAgent && (_chatSnapshotReady || _chatLoading)) return;
    saveDraft();
    _captureChatReadFrontier();
    if (eventSource) { eventSource.close(); eventSource = null; }
    resetChatTransientState();
    selectedAgent = name;
    _hideRateLimitBanner();
    $('#chat').innerHTML = '';
    _prepareChatAnchorRestore(false);
    updateInputState();
    restoreDraft();
    const hadContext = Boolean(contextCache[`${currentScope}:${name}`]);
    renderAgentList(currentSessions);
    if (hadContext) fetchAgentContext(name);
    await _showChatFor(name, currentScope);
}

function updateInputState() {
    const input = $('#chat-input');
    const btn = $('#send-btn');
    if (!selectedAgent) {
        input.placeholder = 'Message...';
        input.disabled = false;
        btn.disabled = false;
        return;
    }
    const sessions = [...document.querySelectorAll('.agent-item')];
    const agentEl = sessions.find(el => {
        const nameEl = el.querySelector('.text-xs.font-medium');
        return nameEl && nameEl.textContent === selectedAgent;
    });
    const isDead = agentEl && (agentEl.classList.contains('opacity-50'));
    if (isDead) {
        input.placeholder = `${selectedAgent} — archived (read-only)`;
        input.disabled = true;
        btn.disabled = true;
    } else {
        input.placeholder = `Message ${selectedAgent}...`;
        input.disabled = false;
        btn.disabled = false;
    }
}

let contextCache = {};
const _agentLiveStatuses = new Map();
let agentColors = {};

// Единственный владелец соответствия «агент → цвет». Серый = цвет ещё не приехал.
function _senderColor(sender) {
    return agentColors[sender] || Object.entries(agentColors).find(([k]) => k.startsWith(sender))?.[1] || '#64748b';
}

// Список агентов приходит позже истории чата → подписи, нарисованные серым фолбэком, перекрасить.
function _repaintSenderColors() {
    for (const div of $('#chat').querySelectorAll('[data-from]')) {
        const color = _senderColor(div.dataset.from);
        div.style.borderLeft = `3px solid ${color}`;
        const label = div.querySelector('.chat-from-label');
        if (label) label.style.color = color;
    }
}

let _MODELS = [];
let _modelsLoaded = false;
async function _ensureModels() {
    if (_modelsLoaded) return;
    try {
        const data = await api('/api/models');
        const models = data.models || [];
        _MODELS = models.map(m => ({ ...m, label: m.name }));
        _modelsLoaded = true;
    } catch {}
}
function _updateProxyStatus(connected) {
    const el = document.getElementById('proxy-status');
    if (!el) return;
    if (connected) {
        el.textContent = '🟢';
        el.title = 'Proxy connected';
    } else {
        el.textContent = '🔴';
        el.title = 'Proxy offline — no models available';
    }
}

function _historyTransferMessage(transfer) {
    if (!transfer || !transfer.mode) return null;
    if (transfer.mode === 'blocked') {
        return {
            type: 'error',
            text: `dialog switch blocked; source retained: ${transfer.error_code || transfer.reason || 'unknown error'}`,
        };
    }
    if (transfer.mode === 'packet' || transfer.mode === 'fallback_packet') {
        const omitted = transfer.omissions || {};
        const omittedLabels = Object.entries(omitted)
            .filter(([, value]) => Boolean(value))
            .map(([key]) => key.replaceAll('_', ' '));
        return {
            type: transfer.mode === 'fallback_packet' ? 'warning' : 'status',
            text: `${transfer.mode === 'fallback_packet' ? 'bounded fallback packet' : 'server state packet'} validated` +
                `${transfer.handoff_id ? ` (${transfer.handoff_id})` : ''}; ` +
                `raw snapshot remains operator-only and untrusted; ` +
                `omitted: ${omittedLabels.length ? omittedLabels.join(', ') : 'none declared'}`,
        };
    }
    if (transfer.mode === 'native_resume') {
        return {
            type: 'status',
            text: 'native provider thread resumed after total-context preflight',
        };
    }
    if (transfer.mode === 'fresh') {
        return {
            type: 'status',
            text: 'fresh target session started; previous dialog discarded',
        };
    }
    if (transfer.mode === 'summary') {
        return {
            type: 'warning',
            text: `native history import unavailable: ${transfer.reason || 'unknown reason'}; summary fallback active`,
        };
    }
    if (transfer.mode !== 'native') return null;
    return {
        type: 'status',
        text: `history imported to ${transfer.runtime} ${transfer.version}: ` +
            `users=${transfer.users}, assistants=${transfer.assistants}, ` +
            `tools=${transfer.tool_calls}/${transfer.tool_results}, ` +
            `tool chars detailed=${transfer.tool_detailed_chars}, truncated=${transfer.truncated}, ` +
            `secrets redacted=${transfer.secrets_redacted}, reasoning omitted=${transfer.reasoning_omitted}`,
    };
}

function _showHistoryTransfer(transfer) {
    const rendered = _historyTransferMessage(transfer);
    if (!rendered) return;
    const chat = $('#chat');
    if (chat && Array.from(chat.children).some(node => node.textContent.includes(rendered.text))) return;
    addChatEntry(rendered.type, rendered.text);
}

async function _showModelPicker(agentName, currentModel, anchor) {
    const existing = document.getElementById('model-picker-dd');
    if (existing) { existing.remove(); return; }
    await _ensureModels();
    if (!_MODELS.length) { console.warn('No models available for picker'); return; }
    const dd = document.createElement('div');
    dd.id = 'model-picker-dd';
    const rect = anchor.getBoundingClientRect();
    dd.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.bottom + 4}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
    for (const m of _MODELS) {
        const item = document.createElement('div');
        const isCurrent = currentModel === m.id;
        item.style.cssText = `padding:5px 14px;font-size:11px;color:${isCurrent ? '#818cf8' : '#94a3b8'};cursor:${isCurrent ? 'default' : 'pointer'};white-space:nowrap`;
        item.textContent = `${isCurrent ? '● ' : ''}${m.label}`;
        if (!isCurrent) {
            item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
            item.addEventListener('mouseleave', () => item.style.background = '');
            item.addEventListener('click', async (e) => {
                e.stopPropagation();
                dd.remove();
                try {
                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope }) });
                    if (resp && !resp.error) {
                        $('#ai-model').textContent = m.id;
                        _showHistoryTransfer(resp.history_transfer);
                        loadSessions();
                    }
                } catch (e) {
                    const match = String(e.message || '').match(/^\d+:\s*(\{.*\})$/s);
                    if (match) {
                        try {
                            const body = JSON.parse(match[1]);
                            _showHistoryTransfer({
                                ...(body.history_transfer || {mode: 'blocked'}),
                                error_code: body.error_code,
                                reason: body.error,
                            });
                        } catch {}
                    }
                    console.warn('Change model failed:', e);
                }
            });
        }
        dd.appendChild(item);
    }
    document.body.appendChild(dd);
    const close = (e) => { if (!dd.contains(e.target) && e.target !== anchor) { dd.remove(); document.removeEventListener('click', close); } };
    setTimeout(() => document.addEventListener('click', close), 10);
}

function updateAgentInfo(session) {
    if (!session) {
        $('#ai-name').textContent = '-';
        $('#ai-status').textContent = '';
        $('#ai-model').textContent = '-';
        $('#ai-role').textContent = '-';
        $('#ai-cost').textContent = '-';
        $('#ai-branch').textContent = '-';
        $('#ai-scope').textContent = '-';
        setContextDisplay('-');
        $('#view-prompt-btn').classList.add('hidden');
        $('#subagents-btn')?.classList.add('hidden');
        $('#compact-btn').classList.add('hidden');
        $('#restart-cli-btn').classList.add('hidden');
        $('#clear-session-btn')?.classList.add('hidden');
        return;
    }
    $('#view-prompt-btn').classList.remove('hidden');
    $('#subagents-btn')?.classList.remove('hidden');
    $('#compact-btn').classList.remove('hidden');
    $('#restart-cli-btn').classList.remove('hidden');
    $('#clear-session-btn')?.classList.remove('hidden');
    const isRunning = session.status === 'running';
    const clearBtn = $('#clear-session-btn');
    if (clearBtn) {
        clearBtn.disabled = isRunning;
        clearBtn.title = isRunning
            ? 'Дождись idle'
            : 'Очистить сессию — начать разговор с нуля (история забывается, worktree и ветка не трогаются)';
    }
    $('#compact-btn').disabled = isRunning;
    $('#compact-btn').title = isRunning ? 'Wait for idle' : 'Compact context';
    $('#ai-name').textContent = session.name;
    const st = $('#ai-status');
    const runtimeDetail = _runtimeStatusDetail(session);
    st.textContent = `● ${session.status}${runtimeDetail ? ' · ' + runtimeDetail : ''}`;
    st.title = runtimeDetail;
    st.className = `text-xs font-mono status-${session.status}`;
    const modelEl = $('#ai-model');
    modelEl.textContent = session.model || '-';
    let changeBtn = $('#ai-model-change');
    if (!changeBtn) {
        changeBtn = document.createElement('span');
        changeBtn.id = 'ai-model-change';
        changeBtn.style.cssText = 'cursor:pointer;font-size:10px;margin-left:4px;color:#475569;transition:color 0.15s';
        changeBtn.textContent = '⇄';
        changeBtn.addEventListener('mouseenter', () => changeBtn.style.color = '#94a3b8');
        changeBtn.addEventListener('mouseleave', () => changeBtn.style.color = '#475569');
        modelEl.parentElement.appendChild(changeBtn);
    }
    // Model can only be changed when the CLI is not actively processing — changing mid-turn would be ignored by the SDK
    const isIdle = session.status === 'idle' || session.status === 'stopped' || session.status === 'waiting';
    changeBtn.style.display = isIdle ? 'inline' : 'none';
    changeBtn.onclick = () => _showModelPicker(session.name, session.model, changeBtn);
    $('#ai-role').textContent = session.role || 'worker';
    // Cost is virtual (API-equivalent), not real spend — subscription model
    $('#ai-cost').textContent = fmtCost(session.cost_usd);
    $('#ai-cost').title = `${MODEL_COST_CURRENCY}${(session.cost_usd || 0).toFixed(4)} (CLI cost, includes cache)`;
    $('#ai-branch').textContent = session.branch || '-';
    $('#ai-scope').textContent = session.scope || '-';
    const descEl = $('#ai-desc'); const descLabel = $('#ai-desc-label');
    if (descEl && descLabel) {
        if (session.description) { descEl.textContent = session.description; descEl.title = session.description; descEl.classList.remove('hidden'); descLabel.classList.remove('hidden'); }
        else { descEl.classList.add('hidden'); descLabel.classList.add('hidden'); }
    }
    const ctxKey = `${currentScope}:${session.name}`;
    if (contextCache[ctxKey]) {
        setContextDisplay(contextCache[ctxKey]);
    } else {
        setContextDisplay('...');
        fetchAgentContext(session.name);
    }
}

function setContextDisplay(text) {
    let ctxEl = $('#ai-context');
    if (!ctxEl) {
        const grid = $('#agent-info .grid');
        const label = document.createElement('span');
        label.className = 'text-slate-500';
        label.textContent = 'Context';
        ctxEl = document.createElement('span');
        ctxEl.id = 'ai-context';
        ctxEl.className = 'text-amber-400';
        grid.append(label, ctxEl);
    }
    ctxEl.textContent = text;
}

function formatContext(ctx) {
    const pct = Math.round(ctx.percentage || 0);
    const total = ctx.total_tokens || 0;
    const max = ctx.max_tokens || 0;
    const totalK = total > 1000 ? `${(total/1000).toFixed(0)}k` : total;
    const maxK = max > 1000 ? `${(max/1000).toFixed(0)}k` : max;
    let s = `${pct}% (${totalK}/${maxK})`;
    if (ctx.cache_hit !== undefined) s += ` · cache ${Number(ctx.cache_hit).toFixed(2)}%`;
    return s;
}

async function _fetchAgentContextNow(name, scope) {
    if (!scope) return;
    try {
        const ctx = await api(`/api/sessions/${name}/context?scope=${encodeURIComponent(scope)}`, {pollKey: 'context'});
        const text = formatContext(ctx);
        contextCache[`${scope}:${name}`] = text;
        if (scope === currentScope && name === selectedAgent) setContextDisplay(text);
    } catch (e) {
        console.warn(`context ${name}: ${e.name}: ${e.message}`);
        // Прошлое значение показать честнее, чем прочерк: контекст растёт медленно, и
        // цифра минутной давности осмысленна, а «-» неотличим от «агент только что создан».
        const known = contextCache[`${scope}:${name}`];
        if (known && scope === currentScope && name === selectedAgent) {
            setContextDisplay(`${known} (не обновлено)`);
        }
    }
}

function fetchAgentContext(name) {
    const scope = currentScope;
    return _pollCoalesce(
        `context-request:${scope}:${name}`,
        () => _fetchAgentContextNow(name, scope),
    );
}

// === Agent List ===
function renderAgentList(sessions) {
    if (!sessions) return;
    currentSessions = sessions;
    const list = $('#agent-list');
    list.innerHTML = '';

    let colorsChanged = false;
    for (const s of sessions) {
        if (s.color && agentColors[s.name] !== s.color) {
            agentColors[s.name] = s.color;
            colorsChanged = true;
        }
        _sessionIds[_chatPositionKey(currentScope, s.name)] = s.id;  // ключ валидности кеша чата
    }
    if (colorsChanged) _repaintSenderColors();

    const byName = new Map();
    for (const s of sessions) byName.set(s.name, s);

    const childrenMap = new Map();
    const roots = [];
    for (const s of sessions) {
        const pn = s.parent_name || '';
        if (pn && byName.has(pn)) {
            if (!childrenMap.has(pn)) childrenMap.set(pn, []);
            childrenMap.get(pn).push(s);
        } else {
            roots.push(s);
        }
    }

    // Guard against cycles in the parent/child graph — shouldn't happen but the data comes from DB
    const seen = new Set();
    const buildNode = (session, isChild, isLast) => {
        if (seen.has(session.name)) return null;
        seen.add(session.name);
        const wrapper = document.createElement('div');
        wrapper.className = 'tree-node' + (isChild ? ' tree-child' : '') + (isLast ? ' tree-last' : '');
        wrapper.appendChild(createAgentItem(session));
        const kids = childrenMap.get(session.name) || [];
        if (kids.length > 0) {
            const childContainer = document.createElement('div');
            childContainer.className = 'tree-children';
            for (let i = 0; i < kids.length; i++) {
                const childNode = buildNode(kids[i], true, i === kids.length - 1);
                if (childNode) childContainer.appendChild(childNode);
            }
            wrapper.appendChild(childContainer);
        }
        return wrapper;
    };
    for (const r of roots) {
        const node = buildNode(r, false, false);
        if (node) list.appendChild(node);
    }
    for (const s of sessions) {
        if (!seen.has(s.name)) {
            seen.add(s.name);
            const node = buildNode(s, false, false);
            if (node) list.appendChild(node);
        }
    }
}

// Static defaults — server may extend these with custom pipeline roles at startup
let _roleIcons = {'orchestrator':'👑','worker':'⚙️','full-cycle':'🔄','sub-orchestrator':'🎯','reviewer':'🔍','watcher':'👁️'};
fetch('/api/role-icons').then(r=>r.json()).then(d=>{_roleIcons={..._roleIcons,...d}}).catch(()=>{});

// Cache timer pill. Claude has an exact 1h policy; Codex exposes a ≈30m reference window.
function _shortModel(m) {
    const meta = _modelMeta(m);
    return meta?.label || m.replace('claude-', '').replace('[1m]', '').replace('-1m', '');
}

function _cachePillState({running, expiresAt, ttlMs, approximate, nowMs = Date.now()}) {
    const ttlMin = ttlMs / 60000;
    if (running) {
        return approximate
            ? {
                tier: 'hot', label: '🔥≈', color: '#22c55e',
                title: `Running — Codex cache reference window ≈${ttlMin}m; actual ChatGPT TTL is not guaranteed`,
            }
            : {
                tier: 'hot', label: '🔥', color: '#22c55e',
                title: 'Running — cache refreshes every turn',
            };
    }

    const remMin = Math.floor((expiresAt - nowMs) / 60000);
    if (remMin <= 0) {
        const pastReferenceMin = Math.max(0, Math.floor((nowMs - expiresAt) / 60000));
        const pastReference = _cacheDuration(pastReferenceMin);
        return approximate
            ? {
                tier: 'unknown', label: `🧊? +${pastReference}`, color: '#64748b',
                title: `Codex cache state unknown · ${pastReference} past the ≈${ttlMin}m reference window; actual ChatGPT TTL is not guaranteed`,
            }
            : {
                tier: 'cold', label: '🧊', color: '#64748b',
                title: 'Cache cold — next turn ~20× дороже',
            };
    }

    let tier, label, color;
    const marker = approximate ? '≈' : '';
    if (remMin > ttlMin * 0.5) {
        tier = 'hot'; label = `🔥${marker}${remMin}m`; color = '#22c55e';
    } else if (remMin >= ttlMin * 0.2) {
        tier = 'warm'; label = `🟡${marker}${remMin}m`; color = '#eab308';
    } else {
        tier = 'cooling'; label = `🔴${marker}${remMin}m`; color = '#ef4444';
    }
    const title = approximate
        ? `Codex cache ≈${remMin}m within a ${ttlMin}m reference window; actual ChatGPT TTL is not guaranteed`
        : `Cache ${remMin}m — после истечения ~20× дороже`;
    return {tier, label, color, title};
}

function _cacheDuration(totalMinutes) {
    const minutes = Math.max(0, Math.floor(totalMinutes));
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours < 24) return `${hours}h${remainingMinutes ? `${remainingMinutes}m` : ''}`;
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    return `${days}d${remainingHours ? `${remainingHours}h` : ''}`;
}

function _cachePill(s) {
    const isDead = s.status === 'stopped' || s.status === 'error' || s.status === 'archived';
    if (isDead) return null;
    const running = s.status === 'running' || s.status === 'starting';
    const rawTtl = s.cache_ttl_seconds == null ? 3600 : Number(s.cache_ttl_seconds);
    if (!Number.isFinite(rawTtl) || rawTtl <= 0) return null;
    const ttl = rawTtl * 1000;
    let expiresAt = null;
    if (!running) {
        if (!s.last_turn_ts) return null;  // never ran a turn → no cache to time
        const lastTurn = new Date(s.last_turn_ts).getTime();
        if (!Number.isFinite(lastTurn)) return null;
        expiresAt = lastTurn + ttl;
    }
    const pill = document.createElement('span');
    pill.className = 'cache-pill';
    pill.dataset.cacheTtlMs = String(ttl);
    pill.dataset.cacheApproximate = s.cache_ttl_approximate === true ? '1' : '0';
    if (running) {
        pill.dataset.cacheRunning = '1';
    } else {
        pill.dataset.cacheExpires = String(expiresAt);
    }
    _renderCachePill(pill);
    return pill;
}

function _renderCachePill(pill) {
    const running = pill.dataset.cacheRunning === '1';
    const ttlMs = Number(pill.dataset.cacheTtlMs);
    if (!Number.isFinite(ttlMs) || ttlMs <= 0) return;
    const state = _cachePillState({
        running,
        expiresAt: Number(pill.dataset.cacheExpires),
        ttlMs,
        approximate: pill.dataset.cacheApproximate === '1',
    });
    pill.textContent = state.label;
    pill.style.color = state.color;
    pill.title = state.title;
    pill.dataset.tier = state.tier;
    if (pill.dataset.hideCold === '1') pill.style.display = state.tier === 'cold' ? 'none' : '';
}

// Client-side countdown — re-render all pills every 30s without re-polling
function _startCacheCountdown() {
    if (window._cacheTimer) return;
    window._cacheTimer = setInterval(() => {
        document.querySelectorAll('.cache-pill[data-cache-expires]').forEach(_renderCachePill);
    }, 30000);
    // Refresh orch tabs every 60s to pick up new last_turn_ts; the poll coordinator
    // pauses it while hidden and coalesces the startup request with this first tick.
    _pollRegister('orchestrators', loadOrchestrators, 60000, false);
}

function createAgentItem(s) {
    const isSelected = s.name === selectedAgent;
    const isDead = s.status === 'stopped' || s.status === 'error';
    const item = document.createElement('div');
    item.className = `agent-item flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
        isSelected ? 'bg-indigo-900/30 border border-indigo-500/30' :
        isDead ? 'opacity-50 hover:opacity-70' : 'hover:bg-slate-800/50'
    }`;
    item.addEventListener('click', () => selectAgent(s.name));
    if (s.id) item.dataset.sessionId = s.id;
    item.dataset.agentName = s.name;

    if (s.color) item.style.borderLeft = `3px solid ${s.color}`;

    const icon = document.createElement('span');
    const roleKey = s.role || (s.is_orchestrator ? 'orchestrator' : 'worker');
    icon.textContent = isDead ? '🪦' : (_roleIcons[roleKey] || '⚙️');
    icon.className = 'text-sm';

    const info = document.createElement('div');
    info.className = 'flex-1 min-w-0';
    const nameRow = document.createElement('div');
    nameRow.className = 'flex items-center justify-between';
    const nameEl = document.createElement('span');
    nameEl.className = 'text-xs font-medium truncate';
    nameEl.textContent = s.name;
    const statusEl = document.createElement('span');
    statusEl.className = 'agent-status text-xs font-mono font-bold shrink-0';
    statusEl.style.color = _STATUS_COLOR[s.status] || '#6b7280';
    statusEl.style.backgroundColor = _STATUS_BG[s.status] || 'rgba(107,114,128,0.1)';
    statusEl.style.padding = '1px 6px';
    statusEl.style.borderRadius = '4px';
    statusEl.textContent = `${_STATUS_ICON[s.status] || '●'} ${s.status}`;
    statusEl.title = [_STATUS_TITLE[s.status], _runtimeStatusDetail(s)].filter(Boolean).join(' · ');
    nameRow.append(nameEl, statusEl);

    const meta = document.createElement('div');
    meta.className = 'text-xs text-slate-600 mt-0.5 flex items-center gap-1';
    const pill = _cachePill(s);
    if (pill) meta.appendChild(pill);
    const modelSpan = document.createElement('span');
    const mc = _modelColor(s.model);
    modelSpan.textContent = _shortModel(s.model || '');
    modelSpan.title = s.model || '';
    modelSpan.style.cssText = `color:${mc};border:1px solid ${mc}44;padding:0 4px;border-radius:4px;font-size:10px`;
    meta.appendChild(modelSpan);
    if (s.cost_usd > 0) {
        const costSpan = document.createElement('span');
        costSpan.className = 'text-green-400';
        costSpan.style.marginLeft = 'auto';
        costSpan.textContent = fmtCost(s.cost_usd);
        costSpan.title = fmtCost(s.cost_usd);
        meta.appendChild(costSpan);
    }

    info.append(nameRow, meta);

    const pct = s.context_pct || 0;
    if (pct > 0) {
        const bar = document.createElement('div');
        bar.className = 'w-full h-1 bg-slate-800 rounded-full mt-1';
        const fill = document.createElement('div');
        fill.className = 'h-1 rounded-full transition-all';
        fill.style.width = `${Math.min(pct, 100)}%`;
        fill.style.backgroundColor = pct > 80 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#22c55e';
        fill.title = `${pct}% context`;
        bar.appendChild(fill);
        info.appendChild(bar);
    }
    item.append(icon, info);

    item.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        _showAgentContextMenu(e, s);
    });

    if (isSelected) updateAgentInfo(s);
    return item;
}

function _applyLiveAgentStatus(name, status) {
    if (!Object.hasOwn(_STATUS_ICON, status)) return;
    const runtimeDetail = _runtimeStatusDetail(currentSessions.find(s => s.name === name) || {});
    _refreshContextAfterTurn(name, status);
    const item = document.querySelector(
        `.agent-item[data-agent-name="${CSS.escape(name)}"]`
    );
    const badge = item?.querySelector('.agent-status');
    if (badge) {
        badge.style.color = _STATUS_COLOR[status] || '#6b7280';
        badge.style.backgroundColor = _STATUS_BG[status] || 'rgba(107,114,128,0.1)';
        badge.textContent = `${_STATUS_ICON[status]} ${status}`;
        badge.title = [_STATUS_TITLE[status], runtimeDetail].filter(Boolean).join(' · ');
    }
    if (name !== selectedAgent) return;
    const selected = $('#ai-status');
    selected.textContent = `● ${status}${runtimeDetail ? ' · ' + runtimeDetail : ''}`;
    selected.title = runtimeDetail;
    selected.className = `text-xs font-mono status-${status}`;
    updateStopButton(status);
}

function _refreshContextAfterTurn(name, status) {
    if (!currentScope) return;
    const key = `${currentScope}:${name}`;
    const wasRunning = _agentLiveStatuses.get(key) === 'running';
    _agentLiveStatuses.set(key, status);
    if (!wasRunning || status === 'running') return;
    delete contextCache[key];
    if (name === selectedAgent) fetchAgentContext(name);
}

let _streamStatusRefreshAt = 0;
function _wakeStatusRefreshFromStream() {
    const now = Date.now();
    if (now - _streamStatusRefreshAt < 3000) return;
    _streamStatusRefreshAt = now;
    _pollWake('sessions');
}

let _agentCtxMenu = null;
function _showAgentContextMenu(e, s) {
    if (_agentCtxMenu) _agentCtxMenu.remove();
    const menu = document.createElement('div');
    _agentCtxMenu = menu;
    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:9999;background:rgba(15,23,42,0.95);border:1px solid rgba(71,85,105,0.5);border-radius:8px;padding:4px 0;backdrop-filter:blur(12px);min-width:160px;box-shadow:0 8px 24px rgba(0,0,0,0.4)`;
    const close = () => { if (_agentCtxMenu) { _agentCtxMenu.remove(); _agentCtxMenu = null; } };
    document.addEventListener('click', close, { once: true });

    const mkItem = (label, color, fn) => {
        const item = document.createElement('div');
        item.style.cssText = `padding:6px 14px;font-size:12px;color:${color};cursor:pointer;white-space:nowrap`;
        item.textContent = label;
        item.addEventListener('mouseenter', () => item.style.background = 'rgba(51,65,85,0.5)');
        item.addEventListener('mouseleave', () => item.style.background = '');
        item.addEventListener('click', (ev) => { ev.stopPropagation(); close(); fn(); });
        return item;
    };

    const tgEnabled = s.tg_topic;
    menu.appendChild(mkItem(
        tgEnabled ? '📌 TG Topic: ON → OFF' : '📌 TG Topic: OFF → ON',
        tgEnabled ? '#f59e0b' : '#94a3b8',
        async () => {
            try {
                await api(`/api/sessions/${s.name}/tg-topic?scope=${encodeURIComponent(currentScope)}&enabled=${!tgEnabled}`, { method: 'PATCH' });
                await refreshSessions();
            } catch (e) { console.error('TG topic toggle failed:', e); }
        }
    ));

    document.body.appendChild(menu);
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 8) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 8) + 'px';
}

const FILE_ICONS = {
    py: '🐍', js: '📜', ts: '📜', json: '📋', md: '📝', html: '🌐', css: '🎨',
    txt: '📄', yml: '⚙️', yaml: '⚙️', toml: '⚙️', sh: '🖥', sql: '🗃',
    png: '🖼', jpg: '🖼', svg: '🖼', gif: '🖼',
};

function getFileIcon(name, isDir) {
    if (isDir) return '📁';
    const ext = name.split('.').pop().toLowerCase();
    return FILE_ICONS[ext] || '📄';
}

// Keyed by scope so each project remembers its own expanded folders independently
function _getExpandedFolders() {
    try { return new Set(JSON.parse(localStorage.getItem('expandedFolders_' + currentScope) || '[]')); } catch { return new Set(); }
}
function _saveExpandedFolder(path, expanded) {
    const set = _getExpandedFolders();
    if (expanded) set.add(path); else set.delete(path);
    localStorage.setItem('expandedFolders_' + currentScope, JSON.stringify([...set]));
}

async function loadFileTree(path, container) {
    container.innerHTML = '<div class="text-slate-600 px-2">Loading...</div>';
    try {
        const files = await api(`/api/files?path=${encodeURIComponent(path)}`);
        container.innerHTML = '';
        for (const f of files) container.appendChild(_createFileItem(f, container));
        if (files.length === 0) {
            container.innerHTML = '<div class="text-slate-600 px-2 italic">empty</div>';
        }
    } catch (e) {
        const errDiv = document.createElement('div');
        errDiv.className = 'text-red-400 px-2';
        errDiv.textContent = e.message;
        container.innerHTML = '';
        container.appendChild(errDiv);
    }
}

function _createFileItem(f, container) {
    const item = document.createElement('div');
    item.className = `file-item ${f.is_dir ? 'file-dir' : 'file-file'}`;
    item.draggable = true;
    item.dataset.path = f.path;
    item.dataset.isDir = f.is_dir;
    item.title = f.path;

    item.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', f.path);
        e.dataTransfer.effectAllowed = 'copy';
    });

    if (f.is_dir) {
        const savedExpanded = _getExpandedFolders();
        let expanded = savedExpanded.has(f.path);
        const children = document.createElement('div');
        children.className = 'file-children' + (expanded ? '' : ' hidden');
        item.textContent = `${expanded ? '📂' : '📁'} ${f.name}`;
        if (expanded) loadFileTree(f.path, children);
        item.addEventListener('click', async () => {
            expanded = !expanded;
            if (expanded && children.children.length === 0) {
                await loadFileTree(f.path, children);
            }
            children.classList.toggle('hidden', !expanded);
            item.textContent = `${expanded ? '📂' : '📁'} ${f.name}`;
            _saveExpandedFolder(f.path, expanded);
        });
        const wrapper = document.createElement('div');
        wrapper.appendChild(item);
        wrapper.appendChild(children);
        return wrapper;
    } else {
        item.textContent = `${getFileIcon(f.name, false)} ${f.name}`;
        item.style.position = 'relative';
        const sendBtn = document.createElement('span');
        sendBtn.textContent = '➜';
        sendBtn.title = 'Send path to chat';
        sendBtn.style.cssText = 'position:absolute;right:4px;top:1px;opacity:0;cursor:pointer;font-size:11px;color:#818cf8;transition:opacity 0.15s';
        sendBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const url = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(f.path)
                ? `/api/files/raw?path=${encodeURIComponent(f.path)}` : f.path;
            _insertPathAtCaret($('#chat-input'), f.path, url);
        });
        item.appendChild(sendBtn);
        item.addEventListener('mouseenter', () => sendBtn.style.opacity = '1');
        item.addEventListener('mouseleave', () => sendBtn.style.opacity = '0');
        item.addEventListener('click', () => openFilePreview(f.path));
        return item;
    }
}

async function _refreshContainer(container, dirPath) {
    try {
        const files = await api(`/api/files?path=${encodeURIComponent(dirPath)}`, {pollKey: 'files'});
        const newPaths = new Set(files.map(f => f.path));
        const existing = new Map();
        for (const child of [...container.children]) {
            const p = child.dataset?.path || child.querySelector?.('[data-path]')?.dataset?.path;
            if (p) existing.set(p, child); else child.remove();
        }
        for (const [p, el] of existing) {
            if (!newPaths.has(p)) el.remove();
        }
        let insertBefore = container.firstChild;
        for (const f of files) {
            if (existing.has(f.path)) {
                insertBefore = existing.get(f.path).nextSibling;
                continue;
            }
            const el = _createFileItem(f, container);
            container.insertBefore(el, insertBefore);
        }
    } catch {}
}

async function refreshOpenFolders() {
    const tree = $('#file-tree');
    if (!tree || !currentScope) return;
    // Панель файлов свёрнута — опрашивать нечего. Запрос всё равно уходил каждые 10 с и
    // занимал одно из ШЕСТИ соединений браузера, из которых одно навсегда держит SSE.
    // Замер 21.08: сам туннель прогоняет 20 параллельных запросов за 0.43 с — узкое место
    // не канал, а число одновременных запросов от вкладки.
    if (tree.offsetParent === null) return;
    await _refreshContainer(tree, currentScope);
    const containers = tree.querySelectorAll('.file-children:not(.hidden)');
    for (const container of containers) {
        const dirItem = container.previousElementSibling;
        if (!dirItem?.dataset?.path) continue;
        await _refreshContainer(container, dirItem.dataset.path);
    }
}

function initFilePanel() {
    const tree = $('#file-tree');

    if (currentScope) {
        loadFileTree(currentScope, tree);
        if (!_tasksTabActive && !_jobsTabActive && !_portfolioTabActive) {
            _pollRegister('files', refreshOpenFolders, 10000);
            _pollWake('files');
        } else _pollStop('files');
    } else {
        _pollStop('files');
    }
}

// === Refresh Loop ===
// Отдельный ритм для списка оркестраторов (55 КБ): метки непрочитанного по чужим
// вкладкам не требуют трёхсекундной свежести. Отметка ставится ДО запроса, иначе
// параллельные заходы успеют войти все.
let _orchFreshAt = 0;
const _ORCH_REFRESH_MS = 60000;
let refreshInProgress = false; // single-flight guard — skips if previous refresh is still in flight
async function refreshSessions() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    // Abort previous in-flight refresh so stale responses don't overwrite newer data
    if (refreshController) refreshController.abort();
    refreshController = new AbortController();
    const signal = refreshController.signal;
    // Capture scope at call time — guard below checks it didn't change while we were fetching
    const capturedScope = currentScope;

    try {
        if (!capturedScope) return;

        const [sessions, stats] = await Promise.all([
            // Свой бюджет тут был 20 с — из предположения, что канал юзера 15–80 КБ/с.
            // Замер perf это опроверг: здоровый ответ приезжает за секунды, а сломанный не
            // приезжает вовсе. Длинное ожидание не спасало ни одного запроса, зато мешало
            // повтору, поэтому здесь теперь дефолтный бюджет и три попытки.
            api(`/api/sessions?scope=${encodeURIComponent(capturedScope)}`, { signal, pollKey: 'sessions' }),
            api(`/api/stats?scope=${encodeURIComponent(capturedScope)}`, { signal, pollKey: 'sessions' }),
        ]);

        if (capturedScope !== currentScope) return;
        _renderSessionsAndStats(sessions, stats);
        snapshotSave(`sessions:${capturedScope}`, {sessions, stats});
        Connection.clear('sessions');

        // Список оркестраторов нужен для меток непрочитанного по ЧУЖИМ вкладкам, но он
        // весит 55 КБ и раньше тянулся каждые 3 с вместе с сессиями — 1.1 МБ в минуту на
        // канале 15–80 КБ/с. Метка, опоздавшая на десяток секунд, никому не мешает.
        if (Date.now() - _orchFreshAt >= _ORCH_REFRESH_MS) try {
            _orchFreshAt = Date.now();
            const freshOrchs = await api('/api/orchestrators', { signal });
            for (const fo of freshOrchs) {
                const existing = orchData.find(o => o.name === fo.name);
                if (existing) {
                    if (_orchestratorTurnFinished(existing, fo) && fo.scope !== currentScope) {
                        _unreadTabs.add(fo.scope);
                    }
                    existing.status = fo.status; existing.cost_usd = fo.cost_usd; existing.any_running = fo.any_running;
                }
            }
            updateOrchTabDots();
        } catch (e) {
            // Метки непрочитанного — украшение, но их пропажа не должна быть немой:
            // юзер иначе решит, что чужие вкладки молчат, а они просто не доехали.
            console.warn(`orchestrator dots: ${e.name}: ${e.message}`);
        }

        if (selectedAgent) {
            const agentSession = sessions.find(s => s.name === selectedAgent);
            if (agentSession) {
                updateStopButton(agentSession.status);
                if (agentSession.status !== 'running') {
                    removeWaitingIndicator();
                }
            }
            if (!eventSource) connectSSE();
        }
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.warn('refresh error:', e);
            _restoreSessionsSnapshot(capturedScope, e);
        }
    } finally {
        refreshInProgress = false;
    }
}

function _renderSessionsAndStats(sessions, stats) {
    $('#stats-line').innerHTML = `${stats.active} active · ${stats.total_sessions} total<br><span style="color:#64748b;font-size:10px">${MODEL_COST_CURRENCY}${stats.total_cost_usd} (w/o cache)</span>`;
    renderAgentList(sessions);
}

// Список агентов — то, из чего заполняются Model/Role/Cost/Branch/Scope. Пока он пуст,
// пуста и панель, и юзер видит прочерки вместо интерфейса. Снимок закрывает окно между
// загрузкой страницы и первым дошедшим ответом; когда список уже нарисован, не трогаем
// его вовсе — свежее в памяти всегда лучше снимка с диска.
function _restoreSessionsSnapshot(scope, error) {
    if (!scope || scope !== currentScope) return;
    if ($('#agent-list')?.children.length) return;
    const snapshot = snapshotLoad(`sessions:${scope}`);
    if (!snapshot?.data?.sessions || !snapshot.data.stats) {
        Connection.fail('/api/sessions', error);
        return;
    }
    _renderSessionsAndStats(snapshot.data.sessions, snapshot.data.stats);
    Connection.stale('sessions', snapshot.ts);
}

// === API ===
// Таймаут и число попыток — из замеров perf через канал юзера. Сломанный ответ не приходит
// НИКОГДА: между сервером и юзером сидит посредник, который подтверждает нам 165 КБ, а до
// браузера доносит 19–23 КБ. Каждая попытка падает с вероятностью ~0.48, три попытки
// опускают «сломано навсегда» с 48% до ~5%.
// Величина таймаута — цена ожидания перед повтором, и она снижена с 3.5 с до 2 с: замер с
// ноутбука юзера показал, что даже `app.js` 382 КБ приезжает за 0.75–0.98 с, а обычный
// API — за 0.2–0.7 с. Двойка
// накрывает виденный максимум с запасом 1.5×, а «аномалия 3.5 с на холодном заходе»,
// которую искали полдня, была этим самым таймаутом: первая попытка `wire=0 Б dur=3500`,
// вторая `wire=2009 Б dur=228`. Повтор отработал штатно — дорого стоило ожидание.
// 21.08: пробовали 4 с — юзер сообщил, что стало ХУЖЕ, и это сходится с механикой:
// когда узкое место — ОЧЕРЕДЬ за шестью соединениями, больший бюджет заставляет
// повисший запрос дольше удерживать слот. Откачено. Двойка выбиралась под сценарий #197 — «канал рвёт УСТАНОВКУ
// соединения, ждать дольше бесполезно». Замер с ноутбука в тот же день показал, что этот
// сценарий сейчас не действует: установка занимает 0.0001 с через туннель и 0.13 с через
// домен, обрывов 0 из 24, шесть параллельных запросов проходят за 0.42 с. Зато действует
// другое: дашборд опрашивает 7 живых scope, за 8 секунд уходит 19 запросов, и при шести
// соединениях HTTP/1.1 запрос ждёт СЛОТА, а не ответа. Замер самого юзера в его браузере:
// самый долгий ответ 526 мс при десятке TimeoutError — бюджет сгорал в очереди. Отвалившись,
// запрос ретраится и снова занимает слот, то есть очередь разгоняла сама себя. Успешные
// ответы приходят за 0.2–0.5 с, поэтому больший бюджет не удлиняет обычную работу — он
// выключает ложные срабатывания. Вернётся сценарий #197 (conn=0.000000s, code=000) — это
// первый кандидат на откат.
const _API_TIMEOUT_MS = 2000;
const _API_ATTEMPTS = 3;
// #197: канал юзера рвёт не передачу, а УСТАНОВКУ соединения — `conn=0.000000s`, `code=000`,
// висит 8-12 с. Замер: 12 попыток, 10 прошли, 2 умерли наглухо (~17%). Отсюда два следствия,
// оба противоположные тому, что подсказывает слово «медленный канал»:
// 1) ждать дольше бесполезно. Соединение либо встаёт быстро, либо не встаёт вовсе, поэтому
//    2 с остаются — растить бюджет значит просто дольше сидеть на заведомо мёртвой попытке;
// 2) а вот подряд повторять вредно. ТСПУ режет пачками, и три попытки вплотную попадают в
//    одно окно потерь. Джиттер разносит их: пауза случайна в [0, _API_RETRY_JITTER_MS],
//    и одна дешёвая пауза меняет три коррелированные попытки на три независимые.
// Верхняя граница выбрана так, чтобы худший случай (2 попытки × 2 с + 2 паузы) укладывался
// в ~5.6 с — меньше, чем те 6 с, что юзер и так ждал раньше без всякого джиттера.
const _API_RETRY_JITTER_MS = 800;
// Мутации остаются на прежних 5 с: повтора у них нет (не идемпотентны), и работу на сервере
// они делают ДО ответа — оборвать спавн воркера раньше значит соврать юзеру про неудачу.
const _API_MUTATION_TIMEOUT_MS = 5000;
const _API_MAX_CONCURRENT_GETS = 4;
const _API_MAX_BACKGROUND_GETS = 3;

let _apiActiveGets = 0;
const _apiGetQueue = [];

function _apiPermitAvailable(priority) {
    return _apiActiveGets < (
        priority === 'critical' ? _API_MAX_CONCURRENT_GETS : _API_MAX_BACKGROUND_GETS
    );
}

function _apiAcquireGetPermit(signal, priority = 'normal') {
    return new Promise((resolve, reject) => {
        const waiter = {signal, priority, resolve, reject, cancelled: false, onAbort: null};
        waiter.grant = () => {
            if (waiter.cancelled) return;
            waiter.onAbort && signal.removeEventListener('abort', waiter.onAbort);
            _apiActiveGets++;
            let released = false;
            resolve(() => {
                if (released) return;
                released = true;
                _apiReleaseGetPermit();
            });
        };
        if (signal?.aborted) {
            reject(signal.reason);
            return;
        }
        if (signal) {
            waiter.onAbort = () => {
                waiter.cancelled = true;
                reject(signal.reason);
            };
            signal.addEventListener('abort', waiter.onAbort, {once: true});
        }
        if (_apiPermitAvailable(priority)) waiter.grant();
        else _apiGetQueue.push(waiter);
    });
}

function _apiReleaseGetPermit() {
    _apiActiveGets--;
    for (let i = _apiGetQueue.length - 1; i >= 0; i--) {
        const waiter = _apiGetQueue[i];
        if (!waiter.cancelled && !waiter.signal?.aborted) continue;
        waiter.cancelled = true;
        waiter.onAbort && waiter.signal.removeEventListener('abort', waiter.onAbort);
        _apiGetQueue.splice(i, 1);
    }
    while (_apiGetQueue.length) {
        // У чата и первого списка оркестраторов есть зарезервированный четвёртый слот.
        // Фоновые poll-запросы используют максимум три и не могут поставить клик за собой.
        let index = _apiGetQueue.findIndex(waiter =>
            !waiter.cancelled && !waiter.signal?.aborted
            && waiter.priority === 'critical' && _apiPermitAvailable('critical'));
        if (index < 0) index = _apiGetQueue.findIndex(waiter =>
            !waiter.cancelled && !waiter.signal?.aborted && _apiPermitAvailable(waiter.priority));
        if (index < 0) break;
        const [waiter] = _apiGetQueue.splice(index, 1);
        waiter.grant();
    }
}

let _quotaMapFetchPromise = null;

function _fetchQuotaMapShared() {
    if (_quotaMapFetchPromise) return _quotaMapFetchPromise;
    const request = api('/api/usage/quota-map', {pollKey: 'quota-map'});
    const flight = request.finally(() => {
        if (_quotaMapFetchPromise === flight) _quotaMapFetchPromise = null;
    });
    _quotaMapFetchPromise = flight;
    return flight;
}

// Таймаут ставится ВСЕГДА, даже когда вызывающий передал свой signal. Раньше здесь было
// `opts.signal || AbortSignal.timeout(5000)`: свой signal (у нас это AbortController для
// single-flight) молча отменял таймаут, и зависший ответ висел вечно. В refreshSessions
// это фатально — `refreshInProgress` снимается в finally, который при зависании не
// наступает никогда, и список сессий больше не обновляется до перезагрузки страницы.
// Свой бюджет — параметром timeoutMs, а не собственным signal: одна ручка вместо двух.
// Повторяем ТОЛЬКО GET и только обрыв: 4xx/5xx — это ответ сервера, повтор его не изменит,
// а не-GET повторять нельзя, он не идемпотентен. Свой timeoutMs = вызывающий заявил, что
// запрос долгий по своей природе (агрегация usage) — такой бюджет он и получает, без повторов.
async function api(url, opts = {}) {
    const isGet = !opts.method || opts.method.toUpperCase() === 'GET';
    const priority = opts.priority === 'critical' ? 'critical' : 'normal';
    const attempts = (isGet && opts.timeoutMs === undefined) ? _API_ATTEMPTS : 1;
    const pollKey = opts.pollKey;
    const requestOpts = {...opts};
    delete requestOpts.pollKey;
    delete requestOpts.priority;
    delete requestOpts.timeoutMs;
    for (let attempt = 1; ; attempt++) {
        const releaseGetPermit = isGet ? await _apiAcquireGetPermit(opts.signal, priority) : null;
        let data;
        let error;
        try {
            try {
                const timeout = AbortSignal.timeout(opts.timeoutMs ?? (isGet ? _API_TIMEOUT_MS : _API_MUTATION_TIMEOUT_MS));
                const signal = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;
                const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...requestOpts, signal });
                Connection.observe(resp, url);
                if (!resp.ok) {
                    const text = await resp.text();
                    // Отказ на время перезапуска — штатный и повторяемый: вызов отклонён ДО
                    // побочного эффекта. Юзер до этого получал в чат сырой служебный JSON.
                    if (Connection.restartFromBody(resp.status, text)) {
                        Connection.setRestarting(true);
                        const refused = new Error('Orchestra перезапускается — вызов отклонён до изменений. Повтори через несколько секунд.');
                        refused.name = 'RestartPendingError';
                        throw refused;
                    }
                    const serverError = new Error(`${resp.status}: ${text}`);
                    serverError.status = resp.status;
                    throw serverError;
                }
                data = await resp.json();
                _pollNoteSuccess(pollKey);
                Connection.ok(url);
            } catch (e) {
                error = e;
            }
        } finally {
            releaseGetPermit?.();
        }
        if (!error) return data;
        // Отмена вызывающим (смена scope, single-flight) — намеренная, повтор воскресил бы
        // запрос, который уже никому не нужен.
        if (opts.signal?.aborted) throw error;
        const broken = error.name === 'TimeoutError' || error.name === 'TypeError';
        const transient = broken || (Number(error.status) >= 500 && Number(error.status) < 600);
        if (!broken || attempt >= attempts) {
            if (transient) _pollNoteFailure(pollKey, error);
            if (broken && attempts > 1) {
                Connection.fail(url, new DOMException('signal timed out', 'TimeoutError'), attempts);
            } else if (transient) Connection.fail(url, error, attempt);
            throw error;
        }
        const pause = Math.round(Math.random() * _API_RETRY_JITTER_MS);
        console.warn(`api ${url}: попытка ${attempt}/${attempts} — ${error.name}, пауза ${pause} мс`);
        await new Promise(resolve => setTimeout(resolve, pause));
    }
}

// === Rate Limit Banner (Anthropic server-side rate_limit, not subscription) ===
let _rateLimitTimer = null;
let _rateLimitAgent = null;

function _showRateLimitBanner(agentName, retryNum, maxRetries, delaySec) {
    const banner = document.getElementById('rate-limit-banner');
    if (!banner) return;
    _rateLimitAgent = agentName;
    let remaining = delaySec;
    banner.classList.remove('hidden');
    banner.classList.add('flex');
    const render = () => {
        banner.innerHTML = `⏳ <b>Rate limit (сервер Anthropic)</b> — ${escHtml(agentName)}: повтор ${retryNum}/${maxRetries} через <b class="text-amber-100">${remaining}с</b> <span class="text-amber-400/70">· это НЕ лимит твоей подписки</span>`;
    };
    render();
    if (_rateLimitTimer) clearInterval(_rateLimitTimer);
    _rateLimitTimer = setInterval(() => {
        remaining--;
        if (remaining <= 0) { render(); _hideRateLimitBanner(); return; }
        render();
    }, 1000);
}

function _hideRateLimitBanner() {
    const banner = document.getElementById('rate-limit-banner');
    if (_rateLimitTimer) { clearInterval(_rateLimitTimer); _rateLimitTimer = null; }
    _rateLimitAgent = null;
    if (banner) { banner.classList.add('hidden'); banner.classList.remove('flex'); banner.innerHTML = ''; }
}

// Parse "rate limited — retry N/M in Xs" from status log content
function _parseRateLimitStatus(content) {
    const m = content.match(/rate limited\s*—\s*retry\s*(\d+)\/(\d+)\s*in\s*(\d+)s/i);
    if (!m) return null;
    return { retry: +m[1], max: +m[2], delay: +m[3] };
}

// === Tasks Panel ===
let _tasksTabActive = false;

let _jobsTabActive = false;

let _portfolioTabActive = false;

const PortfolioPanel = (() => {
    let requestGeneration = 0;
    let currentPayload = {projects: []};
    let operatorCsrf = '';
    const openDisclosures = new Set();

    const _terminalStatuses = new Set(['done', 'paid', 'cancelled']);
    const _queueStatuses = new Set(['new', 'backlog']);

    function init() {
        if (document.querySelector('[data-left-tab="portfolio"]')) return;
        const folderButton = document.getElementById('open-folder-btn');
        const tabs = folderButton?.parentElement;
        if (!tabs) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.leftTab = 'portfolio';
        button.className = 'left-tab portfolio-tab flex-1 px-3 py-2 text-xs font-bold text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-colors';
        button.textContent = 'PROJECTS';
        button.title = 'Portfolio projects';
        button.setAttribute('aria-label', 'Открыть доску проектов');
        button.addEventListener('click', () => switchLeftTab('portfolio'));
        tabs.insertBefore(button, folderButton);
    }

    function projectMeta(project) {
        const owner = project.owner?.name || 'owner missing';
        const contributors = (project.contributors || []).map(member => member.name).filter(Boolean);
        const contributorText = contributors.length
            ? contributors.map(name => `<span class="portfolio-person">+ ${escHtml(name)}</span>`).join('')
            : '<span class="portfolio-person portfolio-person-muted">без саба</span>';
        return `<div class="portfolio-project-meta">
            <span class="portfolio-owner">◆ ${escHtml(owner)}</span>${contributorText}
        </div>`;
    }

    function taskNumber(task) {
        return task.task_display_number ?? task.par_number ?? task.par ?? task.id;
    }

    function waitsForTask(project, task) {
        const stableId = task.task_stable_id || '';
        if (!stableId) return [];
        return (project.waits || []).filter(wait =>
            wait.status === 'open' && wait.task_stable_id === stableId
        );
    }

    function taskCard(project, task, kind) {
        const waits = waitsForTask(project, task);
        const par = String(taskNumber(task));
        const namespace = task.task_namespace_id || project.task_namespace_id || '';
        const stableId = task.task_stable_id || '';
        const waitAttrs = waits.length
            ? ' data-wait-open="true"'
            : ' data-wait-open="false"';
        return `<button type="button" class="portfolio-road-task"
            data-road-task="true" data-road-task-kind="${escHtml(kind)}"
            data-task-par="${escHtml(par)}" data-task-project="${escHtml(namespace)}"
            data-task-status="${escHtml(task.status || '')}"
            data-task-stable-id="${escHtml(stableId)}"${waitAttrs}>
            <span class="portfolio-road-task-ref">#${escHtml(par)}</span>
            <strong>${escHtml(task.title || 'Без названия')}</strong>
            <small>${escHtml(task.status || 'unknown')}</small>
            ${waits.map(wait => `<em>НУЖЕН ОТВЕТ · ${escHtml(wait.question)}</em>`).join('')}
        </button>`;
    }

    function markerTarget(project, stageOrder, staged, unassigned) {
        let target = '';
        for (const label of stageOrder) {
            if ((staged.get(label) || []).some(task => task.status === 'in_progress')) {
                target = label;
            }
        }
        if (target) return `stage:${target}`;
        for (const label of stageOrder) {
            if ((staged.get(label) || []).some(task => _queueStatuses.has(task.status))) {
                return `stage:${label}`;
            }
        }
        if (unassigned.some(task => !_terminalStatuses.has(task.status))) return 'unassigned';
        return stageOrder.length ? `stage:${stageOrder[stageOrder.length - 1]}` : 'unassigned';
    }

    function markerHtml(active) {
        return active ? `<div class="portfolio-road-marker" data-road-marker="true">
            <i></i><span>мы здесь</span>
        </div>` : '';
    }

    function stageHtml(project, label, tasks, marker) {
        const active = tasks.some(task => task.status === 'in_progress');
        return `<section class="portfolio-road-stage" data-road-stage="true"
            data-road-stage-label="${escHtml(label)}" data-stage-active="${active}">
            <header><span>${escHtml(label)}</span><b>${tasks.length}</b></header>
            <div class="portfolio-road-stage-tasks">
                ${tasks.map(task => taskCard(project, task, 'stage')).join('') || '<span class="portfolio-road-empty">пока пусто</span>'}
            </div>
            ${markerHtml(marker)}
        </section>`;
    }

    function disclosure(project, kind, tasks) {
        if (!tasks.length) return '';
        const key = `${project.id}:${kind}`;
        const expanded = openDisclosures.has(key);
        const label = kind === 'queue'
            ? `${expanded ? '−' : '+'}${tasks.length} в очереди`
            : `${expanded ? '−' : '+'}${tasks.length} в истории`;
        return `<div class="portfolio-road-disclosure-block">
            <button type="button" class="portfolio-road-disclosure"
                data-road-disclosure="${kind}" data-disclosure-key="${escHtml(key)}"
                aria-expanded="${expanded}">${escHtml(label)}</button>
            ${expanded ? `<div class="portfolio-road-disclosed">
                ${tasks.map(task => taskCard(project, task, kind)).join('')}
            </div>` : ''}
        </div>`;
    }

    function unassignedHtml(project, tasks, marker, noStages) {
        const active = tasks.filter(task => !_queueStatuses.has(task.status) && !_terminalStatuses.has(task.status));
        const queue = tasks.filter(task => _queueStatuses.has(task.status));
        const history = tasks.filter(task => _terminalStatuses.has(task.status));
        const expanded = openDisclosures.has(`${project.id}:queue`) || openDisclosures.has(`${project.id}:history`);
        const title = noStages ? 'БЕЗ ЭТАПОВ' : 'БЕЗ ЯРЛЫКА';
        const empty = !tasks.length ? '<span class="portfolio-road-empty">Этапы не заданы · задач пока нет</span>' : '';
        return `<section class="portfolio-road-unassigned ${expanded ? 'is-expanded' : ''}"
            data-road-unassigned="true">
            <header><span>${title}</span><b>${tasks.length}</b></header>
            <div class="portfolio-road-stage-tasks">
                ${active.map(task => taskCard(project, task, 'active')).join('')}${empty}
                ${disclosure(project, 'queue', queue)}
                ${disclosure(project, 'history', history)}
            </div>
            ${markerHtml(marker)}
        </section>`;
    }

    function projectRoad(project) {
        const stageOrder = Array.isArray(project.stage_order) ? project.stage_order : [];
        const staged = new Map(stageOrder.map(label => [label, []]));
        const unassigned = [];
        for (const task of project.tasks || []) {
            const canonical = stageOrder.find(label => label === task.stage_label);
            if (canonical) staged.get(canonical).push(task);
            else unassigned.push(task);
        }
        const marker = markerTarget(project, stageOrder, staged, unassigned);
        const taskStableIds = new Set(
            (project.tasks || []).map(task => task.task_stable_id).filter(Boolean)
        );
        const projectWaits = (project.waits || []).filter(wait =>
            wait.status === 'open' && (
                !wait.task_stable_id || !taskStableIds.has(wait.task_stable_id)
            )
        );
        const goal = project.goal && ['active', 'paused'].includes(project.goal.status)
            ? `<div class="portfolio-road-goal"><span>ЦЕЛЬ</span><strong>${escHtml(project.goal.objective)}</strong></div>`
            : '';
        const road = stageOrder.map(label => stageHtml(
            project, label, staged.get(label), marker === `stage:${label}`
        )).join('');
        return `<article class="portfolio-project-road" data-project-id="${escHtml(project.id)}">
            <header class="portfolio-project-road-head">
                <div><h3>${escHtml(project.name)}</h3><code>${escHtml(project.id)}</code></div>
                ${projectMeta(project)}
            </header>
            ${goal}
            ${projectWaits.map(wait => `<button type="button" class="portfolio-project-wait"
                data-project-wait-id="${escHtml(wait.id)}">НУЖНО РЕШЕНИЕ · ${escHtml(wait.question)} · ОТВЕТИТЬ</button>`).join('')}
            <div class="portfolio-road-scroll" data-road-scroll="true">
                <div class="portfolio-road-track">
                    ${road}
                    ${unassignedHtml(project, unassigned, marker === 'unassigned', stageOrder.length === 0)}
                </div>
            </div>
        </article>`;
    }

    function bindInteractions(panel) {
        panel.querySelector('[data-portfolio-refresh]')?.addEventListener('click', load);
        panel.querySelectorAll('[data-road-disclosure]').forEach(button => {
            button.addEventListener('click', event => {
                event.stopPropagation();
                const key = button.dataset.disclosureKey;
                if (openDisclosures.has(key)) openDisclosures.delete(key);
                else openDisclosures.add(key);
                render(currentPayload);
            });
        });
        panel.querySelectorAll('[data-road-task]').forEach(button => {
            button.addEventListener('click', () => {
                const project = (currentPayload.projects || []).find(item =>
                    item.id === button.closest('[data-project-id]')?.dataset.projectId
                );
                const stableId = button.dataset.taskStableId || '';
                const waits = (project?.waits || []).filter(item =>
                    item.status === 'open' && item.task_stable_id === stableId
                ).map(wait => ({...wait, project_id: project.id}));
                showTaskDetail(
                    button.dataset.taskPar,
                    button.dataset.taskProject,
                    waits,
                );
            });
        });
        panel.querySelectorAll('[data-project-wait-id]').forEach(button => {
            button.addEventListener('click', () => {
                const project = (currentPayload.projects || []).find(item =>
                    item.id === button.closest('[data-project-id]')?.dataset.projectId
                );
                const wait = (project?.waits || []).find(item =>
                    item.id === button.dataset.projectWaitId
                );
                if (project && wait) {
                    showProjectWaitResponse(project, {...wait, project_id: project.id});
                }
            });
        });
    }

    function render(payload) {
        const panel = document.getElementById('tasks-panel');
        if (!panel) return;
        currentPayload = payload && typeof payload === 'object' ? payload : {projects: []};
        operatorCsrf = currentPayload.csrf_token || operatorCsrf;
        const projects = Array.isArray(currentPayload.projects) ? currentPayload.projects : [];
        panel.innerHTML = `<div class="portfolio-shell" data-portfolio-board="true">
            <header class="portfolio-board-head">
                <div><span>PORTFOLIO / ROAD</span><h2>Дорога к цели</h2></div>
                <div class="portfolio-board-actions">
                    <span>${projects.length} ${projects.length === 1 ? 'проект' : 'проектов'}</span>
                    <button type="button" data-portfolio-refresh aria-label="Обновить доску">↻</button>
                </div>
            </header>
            <div class="portfolio-road-board" data-portfolio-road="true">
                ${projects.map(projectRoad).join('') || '<div class="portfolio-empty">ПРОЕКТОВ ПОКА НЕТ</div>'}
            </div>
        </div>`;
        bindInteractions(panel);
    }

    // Доска показывает проекты ВЫБРАННОГО оркестратора, а не все подряд (#472).
    // Адресуем сессией по id: именно его хранит portfolio_members, а имена сессий
    // между scope не уникальны. Id лежит в опции пикера, отдельный запрос не нужен.
    function selectedOrchestratorSessionId() {
        return document.getElementById('orch-picker')?.selectedOptions?.[0]?.dataset?.id || '';
    }

    async function load() {
        const panel = document.getElementById('tasks-panel');
        if (!panel || !_portfolioTabActive) return;
        const generation = ++requestGeneration;
        panel.innerHTML = '<div class="portfolio-loading"><span></span>Собираю точное состояние проектов…</div>';
        try {
            const sessionId = selectedOrchestratorSessionId();
            const query = sessionId ? `?agent_session_id=${encodeURIComponent(sessionId)}` : '';
            const payload = await api(`/api/portfolio/projects${query}`);
            if (generation !== requestGeneration || !_portfolioTabActive) return;
            render(payload);
        } catch (error) {
            if (generation !== requestGeneration || !_portfolioTabActive) return;
            panel.innerHTML = `<div class="portfolio-error"><strong>Доска недоступна</strong><span>${escHtml(error.message || String(error))}</span></div>`;
        }
    }

    return { init, load, render, csrfToken: () => operatorCsrf };
})();

window.PortfolioPanel = PortfolioPanel;

function switchLeftTab(tab) {
    const fileTree = document.getElementById('file-tree');
    const tasksPanel = document.getElementById('tasks-panel');
    const jobsPanel = document.getElementById('jobs-panel');
    document.querySelectorAll('.left-tab').forEach(btn => {
        const isActive = btn.dataset.leftTab === tab;
        btn.classList.toggle('text-white', isActive);
        btn.classList.toggle('border-indigo-500', isActive);
        btn.classList.toggle('text-slate-500', !isActive);
        btn.classList.toggle('border-transparent', !isActive);
    });
    if (fileTree) fileTree.classList.toggle('hidden', tab !== 'files');
    if (tasksPanel) tasksPanel.classList.toggle('hidden', !['tasks', 'portfolio'].includes(tab));
    if (jobsPanel) jobsPanel.classList.toggle('hidden', tab !== 'jobs');
    _tasksTabActive = tab === 'tasks';
    _jobsTabActive = tab === 'jobs';
    _portfolioTabActive = tab === 'portfolio';
    document.getElementById('file-panel')?.classList.toggle('portfolio-mode', _portfolioTabActive);
    if (tab === 'files') initFilePanel();
    else _pollStop('files');
    if (_tasksTabActive) {
        _pollRegister('tasks', loadTasks, 5000);
        _pollWake('tasks');
    } else _pollStop('tasks');
    if (_jobsTabActive) {
        _pollRegister('jobs', loadJobs, 10000);
        _pollWake('jobs');
    } else _pollStop('jobs');
    if (_portfolioTabActive) {
        _pollRegister('portfolio', PortfolioPanel.load, 15000);
        _pollWake('portfolio');
    } else _pollStop('portfolio');
}

function openClientModal() {
    const modal = document.getElementById('client-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    _renderClientModal();
}
function closeClientModal() {
    const modal = document.getElementById('client-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}
async function _renderClientModal() {
    const body = document.getElementById('client-modal-body');
    if (!body) return;
    body.innerHTML = '<span class="text-slate-500">Loading...</span>';
    try {
        const data = await api('/api/models');
        const models = data.models || [];
        const connected = data.proxy_connected;
        let html = `<div class="flex items-center justify-between p-2.5 bg-slate-800/60 rounded-xl border border-slate-700/40 mb-3">
            <div class="flex items-center gap-2">
                <span class="text-xs font-medium ${connected ? 'text-emerald-400' : 'text-red-400'}">${connected ? '🟢 Connected' : '🔴 Offline'}</span>
            </div>
            <button id="client-refresh-btn" onclick="_refreshModels(this)" class="text-[10px] px-2.5 py-1 bg-indigo-600/40 hover:bg-indigo-600/60 rounded-lg text-indigo-300 transition-colors">🔄 Refresh</button>
        </div>`;
        if (!models.length) {
            html += `<div class="text-slate-500 italic py-6 text-center">No models available.<br>Models will appear after proxy connects.<br><span class="text-[10px] text-slate-600 mt-1 block">Auto-retry every 60s</span></div>`;
        } else {
            html += `<div class="text-[10px] text-slate-500 mb-2 uppercase tracking-wider font-bold">Models (${models.length})</div>`;
            for (const m of models) {
                const ctx = m.context_length ? `${Math.round(m.context_length / 1000)}k` : '';
                const priceIn = m.price_input != null ? `${MODEL_COST_CURRENCY}${m.price_input}/M` : '';
                const priceOut = m.price_output != null ? `${MODEL_COST_CURRENCY}${m.price_output}/M` : '';
                html += `<div class="p-2.5 bg-slate-800/60 rounded-xl border border-slate-700/40 mb-2">
                    <div class="flex items-center justify-between">
                        <span class="font-medium text-slate-200 text-xs">${escHtml(m.name)}</span>
                        ${ctx ? `<span class="text-[10px] text-indigo-400 font-mono">${ctx}</span>` : ''}
                    </div>
                    <div class="text-[10px] text-slate-500 font-mono mt-0.5">${escHtml(m.id)}</div>
                    ${priceIn || priceOut ? `<div class="text-[10px] text-slate-400 mt-1">↓ ${priceIn} &nbsp; ↑ ${priceOut}</div>` : ''}
                </div>`;
            }
        }
        html += `<div class="mt-3 p-2.5 bg-slate-800/40 rounded-xl border border-slate-700/30">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-1">Usage & Limits</div>
            <div class="text-[10px] text-slate-500 italic">Available in proxy admin panel</div>
        </div>`;
        body.innerHTML = html;
    } catch (e) {
        body.innerHTML = `<span class="text-red-400 text-xs">${escHtml(e.message)}</span>`;
    }
}
async function _refreshModels(btn) {
    const origText = btn.textContent;
    btn.textContent = '⏳ Loading...';
    btn.disabled = true;
    try {
        const result = await api('/api/models/refresh', { method: 'POST' });
        _modelsLoaded = false;
        await _renderClientModal();
        await loadModels();
    } catch {
        btn.textContent = '❌ Failed';
        setTimeout(() => { btn.textContent = origText; btn.disabled = false; }, 2000);
    }
}

const STATUS_ORDER = ['in_progress', 'done', 'new', 'backlog', 'paid', 'cancelled'];
const STATUS_COLORS = {
    in_progress: 'bg-blue-400', done: 'bg-amber-400', new: 'bg-white',
    backlog: 'bg-slate-500', paid: 'bg-emerald-400', cancelled: 'bg-red-400',
};
const STATUS_LABELS = {
    in_progress: 'IN PROGRESS', done: 'DONE', new: 'NEW',
    backlog: 'BACKLOG', paid: 'PAID', cancelled: 'CANCELLED',
};
// These statuses are collapsed by default — they're historical/archive, not actionable
const COLLAPSED_DEFAULT = new Set(['backlog', 'paid', 'cancelled']);
let _taskCollapsed = {};

async function _loadTasksNow() {
    const panel = document.getElementById('tasks-panel');
    if (!panel) return;
    try {
        const scope = currentScope || '';
        const data = await api(`/api/tm/tasks?scope=${encodeURIComponent(scope)}`, {pollKey: 'tasks'});
        renderTasksPanel(panel, data);
    } catch (e) {
        panel.innerHTML = '<div class="p-2 text-slate-500">Failed to load tasks</div>';
    }
}

function loadTasks() {
    return _pollCoalesce('tasks-request', _loadTasksNow);
}

// === Sub-agents Modal (post-hoc telemetry + transcripts) ===
function _fmtTokens(n) {
    n = n || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
}
function _fmtDuration(ms) {
    ms = ms || 0;
    if (ms < 1000) return ms + 'ms';
    const s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    const m = Math.floor(s / 60);
    const rem = Math.round(s % 60);
    if (m < 60) return `${m}m ${rem}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
}

function openSubagentsModal() {
    if (!selectedAgent || !currentScope) return;
    const modal = document.getElementById('subagents-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.getElementById('subagents-modal-agent').textContent = selectedAgent;
    document.addEventListener('keydown', _subagentsEscHandler);
    _loadSubagents();
}
function closeSubagentsModal() {
    const modal = document.getElementById('subagents-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.removeEventListener('keydown', _subagentsEscHandler);
}
function _subagentsEscHandler(e) { if (e.key === 'Escape') closeSubagentsModal(); }

async function _loadSubagents() {
    const body = document.getElementById('subagents-body');
    if (!body) return;
    body.innerHTML = '<div class="text-center text-slate-500 py-8">Loading...</div>';
    try {
        const sid = manager_session_id_for(selectedAgent);
        const data = await api(`/api/subagents/${encodeURIComponent(sid)}`);
        const subs = (data && data.subagents) || [];
        if (!subs.length) {
            body.innerHTML = '<div class="text-center text-slate-500 py-8 italic">Здесь пока нет ни SDK-агентов, ни фоновых задач.</div>';
            return;
        }
        const byNewest = (a, b) => String(b.started_at || '').localeCompare(String(a.started_at || ''));
        const agents = subs.filter(s => s.kind !== 'background').sort(byNewest);
        const jobs = subs.filter(s => s.kind === 'background').sort(byNewest);
        const activeCount = subs.filter(s => s.status === 'running').length;

        const sections = [
            `<div class="mb-4 flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
                <span class="rounded-full bg-purple-500/10 px-2 py-1 text-purple-300">🤖 SDK-агенты: ${agents.length}</span>
                <span class="rounded-full bg-sky-500/10 px-2 py-1 text-sky-300">⚙️ Фоновые задачи: ${jobs.length}</span>
                ${activeCount ? `<span class="rounded-full bg-amber-500/10 px-2 py-1 text-amber-300">⏳ Активны: ${activeCount}</span>` : ''}
            </div>`,
        ];
        if (agents.length) {
            sections.push(`<section class="mb-5">
                <h3 class="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-purple-300">SDK-агенты</h3>
                ${agents.map((s, i) => _renderSubagentCard(s, i)).join('')}
            </section>`);
        }
        if (jobs.length) sections.push(_renderBackgroundJobs(jobs));
        body.innerHTML = sections.join('');

        // Wire transcript toggles
        body.querySelectorAll('.sa-transcript-btn').forEach(btn => {
            btn.addEventListener('click', () => _toggleTranscript(btn, sid));
        });
        body.querySelectorAll('.sa-summary-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const full = btn.nextElementSibling;
                if (full) full.classList.toggle('hidden');
                btn.textContent = full && !full.classList.contains('hidden') ? '▼ Свернуть summary' : '▶ Показать summary';
            });
        });
    } catch (e) {
        body.innerHTML = `<div class="text-center text-red-400 py-8">Ошибка: ${_escHtml(e.message)}</div>`;
    }
}

// session_id lookup — orchData/agent items carry the DB session id
function manager_session_id_for(name) {
    const el = [...document.querySelectorAll('.agent-item')].find(el => {
        const nameEl = el.querySelector('.text-xs.font-medium');
        return nameEl && nameEl.textContent === name;
    });
    return (el && el.dataset.sessionId) || name;
}

// Short, readable card title: prefer description; else first meaningful slice of a
// (possibly huge multiline bash) command — stop at first ; << newline, cap length.
function _subagentTitle(s) {
    let t = (s.description || '').trim();
    if (!t) t = (s.last_tool_name || 'Sub-agent');
    // If it's a long command dump, take up to the first structural boundary
    const boundary = t.search(/[;\n]|<</);
    if (boundary > 0 && boundary < 80) t = t.slice(0, boundary);
    t = t.replace(/\s+/g, ' ').trim();
    return t.length > 80 ? t.slice(0, 80) + '…' : t;
}

function _subagentStatus(s) {
    const statusMap = {
        completed: ['🟢', '#22c55e', 'completed'],
        failed: ['🔴', '#ef4444', 'failed'],
        running: ['⏳', '#eab308', 'running'],
        stopped: ['⏹️', '#94a3b8', 'stopped'],
    };
    return statusMap[s.status] || ['⚪', '#64748b', s.status || '?'];
}

function _subagentDuration(s) {
    if (s.duration_ms) return _fmtDuration(s.duration_ms);
    if (s.status === 'running' && s.started_at) {
        const elapsed = Date.now() - new Date(s.started_at).getTime();
        if (Number.isFinite(elapsed) && elapsed >= 0) return _fmtDuration(elapsed);
    }
    return '';
}

function _meaningfulSummary(s) {
    const summary = String(s.summary || '').trim();
    if (!summary) return '';
    const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
    return normalize(summary) === normalize(s.description) ? '' : summary;
}

function _renderSubagentCard(s, idx) {
    const [icon, color, label] = _subagentStatus(s);
    const desc = _escHtml(_subagentTitle(s));
    const metrics = [];
    if (s.total_tokens) metrics.push(`🔢 ${_fmtTokens(s.total_tokens)}`);
    if (s.tool_uses) metrics.push(`🔧 ${s.tool_uses}`);
    const duration = _subagentDuration(s);
    if (duration) metrics.push(`⏱️ ${duration}`);
    if (s.last_tool_name) metrics.push(`⚙️ ${_escHtml(s.last_tool_name)}`);

    let summaryBlock = '';
    const summary = _meaningfulSummary(s);
    if (summary) {
        summaryBlock = `<div class="mt-2">
            <button class="sa-summary-toggle text-[10px] text-indigo-300 hover:text-indigo-200">▶ Показать summary</button>
            <div class="hidden mt-1 p-2 bg-slate-900/60 rounded-lg text-[11px] text-slate-300 whitespace-pre-wrap break-words">${_escHtml(summary)}</div>
        </div>`;
    }
    let fileBlock = '';
    if (s.output_file) {
        fileBlock = `<div class="mt-1 text-[10px] text-slate-500">📄 <span class="text-emerald-400 break-all">${_escHtml(s.output_file)}</span></div>`;
    }
    const agentId = s.transcript_id || '';
    const transcriptBtn = agentId
        ? `<button class="sa-transcript-btn text-[10px] px-2 py-1 bg-purple-600/30 hover:bg-purple-600/50 rounded-lg text-purple-200 transition-colors" data-agent-id="${_escHtml(agentId)}" data-idx="${idx}">📜 Транскрипт</button>
           <div class="sa-transcript-panel hidden mt-2"></div>`
        : `<span class="text-[10px] text-slate-600 italic">транскрипт ещё не записан</span>`;

    return `<div class="bg-slate-900/50 rounded-xl border border-slate-800 p-3 mb-3" style="border-left:3px solid ${color}">
        <div class="flex items-start justify-between gap-2 mb-2">
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-sm">🤖</span>
                    <span class="text-xs font-semibold text-white break-words">${desc}</span>
                    <span class="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase" style="background:rgba(167,139,250,0.15);color:#c4b5fd">agent</span>
                </div>
            </div>
            <span class="text-[10px] font-mono shrink-0" style="color:${color}">${icon} ${label}</span>
        </div>
        ${metrics.length ? `<div class="flex items-center gap-3 flex-wrap text-[11px] text-slate-400">${metrics.map(m => `<span>${m}</span>`).join('')}</div>` : ''}
        ${fileBlock}
        ${summaryBlock}
        <div class="mt-2">${transcriptBtn}</div>
    </div>`;
}

function _renderBackgroundJob(s) {
    const [icon, color, label] = _subagentStatus(s);
    const duration = _subagentDuration(s);
    const summary = _meaningfulSummary(s);
    const details = summary
        ? `<div class="mt-1 text-[10px] text-slate-400">${_saCollapsible(summary, 180)}</div>`
        : '';
    const output = s.output_file
        ? `<div class="mt-1 text-[10px] text-emerald-400 break-all">📄 ${_escHtml(s.output_file)}</div>`
        : '';
    return `<div class="rounded-lg border border-slate-800/80 bg-slate-950/30 px-3 py-2" style="border-left:2px solid ${color}">
        <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
                <div class="text-[11px] font-medium text-slate-200 break-words">${_escHtml(_subagentTitle(s))}</div>
                ${details}${output}
            </div>
            <div class="shrink-0 text-right">
                <div class="text-[10px] font-mono" style="color:${color}">${icon} ${label}</div>
                ${duration ? `<div class="mt-1 text-[10px] text-slate-500">⏱️ ${duration}</div>` : ''}
            </div>
        </div>
    </div>`;
}

function _renderBackgroundJobs(jobs) {
    const pinned = jobs.filter(s => s.status === 'running' || s.status === 'failed');
    const completed = jobs.filter(s => s.status !== 'running' && s.status !== 'failed');
    const recent = completed.slice(0, 12);
    const visibleIds = new Set([...pinned, ...recent].map(s => s.task_id));
    const visible = jobs.filter(s => visibleIds.has(s.task_id));
    const older = completed.slice(12);
    return `<section>
        <h3 class="mb-2 text-[10px] font-bold uppercase tracking-[0.16em] text-sky-300">Фоновые задачи</h3>
        <div class="space-y-2">${visible.map(_renderBackgroundJob).join('')}</div>
        ${older.length ? `<details class="mt-3 rounded-lg border border-slate-800/70 bg-slate-950/20 p-2">
            <summary class="cursor-pointer select-none text-[10px] text-slate-400 hover:text-slate-200">Показать старые задачи (${older.length})</summary>
            <div class="mt-2 space-y-2">${older.map(_renderBackgroundJob).join('')}</div>
        </details>` : ''}
    </section>`;
}

async function _toggleTranscript(btn, sid) {
    const panel = btn.parentElement.querySelector('.sa-transcript-panel');
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
        panel.classList.add('hidden');
        btn.textContent = '📜 Транскрипт';
        return;
    }
    const agentId = btn.dataset.agentId;
    if (!agentId) { panel.innerHTML = '<div class="text-slate-500 italic text-[10px] p-2">Нет transcript id</div>'; panel.classList.remove('hidden'); return; }
    panel.classList.remove('hidden');
    btn.textContent = '📜 Скрыть транскрипт';
    if (panel.dataset.loaded === '1') return;  // cache — don't refetch
    panel.innerHTML = '<div class="text-slate-500 text-[10px] p-2">Загрузка транскрипта...</div>';
    try {
        const data = await api(`/api/subagent-transcript/${encodeURIComponent(sid)}/${encodeURIComponent(agentId)}?limit=200`);
        const msgs = (data && data.messages) || [];
        if (!msgs.length) {
            panel.innerHTML = '<div class="text-slate-500 italic text-[10px] p-2">Транскрипт пуст или недоступен.</div>';
            return;
        }
        panel.innerHTML = `<div class="bg-slate-950/60 rounded-lg border border-slate-800 p-2 max-h-[300px] overflow-y-auto space-y-1.5">${msgs.map(_renderTranscriptMsg).join('')}</div>`;
        panel.dataset.loaded = '1';
    } catch (e) {
        panel.innerHTML = `<div class="text-red-400 text-[10px] p-2">Ошибка: ${_escHtml(e.message)}</div>`;
    }
}

// Collapsible block for long text (bash commands, prompts, result dumps).
// Short text shows inline; long text collapses behind a <details> toggle.
function _saCollapsible(text, threshold) {
    threshold = threshold || 200;
    const clean = _escHtml(text);
    if (text.length <= threshold) {
        return `<div class="text-slate-300 whitespace-pre-wrap break-words">${clean}</div>`;
    }
    const preview = _escHtml(text.slice(0, threshold));
    return `<details class="sa-details">
        <summary class="cursor-pointer text-slate-500 hover:text-slate-300 select-none">${preview}<span class="text-purple-400"> … показать всё (${text.length} симв.)</span></summary>
        <div class="text-slate-300 whitespace-pre-wrap break-words mt-1">${clean}</div>
    </details>`;
}

function _renderTranscriptMsg(m) {
    const role = m.type === 'user' ? 'user' : m.type === 'assistant' ? 'assistant' : m.type;
    const c = m.content;
    // A tool_use block naming Task/Agent means this line spawned a nested sub-agent
    const rows = [];
    const push = (label, labelColor, bodyHtml, nested) => {
        rows.push(`<div class="text-[10px] leading-relaxed ${nested ? 'ml-3 pl-2 border-l-2 border-purple-800/60' : ''}">
            <span style="color:${labelColor};font-weight:600">${label}</span>
            <div class="pl-2 border-l border-slate-800 mt-0.5">${bodyHtml}</div>
        </div>`);
    };

    if (typeof c === 'string') {
        if (!c.trim()) return '';
        const warning = role === 'assistant'
            ? _unexecutedToolCallWarningHtml(c)
            : '';
        push(role === 'user' ? '🔧 tool result' : '🤖 субагент',
             role === 'user' ? '#38bdf8' : '#a78bfa', warning + _saCollapsible(c));
    } else if (Array.isArray(c)) {
        let textWarning = role === 'assistant'
            ? _unexecutedToolCallWarningHtml(
                c.filter(block => block?.type === 'text')
                    .map(block => block.text || '')
                    .join('\n')
            )
            : '';
        for (const block of c) {
            if (!block || typeof block !== 'object') {
                const t = String(block); if (t.trim()) push('•', '#64748b', _saCollapsible(t));
                continue;
            }
            if (block.type === 'text') {
                if ((block.text || '').trim()) {
                    push('🤖 субагент', '#a78bfa', textWarning + _saCollapsible(block.text));
                    textWarning = '';
                }
            } else if (block.type === 'tool_use') {
                const name = block.name || 'tool';
                const isNested = /^(Task|Agent)$/i.test(name);
                const args = JSON.stringify(block.input || {});
                const bodyHtml = _saCollapsible(args, 120);
                push(`${isNested ? '🤖' : '🔧'} ${_escHtml(name)}`, isNested ? '#c4b5fd' : '#eab308', bodyHtml, isNested);
            } else if (block.type === 'tool_result') {
                const rc = block.content;
                const txt = typeof rc === 'string' ? rc : JSON.stringify(rc);
                push('📎 результат', '#64748b', _saCollapsible(txt, 200));
            } else {
                push('•', '#64748b', _saCollapsible(JSON.stringify(block), 200));
            }
        }
    } else if (c) {
        push('•', '#64748b', _saCollapsible(JSON.stringify(c)));
    }
    return rows.join('');
}

function renderTasksPanel(panel, data) {
    const tasks = data.tasks || [];
    const grouped = {};
    for (const t of tasks) { (grouped[t.status] ||= []).push(t); }

    let html = '';
    if (tasks.length === 0) {
        html += '<div class="p-4 text-center text-slate-600 italic">No tasks yet</div>';
        panel.innerHTML = html;
        return;
    }

    const _PRI_COLOR = {0:'#ef4444',1:'#f97316',2:'#eab308',3:'#22c55e'};
    for (const status of STATUS_ORDER) {
        const group = grouped[status];
        if (!group || group.length === 0) continue;
        const isCollapsed = _taskCollapsed[status] ?? COLLAPSED_DEFAULT.has(status);
        const dot = STATUS_COLORS[status] || 'bg-slate-400';
        const label = STATUS_LABELS[status] || status.toUpperCase();
        const arrow = isCollapsed ? '▸' : '▾';
        let suffix = '';
        if (status === 'done') {
            const debt = group.reduce((s, t) => s + (parseInt(t.debt) || 0), 0);
            if (debt > 0) suffix = ` → ${debt}k`;
        }
        html += '<div class="mt-1">';
        html += `<div class="px-2 py-1 flex items-center gap-1.5 cursor-pointer hover:bg-slate-800/30 rounded select-none" onclick="toggleTaskGroup('${status}')">`;
        html += `<span class="text-[10px]">${arrow}</span>`;
        html += `<span class="w-1.5 h-1.5 rounded-full ${dot} shrink-0"></span>`;
        html += `<span class="text-slate-400 font-bold flex-1">${label} (${group.length})</span>`;
        if (suffix) html += `<span class="text-amber-400 font-mono">${suffix}</span>`;
        html += '</div>';
        if (!isCollapsed) {
            for (const t of group) {
                const par = t.par;
                const priceInfo = t.price !== '0' ? t.price : '';
                const priColor = _PRI_COLOR[t.priority];
                html += `<div class="task-item flex items-center gap-1.5 px-2 py-0.5 hover:bg-slate-800/50 rounded cursor-pointer" style="position:relative" data-par="${par}" onclick="showTaskDetail('${par}')">`;
                if (priColor) html += `<span style="width:8px;height:8px;border-radius:50%;background:${priColor};flex-shrink:0"></span>`;
                html += `<span class="text-slate-600 font-mono shrink-0 w-6 text-right">${par}</span>`;
                html += `<span class="truncate flex-1 ${t.status === 'paid' ? 'text-slate-500' : ''}">${escHtml(t.title)}</span>`;
                if (priceInfo) html += `<span class="text-amber-400/70 shrink-0 font-mono">${priceInfo}</span>`;
                html += `<span class="task-inject-btn" onclick="event.stopPropagation();injectTask('${par}')" title="Insert #${par} into chat">📩</span>`;
                html += '</div>';
            }
        }
        html += '</div>';
    }
    panel.innerHTML = html;
}

function toggleTaskGroup(status) {
    const current = _taskCollapsed[status] ?? COLLAPSED_DEFAULT.has(status);
    _taskCollapsed[status] = !current;
    loadTasks();
}

function injectTask(par) {
    const input = document.getElementById('chat-input');
    if (!input) return;
    const ref = `[#${par}]`;
    if (!input.value.includes(`#${par}`)) {
        input.value = (input.value ? input.value + ' ' : '') + ref;
        input.focus();
    }
}

function _waitResponseSectionHtml(waitContext) {
    return `<section class="portfolio-wait-response"
        data-wait-response-section="true" data-wait-id="${escHtml(waitContext.id)}"
        data-wait-project="${escHtml(waitContext.project_id)}">
        <span>НУЖЕН ОТВЕТ</span>
        <strong>${escHtml(waitContext.question || '')}</strong>
        <textarea data-wait-response rows="4" maxlength="4000" placeholder="Напиши решение для оркестратора"></textarea>
        <div class="portfolio-wait-response-actions">
            <small data-wait-feedback></small>
            <button type="button" data-wait-submit>Отправить ответ</button>
        </div>
    </section>`;
}

function _bindWaitResponseSections(bodyEl) {
    bodyEl.querySelectorAll('[data-wait-response-section]').forEach(section => {
        const submit = section.querySelector('[data-wait-submit]');
        submit?.addEventListener('click', async () => {
            const textarea = section.querySelector('[data-wait-response]');
            const feedback = section.querySelector('[data-wait-feedback]');
            const response = textarea?.value.trim() || '';
            if (!response) {
                feedback.textContent = 'Ответ не может быть пустым';
                return;
            }
            submit.disabled = true;
            feedback.textContent = 'Отправляю…';
            try {
                const result = await api(
                    `/api/portfolio/projects/${encodeURIComponent(section.dataset.waitProject)}/waits/${encodeURIComponent(section.dataset.waitId)}/resolve`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRF-Token': PortfolioPanel.csrfToken(),
                        },
                        body: JSON.stringify({response}),
                    },
                );
                const state = result?.delivery?.delivery_state || result?.wait?.response_delivery_state || '';
                if (state === 'SUBMITTED') feedback.textContent = 'Ответ доставлен';
                else if (state === 'FAILED_BEFORE_SUBMIT') feedback.textContent = 'Не отправлено — можно повторить';
                else if (state === 'DELIVERY_UNKNOWN') feedback.textContent = 'Статус доставки неизвестен — повтор не отправлен';
                else feedback.textContent = 'Ответ принят и отправляется';
                textarea.disabled = true;
            } catch (error) {
                feedback.textContent = error.message || String(error);
                submit.disabled = false;
            }
        });
    });
}

function showProjectWaitResponse(project, waitContext) {
    const modal = document.getElementById('prompt-modal');
    const nameEl = document.getElementById('prompt-modal-name');
    const bodyEl = document.getElementById('prompt-modal-body');
    if (!modal || !nameEl || !bodyEl) return;
    nameEl.textContent = `${project.name} · ответ`;
    bodyEl.innerHTML = `<div class="space-y-3">${_waitResponseSectionHtml(waitContext)}</div>`;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    _bindWaitResponseSections(bodyEl);
}

async function showTaskDetail(par, projectSelector = '', waitContext = null) {
    try {
        const selector = projectSelector
            ? `?project=${encodeURIComponent(projectSelector)}`
            : (currentScope ? `?scope=${encodeURIComponent(currentScope)}` : '');
        const t = await api(`/api/tm/tasks/${encodeURIComponent(par)}${selector}`);
        if (t.error) return;
        const modal = document.getElementById('prompt-modal');
        const nameEl = document.getElementById('prompt-modal-name');
        const bodyEl = document.getElementById('prompt-modal-body');
        if (!modal || !nameEl || !bodyEl) return;
        nameEl.textContent = '#' + t.par + ' ' + t.title;
        let html = '<div class="space-y-3">';
        html += _taskCardBodyHtml(t);
        const commits = t.commits || t.git_commits || [];
        if (commits.length > 0) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">COMMITS</div>';
            for (const c of commits) {
                if (typeof c === 'string') { html += `<div class="text-xs font-mono">${escHtml(c.slice(0,60))}</div>`; continue; }
                const hash = (c.hash || '').slice(0, 7);
                const msg = (c.message || '').length > 50 ? c.message.slice(0, 50) + '…' : (c.message || '');
                const date = (c.date || '').slice(0, 10);
                const ins = c.insertions || 0; const del = c.deletions || 0; const files = c.files || 0;
                html += `<div style="display:flex;align-items:center;gap:6px;font-size:11px;line-height:1.6"><span style="color:#a78bfa;font-family:monospace;flex-shrink:0">${escHtml(hash)}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e2e8f0">${escHtml(msg)}</span><span style="color:#64748b;flex-shrink:0">${escHtml(date)}</span><span style="flex-shrink:0"><span style="color:#22c55e">+${ins}</span>/<span style="color:#ef4444">-${del}</span></span><span style="color:#64748b;flex-shrink:0">${files}f</span></div>`;
            }
            html += '</div>';
        }
        const sys = [];
        if (t.sync_revision) sys.push(`sync rev: ${t.sync_revision}`);
        if (t.worker_session_id) sys.push(`worker: ${t.worker_session_id}`);
        if (sys.length > 0) {
            html += '<div class="border-t border-slate-800 pt-2"><div class="text-slate-500 text-[10px] mb-1">SYSTEM</div>';
            html += `<div class="text-[10px] text-slate-600 font-mono">${sys.join(' · ')}</div></div>`;
        }
        const waits = Array.isArray(waitContext)
            ? waitContext
            : (waitContext?.id ? [waitContext] : []);
        html += waits.map(_waitResponseSectionHtml).join('');
        html += '</div>';
        bodyEl.innerHTML = html;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        _bindWaitResponseSections(bodyEl);
    } catch (e) { console.error('Task detail error:', e); }
}

// === Jobs Panel ===
const _JOB_ICONS = { timer: '⏰', file: '📄', command: '🖥️', ssh: '🔗', run: '▶️' };
const _JOB_STATUS = { active: '🟢', triggered: '✅', expired: '⏰', cancelled: '❌', failed: '❌' };

async function _loadJobsNow() {
    const panel = document.getElementById('jobs-panel');
    if (!panel) return;
    try {
        const scope = currentScope || '';
        const jobs = await api(`/api/bg/jobs?scope=${encodeURIComponent(scope)}`, {pollKey: 'jobs'});
        renderJobsPanel(panel, Array.isArray(jobs) ? jobs : (jobs.jobs || []));
    } catch (e) {
        panel.innerHTML = '<div class="p-2 text-slate-500">Failed to load jobs</div>';
    }
}

function loadJobs() {
    return _pollCoalesce('jobs-request', _loadJobsNow);
}

function _timeLeft(expiresAt) {
    if (!expiresAt) return '';
    const diff = new Date(expiresAt) - Date.now();
    if (diff <= 0) return 'expired';
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

let _jobsTimerInterval = null;
const _expandedJobs = new Set();
function renderJobsPanel(panel, jobs) {
    if (_jobsTimerInterval) { clearInterval(_jobsTimerInterval); _jobsTimerInterval = null; }
    if (jobs.length === 0) {
        panel.innerHTML = '<div class="p-4 text-center text-slate-600 italic">No background jobs</div>';
        return;
    }
    const active = jobs.filter(j => j.status === 'active');
    const done = jobs.filter(j => j.status !== 'active');
    panel.innerHTML = '';
    if (active.length > 0) {
        const hdr = document.createElement('div');
        hdr.className = 'px-2 py-1 text-slate-400 font-bold text-[10px]';
        hdr.textContent = `ACTIVE (${active.length})`;
        panel.appendChild(hdr);
        for (const j of active) panel.appendChild(_createJobItem(j));
    }
    if (done.length > 0) {
        const hdr = document.createElement('div');
        hdr.className = 'px-2 py-1 mt-1 text-slate-500 font-bold text-[10px]';
        hdr.textContent = 'COMPLETED';
        panel.appendChild(hdr);
        for (const j of done.slice(0, 10)) panel.appendChild(_createJobItem(j));
    }
    if (active.length > 0) {
        _jobsTimerInterval = setInterval(() => {
            panel.querySelectorAll('[data-job-elapsed]').forEach(el => {
                const created = el.dataset.jobElapsed;
                if (created) el.textContent = _elapsed(created);
            });
            panel.querySelectorAll('[data-job-expires]').forEach(el => {
                const exp = el.dataset.jobExpires;
                if (exp) el.textContent = _timeLeft(exp);
            });
        }, 1000);
    }
}

function _elapsed(isoStr) {
    const ms = Date.now() - new Date(isoStr).getTime();
    if (ms < 0) return '0s';
    const s = Math.floor(ms / 1000), m = Math.floor(s / 60), h = Math.floor(m / 60);
    if (h > 0) return `${h}h ${m % 60}m`;
    if (m > 0) return `${m}m ${s % 60}s`;
    return `${s}s`;
}

function _createJobItem(j) {
    const icon = _JOB_ICONS[j.type] || '⚙️';
    const statusIcon = _JOB_STATUS[j.status] || '⚪';
    const target = j.target_name || '';
    const msg = j.message ? j.message.slice(0, 50) : '';
    let cfg = {};
    try { cfg = JSON.parse(j.config || '{}'); } catch {}

    const wrap = document.createElement('div');
    const row = document.createElement('div');
    row.className = 'flex items-center gap-1.5 px-2 py-1 hover:bg-slate-800/50 rounded text-xs cursor-pointer';
    row.style.position = 'relative';

    let timerHtml = '';
    if (j.status === 'active' && j.created_at) {
        timerHtml = `<span data-job-elapsed="${j.created_at}" style="color:#38bdf8;font-size:10px;font-family:monospace">${_elapsed(j.created_at)}</span>`;
    }
    if (j.status === 'active' && j.expires_at) {
        timerHtml += `<span data-job-expires="${j.expires_at}" style="color:#64748b;font-size:10px;font-family:monospace">${_timeLeft(j.expires_at)}</span>`;
    }
    const cancelBtn = j.status === 'active' ? `<span class="job-cancel-btn" title="Cancel job">✕</span>` : '';

    row.innerHTML = `<span>${icon}</span><span class="flex-1 truncate"><span style="color:#e2e8f0">${escHtml(target)}</span>${msg ? ' <span style="color:#64748b">'+escHtml(msg)+'</span>' : ''}</span>${timerHtml}<span>${statusIcon}</span>${cancelBtn}`;

    const cancelEl = row.querySelector('.job-cancel-btn');
    if (cancelEl) cancelEl.addEventListener('click', (e) => { e.stopPropagation(); cancelJob(j.id); });

    const detail = document.createElement('div');
    detail.style.cssText = 'display:none;padding:4px 8px 6px 24px;font-size:10px;color:#64748b;line-height:1.6';
    const _dr = (k, v) => v ? `<div><span style="color:#475569">${k}:</span> <span style="color:#94a3b8">${escHtml(String(v))}</span></div>` : '';
    let dh = _dr('Type', j.type);
    dh += _dr('Target', target);
    dh += _dr('Status', j.status);
    if (cfg.command) dh += `<div><span style="color:#475569">Command:</span> <pre style="margin:2px 0;padding:3px 6px;background:#0d1117;border-radius:4px;font-size:10px;color:#cbd5e1;white-space:pre-wrap;word-break:break-all;max-height:60px;overflow-y:auto">${escHtml(cfg.command)}</pre></div>`;
    if (cfg.pattern) dh += _dr('Pattern', cfg.pattern);
    if (cfg.path) dh += _dr('Path', cfg.path);
    if (cfg.host) dh += _dr('Host', cfg.host);
    if (cfg.interval_seconds) dh += _dr('Interval', `${cfg.interval_seconds}s`);
    dh += _dr('Message', j.message);
    if (j.created_at) dh += _dr('Created', new Date(j.created_at).toLocaleString());
    if (j.expires_at) dh += _dr('Expires', new Date(j.expires_at).toLocaleString());
    if (j.output) dh += `<div><span style="color:#475569">Output:</span> <pre style="margin:2px 0;padding:3px 6px;background:#0d1117;border-radius:4px;font-size:10px;color:#cbd5e1;white-space:pre-wrap;word-break:break-all;max-height:80px;overflow-y:auto">${escHtml(String(j.output).slice(0, 500))}</pre></div>`;
    detail.innerHTML = dh;

    const isExpanded = _expandedJobs.has(j.id);
    detail.style.display = isExpanded ? 'block' : 'none';
    row.addEventListener('click', () => {
        const show = detail.style.display === 'none';
        detail.style.display = show ? 'block' : 'none';
        if (show) _expandedJobs.add(j.id); else _expandedJobs.delete(j.id);
    });

    wrap.appendChild(row);
    wrap.appendChild(detail);
    return wrap;
}

async function cancelJob(id) {
    try {
        await fetch(`/api/bg/jobs/${id}`, { method: 'DELETE' });
        loadJobs();
    } catch (e) { console.warn('Cancel job failed:', e); }
}

// ── Profiles Manager (редактор реестра профилей Claude) ──

let _profilesDropdownOpen = false;

function initProfilesManager() {
    const btn = $('#profiles-btn');
    const dropdown = $('#profiles-dropdown');
    if (!btn || !dropdown) return;
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        _profilesDropdownOpen = !_profilesDropdownOpen;
        dropdown.classList.toggle('hidden', !_profilesDropdownOpen);
        if (_profilesDropdownOpen) loadProfilesList();
    });
    document.addEventListener('click', (e) => {
        if (_profilesDropdownOpen && !dropdown.contains(e.target) && e.target !== btn) {
            _profilesDropdownOpen = false;
            dropdown.classList.add('hidden');
        }
    });
    $('#profile-add-btn')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const name = $('#profile-new-name').value.trim();
        const config_dir = $('#profile-new-dir').value.trim();
        const errEl = $('#profile-error');
        errEl.classList.add('hidden');
        if (!name) { errEl.textContent = 'name required'; errEl.classList.remove('hidden'); return; }
        try {
            const res = await api('/api/profiles', { method: 'POST', body: JSON.stringify({ name, config_dir }) });
            $('#profile-new-name').value = '';
            $('#profile-new-dir').value = '';
            await loadProfilesList();
            // Мягкое предупреждение: профиль сохранён, но config_dir не существует.
            if (res && res.warning) {
                errEl.textContent = res.warning;
                errEl.classList.remove('hidden');
            }
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
}

async function loadProfilesList() {
    try {
        const profiles = await api('/api/profiles');
        const list = $('#profiles-list');
        if (!list) return;
        list.innerHTML = '';
        if (!profiles.length) {
            list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No profiles.</div>';
            return;
        }
        for (const p of profiles) {
            const el = document.createElement('div');
            el.className = 'flex items-center gap-2 px-2.5 py-2 rounded-lg bg-slate-800/50 border border-slate-700/50';
            const isPersonal = p.name === 'personal';
            el.innerHTML = `
                <div class="flex-1 min-w-0">
                    <div class="text-xs font-medium text-white truncate">${escHtml(p.name)}</div>
                    <div class="text-[10px] text-slate-500 truncate">${escHtml(p.config_dir || 'env процесса')}</div>
                </div>
                ${isPersonal ? '' : `<button class="profile-del-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-red-900/60 rounded text-slate-400 hover:text-red-400 shrink-0" data-name="${escHtml(p.name)}" title="Delete">✕</button>`}
            `;
            list.appendChild(el);
        }
        list.querySelectorAll('.profile-del-btn').forEach(b => {
            b.addEventListener('click', async (e) => {
                e.stopPropagation();
                const errEl = $('#profile-error');
                errEl.classList.add('hidden');
                b.textContent = '⏳';
                try {
                    await api(`/api/profiles/${encodeURIComponent(b.dataset.name)}`, { method: 'DELETE' });
                    await loadProfilesList();
                } catch (err) {
                    b.textContent = '✕';
                    errEl.textContent = err.message;
                    errEl.classList.remove('hidden');
                }
            });
        });
    } catch (e) { console.warn('loadProfilesList failed:', e); }
}

// ── #366: model catalog screen ──────────────────────────────────────────────
let _CATALOG = [];

function openCatalogModal() {
  const modal = $('#catalog-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  loadCatalog();
}

function closeCatalogModal() {
  const modal = $('#catalog-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function loadCatalog() {
  try {
    const data = await api('/api/models/catalog');
    _CATALOG = data.catalog || [];
    renderCatalogList();
  } catch (e) { console.warn('catalog load failed:', e); }
}

async function refreshCatalog() {
  const btn = $('#catalog-refresh-btn');
  btn.disabled = true; btn.textContent = '…';
  try { await api('/api/models/catalog/refresh', { method: 'POST' }); } catch {}
  btn.disabled = false; btn.textContent = '↻ обновить';
  await loadCatalog();
}

function _catalogMatches(m) {
  const q = ($('#catalog-search')?.value || '').trim().toLowerCase();
  if (q && !(`${m.id} ${m.name}`.toLowerCase().includes(q))) return false;
  if ($('#catalog-free')?.checked && !_catalogIsFree(m)) return false;
  if ($('#catalog-tools')?.checked && !m.supports_tools) return false;
  if ($('#catalog-image')?.checked && !(m.input_modalities || []).includes('image')) return false;
  return true;
}

function _fmtPrice(p) { return p == null ? '—' : (p === 0 ? 'free' : `$${p}/M`); }
function _catalogIsFree(m) {
  return typeof m.is_free === 'boolean' ? m.is_free : String(m.id || '').endsWith(':free');
}
function _catalogHarnessEligible(m) {
  if (m.runtime !== 'harness') return true;
  if (typeof m.harness_eligible === 'boolean') return m.harness_eligible;
  return _catalogIsFree(m) && !!m.supports_tools;
}
function _catalogAvailable(m) { return m.available !== false; }

function _catalogToggle(flag, m) {
  const label = document.createElement('label');
  label.className = 'text-[10px] text-slate-400 flex items-center gap-1 cursor-pointer';
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.setAttribute('data-flag', flag);
  box.dataset.id = m.id;
  box.checked = !!m.flags[flag];
  if (m.runtime === 'harness' && (!_catalogHarnessEligible(m) || !_catalogAvailable(m))) {
    box.disabled = true;
    label.classList.add('opacity-40', 'cursor-not-allowed');
    label.title = _catalogAvailable(m) ? 'Harness допускает только точные :free маршруты с tool calling' : 'Маршрут больше не доступен на OpenRouter';
  }
  label.appendChild(box);
  label.appendChild(document.createTextNode(flag === 'dashboard' ? 'дашборд' : 'агентам'));
  return label;
}

function _catalogRow(m) {
  const row = document.createElement('div');
  row.className = 'flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-slate-800/60';
  const info = document.createElement('div');
  info.className = 'flex-1 min-w-0';
  const nameEl = document.createElement('div');
  nameEl.className = 'text-slate-300 truncate';
  nameEl.textContent = m.name;
  const metaEl = document.createElement('div');
  metaEl.className = 'text-[10px] text-slate-500 truncate';
  const admission = m.runtime === 'harness' && (!_catalogHarnessEligible(m) || !_catalogAvailable(m)) ? ' · blocked' : '';
  metaEl.textContent = `${m.id} · ${Math.round(m.context_length / 1000)}k · ${_fmtPrice(m.price_prompt)} in / ${_fmtPrice(m.price_completion)} out · ${m.runtime}${admission}`;
  info.append(nameEl, metaEl);
  row.append(info, _catalogToggle('dashboard', m), _catalogToggle('agents', m));
  return row;
}

function renderCatalogList() {
  const list = $('#catalog-list');
  list.innerHTML = '';
  const matches = _CATALOG.filter(_catalogMatches);
  for (const m of matches) list.appendChild(_catalogRow(m));
  if (!matches.length) {
    const empty = document.createElement('div');
    empty.className = 'text-slate-500 text-center py-6';
    empty.textContent = 'Ничего не найдено';
    list.appendChild(empty);
  }
}

document.addEventListener('change', async (e) => {
  const t = e.target;
  if (t instanceof HTMLInputElement && t.dataset.flag && t.dataset.id) {
    try {
      await api('/api/models/catalog/flags', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: t.dataset.id, [t.dataset.flag]: t.checked }) });
      const m = _CATALOG.find((x) => x.id === t.dataset.id);
      if (m) m.flags[t.dataset.flag] = t.checked;
    } catch (err) { t.checked = !t.checked; console.warn('flag set failed:', err); }
    return;
  }
  if (['catalog-free', 'catalog-tools', 'catalog-image'].includes(e.target.id)) renderCatalogList();
});

document.addEventListener('input', (e) => {
  if (e.target.id === 'catalog-search') renderCatalogList();
});
