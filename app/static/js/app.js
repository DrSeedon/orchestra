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
// localMessages tracks messages sent from this tab so SSE echo doesn't create duplicates
let localMessages = new Set();
let pendingUserMsgs = [];
let pendingBubble = null;
let uiDebounceTimer = null;
let refreshController = null;
// UI debounce: rapid-fire messages from the user are batched into one send before the timer fires
const UI_DEBOUNCE_MS = 2500;
let scrollAfterLoad = true;
// Следуем ли за новыми сообщениями. Правило как в мессенджерах: внизу — следуем,
// ушёл читать выше — не трогаем вообще. Снимается в обработчике scroll.
let _chatFollow = true;
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
function _trimChatNodes(chat) {
    if (!chat || !_chatFollow) return;
    while (chat.children.length > _chatTrimLimit) chat.removeChild(chat.firstChild);
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
    chat.scrollTo({top: chat.scrollHeight, behavior});
    _syncChatJumpButton();
}

let _chatTimelineObserver = null;

const NOTIFY_USER_TOOL = 'mcp__orchestra__notify_user';
const SILENT_TURN_MARKER = '[[ORCHESTRA:SILENT_TURN]]';

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

function _tagChatTimelineNode(node, type, ts) {
    if (!node || node.dataset.chatNavKind) return;
    const kind = _chatTimelineKind(type, node);
    const labels = {user: 'Моё сообщение', worker: 'Сообщение воркера', tool: 'Инструмент',
                    error: 'Ошибка', status: 'Статус', agent: 'Ответ агента',
                    notify: 'Оркестратор зовёт'};
    let time = '';
    if (ts) {
        const date = new Date(ts);
        if (!Number.isNaN(date.getTime())) time = `, ${date.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'})}`;
    }
    node.dataset.chatNavKind = kind;
    // У зова причина и есть смысл метки: она объясняет, ЗАЧЕМ дёрнули, прямо в подсказке.
    const reason = kind === 'notify' ? _notifyUserReason(node) : '';
    node.dataset.chatNavLabel = reason
        ? `${labels[kind]}: ${reason}${time}`
        : `${labels[kind]}${time}`;
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
}

function _removeChatTimelineMarker(node) {
    const marker = node?._chatTimelineMarker;
    if (!marker) return;
    marker.remove();
    node._chatTimelineMarker = null;
}

// Счёт берём из самой дорожки, а не из отдельных счётчиков: пара «инкремент при вставке /
// декремент при удалении» — вторая копия истины, которая расходится с нарисованным.
function _syncChatTimelineControls() {
    const track = $('#chat-timeline-track');
    for (const [cls, countId, prevId, nextId, label] of [
        ['is-user', '#chat-user-count', '#chat-user-prev', '#chat-user-next', 'Я'],
        ['is-notify', '#chat-notify-count', '#chat-notify-prev', '#chat-notify-next', '🔔'],
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

function initChatTimeline() {
    const chat = $('#chat');
    if (!chat || _chatTimelineObserver) return;
    _addNotifyPermissionBtn();
    _addNotifyNav();
    for (const node of chat.children) _addChatTimelineMarker(node);
    _syncChatTimelineControls();
    _chatTimelineObserver = new MutationObserver(records => {
        for (const record of records) {
            for (const node of record.removedNodes) if (node.nodeType === Node.ELEMENT_NODE) _removeChatTimelineMarker(node);
            for (const node of record.addedNodes) if (node.nodeType === Node.ELEMENT_NODE) _addChatTimelineMarker(node);
        }
        _syncChatTimelineControls();
    });
    _chatTimelineObserver.observe(chat, {childList: true});
    $('#chat-user-prev')?.addEventListener('click', () => _jumpChatTimelineKind('is-user', -1));
    $('#chat-user-next')?.addEventListener('click', () => _jumpChatTimelineKind('is-user', 1));
    $('#chat-notify-prev')?.addEventListener('click', () => _jumpChatTimelineKind('is-notify', -1));
    $('#chat-notify-next')?.addEventListener('click', () => _jumpChatTimelineKind('is-notify', 1));
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

// === Откуда берётся история чата (#8) ===
// Раньше здесь жил кеш отрисованного DOM в памяти вкладки (#2): он давал 30 мс на
// повторном заходе, но умирал на F5 и ключевался по ИМЕНИ агента, из-за чего проверка
// на пересоздание сессии зависела от гонки с фоновым опросом. Теперь история берётся из
// зеркала журнала в IndexedDB (см. _storeRead выше) — одинаково для первого захода,
// повторного и после F5. Один источник, одна инвалидация.
const _sessionIds = {};  // _chatPositionKey() -> session.id, заполняется в renderAgentList и _storeSync
const _CHAT_PAGE = 100;  // столько строк показываем при заходе — как и раньше при limit=100
// Столько строк рисуем в ПЕРВОМ кадре; остальное — после него. Двадцать — это ровно то,
// что раньше лежало в зеркале и давало чат за 871 мс против 1186 мс на сотне строк.
const _CHAT_MIRROR_DEADLINE = 250;  // сколько ждём IndexedDB, прежде чем идти в сеть
// Ниже этого числа строк зеркало считается непригодным и страница берётся сетью.
// Замер 21.08: у редко открываемого агента зеркало отдавало 16 узлов — формально
// «попадание», фактически пустой экран.
const _CHAT_MIN_FROM_STORE = 40;
// Потолок на СУММАРНЫЙ content ответа (db.py:1741). 16 000 Б выбирались под старую схему,
// где страница набиралась четырьмя порциями и каждая должна была влезть под порог, на
// котором посредник у юзера рвал ответ (~19 КБ по проводу, #70/#72). Теперь запрос ровно
// один, и бюджет задаёт не размер порции, а сколько сообщений вообще попадёт на экран: при
// 16 000 приходило 35 строк, то есть ~15 узлов после схлопывания пар «вызов+результат», и
// чат выглядел пустым. 32 000 при замеренном соотношении (11 637 Б content -> 6 063 Б gzip)
// даёт ~16 КБ по проводу — под тем же порогом. Увидишь в консоли «история не пришла» —
// это первый кандидат на откат.
const _CHAT_CHUNK_BYTES = 32000;

// === Зеркало журнала в IndexedDB (#8) ===
// Строки logs неизменяемы (в app/db.py ровно один INSERT и оптовый DELETE по возрасту,
// ни одного UPDATE), поэтому сохранённая строка не может стать неверной — только исчезнуть.
// Отсюда вся инвалидация сводится к трём правилам: чистим сессии, которых больше нет,
// стираем всё при откате БД, и никогда не чистим по пустому списку.
const _STORE_DB = 'orchestra';
// Холодная синхронизация НЕ тянет строки: tail=0 — только карта сессий и отметка.
// Замер (#72, по проводу через домен): tail=20 на все сессии стоил 145.5 КБ, а рисовалось
// из них ~5% — хвост открытого агента. Причём даже при попадании в зеркало страница чата
// всё равно добиралась с сервера (в зеркале 20 строк, показываем 100), так что предзагрузка
// экономила не запрос, а один кадр отрисовки. Зеркало наполняется тем, что юзер открыл
// (_storePut в _fetchHistory) и живёт между заходами — F5 по-прежнему
// рисует открытого агента без сети.
const _STORE_TAIL = 0;
const _STORE_CAP = 16384;       // байт на сообщение; блоб со скриншотом приедет обрезанным
const _STORE_SYNC_MS = 15000;
let _storeDb = null;            // IDBDatabase | null (null = хранилища нет, работаем как раньше)
let _storeReady = null;         // Promise, чтобы не открывать базу дважды
let _storeOff = false;          // отключились навсегда: приватное окно, отказ квоты, старый сервер
let _storeSessionMap = null;    // [{id, name, scope}] — последняя известная карта агентов

// Одна точка, где хранилище объявляется недоступным. Причину печатаем всегда: пустой
// catch тут стоил бы нам тихой деградации, которую никто не заметит месяцами.
function _storeDisable(why, err) {
    if (_storeOff) return;
    _storeOff = true;
    _storeDb = null;
    console.warn(`[store] выключен: ${why}` + (err ? ` — ${err.name || 'Error'}: ${err.message || err}` : ''));
}

function _storeOpen() {
    if (_storeOff) return Promise.resolve(null);
    if (_storeReady) return _storeReady;
    _storeReady = new Promise((resolve) => {
        let rq;
        try { rq = indexedDB.open(_STORE_DB, 1); }
        catch (e) { _storeDisable('indexedDB.open бросил исключение', e); return resolve(null); }
        rq.onupgradeneeded = () => {
            const db = rq.result;
            const logs = db.createObjectStore('logs', {keyPath: 'id'});
            logs.createIndex('by_session', 'session_id');
            db.createObjectStore('meta');
        };
        rq.onsuccess = () => { _storeDb = rq.result; resolve(_storeDb); };
        rq.onerror = () => { _storeDisable('не удалось открыть IndexedDB', rq.error); resolve(null); };
        rq.onblocked = () => { _storeDisable('IndexedDB заблокирована другой вкладкой'); resolve(null); };
    });
    return _storeReady;
}

function _storeTx(mode, names, body) {
    return new Promise((resolve, reject) => {
        const tx = _storeDb.transaction(names, mode);
        let out;
        tx.oncomplete = () => resolve(out);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
        out = body(tx);
    });
}

// Одна синхронизация: холодная при пустой отметке, дальше только новое.
// Возвращает число принятых строк (для замеров и тестов), null — если хранилища нет.
async function _storeSync() {
    const db = await _storeOpen();
    if (!db) return null;
    let watermark = 0, knownSessions = '';
    try {
        [watermark, knownSessions] = await _storeTx('readonly', ['meta'], (tx) => {
            const m = tx.objectStore('meta');
            const w = m.get('watermark'), s = m.get('sessions');
            return new Promise((res) => { s.onsuccess = () => res([w.result || 0, s.result || '']); });
        });
    } catch (e) { _storeDisable('не читается watermark', e); return null; }

    const url = `/api/logs/sync?after_id=${watermark}&tail=${_STORE_TAIL}&cap=${_STORE_CAP}`;
    let data;
    try {
        const resp = await fetch(url, {cache: 'no-store'});
        if (resp.status === 404) {
            // Сервер ещё не перезапущен после мержа — маршрута нет. Это НЕ то же самое,
            // что отсутствие __session в потоке (см. connectSSE): лечится рестартом.
            _storeDisable('сервер не знает /api/logs/sync (404) — нужен рестарт orchestra');
            return null;
        }
        if (!resp.ok) { _storeDisable(`/api/logs/sync ответил ${resp.status}`, new Error((await resp.text()).slice(0, 200))); return null; }
        data = await resp.json();
        _pollNoteSuccess('store');
    } catch (e) {
        _pollNoteFailure('store', e);
        console.warn('[store] синхронизация не удалась:', e.name, e.message);
        return null;
    }

    const live = data.live_sessions;
    if (Array.isArray(live) && live.length) {
        for (const s of live) _sessionIds[_chatPositionKey(s.scope, s.name)] = s.id;
        _storeSessionMap = live;
    }
    // Полный обход индекса стоит денег, а список сессий меняется редко — сверяем его
    // отпечаток и чистим только когда он реально изменился.
    const liveKey = Array.isArray(live) ? live.map(s => s.id).sort().join(',') : '';
    const needPrune = Array.isArray(live) && live.length > 0 && liveKey !== knownSessions;
    try {
        await _storeTx('readwrite', ['logs', 'meta'], (tx) => {
            const logs = tx.objectStore('logs');
            // Откатили или подменили БД: наша отметка выше, чем всё, что есть на сервере.
            // Совпадения id при этом ничего не значат — стираем целиком.
            if (watermark > data.max_log_id) {
                console.warn(`[store] watermark ${watermark} > max_log_id ${data.max_log_id} — БД подменили, стираю зеркало`);
                logs.clear();
                watermark = 0;
            }
            for (const row of data.logs) logs.put(row);
            // Пустой список — это сбой на той стороне, а не «сессий не осталось».
            // Чистка необратима, поэтому по пустому списку не чистим никогда.
            if (needPrune) {
                const alive = new Set(live.map(s => s.id));
                const cur = logs.index('by_session').openKeyCursor();
                cur.onsuccess = () => {
                    const c = cur.result;
                    if (!c) return;
                    if (!alive.has(c.key)) logs.delete(c.primaryKey);
                    c.continue();
                };
            }
            const meta = tx.objectStore('meta');
            const top = data.logs.length ? data.logs[data.logs.length - 1].id : watermark;
            meta.put(Math.max(top, watermark, 0), 'watermark');
            if (needPrune) meta.put(liveKey, 'sessions');
            // Карту имя+scope → id кладём В хранилище: после F5 она понадобится ДО того,
            // как вернётся первый /api/sessions, иначе читать журнал будет нечем.
            if (Array.isArray(live) && live.length) meta.put(live, 'session_map');
        });
    } catch (e) { _storeDisable('не пишется в IndexedDB', e); return null; }
    return data.logs.length;
}

// Какой session_id у этого агента. Свежий ответ /api/sessions главнее, но после F5 его
// ещё нет — тогда берём карту, сохранённую прошлой синхронизацией. Ошибиться тут не страшно:
// поток назовёт настоящую сессию, и несовпадение вычистит чат (см. connectSSE).
async function _storeSessionId(scope, name) {
    const key = _chatPositionKey(scope, name);
    if (!key) return null;
    if (_sessionIds[key]) return _sessionIds[key];
    if (!_storeSessionMap) {
        const db = await _storeOpen();
        if (!db) return null;
        try {
            _storeSessionMap = await _storeTx('readonly', ['meta'], (tx) => {
                const r = tx.objectStore('meta').get('session_map');
                return new Promise((res) => { r.onsuccess = () => res(r.result || []); });
            });
        } catch (e) { _storeDisable('не читается карта сессий', e); return null; }
    }
    const hit = _storeSessionMap.find((s) => s.name === name && s.scope === scope);
    return hit ? hit.id : null;
}

// Последние `limit` строк сессии, по возрастанию id. Пусто → зеркала для неё нет.
async function _storeRead(sessionId, limit) {
    const db = await _storeOpen();
    if (!db || !sessionId) return [];
    try {
        return await _storeTx('readonly', ['logs'], (tx) => {
            const rows = [];
            const cur = tx.objectStore('logs').index('by_session')
                .openCursor(IDBKeyRange.only(sessionId), 'prev');   // от свежих к старым
            return new Promise((res) => {
                cur.onsuccess = () => {
                    const c = cur.result;
                    if (!c || rows.length >= limit) return res(rows.reverse());
                    rows.push(c.value);
                    c.continue();
                };
            });
        });
    } catch (e) { _storeDisable('не читается IndexedDB', e); return []; }
}

function initStoreSync() {
    const kick = () => { _pollRegister('store', _storeSync, _STORE_SYNC_MS); };
    if (window.requestIdleCallback) requestIdleCallback(kick, {timeout: 3000});
    else setTimeout(kick, 500);
    // Единственное место, где обрабатывается «вкладку развернули». Дел здесь два и оба
    // срочные: подтянуть хвост журнала и проверить, жив ли сервер, — при свёрнутой вкладке
    // таймеры идут не по расписанию, и его возврат замечался через десятки секунд (#15).
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        _pollWakeAll();
    });
}

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
    initQuotaLines();
    initHeartbeat();
    _startCacheCountdown();
    // Только после load: холодная синхронизация ~100 КБ не должна делить узкий канал
    // с загрузкой самой страницы (HTTP/1.1, 6 соединений, одно занято SSE).
    window.addEventListener('load', initStoreSync, {once: true});
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
    if (!selectedAgent || !currentScope) return;
    const targetAgent = selectedAgent;
    const lastId = chatLogs[selectedAgent]?.lastId || 0;
    // limit нужен только в запасном режиме, когда истории у нас нет вовсе и её принесёт
    // сам поток (_fetchHistory не смог). В обычной работе сюда приходят с lastId > 0.
    const limitParam = lastId === 0 ? `&limit=${_CHAT_PAGE}` : '';
    _armCallNotifications(lastId);
    const url = `/api/sessions/${selectedAgent}/stream?scope=${encodeURIComponent(currentScope)}&after_id=${lastId}${limitParam}`;
    eventSource = new EventSource(url);
    eventSource.onmessage = (event) => {
        if (selectedAgent !== targetAgent) return;
        try {
            const l = JSON.parse(event.data);
            // Живые куски стрима идут без session_id — их пропускаем, их финал придёт
            // строкой журнала, и вот она уже будет подписана.
            if (l.session_id) {
                if (_chatSessionId && l.session_id !== _chatSessionId) return _onForeignSession(targetAgent, l.session_id);
                if (!_chatSessionId) _chatSessionId = l.session_id;
            }
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
            if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null, initialCount: 0 };
            // Live stream partials carry no id — skip id bookkeeping for them
            if (Number.isFinite(l.id)) {
                if (l.id > chatLogs[selectedAgent].lastId) chatLogs[selectedAgent].lastId = l.id;
                if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                    chatLogs[selectedAgent].firstId = l.id;
                }
                // Count only the initial history burst (scrollAfterLoad is true during it).
                // Load-more shows only if that burst hit the page-size cap (100) → more may exist.
                // Log IDs are global (shared across sessions), so firstId can't tell "start of history".
                if (scrollAfterLoad) {
                    chatLogs[selectedAgent].initialCount++;
                    updateLoadMoreBtn();
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
    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        _onServerError();
        setTimeout(() => { if (selectedAgent === targetAgent) connectSSE(); }, 2000);
    };
}

const _LOAD_MORE_THRESHOLD = 100;  // matches initial history page size (connectSSE limit=100)
function _addLoadMoreBtn() {
    if ($('#load-more-btn')) return;
    const btn = document.createElement('div');
    btn.id = 'load-more-btn';
    btn.className = 'text-xs text-slate-500 hover:text-indigo-300 py-2 text-center cursor-pointer select-none';
    btn.textContent = '▲ Load 500 more';
    btn.addEventListener('click', loadMoreLogs);
    $('#chat').prepend(btn);
}
function updateLoadMoreBtn() {
    // Show only if the initial burst filled the page — otherwise all history is loaded.
    // Can't use firstId: log IDs are global, a fresh session's first id is far above 1.
    const initialCount = chatLogs[selectedAgent]?.initialCount || 0;
    if (initialCount < _LOAD_MORE_THRESHOLD) {
        const existing = $('#load-more-btn');
        if (existing) existing.remove();
        return;
    }
    _addLoadMoreBtn();
}

async function loadMoreLogs() {
    if (!selectedAgent || !currentScope) return;
    const firstId = chatLogs[selectedAgent]?.firstId;
    if (!firstId) return;
    const btn = $('#load-more-btn');
    if (btn) { btn.textContent = '⏳ Loading…'; btn.style.pointerEvents = 'none'; }
    try {
        const res = await fetch(`/api/sessions/${selectedAgent}/logs?scope=${encodeURIComponent(currentScope)}&before_id=${firstId}&limit=500`);
        const logs = await res.json();
        if (!Array.isArray(logs) || logs.length === 0) {
            if (btn) btn.remove();
            return;
        }
        const chat = $('#chat');
        const oldHeight = chat.scrollHeight;
        if (btn) btn.remove();
        const previousTrimLimit = _chatTrimLimit;
        _chatTrimLimit = Math.max(MAX_CHAT_NODES, chat.children.length + logs.length);
        // prepend в правильном порядке (logs уже ASC из db)
        // фиксируем anchor = текущий firstChild, вставляем все перед ним по порядку
        const anchor = chat.firstChild;
        _replayingHistory = true;
        try {
            for (const l of logs) {
                addChatEntry(l.type, l.content, l.ts, anchor, l);
                if (!chatLogs[selectedAgent]) chatLogs[selectedAgent] = { lastId: 0, firstId: null, initialCount: 0 };
                if (chatLogs[selectedAgent].firstId === null || l.id < chatLogs[selectedAgent].firstId) {
                    chatLogs[selectedAgent].firstId = l.id;
                }
            }
        } finally {
            _chatTrimLimit = previousTrimLimit;
            _replayingHistory = false;
        }
        await _storePut(logs);
        chat.scrollTop = chat.scrollHeight - oldHeight;
        // Full page (500) returned → more may exist, re-add button. Fewer → reached the start.
        if (logs.length >= 500) _addLoadMoreBtn();
    } catch (e) {
        if (btn) { btn.textContent = '▲ Load 500 more'; btn.style.pointerEvents = ''; }
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
    const btn = $('#restart-cli-btn');
    btn.disabled = true;
    btn.textContent = '⏳';
    try {
        await api(`/api/sessions/${encodeURIComponent(selectedAgent)}/restart-cli`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scope: currentScope}),
        });
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = '♻️'; btn.disabled = false; }, 1500);
    } catch (e) {
        btn.textContent = '❌';
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
        await api('/api/restart', { method: 'POST' });
    } catch {}
    // Перезагрузки здесь больше нет: она стояла на 3 с, а старт сервиса занимает 4.3-13.9 с
    // (замер по journalctl, docs/tasks/15/research.md) — то есть страница почти всегда
    // перезагружалась в мёртвый сервер и юзер получал 502 от nginx вместо дашборда.
    // Возврат ловит heartbeat и восстанавливает состояние на месте.
}

async function deleteOrchestrator() {
    if (!currentScope || !selectedAgent) return;
    if (!confirm(`Delete "${selectedAgent}" and all its workers?`)) return;
    try {
        await api(`/api/orchestrators/${selectedAgent}?scope=${encodeURIComponent(currentScope)}`, { method: 'DELETE' });
        localStorage.removeItem('lastOrchScope');
        localStorage.removeItem('lastOrchName');
        currentScope = null;
        selectedAgent = null;
        await loadOrchestrators();
    } catch (e) { alert(`Delete failed: ${e.message}`); }
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
        const allOrchs = await api('/api/orchestrators', {pollKey: 'orchestrators'});
        // Данные только что получены. Без этой отметки дроссель в refreshSessions считает
        // их протухшими и через полсекунды тянет тот же список второй раз (#71).
        _orchFreshAt = Date.now();
        _renderOrchestrators(allOrchs);
        snapshotSave('orchestrators', allOrchs);
        _clearStaleNotice('orchestrators');
    } catch (e) {
        // Пустые вкладки без причины — это то, на что юзер и жалуется. Молчать нельзя:
        // без вкладок дашборд не выбирает scope, и не работает ВООБЩЕ ничего.
        console.warn(`orchestrators: ${e.name}: ${e.message}`);
        const snapshot = orchData.length ? null : snapshotLoad('orchestrators');
        if (snapshot) {
            _renderOrchestrators(snapshot.data);
            _showStaleNotice('orchestrators', snapshot.ts);
        } else if (!orchData.length) {
            _showErrorNotice('orchestrators', 'Список оркестраторов не загрузился', e);
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

function _insertPathAtCaret(input, path, url) {
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
    showImagePreview(url, path);
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
let _replayingHistory = false;

function _renderHistory(agent, rows) {
    const meta = chatLogs[agent] = {lastId: 0, firstId: null, initialCount: 0};
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
        meta.initialCount++;
    }
    } finally {
        _replayingHistory = false;
        if (chat) { chat.scrollTop = chat.scrollHeight; chat.style.visibility = ''; }
    }
    updateLoadMoreBtn();
    $('#chat').scrollTop = $('#chat').scrollHeight;
    _scheduleChatInitialSettle();
    _syncChatJumpButton();
}

// Добор страницы до _CHAT_PAGE и запись добранного в зеркало: следующий заход к этому же
// агенту снова бесплатный.
//
// НЕДОСТАЮЩЕЕ БЕРЁТСЯ ОДНИМ ЗАПРОСОМ, а не порциями по 25. Прежнее «сотню строк
// одним ответом не берём: это 27.1 КБ» (#70, #72) не подтвердилось замером 21.08: сервер
// режет каждое сообщение по max_bytes, поэтому 100 строк весят 6 063 байта после gzip
// против 16 598 сырых у 25 — четыре порции не экономят ничего, а стоят четырёх RTT.
// Настоящая цена была видна только на канале юзера: частичное попадание в зеркало
// запускало цепочку из ОДИННАДЦАТИ запросов подряд, и открытие чата занимало 2.40 с при
// латентности 200 мс. Цикл оставлен на два прохода: ответ может оказаться короче
// запрошенного из-за бюджета байт, и тогда второй проход добирает остаток.
// Предзагружать зеркало на все сессии вместо этого нельзя: инкрементальная синхронизация
// (after_id > 0) tail ИГНОРИРУЕТ, дозаполнить уже заведённое зеркало она не может, а
// холодная предзагрузка стоила 145.5 КБ по проводу ради строк, из которых рисуется ~5%.

// Дорисовать старые строки НАД уже показанными. Один владелец на два случая: остаток
// страницы из зеркала (первый кадр рисует только хвост) и добор с сервера.
function _prependHistory(name, scope, rows) {
    if (name !== selectedAgent || scope !== currentScope) return 0;  // успели уйти к другому
    const meta = chatLogs[name];
    if (!meta || !rows.length) return 0;
    const chat = $('#chat');
    const anchor = chat.firstChild;
    const wasAtBottom = _chatAtBottom(chat);
    const heightBefore = chat.scrollHeight;
    const desiredTop = chat.scrollTop;
    _replayingHistory = true;
    try {
        for (const row of rows) {
            addChatEntry(row.type, row.content, row.ts, anchor, row);
            if (!Number.isFinite(row.id)) continue;
            if (meta.firstId === null || row.id < meta.firstId) meta.firstId = row.id;
            meta.initialCount++;
        }
    } finally { _replayingHistory = false; }
    // Дорисовка уходит ВВЕРХ. Юзер внизу — держим его внизу; читает выше — компенсируем
    // прирост высоты, чтобы текст под курсором не уехал (иначе добор из #38 сам себе рывок).
    // Начальная загрузка — всегда низ: там «выше» ещё некому читать.
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
    else chat.scrollTop = desiredTop + (chat.scrollHeight - heightBefore);
    updateLoadMoreBtn();
    return rows.length;
}

// Выполнить после того, как первый кадр УЖЕ нарисован: один rAF срабатывает ДО отрисовки,
// поэтому нужен второй.
function _afterPaint(fn) {
    if (typeof requestAnimationFrame !== 'function') return setTimeout(fn, 0);
    requestAnimationFrame(() => requestAnimationFrame(fn));
}

// Кладём в зеркало то, что уже скачали и показали. Отдельно от _storeSync: тот ходит
// за инкрементом по watermark, а здесь строки СТАРШЕ watermark, и трогать отметку нельзя.
function _compactImageGenerationLogRow(row) {
    if (row?.type !== 'tool_result' || row?.tool_name !== 'ImageGeneration') return row;
    try {
        const data = JSON.parse(row.content || '{}');
        if (!data.saved_path && !data.revised_prompt && !data.status) return row;
        const compact = {
            ...row,
            content: JSON.stringify(_imageGenerationProjection(data)),
            projection: 'image_generation',
            source_bytes: Number(row.source_bytes) || new Blob([row.content || '']).size,
        };
        delete compact.trunc;
        return compact;
    } catch {
        return row;
    }
}

async function _storePut(rows) {
    const db = await _storeOpen();
    if (!db || !rows || !rows.length) return;
    try {
        await _storeTx('readwrite', ['logs'], (tx) => {
            const logs = tx.objectStore('logs');
            for (const row of rows) {
                if (Number.isFinite(row.id)) logs.put(_compactImageGenerationLogRow(row));
            }
        });
    } catch (e) { _storeDisable('не пишется в IndexedDB', e); }
}

// Промах зеркала: тянем историю обычным маршрутом. Он отдаёт application/json, который
// nginx жмёт, — те же 100 сообщений едут в 5 раз меньшим объёмом, чем через SSE (D1).
//
// СТРАНИЦА БЕРЁТСЯ ОДНИМ ЗАПРОСОМ. Раньше здесь стояла порция в 25 строк, а остальные три
// четверти добирались отдельными запросами — открытие чата стоило ЧЕТЫРЁХ круговых
// задержек подряд. Локально это незаметно (6 мс на порцию), а у юзера канал до сервера в
// другой стране, и цена открытия равна 4×RTT. Замер 21.08 на живом журнале: limit=100 —
// 22 мс и 6 063 байта после gzip, limit=25 — 16 598 байт сырых, потому что max_bytes режет
// каждое сообщение и четыре порции почти не экономят трафик. Один запрос строго лучше.
async function _fetchHistory(name, scope) {
    try {
        const q = new URLSearchParams({scope, before_id: String(2 ** 31 - 1), limit: String(_CHAT_PAGE),
                                       max_bytes: String(_CHAT_CHUNK_BYTES), cap: String(_STORE_CAP)});
        const rows = await api(`/api/sessions/${encodeURIComponent(name)}/logs?${q}`);
        if (!Array.isArray(rows)) return [];
        // Обязательно в зеркало: эти строки СТАРШЕ watermark, инкремент их уже не принесёт
        // никогда. Без этой записи в зеркале осталась бы дыра ровно на самом свежем куске
        // истории — а холодная синхронизация его больше не привозит (#72).
        _storePut(rows);
        return rows;
    } catch (e) {
        // Не молчим и не сдаёмся: пустой список → connectSSE пойдёт с after_id=0,
        // и историю принесёт сам поток, как до всей этой затеи.
        console.warn(`[chat] история ${name} не пришла — ${e.name}: ${e.message}; добираю потоком`);
        return [];
    }
}

// Показать чат агента: сперва из зеркала (сети нет вообще), иначе одним запросом.
async function _showChatFor(name, scope) {
    if (!name || !scope) return;
    $('#chat').innerHTML = '';
    chatLogs[name] = {lastId: 0, firstId: null, initialCount: 0};
    scrollAfterLoad = true;
    _chatLoading = true;
    try {
        // Зеркало быстрее сети, но только пока оно свободно: холодная синхронизация
        // (/api/logs/sync?after_id=0 — 2.23 с на замере 21.08) держит readwrite-транзакцию,
        // и наши чтения стоят за ней в очереди. Замер того же дня: переключение на агента
        // без зеркала = 3.08 с пустого чата при том, что /api/sessions/<name>/logs отвечает
        // за 10–20 мс. Поэтому ждём зеркало ограниченно и уходим в сеть, не дожидаясь.
        const mirror = (async () => {
            const id = await _storeSessionId(scope, name);
            return {id, rows: id ? await _storeRead(id, _CHAT_PAGE) : []};
        })();
        const hit = await Promise.race([
            mirror,
            new Promise((res) => setTimeout(() => res(null), _CHAT_MIRROR_DEADLINE)),
        ]);
        const sid = hit ? hit.id : null;
        let rows = hit ? hit.rows : [];
        // Обрезанная строка раньше делала всю историю непригодной: пометить её было нечем,
        // и битую картинку показывать нельзя. Теперь у обрезки есть видимый маркер и кнопка
        // «загрузить целиком» (#74), а сервер режет тем же потолком, что и зеркало, — так что
        // обрезка перестала быть поводом перекачивать страницу целиком.
        // Зеркало наполняется только тем, что мы уже показывали (_storePut), а холодная
        // синхронизация строк не приносит вовсе (tail=0) — у редко открываемого агента там
        // лежит полтора десятка строк. Полупустой экран это не «быстро», а другой дефект,
        // поэтому при скудном зеркале берём страницу сетью: ОДНИМ запросом и ВМЕСТО зеркала,
        // а не в дополнение. Два источника подряд — ровно та достройка на живом экране,
        // ради устранения которой всё и затевалось.
        const fromStore = rows.length >= _CHAT_MIN_FROM_STORE;
        if (!fromStore) rows = await _fetchHistory(name, scope);
        // ДОБОРА ПРИ ОТКРЫТИИ НЕТ. Показываем ровно то, что дал ОДИН источник: зеркало или,
        // при промахе, один запрос за страницей. Прежний добор до ровных ста строк стоил трёх
        // круговых задержек подряд (замер 21.08 при латентности 200 мс), а чат из-за них
        // появлялся почти на секунду позже. Не хватило строк — они в одном клике по
        // «загрузить ещё», и этот клик делает юзер тогда, когда они ему понадобились.
        if (name !== selectedAgent || scope !== currentScope) return;  // успели уйти к другому агенту
        // Чей журнал мы показали. Поток назовёт свою сессию, и несовпадение вычистит чат.
        _chatSessionId = sid || (rows.length ? rows[0].session_id : null);
        // Одна отрисовка на всю страницу, сразу внизу. Прежнее разбиение «сперва хвост из
        // 20 строк, остальное потом» экономило ~300 мс до первого кадра, но платило за это
        // тремя видимыми достройками экрана.
        _renderHistory(name, rows);
        connectSSE(true);
        _afterPaint(async () => {
            if (name === selectedAgent && scope === currentScope) {
                if (_chatAtBottom()) $('#chat').scrollTop = $('#chat').scrollHeight;
            }
        });
        return fromStore;
    } finally {
        // Обязательно снимаем даже на раннем выходе: иначе восстановительный connectSSE
        // окажется заблокирован навсегда и умерший поток никто не поднимет.
        _chatLoading = false;
    }
}

async function onOrchestratorChange() {
    saveDraft();
    _captureChatReadFrontier();
    if (eventSource) { eventSource.close(); eventSource = null; }
    const picker = $('#orch-picker');
    const opt = picker.selectedOptions[0];
    currentScope = picker.value || null;
    const restoreUnreadAnchor = _unreadTabs.delete(currentScope);
    chatLogs = {};
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    _finalizedBubble = null;
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    _streamDeferredFinal = null;
    _lastFinalizedStreamText = '';
    _resetCodexActivityState();
    selectedAgent = opt?.dataset?.name || null;
    if (currentScope && selectedAgent) {
        localStorage.setItem('lastOrchScope', currentScope);
        localStorage.setItem('lastOrchName', selectedAgent);
    }
    $('#chat').innerHTML = '';
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
    if (_jobsTabActive) loadJobs();
}

// === Agent Selection ===
async function selectAgent(name) {
    saveDraft();
    _captureChatReadFrontier();
    if (eventSource) { eventSource.close(); eventSource = null; }
    if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    _finalizedBubble = null;
    selectedAgent = name;
    _hideRateLimitBanner();
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    _streamDeferredFinal = null;
    _lastFinalizedStreamText = '';
    _resetCodexActivityState();
    $('#chat').innerHTML = '';
    _prepareChatAnchorRestore(false);
    updateInputState();
    restoreDraft();
    renderAgentList();
    fetchAgentContext(name);
    await _showChatFor(name, currentScope);
    refreshSessions();  // не в критическом пути: чат уже на экране (D2)
}

function updateInputState() {
    const input = $('#chat-input');
    const btn = $('#send-btn');
    // Отправка всё равно будет отклонена — честнее недоступная кнопка, чем ошибка в ответ.
    if (_restartPending) {
        input.placeholder = 'Идёт перезапуск Orchestra…';
        input.disabled = true;
        btn.disabled = true;
        return;
    }
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
                    const resp = await api(`/api/sessions/${agentName}/change-model`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ model: m.id, scope: currentScope, fresh: true }) });
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
    st.textContent = `● ${session.status}`;
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
    }
    fetchAgentContext(session.name);
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

async function _fetchAgentContextNow(name) {
    if (!currentScope) return;
    try {
        const ctx = await api(`/api/sessions/${name}/context?scope=${encodeURIComponent(currentScope)}`, {pollKey: 'context'});
        const text = formatContext(ctx);
        contextCache[`${currentScope}:${name}`] = text;
        if (name === selectedAgent) setContextDisplay(text);
    } catch (e) {
        console.warn(`context ${name}: ${e.name}: ${e.message}`);
        // Прошлое значение показать честнее, чем прочерк: контекст растёт медленно, и
        // цифра минутной давности осмысленна, а «-» неотличим от «агент только что создан».
        const known = contextCache[`${currentScope}:${name}`];
        if (known && name === selectedAgent) setContextDisplay(`${known} (не обновлено)`);
    }
}

function fetchAgentContext(name) {
    return _pollCoalesce(`context-request:${name}`, () => _fetchAgentContextNow(name));
}

// === Agent List ===
function renderAgentList(sessions) {
    if (!sessions) return;
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
    _pollRegister('orchestrators', loadOrchestrators, 60000);
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
    statusEl.className = 'text-xs font-mono font-bold shrink-0';
    statusEl.style.color = _STATUS_COLOR[s.status] || '#6b7280';
    statusEl.style.backgroundColor = _STATUS_BG[s.status] || 'rgba(107,114,128,0.1)';
    statusEl.style.padding = '1px 6px';
    statusEl.style.borderRadius = '4px';
    statusEl.textContent = `${_STATUS_ICON[s.status] || '●'} ${s.status}`;
    if (_STATUS_TITLE[s.status]) statusEl.title = _STATUS_TITLE[s.status];
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

// === Chat ===
// Optimistic UI: show message immediately, debounce actual send so rapid
// follow-up messages get batched. The server echoes back via SSE which
// replaces the bubble with the canonical version.
async function sendChat() {
    if (_restartPending) return;   // кнопка уже недоступна, это страховка от Enter
    const input = $('#chat-input');
    // Картинка ещё летит → ждём её путь, иначе сообщение уйдёт без картинки.
    // Поле ввода при этом живое: всё, что допечатают за время ожидания, войдёт в msg.
    if (_pendingUploads.size) {
        const btn = $('#send-btn');
        const label = btn.textContent;
        btn.textContent = '⏳';
        await Promise.allSettled([..._pendingUploads]);
        btn.textContent = label;
    }
    const msg = input.value.trim();
    if (!msg || !currentScope || !selectedAgent) return;
    input.value = '';
    clearPastePreview();

    pendingUserMsgs.push(msg);
    localMessages.add(msg);
    showPendingBubble();

    if (uiDebounceTimer) clearTimeout(uiDebounceTimer);
    uiDebounceTimer = setTimeout(() => finalizePending(), UI_DEBOUNCE_MS);

    try {
        await api(`/api/sessions/${selectedAgent}/send`, {
            method: 'POST',
            body: JSON.stringify({ message: msg, scope: currentScope }),
            signal: AbortSignal.timeout(15000),
        });
    } catch (e) {
        if (e.name === 'TimeoutError') return;
        if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
        if (pendingBubble) { const ring = pendingBubble.querySelector('.debounce-ring'); if (ring) ring.remove(); }
        pendingBubble = null; pendingUserMsgs = []; _finalizedBubble = null;
        removeWaitingIndicator();
        // Перезапуск — штатная операция, и красная строка про неё выглядела бы аварией.
        addChatEntry(e.name === 'RestartPendingError' ? 'notification' : 'error', e.message);
    }
}

function showPendingBubble() {
    const chat = $('#chat');
    if (!pendingBubble) {
        pendingBubble = document.createElement('div');
        pendingBubble.className = 'chat-user ml-16 px-3 py-2 rounded-lg text-sm break-words';
        chat.appendChild(pendingBubble);
    }
    pendingBubble.textContent = pendingUserMsgs.join('\n');
    const oldRing = pendingBubble.querySelector('.debounce-ring');
    if (oldRing) oldRing.remove();
    const ring = document.createElement('span');
    ring.className = 'debounce-ring';
    pendingBubble.appendChild(ring);
    chat.scrollTop = chat.scrollHeight;
}

let _finalizedBubble = null;
function finalizePending() {
    if (!pendingBubble) return;
    const ring = pendingBubble.querySelector('.debounce-ring');
    if (ring) ring.remove();
    const combined = pendingUserMsgs.join('\n');
    localMessages.add(combined);
    _finalizedBubble = pendingBubble;
    pendingBubble = null;
    pendingUserMsgs = [];
    uiDebounceTimer = null;
    showWaitingIndicator();
}

const _VOICE_MAX_MS = 5 * 60 * 1000;
let _voiceRecorder = null;
let _voiceStream = null;
let _voiceAudioContext = null;
let _voiceAnalyser = null;
let _voiceFrame = 0;
let _voiceLastFrame = 0;
let _voiceSamples = null;
let _voiceStartedAt = 0;
let _voiceCancelled = false;
let _voiceStarting = false;
let _voiceStopping = false;

function _voiceMimeType() {
    const choices = [
        'audio/webm;codecs=opus',
        'audio/mp4;codecs=mp4a.40.2',
        'audio/mp4',
        'audio/webm',
        'audio/ogg;codecs=opus',
    ];
    return choices.find(type => MediaRecorder.isTypeSupported(type)) || '';
}

function _voiceSetState(state) {
    const controls = $('#voice-controls');
    if (!controls) return;
    controls.dataset.state = state;
    $('#voice-btn').disabled = state === 'processing' || state === 'requesting' || state === 'stopping';
    $('#voice-state-label').textContent = state === 'processing'
        ? 'Распознаю…'
        : (state === 'requesting' ? 'Микрофон…' : (state === 'stopping' ? 'Завершаю…' : 'Запись'));
    $('#voice-cancel-btn').disabled = state !== 'recording';
}

function _showVoiceError(message) {
    const error = $('#voice-error');
    if (!error) return;
    error.textContent = message;
    error.classList.toggle('is-visible', Boolean(message));
}

function _voiceCaptureError(error) {
    if (!window.isSecureContext) return 'Микрофон доступен только через HTTPS.';
    if (error?.name === 'NotAllowedError') return 'Доступ к микрофону запрещён. Разрешите его в настройках браузера.';
    if (error?.name === 'NotFoundError') return 'Микрофон не найден.';
    if (error?.name === 'NotReadableError') return 'Микрофон занят другим приложением.';
    return `Не удалось включить микрофон: ${error?.name || 'Error'}: ${error?.message || error}`;
}

function _stopVoiceCapture() {
    cancelAnimationFrame(_voiceFrame);
    _voiceFrame = 0;
    _voiceAnalyser = null;
    _voiceSamples = null;
    if (_voiceAudioContext) _voiceAudioContext.close().catch(() => {});
    _voiceAudioContext = null;
    if (_voiceStream) _voiceStream.getTracks().forEach(track => track.stop());
    _voiceStream = null;
    $('#voice-level')?.style.setProperty('--voice-level', '1');
}

function _drawVoiceLevel(now) {
    if (!_voiceAnalyser || !_voiceRecorder || _voiceRecorder.state !== 'recording') return;
    if (now - _voiceLastFrame < 33) {
        _voiceFrame = requestAnimationFrame(_drawVoiceLevel);
        return;
    }
    _voiceLastFrame = now;
    _voiceAnalyser.getByteTimeDomainData(_voiceSamples);
    let energy = 0;
    for (const sample of _voiceSamples) {
        const centered = (sample - 128) / 128;
        energy += centered * centered;
    }
    const level = Math.min(1, Math.sqrt(energy / _voiceSamples.length) * 4);
    $('#voice-level')?.style.setProperty('--voice-level', (1 + level * 1.25).toFixed(2));
    const elapsed = now - _voiceStartedAt;
    const seconds = Math.floor(elapsed / 1000);
    $('#voice-timer').textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (elapsed >= _VOICE_MAX_MS) {
        stopVoiceInput();
        return;
    }
    _voiceFrame = requestAnimationFrame(_drawVoiceLevel);
}

function _voiceExtension(mimeType) {
    if (mimeType.startsWith('audio/mp4')) return 'm4a';
    if (mimeType.startsWith('audio/ogg')) return 'ogg';
    return 'webm';
}

async function _transcribeVoiceBlob(blob, mimeType) {
    _voiceSetState('processing');
    const body = new FormData();
    body.append('audio', blob, `voice.${_voiceExtension(mimeType)}`);
    body.append('session_name', selectedAgent || '');
    body.append('scope', currentScope || '');
    try {
        const response = await fetch('/api/transcribe', {
            method: 'POST',
            body,
            signal: AbortSignal.timeout(150000),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || result.detail || `HTTP ${response.status}`);
        const text = (result.text || '').trim();
        if (!text) throw new Error('Сервис не распознал речь.');
        const input = $('#chat-input');
        const separator = input.value && !/\s$/.test(input.value) ? ' ' : '';
        input.value += separator + text;
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        saveDraft();
        _showVoiceError('');
    } catch (error) {
        const detail = error.name === 'TimeoutError'
            ? 'Распознавание не ответило за 150 секунд.'
            : error.message;
        _showVoiceError(`Голосовой ввод: ${detail}`);
    } finally {
        _voiceSetState('idle');
    }
}

async function startVoiceInput() {
    if (_voiceRecorder?.state === 'recording') {
        stopVoiceInput();
        return;
    }
    if (_voiceStarting || _voiceStopping) return;
    _showVoiceError('');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        _showVoiceError(window.isSecureContext
            ? 'Этот браузер не поддерживает запись с микрофона.'
            : 'Микрофон доступен только через HTTPS.');
        return;
    }
    _voiceStarting = true;
    _voiceSetState('requesting');
    try {
        _voiceStream = await navigator.mediaDevices.getUserMedia({audio: true});
        const mimeType = _voiceMimeType();
        const recorder = mimeType
            ? new MediaRecorder(_voiceStream, {mimeType, audioBitsPerSecond: 64000})
            : new MediaRecorder(_voiceStream);
        const chunks = [];
        _voiceRecorder = recorder;
        _voiceCancelled = false;
        recorder.addEventListener('dataavailable', event => {
            if (event.data.size) chunks.push(event.data);
        });
        recorder.addEventListener('error', event => {
            _showVoiceError(_voiceCaptureError(event.error));
            _voiceCancelled = true;
            _voiceStopping = true;
            if (recorder.state === 'recording') recorder.stop();
        });
        recorder.addEventListener('stop', () => {
            const cancelled = _voiceCancelled;
            const actualType = recorder.mimeType || mimeType || chunks[0]?.type || 'audio/webm';
            const blob = new Blob(chunks, {type: actualType});
            if (_voiceRecorder === recorder) _voiceRecorder = null;
            _voiceStopping = false;
            _stopVoiceCapture();
            if (cancelled) {
                _voiceSetState('idle');
                return;
            }
            if (!blob.size) {
                _showVoiceError('Голосовой ввод: браузер вернул пустую запись.');
                _voiceSetState('idle');
                return;
            }
            _transcribeVoiceBlob(blob, actualType);
        }, {once: true});

        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        _voiceAudioContext = new AudioContextClass();
        const source = _voiceAudioContext.createMediaStreamSource(_voiceStream);
        _voiceAnalyser = _voiceAudioContext.createAnalyser();
        _voiceAnalyser.fftSize = 256;
        _voiceSamples = new Uint8Array(_voiceAnalyser.fftSize);
        source.connect(_voiceAnalyser);
        _voiceStartedAt = performance.now();
        _voiceLastFrame = 0;
        $('#voice-timer').textContent = '0:00';
        _voiceStarting = false;
        _voiceSetState('recording');
        recorder.start();
        _voiceFrame = requestAnimationFrame(_drawVoiceLevel);
    } catch (error) {
        _voiceStarting = false;
        _stopVoiceCapture();
        _voiceRecorder = null;
        _voiceSetState('idle');
        _showVoiceError(_voiceCaptureError(error));
    }
}

function stopVoiceInput(cancel = false) {
    if (!_voiceRecorder || _voiceRecorder.state !== 'recording') return;
    _voiceCancelled = cancel;
    _voiceStopping = true;
    _voiceSetState('stopping');
    _voiceRecorder.stop();
}

function initVoiceInput() {
    const input = $('#chat-input');
    const actions = $('#send-btn')?.parentElement;
    if (!input || !actions || $('#voice-controls')) return;
    const controls = document.createElement('div');
    controls.id = 'voice-controls';
    controls.className = 'voice-controls';
    controls.dataset.state = 'idle';
    controls.innerHTML = `
        <button id="voice-btn" type="button" class="voice-button" title="Голосовой ввод" aria-label="Начать или остановить голосовой ввод">
            <span id="voice-level" class="voice-level"></span><span class="voice-icon">🎤</span>
        </button>
        <div class="voice-recording" aria-live="polite">
            <span id="voice-timer" class="voice-timer">0:00</span>
            <span id="voice-state-label">Запись</span>
            <button id="voice-cancel-btn" type="button" class="voice-cancel" title="Отменить запись" aria-label="Отменить запись">×</button>
        </div>`;
    input.parentElement.insertBefore(controls, actions);
    const error = document.createElement('div');
    error.id = 'voice-error';
    error.className = 'voice-error';
    error.setAttribute('role', 'alert');
    input.parentElement.after(error);
    $('#voice-btn').addEventListener('click', startVoiceInput);
    $('#voice-cancel-btn').addEventListener('click', () => stopVoiceInput(true));
    window.addEventListener('pagehide', () => stopVoiceInput(true));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && _voiceRecorder?.state === 'recording') stopVoiceInput(true);
    });
}

function showWaitingIndicator() {
    removeWaitingIndicator();
    const chat = $('#chat');
    const wasAtBottom = _chatAtBottom(chat);
    const div = document.createElement('div');
    div.id = 'waiting-indicator';
    div.className = 'flex items-center gap-2 text-xs text-slate-500 py-2 px-3';
    div.innerHTML = '<span class="waiting-dots"><span>.</span><span>.</span><span>.</span></span> waiting for response';
    chat.appendChild(div);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

let pastedImages = [];
// Работа с файлом, которую sendChat обязан дождаться — вся, от сжатия до ответа
// сервера. Иначе сообщение уйдёт без картинки, а её путь допишется в уже пустое
// поле осиротевшей строкой. Регистрируем на верхнем уровне, по разу на файл.
const _pendingUploads = new Set();
function _trackUpload(promise) {
    _pendingUploads.add(promise);
    promise.finally(() => _pendingUploads.delete(promise));
    return promise;
}

// Одна дорога для paste и drop: ошибку показываем строкой над полем ввода,
// путь ДОПИСЫВАЕМ в textarea и только после ответа сервера. Трогать input.value
// во время загрузки нельзя — юзер в это время печатает, и его текст пропадёт.
async function _uploadToChat(file, filename) {
    const promise = (async () => {
        const formData = new FormData();
        formData.append('file', file, filename);
        // Без таймаута зависший аплоад навсегда запер бы отправку в sendChat
        const resp = await fetch('/api/upload', { method: 'POST', body: formData,
                                                  signal: AbortSignal.timeout(60000) });
        const data = resp.headers.get('content-type')?.includes('application/json')
            ? await resp.json() : {};
        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
        if (!data.path) throw new Error('server returned no file path');
        return data;
    })();
    try {
        const data = await promise;
        _insertPathAtCaret($('#chat-input'), data.path, data.url || data.path);
        return data;
    } catch (error) {
        // У TimeoutError и сетевых ошибок message бывает пустой — печатаем и класс.
        // Дописываем к уже показанной ошибке: при дропе пачки файлов упасть может не один
        const detail = `${filename}: ${error.name}: ${error.message}`;
        const shown = $('#chat-drop-error')?.textContent;
        _showChatDropError(shown ? `${shown}; ${detail}` : `Upload failed — ${detail}`);
        return null;
    }
}

// Аплоад с машины юзера идёт на 53-82 КБ/с (замер оттуда же): типичный retina-скриншот
// 667 КБ ползёт 12 с, и это упирается в канал, а не в сервер — единственный способ
// ускорить — отправить меньше байтов. WebP q=0.9 даёт 354 КБ (1.9×) при PSNR 38.6 дБ:
// на кропе 1:1 текст неотличим от оригинала. Цифры — docs/tasks/5/report.md.
// Только для вставки из буфера: дропнутый файл юзер выбрал сам, его формат не наш.
const _COMPRESS_MIN_BYTES = 100 * 1024;  // мельче — экономия секунды не стоит работы CPU

async function _compressScreenshot(file) {
    if (file.size < _COMPRESS_MIN_BYTES) return {blob: file, ext: 'png'};
    try {
        const bitmap = await createImageBitmap(file);
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        canvas.getContext('2d').drawImage(bitmap, 0, 0);
        bitmap.close();
        const blob = await canvas.convertToBlob({type: 'image/webp', quality: 0.9});
        // Фото и мелкие картинки от WebP не выигрывают — тогда шлём как есть
        if (blob.size < file.size) return {blob, ext: 'webp'};
    } catch (error) {
        // Не ошибка юзера: файл всё равно уйдёт оригиналом, поэтому в консоль, не в UI
        console.warn('Screenshot compression skipped:', error.name, error.message);
    }
    return {blob: file, ext: 'png'};
}

async function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
        if (!item.type.startsWith('image/')) continue;
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;
        _showChatDropError('');
        const removeChip = _showUploadingChip(file);
        await _trackUpload((async () => {
            const {blob, ext} = await _compressScreenshot(file);
            await _uploadToChat(blob, `paste-${Date.now()}.${ext}`);
        })());
        removeChip();
        break;
    }
}

// Пока файл летит, показываем его же из памяти браузера — сеть для этого не нужна.
// Возвращает функцию снятия: сам узел + освобождение objectURL, чтобы не текла память.
function _showUploadingChip(file) {
    const objectUrl = URL.createObjectURL(file);
    const container = _pastePreviewContainer();
    const wrap = document.createElement('div');
    wrap.className = 'relative';
    wrap.innerHTML = '<div class="absolute inset-0 flex items-center justify-center text-xs">⏳</div>';
    const img = document.createElement('img');
    img.src = objectUrl;
    img.className = 'h-16 rounded border border-slate-700 opacity-40';
    wrap.prepend(img);
    container.appendChild(wrap);
    return () => {
        wrap.remove();
        URL.revokeObjectURL(objectUrl);
        if (!container.children.length) container.remove();
    };
}

function _pastePreviewContainer() {
    let container = $('#paste-preview');
    if (!container) {
        container = document.createElement('div');
        container.id = 'paste-preview';
        container.className = 'flex flex-wrap gap-2 px-1 pb-1';
        const inputRow = $('#chat-input').parentElement;
        inputRow.parentElement.insertBefore(container, inputRow);
    }
    return container;
}

function showImagePreview(url, filePath) {
    const container = _pastePreviewContainer();
    const wrap = document.createElement('div');
    wrap.className = 'relative';
    wrap.dataset.url = url;
    wrap.dataset.filePath = filePath || url;
    const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(filePath || url);
    if (isImage) {
        const img = document.createElement('img');
        img.src = url;
        img.className = 'h-16 rounded border border-slate-700';
        img.loading = 'lazy';
        img.style.cursor = 'pointer';
        img.addEventListener('click', () => openFilePreview(filePath || url));
        wrap.appendChild(img);
    } else {
        const name = (filePath || url).split('/').pop();
        const chip = document.createElement('div');
        chip.className = 'flex items-center gap-1 px-2 py-1 rounded border border-slate-700 text-xs text-slate-400 cursor-pointer hover:border-indigo-500';
        chip.style.maxWidth = '180px';
        chip.innerHTML = `<span>📄</span><span class="truncate">${DOMPurify.sanitize(name)}</span>`;
        chip.addEventListener('click', () => openFilePreview(filePath || url));
        wrap.appendChild(chip);
    }
    const rm = document.createElement('button');
    rm.className = 'absolute -top-1 -right-1 bg-red-600 text-white rounded-full w-4 h-4 text-xs leading-none';
    rm.textContent = '×';
    rm.addEventListener('click', () => {
        wrap.remove();
        pastedImages = pastedImages.filter(u => u !== url);
        const input = $('#chat-input');
        const removePath = filePath || url;
        input.value = input.value.split('\n').filter(line => line.trim() !== removePath.trim()).join('\n').trim();
        if (!container.children.length) container.remove();
    });
    wrap.appendChild(rm);
    container.appendChild(wrap);
}

function clearPastePreview() {
    pastedImages = [];
    const el = $('#paste-preview');
    if (el) el.remove();
}


function renderImages(el, content) {
    const re = /(\/\S+\.(png|jpg|jpeg|gif|webp|svg))/gi;
    const matches = content.match(re);
    if (!matches) return;

    const imageUrl = (path) => `/api/files/raw?path=${encodeURIComponent(path)}`;
    const makeImage = (path, className = '', openOnClick = true) => {
        const img = document.createElement('img');
        img.src = imageUrl(path);
        img.loading = 'lazy';
        img.className = className;
        if (openOnClick) {
            img.addEventListener('click', () => openImageLightbox(imageUrl(path)));
        }
        return img;
    };

    if (matches.length === 1) {
        const img = makeImage(matches[0], 'chat-inline-image');
        img.onerror = () => img.remove();
        el.appendChild(img);
        return;
    }

    const previewCount = 4;
    const gallery = document.createElement('section');
    gallery.className = 'chat-image-gallery';
    gallery.dataset.imageCount = String(matches.length);
    gallery.setAttribute('aria-label', `Галерея: ${matches.length} фото`);

    const header = document.createElement('div');
    header.className = 'chat-image-gallery-header';
    const count = document.createElement('span');
    count.className = 'chat-image-gallery-count';
    count.textContent = `📷 ${matches.length} фото`;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'chat-image-gallery-toggle';
    toggle.hidden = matches.length <= previewCount;
    header.append(count, toggle);

    const grid = document.createElement('div');
    grid.className = 'chat-image-gallery-grid';

    const renderGallery = (expanded) => {
        gallery.classList.toggle('is-expanded', expanded);
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.textContent = expanded ? 'Свернуть' : `Показать все ${matches.length}`;
        grid.replaceChildren();
        const shown = expanded ? matches : matches.slice(0, previewCount);
        shown.forEach((path, index) => {
            const thumb = document.createElement('button');
            thumb.type = 'button';
            thumb.className = 'chat-image-gallery-thumb';
            thumb.setAttribute('aria-label', `Открыть фото ${index + 1} из ${matches.length}`);
            const img = makeImage(path, '', false);
            img.alt = `Фото ${index + 1} из ${matches.length}`;
            img.onerror = () => thumb.remove();
            thumb.appendChild(img);

            const hiddenCount = matches.length - previewCount;
            const expandsGallery = !expanded && index === previewCount - 1 && hiddenCount > 0;
            if (expandsGallery) {
                const more = document.createElement('span');
                more.className = 'chat-image-gallery-more';
                more.textContent = `+${hiddenCount}`;
                thumb.appendChild(more);
                thumb.setAttribute('aria-label', `Показать остальные ${hiddenCount} фото`);
            }
            thumb.addEventListener('click', () => {
                if (expandsGallery) renderGallery(true);
                else openImageLightbox(imageUrl(path));
            });
            grid.appendChild(thumb);
        });
    };

    toggle.addEventListener('click', () => {
        renderGallery(!gallery.classList.contains('is-expanded'));
    });
    gallery.append(header, grid);
    renderGallery(false);
    el.appendChild(gallery);
}

function removeWaitingIndicator() {
    const el = $('#waiting-indicator');
    if (el) el.remove();
}

async function stopAgent() {
    if (!selectedAgent || !currentScope) return;
    try {
        await api(`/api/sessions/${selectedAgent}/interrupt`, {
            method: 'POST',
            body: JSON.stringify({ scope: currentScope }),
        });
    } catch {}
}

function updateStopButton(status) {
    const btn = $('#stop-btn');
    if (status === 'running') {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

function _showImageOverlay(src) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.9);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:pointer';
    const bigImg = document.createElement('img');
    bigImg.src = src;
    bigImg.style.cssText = 'max-width:90vw;max-height:90vh;object-fit:contain';
    overlay.appendChild(bigImg);
    overlay.addEventListener('click', () => overlay.remove());
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', esc); } });
    document.body.appendChild(overlay);
}

function addTimestamp(el, ts) {
    if (!el || !ts || el.querySelector('.chat-time')) return;
    const d = new Date(ts);
    const local = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const time = document.createElement('span');
    time.className = 'chat-time';
    time.textContent = local;
    el.appendChild(time);
}

function addCopyBtn(el, text) {
    if (!el || el.querySelector('.copy-btn')) return;
    el.style.position = 'relative';
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = '📋';
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        // navigator.clipboard requires HTTPS — fallback for HTTP
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text);
        } else {
            const ta = document.createElement('textarea');
            ta.value = text; ta.style.cssText = 'position:fixed;left:-9999px';
            document.body.appendChild(ta); ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        btn.textContent = '✅';
        setTimeout(() => btn.textContent = '📋', 1500);
    });
    el.appendChild(btn);
}

let streamBubble = null;
let streamContent = '';
let streamPending = '';
let _streamRafId = null;
let _streamLastParse = 0;
let _streamDeferredFinal = null;
// Last text that closed a live stream bubble. Grok (and any async log writer) can deliver
// `turn ended` status before the matching `text` row; if we already finalized the stream,
// a second identical `text` must not paint a second bubble.
let _lastFinalizedStreamText = '';
const _STREAM_BASE_CPS = 12;  // chars per frame at 60fps (~720 chars/sec)
const _STREAM_PARSE_INTERVAL = 50;  // ms between marked.parse calls

const _UNEXECUTED_TOOL_CALL_WARNING = 'НЕ ВЫПОЛНЕНО — похоже на вызов инструмента, напечатанный текстом';

// Cross-runtime duplicate of app/tool_call_guard.py: browser JS cannot import the Python helper.
function _looksLikeUnexecutedToolCall(text) {
    const prose = String(text || '')
        .replace(/(```|~~~)[\s\S]*?(?:\1|$)/g, '')
        .replace(/`[^`\n]*`/g, '');
    const signals = [
        /<invoke\s+name\s*=/i,
        /<\/invoke\s*>/i,
        /<parameter\s+name\s*=/i,
        /<\/parameter\s*>/i,
        /<function_calls(?:\s[^>]*)?>/i,
    ];
    return signals.filter(pattern => pattern.test(prose)).length >= 2;
}

function _unexecutedToolCallWarningHtml(content) {
    if (!_looksLikeUnexecutedToolCall(content)) return '';
    return `<div class="codex-warning unexecuted-tool-call-warning"><span class="codex-warning-icon">⚠</span><span>${_UNEXECUTED_TOOL_CALL_WARNING}</span></div>`;
}

function _markUnexecutedToolCall(container, content) {
    const oldWarning = container.querySelector(':scope > .unexecuted-tool-call-warning');
    if (!_looksLikeUnexecutedToolCall(content)) {
        if (oldWarning) oldWarning.remove();
        return;
    }
    if (oldWarning) return;
    const warning = document.createElement('div');
    warning.className = 'codex-warning unexecuted-tool-call-warning';
    warning.innerHTML = '<span class="codex-warning-icon">⚠</span><span></span>';
    warning.lastChild.textContent = _UNEXECUTED_TOOL_CALL_WARNING;
    container.prepend(warning);
}

function _selectionTouchesStream() {
    if (!streamBubble?.isConnected) return false;
    const selection = window.getSelection();
    return !!selection && !selection.isCollapsed && selection.rangeCount > 0
        && selection.getRangeAt(0).intersectsNode(streamBubble);
}

function _finalizeStreamBubble(finalText, ts) {
    streamBubble.classList.remove('streaming');
    streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(finalText));
    _markUnexecutedToolCall(streamBubble, finalText);
    addCopyBtn(streamBubble, finalText);
    addTimestamp(streamBubble, ts);
    _lastFinalizedStreamText = finalText || '';
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    _streamDeferredFinal = null;
}

function _completeStreamBubble(content, ts) {
    _streamFlush();
    const finalText = content || streamContent;
    if (_selectionTouchesStream()) {
        _streamDeferredFinal = { finalText, ts };
        return;
    }
    _finalizeStreamBubble(finalText, ts);
}

function _resumeStreamAfterSelection() {
    if (_selectionTouchesStream()) return;
    if (_streamDeferredFinal) {
        const deferred = _streamDeferredFinal;
        _streamDeferredFinal = null;
        _finalizeStreamBubble(deferred.finalText, deferred.ts);
    } else if (streamPending && !_streamRafId) {
        _streamRafId = requestAnimationFrame(_streamRenderTick);
    }
}

document.addEventListener('selectionchange', _resumeStreamAfterSelection);

function _streamRenderTick() {
    _streamRafId = null;
    if (!streamBubble || !streamPending) return;
    if (_selectionTouchesStream()) return;
    const chat = $('#chat');
    const wasAtBottom = _chatAtBottom(chat);
    // Adaptive speed: if buffer is growing, accelerate to not fall behind
    const chunkSize = Math.max(_STREAM_BASE_CPS, Math.floor(streamPending.length / 8));
    const chunk = streamPending.slice(0, chunkSize);
    streamPending = streamPending.slice(chunkSize);
    streamContent += chunk;
    const now = performance.now();
    const sinceLastParse = now - _streamLastParse;
    if (sinceLastParse >= _STREAM_PARSE_INTERVAL || !streamPending) {
        _streamLastParse = now;
        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
    }
    _markUnexecutedToolCall(streamBubble, streamContent);
    // Typing cursor — remove stale one before adding
    const oldCur = streamBubble.querySelector('.typing-cursor');
    if (oldCur) oldCur.remove();
    const lastEl = streamBubble.querySelector(':scope > :last-child') || streamBubble;
    const cur = document.createElement('span');
    cur.className = 'typing-cursor';
    cur.textContent = '▍';
    lastEl.appendChild(cur);
    if (wasAtBottom) chat.scrollTo({ top: chat.scrollHeight, behavior: 'smooth' });
    else _markChatHasNewBelow();
    if (streamPending) _streamRafId = requestAnimationFrame(_streamRenderTick);
}

function _streamFlush() {
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    if (streamPending) {
        streamContent += streamPending;
        streamPending = '';
    }
}

function _renderJsonGrid(obj, container, maxDepth) {
    if (maxDepth === undefined) maxDepth = 2;
    const grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px;align-items:baseline';
    const entries = Object.entries(obj);
    for (const [key, val] of entries) {
        if (key === 'system_prompt' || key === 'error_trace' || key === '_codex_item_id') continue;
        const keyEl = document.createElement('span');
        keyEl.style.cssText = 'color:#64748b;white-space:nowrap;font-family:monospace';
        keyEl.textContent = key;
        grid.appendChild(keyEl);
        const valEl = document.createElement('span');
        valEl.style.cssText = 'overflow:hidden;text-overflow:ellipsis;overflow-wrap:anywhere;min-width:0';
        if (val === null || val === undefined) {
            valEl.textContent = 'null';
            valEl.style.color = '#6b7280';
        } else if (typeof val === 'boolean') {
            valEl.textContent = String(val);
            valEl.style.color = val ? '#22c55e' : '#ef4444';
        } else if (typeof val === 'number') {
            valEl.textContent = String(val);
            valEl.style.color = '#eab308';
        } else if (typeof val === 'string') {
            const MAX_STR = 150;
            const short = val.length > MAX_STR ? val.slice(0, MAX_STR) + '…' : val;
            valEl.textContent = short;
            valEl.style.color = '#cbd5e1';
            if (val.length > MAX_STR) {
                valEl.style.cursor = 'pointer';
                valEl.title = 'Click to expand';
                let _strExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _strExp = !_strExp;
                    valEl.textContent = _strExp ? val : short;
                });
            }
        } else if (Array.isArray(val)) {
            if (val.length === 0) {
                valEl.textContent = '[]';
                valEl.style.color = '#6b7280';
            } else if (val.every(v => typeof v === 'string' || typeof v === 'number')) {
                const arrStr = val.join(', ');
                valEl.textContent = arrStr.length > 120 ? arrStr.slice(0, 120) + '…' : arrStr;
                valEl.style.color = '#cbd5e1';
            } else {
                valEl.textContent = `[${val.length} items]`;
                valEl.style.color = '#38bdf8';
                valEl.style.cursor = 'pointer';
                let _arrExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _arrExp = !_arrExp;
                    if (_arrExp) {
                        valEl.textContent = '';
                        const pre = document.createElement('pre');
                        pre.style.cssText = 'font-size:10px;color:#94a3b8;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;overflow-y:auto';
                        pre.textContent = JSON.stringify(val, null, 2);
                        valEl.appendChild(pre);
                    } else {
                        valEl.textContent = `[${val.length} items]`;
                    }
                });
            }
        } else if (typeof val === 'object' && maxDepth > 0) {
            const subKeys = Object.keys(val);
            if (subKeys.length <= 4) {
                const sub = document.createElement('div');
                _renderJsonGrid(val, sub, maxDepth - 1);
                valEl.textContent = '';
                valEl.appendChild(sub);
            } else {
                valEl.textContent = `{${subKeys.length} keys}`;
                valEl.style.color = '#38bdf8';
                valEl.style.cursor = 'pointer';
                let _objExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _objExp = !_objExp;
                    if (_objExp) {
                        valEl.textContent = '';
                        const pre = document.createElement('pre');
                        pre.style.cssText = 'font-size:10px;color:#94a3b8;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;overflow-y:auto';
                        pre.textContent = JSON.stringify(val, null, 2);
                        valEl.appendChild(pre);
                    } else {
                        valEl.textContent = `{${subKeys.length} keys}`;
                    }
                });
            }
        } else {
            valEl.textContent = JSON.stringify(val);
            valEl.style.color = '#94a3b8';
        }
        grid.appendChild(valEl);
    }
    container.appendChild(grid);
    return grid;
}

function buildCompactToolLine(type, content, ts, payload) {
    const line = document.createElement('div');
    line.className = 'flex items-center gap-2 text-xs py-0.5 px-2 cursor-pointer rounded group';
    line.style.color = '#64748b';

    if (type === 'tool') {
        const colonIdx = content.indexOf(':');
        const rawName = canonicalToolName(colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30));
        const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
        const icon = toolIcon(rawName);
        const short = toolShortName(rawName);

        let preview = body;
        const _safeTaskFilter = (value) => typeof value === 'string' && value.length <= 32 && !/[<>\"'`]/.test(value);
        const _taskListFilter = (parsedObj) => {
            const parts = [parsedObj.status, parsedObj.project, parsedObj.assignee]
                .map((value) => (typeof value === 'string' ? value.trim() : ''))
                .filter((value) => value && _safeTaskFilter(value));
            return parts.length > 0 ? parts.join(', ') : '';
        };
        try {
            const parsed = JSON.parse(body);
            if (rawName === NOTIFY_USER_TOOL) preview = `🔔 ${parsed.reason || 'зовёт'}`;
            else if (rawName === 'mcp__orchestra__spawn_worker') preview = `🚀 ${parsed.name || '?'} (${_modelLabel(parsed.model || 'claude-sonnet-4-6')})`;
            else if (rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch') preview = codexWebSearchCompactLabel(codexWebSearchSpec(parsed));
            else if (rawName === 'ToolSearch') preview = `🔍 ${parsed.query || ''}`;
            else if (rawName === 'mcp__orchestra__report_bug') preview = `🐛 ${parsed.title || '?'}`;
            else if (rawName === 'mcp__orchestra__send_file') preview = `📎 ${(parsed.path || '').split('/').pop() || '?'}`;
            else if (rawName === 'mcp__orchestra__kill_worker') preview = `💀 Kill: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__stop_worker') preview = `⏸️ Stop: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__get_worker_logs') preview = `📋 Logs: ${parsed.name || '?'} (${parsed.limit || 20})`;
            else if (rawName === 'mcp__orchestra__get_worker_info') preview = `🤖 Info: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__list_agents') preview = '🎼 Agents';
            else if (rawName === 'mcp__orchestra__list_orchestrators') preview = '🎯 Orchestrators';
            else if (rawName === 'mcp__orchestra__compact_worker') preview = `🗜 Compact: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__rename_worker') preview = `✏️ ${parsed.old_name || '?'} → ${parsed.new_name || '?'}`;
            else if (rawName === 'mcp__orchestra__change_worker_model') preview = `🔄 ${parsed.name || '?'} → ${parsed.model || '?'}`;
            else if (rawName === 'mcp__orchestra__update_worker_description') preview = `✏️ ${parsed.name || '?'} — description`;
            else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
            else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
            else if (rawName === 'TodoWrite') {
                const _tds = Array.isArray(parsed.todos) ? parsed.todos : [];
                const _dn = _tds.filter(t => t.status === 'completed').length;
                const _cur = _tds.find(t => t.status === 'in_progress');
                preview = `📝 ${_dn}/${_tds.length} todos${_cur ? ' · ' + String(_cur.content || '').slice(0, 40) : ''}`;
            }
            else if (rawName === 'Review') preview = `🧠 ${(parsed.focus || 'review').slice(0, 60)}`;
            else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
            else if (rawName === 'FileChange') {
                const changes = parsed.changes || [];
                preview = `📝 ${changes.length} file${changes.length === 1 ? '' : 's'}`;
            }
            else if (rawName === 'ViewImage') preview = `🖼 ${(parsed.file_path || '').split('/').pop() || 'image'}`;
            else if (rawName === 'ImageGeneration') preview = '🎨 generating image';
            else if (rawName === 'Sleep') preview = `⏱ ${Math.round((parsed.duration_ms || 0) / 1000)}s`;
            else if (rawName === 'mcp__orchestra__task_create') preview = `создаёт задачу «${typeof parsed.title === 'string' ? parsed.title : '?'}»`;
            else if (rawName === 'mcp__orchestra__task_update') {
                const status = typeof parsed.status === 'string' && parsed.status.length > 0 ? ` • статус ${parsed.status}` : '';
                preview = `обновляет задачу #${taskNum(parsed.par) || '?'}${status}`;
            } else if (rawName === 'mcp__orchestra__task_list') {
                const _fl = _taskListFilter(parsed);
                preview = `читает список задач${_fl ? ` (${_fl})` : ''}`;
            } else if (rawName === 'mcp__orchestra__task_get') preview = `читает задачу #${taskNum(parsed.par) || '?'}`;
            else if (rawName === 'mcp__orchestra__bg_create') { const _bi = _JOB_ICONS[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
            else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
            else if (rawName === 'mcp__orchestra__bg_cancel') preview = `⏹ Cancel job ${(parsed.job_id||'').slice(0,8)}`;
            else if (rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch') { let _d = '?'; try { _d = new URL(parsed.url).hostname; } catch {} preview = `🌐 ${_d}`; }
            else if (parsed.file_path) preview = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') + (parsed.offset ? ` :${parsed.offset}` : '') + (parsed.limit ? ` (${parsed.limit} lines)` : '');
            else if (parsed.command) preview = parsed.command;
            else if (parsed.pattern) preview = parsed.pattern;
            else if (parsed.path) preview = parsed.path;
            else if (parsed.message) preview = parsed.message;
            else if (parsed.content) preview = parsed.content.slice(0, 80);
            else preview = body.slice(0, 80);
        } catch {
            preview = rawName === 'WebSearch'
                ? `🌐 "${body.slice(0, 120)}"`
                : body.slice(0, 120);
        }

        const isOrch = rawName.startsWith('mcp__orchestra__');
        const nameColor = isOrch ? '#a78bfa' : '#38bdf8';

        const iconSpan = document.createElement('span');
        iconSpan.textContent = icon;
        iconSpan.style.minWidth = '1.2em';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = short;
        nameSpan.style.color = nameColor;
        nameSpan.style.minWidth = 'max-content';

        let desc = '';
        try { desc = JSON.parse(body).description || ''; } catch {}

        const descSpan = document.createElement('span');
        descSpan.className = 'shrink-0';
        descSpan.style.color = '#64748b';
        descSpan.textContent = desc ? `— ${desc}` : '';

        const previewSpan = document.createElement('span');
        previewSpan.className = 'truncate flex-1 opacity-60 compact-preview';
        previewSpan.textContent = preview;

        const resultSpan = document.createElement('span');
        resultSpan.className = 'compact-result shrink-0';
        resultSpan.style.color = '#475569';

        line.append(iconSpan, nameSpan, descSpan, previewSpan, resultSpan);
        line.dataset.compactTool = '1';
        line.dataset.toolContent = content;
        line.dataset.toolRaw = rawName;
        if (rawName === NOTIFY_USER_TOOL) {
            line.classList.add('chat-notify-user');
            line.style.color = '#fca5a5';
        }
        if (payload?.tool_use_id) line.dataset.toolUseId = payload.tool_use_id;
        try {
            const parsed = JSON.parse(body);
            if (parsed._codex_item_id && !line.dataset.toolUseId) {
                line.dataset.toolUseId = parsed._codex_item_id;
                _flushCodexToolUpdates(line, parsed._codex_item_id);
            }
        } catch {}

        line.addEventListener('mouseenter', () => line.style.backgroundColor = 'rgba(30,41,59,0.5)');
        line.addEventListener('mouseleave', () => line.style.backgroundColor = '');

        let fullBubble = null;
        line.addEventListener('click', () => {
            if (fullBubble) {
                fullBubble.remove();
                fullBubble = null;
                return;
            }
            fullBubble = document.createElement('div');
            fullBubble.className = 'ml-4 mb-1';
            const tempContent = line.dataset.toolContent;
            const tempResult = line.dataset.resultContent || '';
            const savedCompact = window.compactMode;
            window.compactMode = false;
            const anchor = line.nextSibling;
            const chat = $('#chat');
            const sentinel = document.createElement('span');
            sentinel.style.display = 'none';
            if (anchor) chat.insertBefore(sentinel, anchor);
            else chat.appendChild(sentinel);
            const toolPayload = line.dataset.toolUseId
                ? {tool_use_id: line.dataset.toolUseId}
                : undefined;
            addChatEntry('tool', tempContent, null, sentinel, toolPayload);
            if (tempResult) {
                addChatEntry('tool_result', tempResult, null, sentinel, toolPayload);
            }
            window.compactMode = savedCompact;
            const rendered = [];
            let node = line.nextSibling;
            while (node && node !== sentinel) {
                rendered.push(node);
                node = node.nextSibling;
            }
            sentinel.remove();
            for (const el of rendered) {
                el.remove();
                fullBubble.appendChild(el);
            }
            line.after(fullBubble);
        });
    } else {
        line.dataset.unmatchedToolResult = '1';
        line.style.color = '#f59e0b';
        const toolUseId = payload?.tool_use_id;
        if (toolUseId) {
            line.dataset.orphanResultFor = toolUseId;
            line._orphanResult = {content, ts, payload};
        }
        line.textContent = `⚠️ Результат без вызова${toolUseId ? ` · ${toolUseId}` : ''} — ${content.slice(0, 100)}`;
    }

    return line;
}

function _findLastBefore(parent, selector, anchor) {
    let node = anchor ? anchor.previousElementSibling : parent.lastElementChild;
    while (node) {
        if (node.matches(selector)) return node;
        node = node.previousElementSibling;
    }
    return null;
}

// У результата без tool_use_id связать его с вызовом можно только соседством: поле
// появилось недавно, и 63.7% строк журнала (все до него) идентификатора не несут.
// Точный поиск для них означал бы «Результат без вызова» на КАЖДОЙ старой строке.
function _toolForResult(chat, payload, anchor, compact) {
    const toolUseId = payload?.tool_use_id;
    if (!toolUseId) return _findLastBefore(chat, compact ? '[data-compact-tool]' : '[data-last-tool]', anchor);
    // Идентификатор уникален, поэтому ищем по всему чату, а не назад от якоря: страница
    // истории разрезает параллельный блок, и вызов приезжает ПОЗЖЕ своего результата;
    // у Codex вызов и вовсе попадает в журнал после него.
    const idSelector = `[data-tool-use-id="${CSS.escape(String(toolUseId))}"]`;
    return chat.querySelector(compact
        ? `${idSelector}[data-compact-tool]`
        : `${idSelector}:not([data-compact-tool])`);
}

// Вызова ещё не было в DOM, когда рисовался результат — он стал сиротой. Как только
// вызов появился, забираем сироту к нему: перерисовываем результат на прежнем месте.
function _adoptOrphanResults(chat, toolUseId) {
    if (!toolUseId) return;
    const selector = `[data-orphan-result-for="${CSS.escape(String(toolUseId))}"]`;
    for (const node of [...chat.querySelectorAll(selector)]) {
        const saved = node._orphanResult;
        if (!saved) continue;
        // Узел НЕ удаляем: он может быть якорем текущей пачки дорисовки — `_prependHistory`
        // держит `chat.firstChild` на весь цикл, и удаление роняет вставку следующей строки
        // с NotFoundError. Гасим его и перерисовываем результат ровно на его месте.
        delete node.dataset.orphanResultFor;
        delete node.dataset.unmatchedToolResult;
        node._orphanResult = null;
        node.textContent = '';
        node.style.display = 'none';
        addChatEntry('tool_result', saved.content, saved.ts, node, saved.payload);
    }
}

const HIDE_THINKING = document.body.dataset.hideThinking === 'true';

// SDK stream events can beat TaskStarted by a few milliseconds. Buffer those
// lines by parent tool id, then move them into the task-id card once it exists.
const _pendingSubagentLogs = new Map();
function appendSubagentLog(subId, evType, content) {
    const chat = $('#chat');
    const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
    if (!host) {
        if (!_pendingSubagentLogs.has(subId) && _pendingSubagentLogs.size >= 50) {
            _pendingSubagentLogs.delete(_pendingSubagentLogs.keys().next().value);
        }
        const pending = _pendingSubagentLogs.get(subId) || [];
        pending.push([evType, content]);
        if (pending.length > 100) pending.shift();
        _pendingSubagentLogs.set(subId, pending);
        return;
    }
    const body = host.querySelector('.sa-body');
    if (!body) return;
    if (evType === 'stream') {
        // Coalesce contiguous stream text into one line (typewriter feel)
        let last = body.lastElementChild;
        if (last && last.classList.contains('sa-stream')) {
            last.textContent += content;
        } else {
            last = document.createElement('div');
            last.className = 'sa-stream';
            last.textContent = content;
            body.appendChild(last);
        }
    } else {
        const line = document.createElement('div');
        const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
        line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
        const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
        line.textContent = `${icon} ${short}`;
        body.appendChild(line);
    }
    body.scrollTop = body.scrollHeight;
}

function _flushPendingSubagentLogs(sourceId, targetId) {
    if (!sourceId || !targetId) return;
    const pending = _pendingSubagentLogs.get(sourceId);
    if (!pending) return;
    _pendingSubagentLogs.delete(sourceId);
    for (const [evType, content] of pending) {
        appendSubagentLog(targetId, evType, content);
    }
}

let _codexThinkingLive = null;
let _codexThinkingKey = '';
let _codexTurnDiffBubble = null;
const _pendingCodexToolUpdates = new Map();

function _resetCodexActivityState() {
    _removeCodexThinkingLive();
    _codexTurnDiffBubble = null;
    _pendingCodexToolUpdates.clear();
}

function _removeCodexThinkingLive(activity) {
    if (!_codexThinkingLive) return;
    if (activity && _codexThinkingLive.dataset.activity !== activity) return;
    _codexThinkingLive.remove();
    _codexThinkingLive = null;
    _codexThinkingKey = '';
}

function _codexToolHost(chat, payload, anchor) {
    const itemId = payload && payload.tool_use_id;
    if (itemId) {
        const exact = chat.querySelector(`[data-tool-use-id="${CSS.escape(itemId)}"]`);
        if (exact) return exact;
    }
    return _findLastBefore(chat, '[data-last-tool], [data-compact-tool]', anchor);
}

function _applyCodexToolUpdate(host, type, content) {
    if (!host) return;
    if (type === 'tool_patch') {
        const patch = renderCodexFileChange(content);
        if (!patch) return;
        const old = host.querySelector('.codex-file-change');
        if (old) old.replaceWith(patch);
        else host.appendChild(patch);
        return;
    }
    if (host.dataset.compactTool) {
        const result = host.querySelector('.compact-result');
        if (result) {
            const lastLine = String(content).trim().split('\n').pop() || 'working';
            result.textContent = `⚡ ${lastLine.slice(0, 42)}`;
            result.style.color = '#38bdf8';
        }
        return;
    }
    let pre = host.querySelector('.codex-live-output');
    if (!pre) {
        pre = document.createElement('pre');
        pre.className = 'codex-live-output';
        host.appendChild(pre);
    }
    const prefix = type === 'tool_stream' && host.dataset.toolStream === 'stdin' ? '› ' : '';
    pre.textContent = (pre.textContent + prefix + content).slice(-20_000);
    pre.scrollTop = pre.scrollHeight;
}

function _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor) {
    const host = _codexToolHost(chat, payload, anchor);
    const itemId = payload && payload.tool_use_id;
    if (host) {
        if (itemId) host.dataset.toolUseId = itemId;
        if (payload && payload.stream) host.dataset.toolStream = payload.stream;
        _applyCodexToolUpdate(host, type, content);
        return;
    }
    if (!itemId) return;
    const pending = _pendingCodexToolUpdates.get(itemId) || [];
    pending.push([type, content, payload || {}]);
    if (pending.length > 100) pending.shift();
    _pendingCodexToolUpdates.set(itemId, pending);
}

function _flushCodexToolUpdates(host, itemId) {
    if (!host || !itemId) return;
    const pending = _pendingCodexToolUpdates.get(itemId);
    if (!pending) return;
    _pendingCodexToolUpdates.delete(itemId);
    for (const [type, content, payload] of pending) {
        if (payload.stream) host.dataset.toolStream = payload.stream;
        _applyCodexToolUpdate(host, type, content);
    }
}

function _imageGenerationProjection(data) {
    return {
        status: String(data?.status || ''),
        saved_path: String(data?.saved_path || ''),
        revised_prompt: String(data?.revised_prompt || ''),
    };
}

function _completeImageGenerationTool(host, data) {
    const projected = _imageGenerationProjection(data);
    const header = host.querySelector('.flex.items-center');
    const failed = projected.status === 'failed';
    if (header) {
        header.textContent = failed ? '❌ Image generation failed' : '✅ Image generated';
        header.style.color = failed ? '#f87171' : '#f472b6';
    }
    host.querySelectorAll('.codex-tool-image, .codex-image-prompt').forEach(el => el.remove());
    if (projected.saved_path) {
        const img = document.createElement('img');
        img.src = `/api/files/raw?path=${encodeURIComponent(projected.saved_path)}&t=${Date.now()}`;
        img.loading = 'lazy';
        img.className = 'codex-tool-image';
        img.addEventListener('click', () => openImageLightbox(img.src));
        host.appendChild(img);
    }
    if (projected.revised_prompt) {
        const prompt = document.createElement('div');
        prompt.className = 'codex-image-prompt';
        prompt.textContent = projected.revised_prompt;
        host.appendChild(prompt);
    }
    return projected;
}

async function _restoreImageGenerationResult(host, payload) {
    const logId = Number(payload?.id);
    if (!host || !Number.isFinite(logId) || host.dataset.imageRestore === 'loading') return;
    host.dataset.imageRestore = 'loading';
    const header = host.querySelector('.flex.items-center');
    if (header) header.textContent = '↻ Restoring generated image';
    try {
        const row = await api(`/api/logs/${logId}`);
        const data = JSON.parse(row.content || '{}');
        const projected = _imageGenerationProjection(data);
        if (host.isConnected) _completeImageGenerationTool(host, projected);
        const compactRow = {
            ...row,
            content: JSON.stringify(projected),
            projection: 'image_generation',
            source_bytes: Number(payload.trunc) || String(row.content || '').length,
        };
        delete compactRow.trunc;
        _storePut([compactRow]);
    } catch (error) {
        if (host.isConnected && header) {
            header.textContent = `❌ Image unavailable · ${error.name}`;
            header.style.color = '#f87171';
        }
    } finally {
        delete host.dataset.imageRestore;
    }
}

function _renderCodexThinking(content, label) {
    const card = document.createElement('div');
    card.className = 'codex-activity-card codex-thinking-card';
    const header = document.createElement('button');
    header.className = 'codex-activity-header';
    header.innerHTML = `<span class="codex-activity-caret">▶</span><span>${label || 'Reasoning'}</span>`;
    const body = document.createElement('div');
    body.className = 'codex-activity-body markdown-body';
    body.innerHTML = DOMPurify.sanitize(marked.parse(content || ''));
    body.style.display = 'none';
    header.addEventListener('click', () => {
        const expanded = body.style.display !== 'none';
        body.style.display = expanded ? 'none' : 'block';
        header.querySelector('.codex-activity-caret').textContent = expanded ? '▶' : '▼';
    });
    card.append(header, body);
    return card;
}

function _renderCodexPlan(content) {
    let data;
    try { data = JSON.parse(content); } catch { data = {explanation: '', plan: []}; }
    const card = document.createElement('div');
    card.className = 'codex-activity-card codex-plan-card';
    const title = document.createElement('div');
    title.className = 'codex-plan-title';
    title.textContent = '▦ Plan';
    card.appendChild(title);
    if (data.explanation) {
        const explanation = document.createElement('div');
        explanation.className = 'codex-plan-explanation';
        explanation.textContent = data.explanation;
        card.appendChild(explanation);
    }
    const steps = document.createElement('div');
    steps.className = 'codex-plan-steps';
    for (const step of data.plan || []) {
        const row = document.createElement('div');
        const status = String(step.status || 'pending');
        row.className = `codex-plan-step codex-plan-${status.toLowerCase()}`;
        const icon = status === 'completed' ? '✓' : status === 'inProgress' ? '●' : '○';
        row.innerHTML = `<span class="codex-plan-icon">${icon}</span><span></span>`;
        row.lastChild.textContent = step.step || '';
        steps.appendChild(row);
    }
    card.appendChild(steps);
    return card;
}

const _TASK_PRIORITY_META = {
    0: ['🔴', 'Critical'],
    1: ['🟠', 'High'],
    2: ['🟡', 'Medium'],
    3: ['🟢', 'Low'],
};

function _taskMoney(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'number') {
        return String(Math.abs(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    }
    return DOMPurify.sanitize(String(value));
}

function _taskDescriptionHtml(description) {
    const text = String(description || '');
    if (!text) return '';
    const collapsible = text.length > 180 || text.split('\n').length > 3;
    const bodyStyle = collapsible ? 'max-height:64px;overflow:hidden' : '';
    const button = collapsible
        ? '<button type="button" data-task-description-toggle onclick="event.stopPropagation();_toggleTaskDescription(this)" style="margin-top:3px;padding:0;border:0;background:none;color:#818cf8;font-size:10px;cursor:pointer">▼ Развернуть</button>'
        : '';
    return `<div data-task-description style="margin-top:6px;border-top:1px solid rgba(51,65,85,0.55);padding-top:5px">
        <div style="font-size:9px;color:#64748b;margin-bottom:2px">DESCRIPTION</div>
        <div data-task-description-body class="markdown-body text-xs" style="${bodyStyle};overflow-wrap:anywhere;line-height:1.4;color:#94a3b8">${DOMPurify.sanitize(marked.parse(text))}</div>
        ${button}
    </div>`;
}

function _toggleTaskDescription(button) {
    const body = button.parentElement.querySelector('[data-task-description-body]');
    if (!body) return;
    const expanded = button.dataset.expanded === '1';
    button.dataset.expanded = expanded ? '0' : '1';
    body.style.maxHeight = expanded ? '64px' : 'none';
    body.style.overflow = expanded ? 'hidden' : 'visible';
    button.textContent = expanded ? '▼ Развернуть' : '▲ Свернуть';
}

function _taskCardBodyHtml(task) {
    const rows = [];
    const safe = (value) => DOMPurify.sanitize(String(value));
    const statusColor = {'done':'#22c55e','paid':'#22c55e','in_progress':'#38bdf8','new':'#e2e8f0','cancelled':'#ef4444'}[task.status] || '#e2e8f0';
    if (task.status) rows.push(`<div><span style="color:#64748b">Status:</span> <b style="color:${statusColor}">${safe(task.status)}</b></div>`);
    if (task.project) rows.push(`<div><span style="color:#64748b">Project:</span> <span style="color:#94a3b8">${safe(task.project)}</span></div>`);
    const price = task.price_rub ?? task.price;
    if (Number(price) > 0) rows.push(`<div><span style="color:#64748b">Price:</span> <b style="color:#eab308">${_taskMoney(price)} ${CUR}</b></div>`);
    if (task.assignee) rows.push(`<div><span style="color:#64748b">Assignee:</span> ${safe(task.assignee)}</div>`);
    if (task.priority != null && _TASK_PRIORITY_META[task.priority]) {
        const [icon, label] = _TASK_PRIORITY_META[task.priority];
        rows.push(`<div><span style="color:#64748b">Priority:</span> ${icon} ${label}</div>`);
    }
    const taskId = task.task_id ?? task.id;
    if (taskId != null && taskId !== '') rows.push(`<div><span style="color:#64748b">Task ID:</span> <span style="font-family:monospace">${safe(taskId)}</span></div>`);
    if (task.created_at) rows.push(`<div><span style="color:#64748b">Created:</span> ${safe(String(task.created_at).slice(0, 10))}</div>`);
    if (task.updated_at) rows.push(`<div><span style="color:#64748b">Updated:</span> ${safe(String(task.updated_at).slice(0, 10))}</div>`);
    if (task.completed_at) rows.push(`<div><span style="color:#64748b">Done:</span> ${safe(String(task.completed_at).slice(0, 10))}</div>`);
    if (task.paid_at) rows.push(`<div><span style="color:#64748b">Paid at:</span> ${safe(String(task.paid_at).slice(0, 10))}</div>`);
    const fields = rows.length
        ? `<div data-task-fields style="display:grid;grid-template-columns:1fr 1fr;gap:2px 8px;font-size:10px;color:#94a3b8">${rows.join('')}</div>`
        : '';
    return fields + _taskDescriptionHtml(task.description);
}

function _appendToolTechnicalDetails(card, content) {
    const details = document.createElement('details');
    details.dataset.toolTechnicalDetails = '1';
    details.style.cssText = 'margin-top:6px;border-top:1px solid rgba(51,65,85,0.55);padding-top:4px';
    const summary = document.createElement('summary');
    summary.style.cssText = 'font-size:10px;color:#64748b;cursor:pointer;user-select:none';
    summary.textContent = 'Технические детали';
    const raw = document.createElement('pre');
    raw.style.cssText = 'margin:5px 0 0;padding:6px 8px;border-radius:6px;background:#0d1117;color:#64748b;font-size:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto';
    try { raw.textContent = JSON.stringify(JSON.parse(content), null, 2); }
    catch { raw.textContent = content; }
    details.append(summary, raw);
    card.appendChild(details);
}

function _agentResultSummary(content) {
    const lines = content.split('\n').filter(line => line.includes('|'));
    if (!lines.length) return null;
    const agents = lines.map(line => {
        const parts = line.split('|').map(part => part.trim());
        return {
            line,
            name: (parts[0] || '').replace(/\*\*/g, '').replace(/^[^\p{L}\p{N}_-]*/u, '').trim(),
            status: parts[1] || 'unknown',
        };
    });
    const counts = {running: 0, waiting: 0, broken: 0};
    for (const agent of agents) {
        if (Object.hasOwn(counts, agent.status)) counts[agent.status] += 1;
    }
    return {lines, agents, counts};
}

function _agentCountText(counts) {
    const word = (count, one, many) => `${count} ${count === 1 ? one : many}`;
    return [
        word(counts.running, 'работает', 'работают'),
        word(counts.waiting, 'ждёт', 'ждут'),
        word(counts.broken, 'сломан', 'сломаны'),
    ];
}

// Platform notices (`system`) and Codex `warning` share one look: otherwise `system`
// falls through to `.chat-bot` and a delivery failure reads as an agent reply (#51).
function renderSystemChatEntry(type, content, ts) {
    if (type !== 'system' && type !== 'warning') return null;
    const el = document.createElement('div');
    el.className = 'codex-warning';
    if (type === 'system') el.dataset.chatSystem = '1';
    const icon = document.createElement('span');
    icon.className = 'codex-warning-icon';
    icon.textContent = '⚠';
    const body = document.createElement('span');
    body.textContent = content;
    el.append(icon, body);
    addTimestamp(el, ts);
    return el;
}

// Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
// anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
// payload = full SSE log object (carries subagent_id for sub-agent nesting)
function addChatEntry(type, content, ts, anchor, payload) {
    if (_isSilentTurnMarker(type, content)) return;
    if (HIDE_THINKING && (type === 'thinking' || type === 'thinking_stream')) return;
    // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
    if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
        return;
    }
    if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
    const chat = $('#chat');
    let _insertedBeforeStream = false;
    const _insert = (el) => {
        _tagChatTimelineNode(el, type, ts);
        _stampChatLogNode(el, payload);
        if (payload && payload.trunc) _attachTruncNotice(el, payload, type, ts);
        if (anchor) return chat.insertBefore(el, anchor);
        const wasAtBottom = _chatAtBottom(chat);
        let inserted;
        if (streamBubble && streamBubble.parentNode === chat) {
            _insertedBeforeStream = true;
            inserted = chat.insertBefore(el, streamBubble);
        } else {
            inserted = chat.appendChild(el);
        }
        if (!scrollAfterLoad && !wasAtBottom) _markChatHasNewBelow();
        return inserted;
    };

    // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
    const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);

    if (type === 'thinking_stream') {
        const activity = (payload && payload.activity) || 'reasoning';
        const key = `${activity}:${(payload && payload.item_id) || ''}`;
        if (!_codexThinkingLive || _codexThinkingKey !== key) {
            _removeCodexThinkingLive();
            _codexThinkingLive = document.createElement('div');
            _codexThinkingLive.className = 'codex-activity-card codex-thinking-live';
            _codexThinkingLive.dataset.activity = activity;
            const label = document.createElement('div');
            label.className = 'codex-live-label';
            label.textContent = activity === 'plan'
                ? '▦ Planning live'
                : activity === 'waiting'
                    ? '⌁ Codex still working'
                    : '◇ Reasoning live';
            const body = document.createElement('div');
            body.className = 'codex-live-thinking-body';
            _codexThinkingLive.append(label, body);
            _codexThinkingKey = key;
            _insert(_codexThinkingLive);
        }
        const body = _codexThinkingLive.querySelector('.codex-live-thinking-body');
        body.textContent = activity === 'waiting'
            ? content
            : (body.textContent + content).slice(-30_000);
        return;
    }

    if (type === 'tool_stream' || type === 'tool_patch') {
        _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor);
        return;
    }

    if (type === 'turn_diff') {
        const patch = renderCodexFileChange({
            changes: [{path: 'Current turn', kind: 'update', diff: content}],
        });
        if (!_codexTurnDiffBubble) {
            _codexTurnDiffBubble = document.createElement('div');
            _codexTurnDiffBubble.className = 'codex-activity-card codex-turn-diff';
            const title = document.createElement('div');
            title.className = 'codex-live-label';
            title.textContent = '± Live turn diff';
            _codexTurnDiffBubble.appendChild(title);
            _insert(_codexTurnDiffBubble);
        }
        const old = _codexTurnDiffBubble.querySelector('.codex-file-change');
        if (old && patch) old.replaceWith(patch);
        else if (patch) _codexTurnDiffBubble.appendChild(patch);
        return;
    }

    if (_isBase64Image && type !== 'tool' && type !== 'tool_result') {
        const div = document.createElement('div');
        div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
        const b64Match = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{500,})['"]/);
        if (b64Match && !(payload && payload.trunc)) {
            const img = document.createElement('img');
            img.src = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
            img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;cursor:pointer';
            img.addEventListener('click', () => _showImageOverlay(img.src));
            div.appendChild(img);
        } else {
            div.textContent = '🖼 [Image]';
            div.style.color = '#64748b';
        }
        addTimestamp(div, ts);
        const wasAtBottom = _chatAtBottom(chat);
        _insert(div);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (window.compactMode && (type === 'tool' || type === 'tool_result')) {
        if (type === 'tool_result') {
            const lastC = _toolForResult(chat, payload, anchor, true);
            if (lastC && _isBase64Image) {
                const resultSpan = lastC.querySelector('.compact-result');
                if (resultSpan) resultSpan.textContent = '🖼 image';
                lastC.dataset.resultContent = '[image]';
                return;
            }
            if (lastC) {
                const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
                const rawName = lastC.dataset.toolRaw || '';
                const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
                const isReadTool = rawName === 'Read';
                const isToolSearch = rawName === 'ToolSearch';
                const isBugReportCompact = rawName === 'mcp__orchestra__report_bug';
                const isSendFileCompact = rawName === 'mcp__orchestra__send_file';
        const isOrchSimpleCompact = ['mcp__orchestra__kill_worker','mcp__orchestra__stop_worker','mcp__orchestra__compact_worker','mcp__orchestra__rename_worker','mcp__orchestra__change_worker_model','mcp__orchestra__update_worker_description','mcp__orchestra__merge_worker','mcp__orchestra__send_message','mcp__orchestra__list_agents','mcp__orchestra__list_orchestrators','mcp__orchestra__get_worker_logs','mcp__orchestra__get_worker_info','mcp__orchestra__bg_create','mcp__orchestra__bg_cancel'].includes(rawName);
                const isGlobCompact = rawName === 'Glob';
                const isSkillCompact = rawName === 'Skill';
                const isWebFetchCompact = rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch';
                const isWebSearchCompact = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
                const isSpawnWorkerCompact = rawName === 'mcp__orchestra__spawn_worker';
                const isTaskCompact = ['mcp__orchestra__task_create','mcp__orchestra__task_get','mcp__orchestra__task_update','mcp__orchestra__task_list'].includes(rawName);
                const isAgentListCompact = rawName === 'mcp__orchestra__list_agents' || rawName === 'mcp__orchestra__list_orchestrators';
                const resultSpan = lastC.querySelector('.compact-result');
                if (resultSpan && isTaskCompact) {
                    let parsed = null;
                    try { parsed = JSON.parse(content); } catch {}
                    if (parsed && !parsed.error) {
                        if (rawName === 'mcp__orchestra__task_create') {
                            const number = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
                            resultSpan.textContent = `✅ задача #${number} создана`;
                        } else if (rawName === 'mcp__orchestra__task_get') {
                            const number = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
                            resultSpan.textContent = `📋 читает задачу #${number}`;
                        } else if (rawName === 'mcp__orchestra__task_list') {
                            resultSpan.textContent = `📋 читает список задач (${(parsed.tasks || []).length})`;
                        } else {
                            const number = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
                            const status = parsed.new_status || parsed.status;
                            resultSpan.textContent = `✏️ обновляет задачу #${number}${typeof status === 'string' && status ? ` • ${status}` : ''}`;
                        }
                    } else {
                        resultSpan.textContent = '❌';
                    }
                } else if (resultSpan && isAgentListCompact) {
                    const summary = _agentResultSummary(clean);
                    if (summary) {
                        resultSpan.textContent = `${summary.agents.length} всего · ${_agentCountText(summary.counts).join(' · ')}`;
                        resultSpan.style.color = summary.counts.broken ? '#ef4444' : summary.counts.waiting ? '#f59e0b' : '#64748b';
                    } else {
                        resultSpan.textContent = '❌ нет списка';
                    }
                } else if (resultSpan && isSendFileCompact) {
                    resultSpan.textContent = clean.includes('error') ? '❌' : '✅ sent';
                } else if (resultSpan && isOrchSimpleCompact) {
                    const hasErr = clean.includes('error') || clean.includes('Error') || clean.includes('fail') || clean.includes('Fail');
                    if (['mcp__orchestra__kill_worker','mcp__orchestra__stop_worker','mcp__orchestra__rename_worker','mcp__orchestra__change_worker_model','mcp__orchestra__update_worker_description','mcp__orchestra__merge_worker','mcp__orchestra__bg_create'].includes(rawName)) resultSpan.textContent = hasErr ? '❌' : '✅';
                    else if (rawName === 'mcp__orchestra__send_message') { const m = clean.match(/sent to '(.+?)'/i); resultSpan.textContent = hasErr ? '❌' : m ? `✅ → ${m[1]}` : '✅'; }
                    else if (rawName === 'mcp__orchestra__bg_cancel') resultSpan.textContent = hasErr ? '❌' : '⏹';
                    else if (rawName === 'mcp__orchestra__compact_worker') { const m = clean.match(/(\d+)%/); resultSpan.textContent = m ? `✅ ${m[1]}%` : '✅'; }
                    else if (rawName === 'mcp__orchestra__get_worker_info') { try { const d = JSON.parse(clean); resultSpan.textContent = `${d.status === 'running' ? '🟢' : d.status === 'idle' ? '🟡' : '⚪'} ${d.name || '?'}`; } catch { resultSpan.textContent = '✅'; } }
                    else { const ct = clean.split('\n').filter(l=>l.trim()).length; resultSpan.textContent = `📎 ${ct} items`; }
                } else if (resultSpan && isGlobCompact) {
                    const ct = clean.split('\n').filter(l=>l.trim()).length;
                    resultSpan.textContent = `📎 ${ct} files`;
                } else if (resultSpan && isSkillCompact) {
                    resultSpan.textContent = clean.includes('error') ? '❌' : '✅';
                } else if (resultSpan && isWebFetchCompact) {
                    const short = clean.length > 40 ? clean.replace(/\n/g, ' ').slice(0, 40) + '…' : clean.replace(/\n/g, ' ');
                    resultSpan.textContent = '📎 ' + short;
                } else if (resultSpan && isBugReportCompact) {
                    resultSpan.textContent = '✅ reported';
                } else if (resultSpan && isToolSearch) {
                    let toolName = '';
                    try { const d = JSON.parse(content); toolName = d.tool_name || ''; } catch {}
                    if (!toolName) { const m = clean.match(/tool_name['":\s]+(\w+)/); toolName = m ? m[1] : ''; }
                    resultSpan.textContent = toolName ? `✅ ${toolName}` : '✅ loaded';
                } else if (resultSpan && isWebSearchCompact) {
                    const spec = codexWebSearchSpec(content);
                    const compactPreview = lastC.querySelector('.compact-preview');
                    if (compactPreview && spec) compactPreview.textContent = codexWebSearchCompactLabel(spec);
                    resultSpan.textContent = spec?.queries.length ? `✅ ${spec.queries.length} queries` : '✅';
                } else if (resultSpan && isSpawnWorkerCompact) {
                    resultSpan.textContent = clean.toLowerCase().includes('error') ? '❌' : '✅ spawned';
                } else if (resultSpan && !isEditTool && !isReadTool) {
                    const short = clean.length > 40 ? clean.slice(0, 40).replace(/\n/g, ' ') + '…' : clean.replace(/\n/g, ' ');
                    resultSpan.textContent = '📎 ' + short;
                } else if (resultSpan && isEditTool) {
                    resultSpan.textContent = '📎 updated';
                } else if (resultSpan && isReadTool) {
                    let readShort = 'OK';
                    try {
                        const colonIdx = lastC.dataset.toolContent.indexOf(':');
                        const bd = colonIdx > 0 ? lastC.dataset.toolContent.slice(colonIdx + 1).trim() : '';
                        const parsed = JSON.parse(bd);
                        if (parsed.file_path) readShort = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || parsed.file_path;
                    } catch {}
                    resultSpan.textContent = '📖 ' + readShort;
                }
                lastC.dataset.resultContent = (isTaskCompact || isAgentListCompact) ? content : clean;
                return;
            }
        }
        const line = buildCompactToolLine(type, content, ts, payload);
        const wasAtBottom = _chatAtBottom(chat);
        _insert(line);
        // Trim oldest nodes to cap memory — loses old history but prevents unbounded DOM growth
        _trimChatNodes(chat);
        if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    // Stream events feed the typewriter buffer — RAF loop renders incrementally
    if (type === 'stream') {
        removeWaitingIndicator();
        if (_rateLimitAgent) _hideRateLimitBanner();  // agent resumed → rate limit cleared
        if (!streamBubble) {
            streamBubble = document.createElement('div');
            streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
            streamBubble.style.position = 'relative';
            const agentColor = agentColors[selectedAgent];
            if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
            _insert(streamBubble);
            _streamLastParse = 0;
        }
        streamPending += content;
        if (!_streamRafId) _streamRafId = requestAnimationFrame(_streamRenderTick);
        return;
    }

    // 'text' event signals streaming finished — flush typewriter buffer,
    // replace with authoritative DB content, finalize with copy/timestamp.
    if (type === 'text') {
        if (streamBubble) {
            _stampChatLogNode(streamBubble, payload);
            _completeStreamBubble(content, ts);
            _scheduleChatReadCapture();
            return;
        }
        // Stream already closed (e.g. status `turn ended` raced ahead of this row) with
        // the same body — skip the second paint. History reload has no streamBubble and
        // content differs from any prior live finalize, so it still creates a bubble.
        if (content && content === _lastFinalizedStreamText) {
            _lastFinalizedStreamText = '';
            _scheduleChatReadCapture();
            return;
        }
        // No live stream (history, or runtime that only emits final text) → fall through
        // to the normal chat-bot bubble renderer below.
    }

    if (type === 'thinking') {
        _removeCodexThinkingLive('reasoning');
        const card = _renderCodexThinking(content, '◇ Reasoning');
        addTimestamp(card, ts);
        _insert(card);
        return;
    }

    if (type === 'plan') {
        _removeCodexThinkingLive('plan');
        const card = _renderCodexPlan(content);
        addTimestamp(card, ts);
        _insert(card);
        return;
    }

    const platformNotice = renderSystemChatEntry(type, content, ts);
    if (platformNotice) {
        _insert(platformNotice);
        return;
    }

    if (type === 'review') {
        let reviewData = {};
        try { reviewData = JSON.parse(content); } catch {}
        const review = document.createElement('div');
        review.className = 'codex-review';
        const phase = reviewData.phase === 'exited' ? 'Review completed' : 'Review mode';
        review.innerHTML = `<div class="codex-review-title">◎ ${phase}</div><div class="codex-review-body"></div>`;
        review.querySelector('.codex-review-body').textContent = reviewData.review || '';
        addTimestamp(review, ts);
        _insert(review);
        return;
    }

    if (type === 'status') {
        // precompact timer scheduled/cancelled = internal housekeeping noise, never show in chat
        if (content && content.startsWith('precompact timer')) return;
        if (/^codex hook .+: (?:running|started|completed)(?: · \d+ms)?$/i.test(content || '')) return;
        if (/^codex mcp .+: (?:starting|ready)$/i.test(content || '')) return;
        if (/^compact started \(native Codex,/i.test(content || '')) return;
        // Do NOT finalize streamBubble on `turn ended`: `_log` is async, so status can
        // land before the matching `text` row. Finalizing here left streamBubble=null and
        // the later `text` painted a second copy of the same answer (Grok harness, 15.08).
        // Orphan streams (no final text ever) are rare now that Grok flushes text on turn_end.
        if (content && /^grok mcp ready\b/i.test(content)) {
            const badge = document.createElement('div');
            badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
            badge.textContent = `🔌 ${content}`;
            addTimestamp(badge, ts);
            const wasAtBottom = _chatAtBottom(chat);
            _insert(badge);
            if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            return;
        }
        const nativeCodexCompact = (content || '').match(
            /^compact done \(native Codex\):\s*(\d+)%\s*→\s*(\d+)%/i
        );
        const rl = _parseRateLimitStatus(content);
        const codexReconnect = content.startsWith('codex reconnecting:');
        const codexSteer = content === 'message steered into active Codex turn';
        const codexReroute = content.startsWith('model rerouted:');
        const codexHook = content.startsWith('codex hook ');
        const codexMcp = content.startsWith('codex mcp ');
        const codexCompaction = content.includes('codex context compact');
        const badge = document.createElement('div');
        if (rl) {
            // Rate limit: trigger the global banner (live logs only, not history/initial replay)
            if (!anchor && !scrollAfterLoad) _showRateLimitBanner(selectedAgent, rl.retry, rl.max, rl.delay);
            badge.className = 'text-center text-xs py-1 text-amber-400 italic';
            badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rl.retry}/${rl.max} через ${rl.delay}с (это НЕ твой лимит подписки)`;
        } else if (codexReconnect) {
            badge.className = 'text-center text-xs py-1 text-amber-400 italic';
            badge.textContent = `🔌 Codex reconnecting — ${content.slice('codex reconnecting:'.length).trim()}`;
        } else if (codexSteer) {
            badge.className = 'text-center text-xs py-1 text-cyan-400 italic';
            badge.textContent = '↪ Message steered into the current Codex turn';
        } else if (codexReroute) {
            badge.className = 'text-center text-xs py-1 text-fuchsia-400 italic';
            badge.textContent = `⇄ Codex model rerouted — ${content.slice('model rerouted:'.length).trim()}`;
        } else if (codexHook) {
            badge.className = 'text-center text-xs py-1 text-sky-400 italic';
            badge.textContent = `⌁ ${content}`;
        } else if (codexMcp) {
            badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
            badge.textContent = `🔌 ${content}`;
        } else if (nativeCodexCompact) {
            badge.className = 'text-center text-xs py-1 text-amber-300 italic';
            badge.textContent = `🗜 Codex context compacted natively · ${nativeCodexCompact[1]}% → ${nativeCodexCompact[2]}% · same thread`;
        } else if (codexCompaction) {
            badge.className = 'text-center text-xs py-1 text-amber-300 italic';
            badge.textContent = '🗜 Codex context compacted';
        } else {
            badge.className = 'text-center text-xs py-1 text-slate-500 italic';
            badge.textContent = `⚡ ${content}`;
        }
        addTimestamp(badge, ts);
        const wasAtBottom = _chatAtBottom(chat);
        _insert(badge);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    if (type === 'subagent_start' || type === 'subagent_end' || type === 'subagent_progress') {
        const parts = content.split('|').map(p => p.trim());
        const meta = {};
        const textParts = [];
        for (const p of parts) {
            const eq = p.indexOf('=');
            if (eq > 0 && /^\w+$/.test(p.slice(0, eq))) meta[p.slice(0, eq)] = p.slice(eq + 1);
            else if (p) textParts.push(p);
        }
        const desc = textParts[0] || textParts[1] || '';
        const el = document.createElement('div');
        el.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';

        const subId = (payload && payload.subagent_id) || meta.id || '';
        const isBackground = meta.type === 'local_bash';

        if (type === 'subagent_start') {
            // Collapsible accordion: header + body where live sub-agent logs nest.
            el.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
            if (subId) el.dataset.subagentId = subId;
            el.dataset.subagentKind = isBackground ? 'background' : 'agent';
            const header = document.createElement('div');
            header.style.cssText = 'cursor:pointer;user-select:none';
            const noun = isBackground ? 'Background task' : 'Sub-agent';
            header.innerHTML = `<span class="sa-caret">▶</span> ${isBackground ? '⚙️' : '🤖'} <span style="color:#e2e8f0">${noun}: "${DOMPurify.sanitize(desc)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
            const body = document.createElement('div');
            body.className = 'sa-body';
            body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
            let _expanded = false;
            header.addEventListener('click', () => {
                _expanded = !_expanded;
                body.style.display = _expanded ? 'block' : 'none';
                header.querySelector('.sa-caret').textContent = _expanded ? '▼' : '▶';
            });
            el.appendChild(header);
            el.appendChild(body);
        } else if (type === 'subagent_progress') {
            // Update the live progress line inside the matching accordion (or standalone)
            const tokens = meta.tokens ? (parseInt(meta.tokens) >= 1000 ? (parseInt(meta.tokens) / 1000).toFixed(1) + 'k' : meta.tokens) : '';
            const line = `⏳ ${meta.tool ? 'using ' + meta.tool : 'working'}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
            if (host) {
                let prog = host.querySelector('.sa-progress');
                if (!prog) {
                    prog = document.createElement('div');
                    prog.className = 'sa-progress';
                    prog.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
                    host.appendChild(prog);
                }
                prog.textContent = line;
                return;  // updated in place, no new bubble
            }
            el.style.cssText += ';color:#64748b';
            el.textContent = `⏳ ${isBackground ? 'Background task' : 'Sub-agent'} "${desc}" — ${line}`;
        } else {  // subagent_end → mark the accordion done + collapse
            const ok = !meta.status || ['completed', 'shutdown'].includes(meta.status);
            const host = subId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`) : null;
            const summaryText = textParts.slice(1).join(' | ').trim();
            if (host) {
                const hdr = host.querySelector('div');
                const noun = host.dataset.subagentKind === 'background' ? 'Background task' : 'Sub-agent';
                if (hdr) hdr.innerHTML = `<span class="sa-caret">▶</span> ${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'done' : 'failed'}: "${DOMPurify.sanitize(desc)}"</span>`;
                const prog = host.querySelector('.sa-progress');
                if (prog) prog.remove();
                if (summaryText) {
                    const sumEl = document.createElement('div');
                    sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
                    sumEl.textContent = summaryText;
                    host.appendChild(sumEl);
                }
                host.style.borderLeftColor = ok ? '#22c55e' : '#ef4444';
                return;  // updated existing accordion, no new bubble
            }
            el.style.cssText += `;border-left:3px solid ${ok ? '#22c55e' : '#ef4444'};background:rgba(${ok ? '34,197,94' : '239,68,68'},0.06);color:${ok ? '#86efac' : '#fca5a5'}`;
            const noun = isBackground ? 'Background task' : 'Sub-agent';
            el.innerHTML = `${ok ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${ok ? 'completed' : 'failed'}${desc ? ': "'+DOMPurify.sanitize(desc)+'"' : ''}</span>`;
            if (summaryText) {
                const sumEl = document.createElement('div');
                sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
                sumEl.textContent = summaryText.length > 300 ? summaryText.slice(0, 300) + '…' : summaryText;
                el.appendChild(sumEl);
            }
        }
        addTimestamp(el, ts);
        const wasAtBottom = _chatAtBottom(chat);
        _insert(el);
        if (type === 'subagent_start' && subId) {
            _flushPendingSubagentLogs(subId, subId);
            _flushPendingSubagentLogs(meta.tool_use_id, subId);
        }
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return;
    }

    const div = document.createElement('div');
    div.className = `px-3 py-2 rounded-lg text-sm break-words ${
        type === 'user_message' ? 'chat-user ml-16' :
        type === 'tool' ? 'chat-tool' :
        type === 'tool_result' ? 'chat-tool-result' :
        type === 'error' ? 'text-red-400 text-xs' :
        'chat-bot markdown-body'
    }`;
    if (type === 'user_message') {
        content = content.replace(/^\[\d{2}:\d{2}\] /, '');
        // Hide prompt injection (system prompt prepended to first message after resume)
        if (content.startsWith('[Orchestra platform note:') || content.startsWith('[Orchestra platform')) return;
        // [from:agent-name] prefix means this was an agent-to-agent message injected by the MCP send_message tool,
        // not a human message — style it differently (colored border, sender label)
        const fromMatch = content.match(/^\[from:(.+?)\]\s*([\s\S]*)$/);
        if (fromMatch) {
            const sender = fromMatch[1];
            const msg = fromMatch[2];
            const senderColor = _senderColor(sender);
            div.dataset.from = sender;  // якорь для _repaintSenderColors, если список агентов ещё не приехал
            div.style.borderLeft = `3px solid ${senderColor}`;
            div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
            const label = document.createElement('div');
            label.className = 'text-xs mb-1 chat-from-label';
            label.style.color = senderColor;
            label.textContent = `${sender} → ${selectedAgent}`;
            div.appendChild(label);
            const body = document.createElement('div');
            body.className = 'markdown-body';
            body.innerHTML = DOMPurify.sanitize(marked.parse(msg));
            div.appendChild(body);
        } else {
            div.className += ' markdown-body';
            div.innerHTML = DOMPurify.sanitize(marked.parse(content));
            renderImages(div, content);
        }
    }
    else if (type === 'tool') {
        const colonIdx = content.indexOf(':');
        const rawName = canonicalToolName(colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30));
        const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
        const icon = toolIcon(rawName);
        const short = toolShortName(rawName);
        const isOrch = rawName.startsWith('mcp__orchestra__');

        div.dataset.lastTool = '1';
        div.dataset.toolContent = content;
        div.dataset.toolRawName = rawName;
        div.style.cursor = 'pointer';
        if (payload?.tool_use_id) div.dataset.toolUseId = payload.tool_use_id;
        let codexItemId = '';
        try {
            const parsed = JSON.parse(body);
            if (parsed._codex_item_id) {
                codexItemId = parsed._codex_item_id;
                if (!div.dataset.toolUseId) div.dataset.toolUseId = codexItemId;
            }
        } catch {}

        const header = document.createElement('div');
        header.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
        header.style.color = isOrch ? '#a78bfa' : '#38bdf8';
        let toolDesc = '';
        try { toolDesc = JSON.parse(body).description || ''; } catch {}
        header.innerHTML = `${icon} ${DOMPurify.sanitize(short)}${toolDesc ? ` <span style="color:#64748b;font-weight:normal">— ${DOMPurify.sanitize(toolDesc)}</span>` : ''}`;
        div.appendChild(header);

        // Единственный вызов, которым оркестратор зовёт юзера (#241). Красный и без JSON:
        // юзер ищет эти строки глазами, а `reason` объясняет, зачем дёрнули.
        const isNotify = rawName === NOTIFY_USER_TOOL;
        if (isNotify) {
            let reason = '';
            try { reason = JSON.parse(body).reason || ''; } catch {}
            div.classList.add('chat-notify-user');
            header.textContent = '🔔 Оркестратор зовёт';
            header.style.color = '#fca5a5';
            const reasonEl = document.createElement('div');
            reasonEl.className = 'chat-notify-user-reason';
            reasonEl.textContent = reason || body;
            div.appendChild(reasonEl);
        }
        const isSendMsg = rawName === 'mcp__orchestra__send_message';
        if (isSendMsg) {
            try {
                const d = JSON.parse(body);
                const to = d.to || d.message?.substring(0, 30) || '?';
                const msg = d.message || '';
                header.textContent = `📨 → ${to}`;
                header.style.color = '#a78bfa';
                const SEND_PREVIEW_H = 90;
                const bodyEl = document.createElement('div');
                bodyEl.className = 'text-xs opacity-80 markdown-body';
                bodyEl.style.cssText = `max-height:${SEND_PREVIEW_H}px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word`;
                bodyEl.innerHTML = DOMPurify.sanitize(marked.parse(msg));
                div.appendChild(bodyEl);
                const hint = document.createElement('div');
                hint.className = 'text-xs mt-1';
                hint.style.cssText = 'color:#a78bfa;cursor:pointer';
                hint.textContent = '▼ expand';
                div.appendChild(hint);
                div.style.cursor = 'pointer';
                let sendExpanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    sendExpanded = !sendExpanded;
                    bodyEl.style.maxHeight = sendExpanded ? 'none' : SEND_PREVIEW_H + 'px';
                    bodyEl.style.overflowY = sendExpanded ? 'visible' : 'hidden';
                    hint.textContent = sendExpanded ? '▲ collapse' : '▼ expand';
                });
                requestAnimationFrame(() => {
                    if (bodyEl.scrollHeight <= SEND_PREVIEW_H + 4) { hint.style.display = 'none'; bodyEl.style.maxHeight = 'none'; bodyEl.style.overflowY = 'visible'; }
                });
                div.dataset.isEdit = '1';
            } catch {}
        }
        const isSpawnWorker = rawName === 'mcp__orchestra__spawn_worker';
        if (isSpawnWorker) {
            try {
                const d = JSON.parse(body);
                const workerName = d.name || '?';
                const task = d.task || '';
                const model = d.model || 'claude-sonnet-4-6';
                const sysPrompt = d.system_prompt || '';
                const repoPath = d.repo_path || '';

                setCodexToolTitle(header, `Spawning ${workerName}`, '🚀');
                header.style.color = '#a78bfa';
                div.dataset.isSpawnWorker = '1';
                div.dataset.workerName = workerName;

                if (model) {
                    const badge = document.createElement('span');
                    const color = _modelColor(model);
                    badge.textContent = _modelLabel(model);
                    badge.style.cssText = `font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:${color};border-color:${color};opacity:0.8;vertical-align:middle;margin-left:6px`;
                    header.appendChild(badge);
                }
                const role = d.role || '';
                if (role && role !== 'worker') {
                    const roleBadge = document.createElement('span');
                    roleBadge.textContent = role;
                    roleBadge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:#fbbf24;border-color:#fbbf24;opacity:0.8;vertical-align:middle;margin-left:4px';
                    header.appendChild(roleBadge);
                }

                const PREVIEW = 200;
                let cutAt = PREVIEW;
                if (task.length > PREVIEW) {
                    const nl = task.lastIndexOf('\n', PREVIEW);
                    if (nl > PREVIEW / 2) cutAt = nl;
                }
                const hasMoreTask = task.length > cutAt;
                const expandables = [];

                if (task) {
                    const taskEl = document.createElement('div');
                    taskEl.className = 'text-xs opacity-80 markdown-body';
                    taskEl.innerHTML = DOMPurify.sanitize(marked.parse(hasMoreTask ? task.slice(0, cutAt) : task));
                    div.appendChild(taskEl);
                    if (hasMoreTask) {
                        const restEl = document.createElement('div');
                        restEl.className = 'text-xs opacity-80 markdown-body';
                        restEl.innerHTML = DOMPurify.sanitize(marked.parse(task.slice(cutAt)));
                        restEl.style.display = 'none';
                        div.appendChild(restEl);
                        expandables.push(restEl);
                    }
                }

                if (sysPrompt) {
                    const promptLabel = document.createElement('div');
                    promptLabel.className = 'text-xs mt-2';
                    promptLabel.style.cssText = 'color:#64748b;font-weight:500';
                    promptLabel.textContent = '📋 System prompt';
                    promptLabel.style.display = 'none';
                    div.appendChild(promptLabel);
                    expandables.push(promptLabel);
                    const promptEl = document.createElement('div');
                    promptEl.style.cssText = 'margin-top:4px;padding:6px 8px;background:#0d1117;border:1px solid #1e293b;border-radius:6px;font-size:11px;white-space:pre-wrap;word-break:break-word;color:#94a3b8;max-height:200px;overflow-y:auto;display:none';
                    promptEl.textContent = sysPrompt;
                    div.appendChild(promptEl);
                    expandables.push(promptEl);
                }

                if (repoPath) {
                    const pathEl = document.createElement('div');
                    pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                    pathEl.textContent = repoPath;
                    pathEl.title = repoPath;
                    div.appendChild(pathEl);
                }

                if (expandables.length) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#a78bfa;cursor:pointer';
                    hint.textContent = `▼ expand`;
                    div.appendChild(hint);
                    div.style.cursor = 'pointer';
                    let spawnExpanded = false;
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        spawnExpanded = !spawnExpanded;
                        expandables.forEach(el => el.style.display = spawnExpanded ? 'block' : 'none');
                        hint.textContent = spawnExpanded ? '▲ collapse' : '▼ expand';
                    });
                }

                div.dataset.isEdit = '1';
            } catch {}
        }
        const isWebSearchCall = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
        if (isWebSearchCall) {
            try {
                const d = JSON.parse(body);
                setCodexToolTitle(header, 'Web search', '🌐');
                header.style.color = '#38bdf8';
                div.dataset.isCodexWebSearch = '1';
                updateCodexWebSearchActivity(div, codexWebSearchSpec(d));
                if (d.model) {
                    const badge = document.createElement('span');
                    badge.textContent = d.model;
                    badge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid #38bdf8;color:#38bdf8;opacity:0.8;vertical-align:middle;margin-left:6px';
                    header.appendChild(badge);
                }
            } catch {}
        }
        const isToolSearchCall = rawName === 'ToolSearch';
        if (isToolSearchCall) {
            try {
                const d = JSON.parse(body);
                const q = d.query || '';
                header.textContent = `🔍 Loading: ${q}`;
                header.style.color = '#38bdf8';
            } catch {}
        }
        const isBugReport = rawName === 'mcp__orchestra__report_bug';
        if (isBugReport) {
            try {
                const d = JSON.parse(body);
                header.textContent = `🐛 Bug: ${d.title || '?'}`;
                header.style.color = '#f97316';
                if (d.description) {
                    const descLines = d.description.split('\n');
                    const PREVIEW = 5;
                    const descEl = document.createElement('div');
                    descEl.className = 'text-xs markdown-body';
                    descEl.style.cssText = 'margin-top:4px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
                    descEl.innerHTML = DOMPurify.sanitize(marked.parse(d.description));
                    div.appendChild(descEl);
                    if (descLines.length > PREVIEW) {
                        const hint = document.createElement('div');
                        hint.className = 'text-xs mt-1';
                        hint.style.cssText = 'color:#f97316;cursor:pointer';
                        hint.textContent = '▼ expand';
                        div.appendChild(hint);
                        let bugExpanded = false;
                        div.style.cursor = 'pointer';
                        div.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            bugExpanded = !bugExpanded;
                            descEl.style.maxHeight = bugExpanded ? 'none' : '90px';
                            descEl.style.overflowY = bugExpanded ? 'visible' : 'hidden';
                            hint.textContent = bugExpanded ? '▲ collapse' : '▼ expand';
                        });
                    }
                }
            } catch {}
        }
        const isWebFetch = rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch';
        if (isWebFetch) {
            try {
                const d = JSON.parse(body);
                const url = d.url || '';
                let domain = '?';
                try { domain = new URL(url).hostname; } catch {}
                header.textContent = `🌐 Fetching: ${domain}`;
                header.style.color = '#38bdf8';
                if (url) {
                    const linkEl = document.createElement('a');
                    linkEl.href = url;
                    linkEl.target = '_blank';
                    linkEl.style.cssText = 'display:block;font-size:10px;color:#64748b;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none';
                    linkEl.textContent = url;
                    linkEl.onmouseenter = () => linkEl.style.color = '#94a3b8';
                    linkEl.onmouseleave = () => linkEl.style.color = '#64748b';
                    div.appendChild(linkEl);
                }
                if (d.prompt) {
                    const promptEl = document.createElement('div');
                    promptEl.className = 'text-xs';
                    promptEl.style.cssText = 'margin-top:4px;color:#94a3b8;max-height:90px;overflow:hidden;white-space:pre-wrap';
                    promptEl.textContent = d.prompt;
                    div.appendChild(promptEl);
                    if (d.prompt.split('\n').length > 5 || d.prompt.length > 300) {
                        const hint = document.createElement('div');
                        hint.className = 'text-xs mt-1';
                        hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                        hint.textContent = '▼ expand';
                        div.appendChild(hint);
                        let fetchExpanded = false;
                        div.style.cursor = 'pointer';
                        div.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            fetchExpanded = !fetchExpanded;
                            promptEl.style.maxHeight = fetchExpanded ? 'none' : '90px';
                            promptEl.style.overflowY = fetchExpanded ? 'visible' : 'hidden';
                            hint.textContent = fetchExpanded ? '▲ collapse' : '▼ expand';
                        });
                    }
                }
            } catch {}
        }
        const isSendFile = rawName === 'mcp__orchestra__send_file';
        if (isSendFile) {
            try {
                const d = JSON.parse(body);
                const filePath = d.path || '';
                const fileName = filePath.split('/').pop() || '?';
                header.textContent = `📎 Sending: ${fileName}`;
                header.style.color = '#22c55e';
                if (filePath) div.dataset.filePath = filePath;
                if (d.caption) {
                    const capEl = document.createElement('div');
                    capEl.className = 'text-xs';
                    capEl.style.cssText = 'margin-top:2px;color:#cbd5e1';
                    capEl.textContent = d.caption;
                    div.appendChild(capEl);
                }
                if (filePath) {
                    const pathEl = document.createElement('div');
                    pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                    pathEl.textContent = filePath;
                    pathEl.title = filePath;
                    div.appendChild(pathEl);
                }
            } catch {}
        }
        const _orchSimple = {
            'mcp__orchestra__kill_worker': (d) => ({ icon: '💀', label: `Kill: ${d.name||'?'}`, color: '#ef4444' }),
            'mcp__orchestra__stop_worker': (d) => ({ icon: '⏸️', label: `Stop: ${d.name||'?'}`, color: '#eab308' }),
            'mcp__orchestra__compact_worker': (d) => ({ icon: '🗜', label: `Compact: ${d.name||'?'}`, color: '#eab308' }),
            'mcp__orchestra__rename_worker': (d) => ({ icon: '✏️', label: `Rename: ${d.old_name||'?'} → ${d.new_name||'?'}`, color: '#38bdf8' }),
            'mcp__orchestra__change_worker_model': (d) => ({ icon: '🔄', label: `Model: ${d.name||'?'} → ${d.model||'?'}`, color: '#38bdf8' }),
            'mcp__orchestra__update_worker_description': (d) => ({ icon: '✏️', label: `${d.name||'?'} — description updated`, color: '#38bdf8', sub: d.description ? `"${d.description}"` : '' }),
            'mcp__orchestra__merge_worker': (d) => ({ icon: '🔀', label: `Merge: ${d.name||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__list_agents': () => ({ icon: '🎼', label: 'Agents', color: '#a78bfa' }),
            'mcp__orchestra__list_orchestrators': () => ({ icon: '🎯', label: 'Orchestrators', color: '#a78bfa' }),
            'mcp__orchestra__get_worker_logs': (d) => ({ icon: '📋', label: `Logs: ${d.name||'?'}`, color: '#a78bfa', sub: d.limit ? `${d.limit} entries` : '' }),
            'mcp__orchestra__get_worker_info': (d) => ({ icon: '🤖', label: `Info: ${d.name||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `создаёт задачу «${typeof d.title === 'string' ? d.title : '?'}»`, color: '#22c55e', sub: d.price ? `${d.price} ${CUR}` : '' }),
            'mcp__orchestra__task_update': (d) => {
                const status = typeof d.status === 'string' && d.status.length > 0 ? ` • статус ${d.status}` : '';
                return { icon: '✏️', label: `обновляет задачу #${taskNum(d.par)||'?'}${status}`, color: '#38bdf8' };
            },
            'mcp__orchestra__task_list': (d) => {
                const _safeTaskFilter = (value) => typeof value === 'string' && value.length <= 32 && !/[<>\"'`]/.test(value);
                const f = [d.status,d.project,d.assignee]
                    .map((value) => (typeof value === 'string' ? value.trim() : ''))
                    .filter((value) => value && _safeTaskFilter(value))
                    .join(', ');
                return { icon: '📋', label: `читает список задач${f ? ` (${f})` : ''}`, color: '#a78bfa' };
            },
            'mcp__orchestra__task_get': (d) => ({ icon: '📋', label: `читает задачу #${taskNum(d.par)||'?'}`, color: '#a78bfa' }),
            'mcp__orchestra__bg_create': (d) => { const i = _JOB_ICONS[d.type]||'⚙️'; return { icon: i, label: `BG ${d.type||'job'}${d.delay_seconds ? ' '+Math.round(d.delay_seconds/60)+'m' : ''}`, color: '#38bdf8', sub: d.message || d.target || '' }; },
            'mcp__orchestra__bg_list': () => ({ icon: '📊', label: 'BG Jobs', color: '#a78bfa' }),
            'mcp__orchestra__bg_cancel': (d) => ({ icon: '⏹', label: `Cancel ${(d.job_id||'').slice(0,8)}`, color: '#94a3b8' }),
        };
        const isOrchSimple = _orchSimple[rawName];
        if (isOrchSimple) {
            try {
                const d = JSON.parse(body);
                const cfg = isOrchSimple(d);
                header.textContent = `${cfg.icon} ${cfg.label}`;
                header.style.color = cfg.color;
                if (cfg.sub) {
                    const subEl = document.createElement('div');
                    subEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
                    subEl.textContent = cfg.sub;
                    div.appendChild(subEl);
                }
            } catch {}
        }
        const isGlob = rawName === 'Glob';
        if (isGlob) {
            try {
                const d = JSON.parse(body);
                header.textContent = `🔎 Glob: ${d.pattern || '?'}`;
                header.style.color = '#38bdf8';
                if (d.path) {
                    const pathEl = document.createElement('div');
                    pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px';
                    pathEl.textContent = d.path;
                    div.appendChild(pathEl);
                }
            } catch {}
        }
        const isSkill = rawName === 'Skill';
        if (isSkill) {
            try {
                const d = JSON.parse(body);
                header.textContent = `⚡ Skill: ${d.skill || '?'}`;
                header.style.color = '#eab308';
            } catch {}
        }
        const isBashTool = rawName === 'Bash';
        if (isBashTool) {
            try {
                let cmd = body;
                let commandData = {};
                try {
                    commandData = JSON.parse(body);
                    cmd = commandData.command || body;
                } catch {}
                cmd = cmd.replace(/^\/(?:usr\/)?bin\/(?:bash|zsh) -lc /, '').replace(/^["']|["']$/g, '');
                const cmdLines = cmd.split('\n');
                const PREVIEW_LINES = 3;
                const previewCmd = cmdLines.slice(0, PREVIEW_LINES).join('\n');
                const restCmd = cmdLines.slice(PREVIEW_LINES).join('\n');
                const hasMoreCmd = cmdLines.length > PREVIEW_LINES;
                const cmdWrap = document.createElement('div');
                cmdWrap.className = 'diff-view';
                cmdWrap.style.marginTop = '4px';
                const previewPre = document.createElement('pre');
                previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none';
                previewPre.textContent = previewCmd;
                cmdWrap.appendChild(previewPre);
                if (hasMoreCmd) {
                    const restPre = document.createElement('pre');
                    restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;display:none';
                    restPre.dataset.role = 'bash-rest';
                    restPre.textContent = restCmd;
                    cmdWrap.appendChild(restPre);
                    const hint = document.createElement('div');
                    hint.className = 'diff-file';
                    hint.dataset.role = 'bash-hint';
                    hint.dataset.count = cmdLines.length - PREVIEW_LINES;
                    hint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                    hint.textContent = `▼ ${cmdLines.length - PREVIEW_LINES} more lines`;
                    cmdWrap.appendChild(hint);
                }
                div.appendChild(cmdWrap);
                const actions = commandData.command_actions || [];
                if (actions.length) {
                    const actionRow = document.createElement('div');
                    actionRow.className = 'codex-command-actions';
                    for (const action of actions) {
                        const pill = document.createElement('span');
                        pill.className = `codex-command-action codex-command-${action.type || 'unknown'}`;
                        const actionIcon = action.type === 'read' ? '📖' :
                            action.type === 'search' ? '🔎' :
                            action.type === 'listFiles' ? '🗂' : '⌁';
                        const detail = action.query || action.path || action.name || '';
                        pill.textContent = `${actionIcon} ${action.type || 'command'}${detail ? ': ' + detail : ''}`;
                        pill.title = action.command || '';
                        actionRow.appendChild(pill);
                    }
                    div.appendChild(actionRow);
                }
                div.dataset.isBash = '1';
                div.style.cursor = 'pointer';
                let bashExpanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    bashExpanded = !bashExpanded;
                    const restPre = cmdWrap.querySelector('[data-role="bash-rest"]');
                    const hint = cmdWrap.querySelector('[data-role="bash-hint"]');
                    if (restPre) restPre.style.display = bashExpanded ? 'block' : 'none';
                    if (hint) hint.textContent = bashExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                    const resWrap = div.querySelector('[data-role="bash-result"]');
                    const resHint = div.querySelector('[data-role="bash-result-hint"]');
                    if (resWrap) resWrap.style.display = bashExpanded ? 'block' : 'none';
                    if (resHint) resHint.textContent = bashExpanded ? '▲ collapse result' : `▼ ${resHint.dataset.count} more lines`;
                });
            } catch {}
        }
        const isFileChangeTool = rawName === 'FileChange';
        if (isFileChangeTool) {
            const patch = renderCodexFileChange(body);
            header.textContent = '📝 Applying file changes';
            header.style.color = '#f59e0b';
            if (patch) div.appendChild(patch);
            div.dataset.isFileChange = '1';
        }
        const isViewImageTool = rawName === 'ViewImage';
        if (isViewImageTool) {
            try {
                const data = JSON.parse(body);
                const path = data.file_path || '';
                header.textContent = `🖼 Viewing ${(path.split('/').pop() || 'image')}`;
                const img = document.createElement('img');
                img.src = `/api/files/raw?path=${encodeURIComponent(path)}&t=${Date.now()}`;
                img.loading = 'eager';
                img.className = 'codex-tool-image';
                img.alt = path.split('/').pop() || 'Viewed image';
                img.addEventListener('error', () => {
                    img.classList.add('codex-tool-image-error');
                    img.alt = 'Image unavailable';
                });
                img.addEventListener('load', () => {
                    img.classList.remove('codex-tool-image-error');
                });
                img.addEventListener('click', () => openImageLightbox(img.src));
                div.appendChild(img);
            } catch {}
        }
        const isImageGenerationTool = rawName === 'ImageGeneration';
        if (isImageGenerationTool) {
            header.textContent = '🎨 Generating image';
            header.style.color = '#f472b6';
        }
        const isSleepTool = rawName === 'Sleep';
        if (isSleepTool) {
            try {
                const data = JSON.parse(body);
                header.textContent = `⏱ Waiting ${((data.duration_ms || 0) / 1000).toFixed(1)}s`;
                header.style.color = '#94a3b8';
            } catch {}
        }
        const isTodoWrite = rawName === 'TodoWrite';
        if (isTodoWrite) {
            try {
                const d = JSON.parse(body);
                const todos = Array.isArray(d.todos) ? d.todos : [];
                const done = todos.filter(t => t.status === 'completed').length;
                header.textContent = `📝 Todos ${done}/${todos.length}`;
                header.style.color = '#38bdf8';
                const listEl = document.createElement('div');
                listEl.className = 'text-xs mt-1';
                listEl.style.cssText = 'display:flex;flex-direction:column;gap:2px';
                const _todoMark = (st) => st === 'completed' ? ['✅', '#4ade80', 'line-through']
                    : st === 'in_progress' ? ['◔', '#fbbf24', 'none'] : ['☐', '#64748b', 'none'];
                for (const t of todos) {
                    const [mark, color, deco] = _todoMark(t.status);
                    const row = document.createElement('div');
                    row.style.cssText = 'display:flex;gap:6px;align-items:baseline;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                    const m = document.createElement('span');
                    m.textContent = mark;
                    m.style.minWidth = '1.2em';
                    const c = document.createElement('span');
                    c.textContent = t.content || '';
                    c.style.cssText = `color:${color};text-decoration:${deco}`;
                    row.append(m, c);
                    listEl.appendChild(row);
                }
                if (todos.length) div.appendChild(listEl);
                div.dataset.isEdit = '1';   // swallow the raw JSON result
            } catch {}
        }
        const isReviewTool = rawName === 'Review';
        if (isReviewTool) {
            try {
                const d = JSON.parse(body);
                const focus = String(d.focus || '').trim();
                header.textContent = `🧠 Review${focus ? ': ' + focus.slice(0, 100) : ''}`;
                header.title = focus;
                header.style.color = '#a78bfa';
            } catch {}
        }
        const isAgentTool = rawName === 'Agent';
        if (isAgentTool) {
            try {
                const d = JSON.parse(body);
                const desc = d.description || '';
                const prompt = d.prompt || '';
                header.textContent = '🤖 Agent';
                header.style.color = '#a78bfa';
                if (desc) {
                    const descEl = document.createElement('div');
                    descEl.className = 'text-xs font-medium mb-1';
                    descEl.style.color = '#c7d2fe';
                    descEl.textContent = desc;
                    div.appendChild(descEl);
                }
                if (prompt) {
                    const promptLines = prompt.split('\n');
                    const PREVIEW_LINES = 2;
                    const previewPrompt = promptLines.slice(0, PREVIEW_LINES).join('\n');
                    const restPrompt = promptLines.slice(PREVIEW_LINES).join('\n');
                    const hasMorePrompt = promptLines.length > PREVIEW_LINES;
                    const promptWrap = document.createElement('div');
                    promptWrap.className = 'diff-view';
                    promptWrap.style.marginTop = '4px';
                    const previewPre = document.createElement('pre');
                    previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;white-space:pre-wrap;word-break:break-word';
                    previewPre.textContent = previewPrompt;
                    promptWrap.appendChild(previewPre);
                    if (hasMorePrompt) {
                        const restPre = document.createElement('pre');
                        restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;white-space:pre-wrap;word-break:break-word;display:none';
                        restPre.dataset.role = 'agent-rest';
                        restPre.textContent = restPrompt;
                        promptWrap.appendChild(restPre);
                        const hint = document.createElement('div');
                        hint.className = 'diff-file';
                        hint.dataset.role = 'agent-hint';
                        hint.dataset.count = promptLines.length - PREVIEW_LINES;
                        hint.style.cssText = 'cursor:pointer;text-align:center;color:#a78bfa;font-size:10px';
                        hint.textContent = `▼ ${promptLines.length - PREVIEW_LINES} more lines`;
                        promptWrap.appendChild(hint);
                    }
                    div.appendChild(promptWrap);
                    div.style.cursor = 'pointer';
                    let agentExpanded = false;
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        agentExpanded = !agentExpanded;
                        const restPre = promptWrap.querySelector('[data-role="agent-rest"]');
                        const hint = promptWrap.querySelector('[data-role="agent-hint"]');
                        if (restPre) restPre.style.display = agentExpanded ? 'block' : 'none';
                        if (hint) hint.textContent = agentExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                    });
                }
                div.dataset.isEdit = '1';
            } catch {}
        }
        const isGrepTool = rawName === 'Grep';
        if (isGrepTool) {
            try {
                const d = JSON.parse(body);
                const grepPath = d.path || d.glob || '';
                const shortGrepPath = grepPath.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || grepPath;
                header.textContent = `🔎 Grep: ${d.pattern || ''}${shortGrepPath ? ' in ' + shortGrepPath : ''}`;
                header.style.color = '#38bdf8';
                div.dataset.isGrep = '1';
                div.dataset.grepPattern = d.pattern || '';
                div.dataset.grepPath = grepPath;
            } catch {}
        }
        const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
        const isReadTool = rawName === 'Read';
        if (isReadTool) {
            try { const d = JSON.parse(body); if (d.file_path) div.dataset.filePath = d.file_path; } catch {}
        }
        const diffEl = isEditTool ? renderEditDiff(body) : null;
        const readEl = isReadTool ? renderReadView(body) : null;

        if (readEl) {
            div.appendChild(readEl);
            div.dataset.isRead = '1';
            div.style.cursor = 'pointer';
            div.addEventListener('click', () => {
                const restEl = readEl.querySelector('[data-role="read-rest"]');
                const moreEl = readEl.querySelector('[data-role="read-more"]');
                if (restEl && moreEl) {
                    const showing = restEl.style.display !== 'none';
                    restEl.style.display = showing ? 'none' : 'block';
                    moreEl.textContent = showing ? `▼ ${moreEl.dataset.count} more lines` : `▲ collapse`;
                }
            });
        } else if (diffEl) {
            div.appendChild(diffEl);
            div.dataset.isEdit = '1';
            div.style.cursor = 'pointer';
            div.addEventListener('click', () => {
                const restEl = diffEl.querySelector('[style*="display"]');
                const moreEl = diffEl.querySelector('.diff-file[style*="cursor"]');
                if (restEl && moreEl) {
                    const showing = restEl.style.display !== 'none';
                    restEl.style.display = showing ? 'none' : 'block';
                    const restCount = moreEl.dataset.count || '0';
                    moreEl.textContent = showing ? `▼ ${restCount} more lines` : `▲ collapse`;
                }
            });
        } else if (!isSendMsg && !isNotify && !isGrepTool && !isBashTool &&
                   !isAgentTool && !isSpawnWorker && !isWebSearchCall &&
                   !isToolSearchCall && !isBugReport && !isWebFetch &&
                   !isSendFile && !isOrchSimple && !isGlob && !isSkill &&
                   !isFileChangeTool && !isViewImageTool &&
                   !isImageGenerationTool && !isSleepTool && !isTodoWrite && !isReviewTool) {
            let _inputJsonRendered = false;
            if (body) {
                try {
                    const _inputParsed = JSON.parse(body);
                    if (_inputParsed && typeof _inputParsed === 'object' && !Array.isArray(_inputParsed)) {
                        const gridWrap = document.createElement('div');
                        gridWrap.className = 'text-xs opacity-80 tool-body';
                        gridWrap.style.cssText = 'margin-top:2px';
                        _renderJsonGrid(_inputParsed, gridWrap);
                        div.appendChild(gridWrap);
                        _inputJsonRendered = true;
                    }
                } catch {}
            }
            if (!_inputJsonRendered && body) {
                const toolPreview = body.length > 200 ? body.slice(0, 200) + '…' : body;
                const toolFull = body.length > 200 ? body : null;
                const bodyEl = document.createElement('div');
                bodyEl.style.whiteSpace = 'pre-wrap';
                bodyEl.className = 'text-xs opacity-70 tool-body';
                bodyEl.textContent = toolPreview;
                bodyEl.dataset.preview = toolPreview;
                if (toolFull) bodyEl.dataset.full = toolFull;
                div.appendChild(bodyEl);
                if (toolFull) {
                    const remaining = body.split('\n').length - toolPreview.split('\n').length;
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.color = '#38bdf8';
                    hint.textContent = `▼ ${remaining} more lines`;
                    hint.dataset.role = 'expand-hint';
                    div.appendChild(hint);
                }
                let expanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    expanded = !expanded;
                    const tb = div.querySelector('.tool-body');
                    if (tb && tb.dataset.full) tb.textContent = expanded ? tb.dataset.full : tb.dataset.preview;
                    const hint = div.querySelector('[data-role="expand-hint"]');
                    if (hint) hint.style.display = expanded ? 'none' : 'block';
                    const rb = div.querySelector('.result-body');
                    if (rb && rb.dataset.full) rb.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? rb.dataset.full : rb.dataset.preview, {ADD_ATTR: ['target']});
                });
            }
        }
        if (codexItemId) {
            decorateCodexToolCard(div, div.querySelector('.flex.items-center'), isOrch ? 'orchestra' : 'native');
            _flushCodexToolUpdates(div, codexItemId);
        }
    }
    else if (type === 'tool_result') {
        const chat = $('#chat');
        const resultToolId = payload?.tool_use_id || '';
        const lastTool = _toolForResult(chat, payload, anchor, false);
        if (!lastTool) {
            div.dataset.unmatchedToolResult = '1';
            if (resultToolId) {
                div.dataset.orphanResultFor = resultToolId;
                div._orphanResult = {content, ts, payload};
            }
            const warning = document.createElement('div');
            warning.className = 'text-amber-400 text-xs font-medium mb-1';
            warning.textContent = `⚠️ Результат без вызова${resultToolId ? ` · ${resultToolId}` : ''}`;
            div.appendChild(warning);
        }
        if (lastTool) {
            const liveOutput = lastTool.querySelector('.codex-live-output');
            if (liveOutput) liveOutput.remove();
            completeCodexToolCard(lastTool);
            if (lastTool.dataset.isFileChange) {
                let data = {};
                try { data = JSON.parse(content); } catch {}
                const header = lastTool.querySelector('.flex.items-center');
                const ok = !data.status || data.status === 'completed';
                if (header) {
                    header.textContent = `${ok ? '✅' : '❌'} File changes ${ok ? 'applied' : 'failed'}${data.files != null ? ` · ${data.files} file${data.files === 1 ? '' : 's'}` : ''}`;
                    header.style.color = ok ? '#4ade80' : '#f87171';
                }
                delete lastTool.dataset.lastTool;
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'ImageGeneration') {
                let data = {};
                try { data = JSON.parse(content); } catch {}
                delete lastTool.dataset.lastTool;
                addTimestamp(lastTool, ts);
                if (payload?.trunc && payload?.id) {
                    void _restoreImageGenerationResult(lastTool, payload);
                    return;
                }
                _completeImageGenerationTool(lastTool, data);
                return;
            }
            if (lastTool.dataset.toolRawName === 'ViewImage') {
                const header = lastTool.querySelector('.flex.items-center');
                if (header) header.style.color = '#7dd3fc';
                const img = lastTool.querySelector('.codex-tool-image');
                if (img && (!img.complete || !img.naturalWidth)) {
                    img.src = img.src.replace(/([?&])t=\d+/, `$1t=${Date.now()}`);
                }
                delete lastTool.dataset.lastTool;
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'Sleep') {
                const header = lastTool.querySelector('.flex.items-center');
                if (header) {
                    header.textContent = '✓ Wait completed';
                    header.style.color = '#64748b';
                }
                delete lastTool.dataset.lastTool;
                addTimestamp(lastTool, ts);
                return;
            }
        }
        if (_isBase64Image) {
            const inlineSrc = _toolResultImageSrc(content);
            if (lastTool) {
                delete lastTool.dataset.lastTool;
                const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
                if (skeleton) skeleton.remove();
            }
            const target = lastTool || div;
            const origPath = lastTool && lastTool.dataset.filePath;
            if (inlineSrc || origPath || payload?.id) {
                const img = document.createElement('img');
                img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;margin-top:6px;cursor:pointer';
                img.style.display = 'none';
                img.addEventListener('click', () => _showImageOverlay(img.src));
                target.appendChild(img);
                // Use original file via API if Read tool has file_path — SDK compresses base64
                _loadToolResultImage(img, origPath, inlineSrc, payload).then(ok => {
                    if (ok) img.style.display = '';
                    else img.replaceWith(Object.assign(document.createElement('div'), {textContent: '🖼 Image unavailable'}));
                });
            } else {
                const placeholder = document.createElement('div');
                placeholder.className = 'text-xs';
                placeholder.style.cssText = 'color:#64748b;margin-top:4px';
                placeholder.textContent = '🖼 [Image result]';
                target.appendChild(placeholder);
            }
            addTimestamp(target, ts);
            if (!lastTool) {
                const wasAtBottom = _chatAtBottom(chat);
                _insert(div);
                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            }
            return;
        }
        const toolErrorMatch = content.match(/<tool_use_error>([\s\S]*?)<\/tool_use_error>/);
        if (toolErrorMatch) {
            const errMsg = toolErrorMatch[1].trim();
            const errDiv = document.createElement('div');
            errDiv.className = 'px-3 py-2 rounded-lg text-xs text-red-400 bg-red-950/30 border border-red-900/50';
            errDiv.textContent = '⚠️ ' + errMsg;
            if (lastTool) {
                completeCodexToolCard(lastTool, false);
                delete lastTool.dataset.lastTool;
                const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
                if (skeleton) skeleton.remove();
                lastTool.appendChild(errDiv);
                addTimestamp(lastTool, ts);
            } else {
                div.appendChild(errDiv);
                addTimestamp(div, ts);
                const wasAtBottom = _chatAtBottom(chat);
                _insert(div);
                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            }
            return;
        }
        const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
        // Strip raw JSON link arrays from WebSearch results (shown as ugly JSON at top)
        const stripped = clean.replace(/^(Links:\s*\[.*?\}\]\s*\n?)+/gms, '');
        const escaped = _escHtml(stripped);
        // Render markdown links [text](url) first, then bare URLs
        const mdLinked = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
        const linked = mdLinked.replace(/((?<!href="|">)https?:\/\/[^\s\])"&<]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
        const _resultLines = linked.split('\n');
        const _RESULT_PREVIEW = 5;
        const _hasMore = _resultLines.length > _RESULT_PREVIEW;
        const preview = _hasMore ? _resultLines.slice(0, _RESULT_PREVIEW).join('\n') : linked;
        const full = _hasMore ? linked : null;

        if (lastTool) {
            if (lastTool.dataset.isCodexWebSearch) {
                // Codex шлёт результатом ту же структуру с action/queries — ею обновляем шапку.
                // Встроенный WebSearch и MCP-поиск отдают ТЕКСТ: spec=null, и его надо
                // отрисовать обычным телом результата, а не проглотить ранним return.
                const resultSpec = codexWebSearchSpec(content);
                if (resultSpec) {
                    updateCodexWebSearchActivity(lastTool, resultSpec);
                    delete lastTool.dataset.lastTool;
                    addTimestamp(lastTool, ts);
                    return;
                }
            }
            if (lastTool.dataset.isSpawnWorker) {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr) setCodexToolTitle(hdr, `${lastTool.dataset.workerName || 'Worker'} spawned`);
                delete lastTool.dataset.lastTool;
                addTimestamp(lastTool, ts);
                return;
            }
            delete lastTool.dataset.lastTool;
            if (lastTool.dataset.isEdit) {
                addTimestamp(lastTool, ts);
                return;
            }
            const isToolSearch = lastTool.dataset.toolRawName === 'ToolSearch';
            if (isToolSearch) {
                let toolName = '';
                try { const d = JSON.parse(content); toolName = d.tool_name || ''; } catch {}
                if (!toolName) { const m = content.match(/tool_name['":\s]+(\w+)/); toolName = m ? m[1] : ''; }
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr && toolName) hdr.textContent = `✅ Loaded: ${toolName}`;
                else if (hdr) hdr.textContent = '✅ Tool loaded';
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__report_bug') {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr) { hdr.textContent = '✅ Bug reported'; hdr.style.color = '#22c55e'; }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__send_file') {
                const hdr = lastTool.querySelector('.flex.items-center');
                const hasError = content.includes('error') || content.includes('Error') || content.includes('failed');
                if (hdr) {
                    hdr.textContent = hasError ? '❌ Send failed' : '✅ Sent to TG';
                    hdr.style.color = hasError ? '#ef4444' : '#22c55e';
                }
                const fp = lastTool.dataset.filePath;
                if (!hasError && fp) {
                    // Image thumbnail above the buttons — click opens full-size lightbox
                    if (/\.(png|jpe?g|gif|webp|svg)$/i.test(fp) && !lastTool.querySelector('.sf-thumb')) {
                        const rawUrl = `/api/files/raw?path=${encodeURIComponent(fp)}&t=${Date.now()}`;
                        const img = document.createElement('img');
                        img.className = 'sf-thumb';
                        img.src = rawUrl;
                        img.loading = 'lazy';
                        img.style.cssText = 'display:block;margin-top:6px;max-height:200px;max-width:100%;border-radius:8px;cursor:pointer;border:1px solid rgba(99,102,241,0.2)';
                        img.addEventListener('click', () => openImageLightbox(rawUrl));
                        img.onerror = () => img.remove();  // broken/missing file → no ugly broken-icon
                        lastTool.appendChild(img);
                    }
                    const btnRow = document.createElement('div');
                    btnRow.style.cssText = 'margin-top:4px;display:flex;gap:6px;flex-wrap:wrap';
                    const _fileBtn = (label, onClick) => {
                        const b = document.createElement('button');
                        b.textContent = label;
                        b.style.cssText = 'padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid rgba(99,102,241,0.3);background:rgba(15,23,42,0.95);color:#a5b4fc;cursor:pointer;transition:all 0.15s;backdrop-filter:blur(8px)';
                        b.onmouseenter = () => { b.style.borderColor = 'rgba(99,102,241,0.6)'; b.style.color = '#c7d2fe'; };
                        b.onmouseleave = () => { b.style.borderColor = 'rgba(99,102,241,0.3)'; b.style.color = '#a5b4fc'; };
                        b.onclick = onClick;
                        return b;
                    };
                    btnRow.appendChild(_fileBtn('📥 Download', () => {
                        window.open(`/api/files/raw?path=${encodeURIComponent(fp)}&download=1`, '_blank');
                    }));
                    if (/\.html?$/i.test(fp)) {
                        btnRow.appendChild(_fileBtn('👁 Preview', () => {
                            window.open(`/api/files/raw?path=${encodeURIComponent(fp)}`, '_blank');
                        }));
                    }
                    lastTool.appendChild(btnRow);
                }
                addTimestamp(lastTool, ts);
                return;
            }
            const _tmTools = ['mcp__orchestra__task_create','mcp__orchestra__task_update','mcp__orchestra__task_list','mcp__orchestra__task_get','mcp__orchestra__bg_list','mcp__orchestra__get_worker_info'];
            if (_tmTools.includes(lastTool.dataset.toolRawName)) {
                const hdr = lastTool.querySelector('.flex.items-center');
                let parsed = null;
                try { parsed = JSON.parse(content); } catch {}
                const tn = lastTool.dataset.toolRawName;
                if (!parsed || parsed.error) {
                    if (hdr) { hdr.textContent = `❌ ${parsed?.error || clean.slice(0, 80)}`; hdr.style.color = '#ef4444'; }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (tn === 'mcp__orchestra__task_create' || tn === 'mcp__orchestra__task_get') {
                    const taskNumber = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
                    if (hdr) {
                        if (tn.includes('create')) {
                            hdr.textContent = `✅ создаёт задачу «${parsed.title || '?'}»`;
                        } else {
                            hdr.textContent = `📋 читает задачу #${taskNumber}`;
                        }
                        hdr.style.color = tn.includes('create') ? '#22c55e' : '#a78bfa';
                    }
                    const taskBody = document.createElement('div');
                    taskBody.style.marginTop = '4px';
                    taskBody.innerHTML = _taskCardBodyHtml(parsed);
                    lastTool.appendChild(taskBody);
                    const sys = [];
                    if (parsed.yougile_id || parsed.yougile_task_id) sys.push(`yougile: ${parsed.yougile_id || parsed.yougile_task_id}`);
                    if (parsed.sync_revision) sys.push(`rev: ${parsed.sync_revision}`);
                    if (sys.length > 0) {
                        const sEl = document.createElement('div');
                        sEl.style.cssText = 'margin-top:4px;font-size:9px;color:#475569;font-family:monospace';
                        sEl.textContent = sys.join(' · ');
                        lastTool.appendChild(sEl);
                    }
                } else if (tn === 'mcp__orchestra__task_update') {
                    const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                    const changes = [];
                    if (parsed.old_status && parsed.new_status && parsed.old_status !== parsed.new_status) changes.push(`status ${parsed.old_status}→${parsed.new_status}`);
                    if (parsed.updated) {
                        for (const f of parsed.updated) {
                            if (f === 'status') continue;
                            if (f === 'price' && parsed.price_rub != null) changes.push(`price ${_kr(parsed.price_rub)} ${CUR}`);
                            else if (f === 'assignee' && parsed.assignee != null) changes.push(`assignee→${parsed.assignee || '—'}`);
                            else if (f === 'title') changes.push('title');
                            else if (f === 'description') changes.push('description');
                            else changes.push(f);
                        }
                    }
                    const parNum = (parsed.par || '?').replace(/^[A-Z]+-/, '');
                    const titleStr = parsed.title ? ` "${parsed.title.slice(0,40)}"` : '';
                    const status = parsed.new_status || parsed.status;
                    const statusLabel = typeof status === 'string' && status ? ` • статус ${status}` : '';
                    if (hdr) {
                        hdr.textContent = `✏️ обновляет задачу #${parNum}${titleStr}${statusLabel}`;
                        hdr.style.color = '#22c55e';
                    }
                    if (parsed.old_title && parsed.title && parsed.old_title !== parsed.title) {
                        const titleDiff = document.createElement('div');
                        titleDiff.style.cssText = 'margin-top:3px;font-size:10px';
                        titleDiff.innerHTML = `<span style="color:#64748b;text-decoration:line-through">${DOMPurify.sanitize(parsed.old_title.slice(0,60))}</span> → <span style="color:#e2e8f0">${DOMPurify.sanitize(parsed.title.slice(0,60))}</span>`;
                        lastTool.appendChild(titleDiff);
                    }
                    if (parsed.description && (parsed.updated || []).includes('description')) {
                        const descWrap = document.createElement('div');
                        descWrap.style.cssText = 'margin-top:4px';
                        if (parsed.old_description) {
                            const oldEl = document.createElement('div');
                            oldEl.style.cssText = 'font-size:10px;color:#64748b;text-decoration:line-through;max-height:40px;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                            oldEl.textContent = parsed.old_description.split('\n').slice(0,3).join('\n');
                            descWrap.appendChild(oldEl);
                        }
                        const newEl = document.createElement('div');
                        newEl.style.cssText = 'font-size:10px;color:#86efac;max-height:40px;overflow-y:hidden;overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere;margin-top:2px';
                        newEl.textContent = parsed.description.split('\n').slice(0,3).join('\n') + (parsed.description.split('\n').length > 3 ? '…' : '');
                        descWrap.appendChild(newEl);
                        lastTool.appendChild(descWrap);
                        if (parsed.description.split('\n').length > 3) {
                            lastTool.style.cursor = 'pointer';
                            let _duExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _duExp = !_duExp;
                                newEl.textContent = _duExp ? parsed.description : parsed.description.split('\n').slice(0,3).join('\n') + '…';
                                newEl.style.maxHeight = _duExp ? 'none' : '40px';
                                newEl.style.overflowY = _duExp ? 'visible' : 'hidden';
                            });
                        }
                    }
                    const detail = document.createElement('div');
                    detail.style.cssText = 'margin-top:3px;font-size:10px;color:#64748b;display:flex;gap:8px;flex-wrap:wrap';
                    if (parsed.price_rub > 0) detail.innerHTML += `<span>Price: <b style="color:#eab308">${_kr(parsed.price_rub)} ${CUR}</b></span>`;
                    if (detail.innerHTML) lastTool.appendChild(detail);
                } else if (tn === 'mcp__orchestra__task_list') {
                    const tasks = parsed.tasks || [];
                    const resultMeta = document.createElement('div');
                    resultMeta.className = 'text-xs mt-1';
                    resultMeta.style.color = '#64748b';
                    resultMeta.textContent = `Результат: ${tasks.length}`;
                    lastTool.appendChild(resultMeta);
                    if (tasks.length > 0 && parsed.detailed) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:6px';
                        const PREVIEW = 3;
                        for (const [i, t] of tasks.entries()) {
                            const card = document.createElement('div');
                            card.style.cssText = `padding:6px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${t.status==='done'||t.status==='paid'?'#22c55e':t.status==='in_progress'?'#38bdf8':'#334155'}${i >= PREVIEW ? ';display:none' : ''}`;
                            card.dataset.taskRow = '1';
                            let h = `<div style="font-size:11px;color:#e2e8f0;font-weight:600">${DOMPurify.sanitize(t.par)}: ${DOMPurify.sanitize(t.title)}</div>`;
                            h += _taskCardBodyHtml(t);
                            card.innerHTML = h;
                            container.appendChild(card);
                        }
                        lastTool.appendChild(container);
                        if (tasks.length > PREVIEW) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${tasks.length - PREVIEW} more`;
                            lastTool.appendChild(hint);
                            let _tlExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _tlExp = !_tlExp;
                                container.querySelectorAll('[data-task-row]').forEach((r, i) => { if (i >= PREVIEW) r.style.display = _tlExp ? 'block' : 'none'; });
                                hint.textContent = _tlExp ? '▲ collapse' : `▼ ${tasks.length - PREVIEW} more`;
                            });
                        }
                    } else if (tasks.length > 0) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                        const PREVIEW = 4;
                        for (const [i, t] of tasks.entries()) {
                            const row = document.createElement('div');
                            row.style.cssText = `font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:6px;align-items:center${i >= PREVIEW ? ';display:none' : ''}`;
                            row.dataset.taskRow = '1';
                            const priceStr = t.price && t.price !== '0' ? `<span style="color:#eab308">${t.price}</span>` : '';
                            row.innerHTML = `<span style="color:#64748b;font-family:monospace;min-width:32px">#${t.par}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(t.title)}</span><span style="color:#64748b">${t.status}</span>${priceStr}`;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                        if (tasks.length > PREVIEW) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${tasks.length - PREVIEW} more`;
                            lastTool.appendChild(hint);
                            let _tlExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _tlExp = !_tlExp;
                                container.querySelectorAll('[data-task-row]').forEach((r, i) => { if (i >= PREVIEW) r.style.display = _tlExp ? 'flex' : 'none'; });
                                hint.textContent = _tlExp ? '▲ collapse' : `▼ ${tasks.length - PREVIEW} more`;
                            });
                        }
                    }
                } else if (tn === 'mcp__orchestra__bg_list') {
                    const jobs = Array.isArray(parsed) ? parsed : (parsed.jobs || []);
                    if (hdr) hdr.textContent = `📊 ${jobs.length} jobs`;
                    if (jobs.length > 0) {
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                        for (const j of jobs.slice(0, 8)) {
                            const icon = _JOB_ICONS[j.type] || '⚙️';
                            const st = _JOB_STATUS[j.status] || '⚪';
                            const row = document.createElement('div');
                            row.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:4px;align-items:center';
                            row.innerHTML = `<span>${icon}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(j.target_name || '')} ${DOMPurify.sanitize((j.message||'').slice(0,30))}</span><span>${st}</span>`;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                    }
                } else if (tn === 'mcp__orchestra__get_worker_info') {
                    const stColor = _STATUS_COLOR[parsed.status] || '#94a3b8';
                    const modelShort = _modelLabel(parsed.model);
                    if (hdr) {
                        hdr.innerHTML = `🤖 <b>${DOMPurify.sanitize(parsed.name || '?')}</b> <span style="font-size:10px;color:#64748b">(${DOMPurify.sanitize(modelShort)})</span> — <span style="color:${stColor}">${parsed.status || '?'}</span>`;
                    }
                    const grid = document.createElement('div');
                    grid.style.cssText = 'margin-top:4px;display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px';
                    const _row = (label, val, color) => { if (val != null && val !== '') grid.innerHTML += `<span style="color:#64748b">${label}</span><span style="color:${color||'#cbd5e1'}">${DOMPurify.sanitize(String(val))}</span>`; };
                    _row('Role', parsed.is_orchestrator ? '🎯 orchestrator' : '⚙️ worker');
                    _row('Branch', parsed.branch, '#818cf8');
                    const ctxPct = parsed.context_pct || 0;
                    const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                    _row('Context', `${ctxPct}%`, ctxColor);
                    _row('Cost', `${MODEL_COST_CURRENCY}${parsed.cost_usd ?? 0}`, '#22c55e');
                    if (parsed.task_id) _row('Task', `#${parsed.task_id}`, '#a78bfa');
                    if (parsed.total_turns) _row('Turns', parsed.total_turns);
                    if (parsed.total_tool_calls) _row('Tool calls', parsed.total_tool_calls);
                    if (parsed.total_input_tokens || parsed.total_output_tokens) _row('Tokens', `${(parsed.total_input_tokens||0).toLocaleString()} in / ${(parsed.total_output_tokens||0).toLocaleString()} out`);
                    lastTool.appendChild(grid);
                    if (parsed.description) {
                        const descEl = document.createElement('div');
                        descEl.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8;font-style:italic;max-height:40px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere';
                        descEl.textContent = parsed.description;
                        lastTool.appendChild(descEl);
                        if (parsed.description.length > 120) {
                            lastTool.style.cursor = 'pointer';
                            let _wiExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _wiExp = !_wiExp;
                                descEl.style.maxHeight = _wiExp ? 'none' : '40px';
                                descEl.style.overflowY = _wiExp ? 'visible' : 'hidden';
                            });
                        }
                    }
                }
                if (tn.startsWith('mcp__orchestra__task_')) {
                    _appendToolTechnicalDetails(lastTool, content);
                }
                addTimestamp(lastTool, ts);
                // Панель задач обновляется на ЖИВОМ вызове инструмента. При отрисовке
                // истории те же строки — это прошлое, и каждая из них дёргала бы полную
                // перезагрузку панели: замер по живому дашборду — 8 пар запросов
                if (!_replayingHistory
                    && ['mcp__orchestra__task_create','mcp__orchestra__task_update'].includes(tn)) loadTasks();
                return;
            }
            const _orchSimpleResults = {
                'mcp__orchestra__kill_worker': (c) => { const m = c.match(/Worker '(.+?)' stopped/); return m ? { text: `💀 ${m[1]} killed`, color: '#22c55e' } : null; },
                'mcp__orchestra__stop_worker': (c) => { const m = c.match(/Worker '(.+?)' stopped|stopped.*'(.+?)'/i); const n = m?.[1]||m?.[2]; return n ? { text: `⏸️ ${n} stopped`, color: '#22c55e' } : null; },
                'mcp__orchestra__rename_worker': (c) => { const m = c.match(/Worker '(.+?)' renamed to '(.+?)'/); return m ? { text: `✏️ ${m[1]} → ${m[2]}`, color: '#22c55e' } : null; },
                'mcp__orchestra__change_worker_model': (c) => { const m = c.match(/model.*changed|'(.+?)'/i); return { text: '✅ Model changed', color: '#22c55e' }; },
                'mcp__orchestra__update_worker_description': (c) => { const m = c.match(/Description updated for '(.+?)'/); return m ? { text: `✏️ ${m[1]} — description updated`, color: '#22c55e' } : { text: '✅ description updated', color: '#22c55e' }; },
                'mcp__orchestra__merge_worker': (c) => { const m = c.match(/(\d+) commits? merged|Merged/i); return m ? { text: `🔀 Merged${m[1] ? ' ('+m[1]+' commits)' : ''}`, color: '#22c55e' } : null; },
                'mcp__orchestra__send_message': (c) => { const m = c.match(/sent to '(.+?)'/i); return m ? { text: `✅ → ${m[1]}`, color: '#22c55e' } : c.includes('fail') || c.includes('error') || c.includes('Error') ? { text: `❌ ${c.substring(0, 60)}`, color: '#ef4444' } : { text: '✅ Sent', color: '#22c55e' }; },
                'mcp__orchestra__compact_worker': null,
                'mcp__orchestra__list_agents': null,
                'mcp__orchestra__list_orchestrators': null,
                'mcp__orchestra__get_worker_logs': null,
                'mcp__orchestra__bg_create': (c) => { const m = c.match(/Background job created: (\S+)/); return m ? { text: `✅ Job ${m[1].slice(0,12)}`, color: '#22c55e' } : c.includes('rror') ? null : { text: '✅ Job created', color: '#22c55e' }; },
                'mcp__orchestra__bg_cancel': (c) => { const m = c.match(/Job (\S+) cancelled/); return m ? { text: `⏹ ${m[1].slice(0,12)} cancelled`, color: '#94a3b8' } : c.includes('rror') ? null : { text: '⏹ Cancelled', color: '#94a3b8' }; },
            };
            const _orchResultCfg = _orchSimpleResults[lastTool.dataset.toolRawName];
            if (_orchResultCfg !== undefined) {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (typeof _orchResultCfg === 'function') {
                    const hasErr = content.includes('failed') || content.includes('Failed') || content.includes('error') || content.includes('Error');
                    if (hasErr) {
                        const toolAction = lastTool.dataset.toolRawName.split('__').pop().replace(/_/g, ' ');
                        if (hdr) { hdr.textContent = `❌ ${toolAction} failed`; hdr.style.color = '#ef4444'; }
                        const errEl = document.createElement('div');
                        errEl.style.cssText = 'margin-top:4px;font-size:10px;color:#fca5a5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:54px;overflow-y:hidden;overflow-x:hidden';
                        errEl.textContent = clean;
                        lastTool.appendChild(errEl);
                        if (clean.split('\n').length > 3 || clean.length > 200) {
                            lastTool.style.cursor = 'pointer';
                            let _errExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _errExp = !_errExp;
                                errEl.style.maxHeight = _errExp ? 'none' : '54px';
                                errEl.style.overflowY = _errExp ? 'visible' : 'hidden';
                            });
                        }
                    } else {
                        const result = _orchResultCfg(clean);
                        if (hdr) { hdr.textContent = result?.text || '✅ Done'; hdr.style.color = result?.color || '#22c55e'; }
                    }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__compact_worker') {
                    let workerName = '';
                    try { const ci = lastTool.dataset.toolContent.indexOf(':'); const cd = JSON.parse(lastTool.dataset.toolContent.slice(ci+1)); workerName = cd.name || ''; } catch {}
                    const pctMatch = clean.match(/(\d+)%\s*→\s*(\d+)%/);
                    const sumMatch = clean.match(/Summary \((\d+) chars?\):\s*([\s\S]*)/);
                    if (hdr && pctMatch) { hdr.textContent = `🗜 ${workerName ? workerName+': ' : ''}${pctMatch[1]}% → ${pctMatch[2]}%`; hdr.style.color = '#22c55e'; }
                    else if (hdr) { hdr.textContent = `✅ ${workerName ? workerName+' ' : ''}Compacted`; hdr.style.color = '#22c55e'; }
                    if (sumMatch) {
                        const chars = sumMatch[1];
                        const summaryText = sumMatch[2].trim();
                        const charEl = document.createElement('div');
                        charEl.style.cssText = 'font-size:10px;color:#64748b;margin-top:2px';
                        charEl.textContent = `Summary: ${chars} chars`;
                        lastTool.appendChild(charEl);
                        if (summaryText) {
                            const sumEl = document.createElement('div');
                            sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;max-height:48px;overflow-y:hidden;overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                            sumEl.textContent = summaryText;
                            lastTool.appendChild(sumEl);
                            if (summaryText.split('\n').length > 3 || summaryText.length > 200) {
                                lastTool.style.cursor = 'pointer';
                                let _cExp = false;
                                lastTool.addEventListener('click', (e) => {
                                    if (e.target.tagName === 'A') return;
                                    _cExp = !_cExp;
                                    sumEl.style.maxHeight = _cExp ? 'none' : '48px';
                                    sumEl.style.overflowY = _cExp ? 'visible' : 'hidden';
                                });
                            }
                        }
                    }
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__list_agents' || lastTool.dataset.toolRawName === 'mcp__orchestra__list_orchestrators') {
                    const agentSummary = _agentResultSummary(clean);
                    const agentLines = agentSummary?.lines || [];
                    if (agentLines.length > 0) {
                        const PREVIEW_COUNT = 4;
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:4px';
                        for (const [i, line] of agentLines.entries()) {
                            const parts = line.split('|').map(p => p.trim());
                            const nameRaw = parts[0] || '';
                            const status = parts[1] || '';
                            const model = parts[2] || '';
                            let ctxRaw = '', taskId = '', desc = '';
                            for (let pi = 3; pi < parts.length; pi++) {
                                const p = parts[pi];
                                if (p.match(/ctx:\d+%/)) ctxRaw = p;
                                else if (p.startsWith('"')) desc = p.replace(/^"|"$/g, '');
                                else if (p && !p.startsWith('$')) taskId = p;
                            }
                            const nameClean = nameRaw.replace(/\*\*/g, '').replace(/^[^\w]*/, '').trim();
                            const icon = nameRaw.match(/[🎯⚙️🔧]/)?.[0] || '⚙️';
                            const ctxPct = parseInt(ctxRaw.match(/(\d+)%/)?.[1] || '0');
                            const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                            const isRunning = status.includes('running');
                            const row = document.createElement('div');
                            row.style.cssText = `padding:4px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${isRunning ? '#22c55e' : '#334155'}`;
                            if (i >= PREVIEW_COUNT) row.style.display = 'none';
                            row.dataset.agentRow = '1';
                            let h = `<div style="display:flex;align-items:center;gap:6px"><span style="font-size:11px;color:#e2e8f0;font-weight:600">${icon} ${DOMPurify.sanitize(nameClean)}</span><span style="margin-left:auto;font-size:10px;color:${isRunning ? '#22c55e' : '#64748b'}">${DOMPurify.sanitize(status)}</span></div>`;
                            h += `<div style="display:flex;align-items:center;gap:8px;margin-top:2px;font-size:10px;color:#64748b"><span>${DOMPurify.sanitize(model)}</span>`;
                            if (taskId) h += `<span style="color:#a78bfa;font-weight:600">#${DOMPurify.sanitize(taskId.replace(/^[A-Z]+-/, ''))}</span>`;
                            h += `<span style="display:inline-flex;align-items:center;gap:3px">ctx:<span style="color:${ctxColor}">${ctxPct}%</span></span></div>`;
                            if (desc) h += `<div style="font-size:10px;color:#64748b;font-style:italic;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(desc)}</div>`;
                            row.innerHTML = h;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                        if (hdr) {
                            const counts = agentSummary.counts;
                            hdr.textContent = `🎼 Агенты · ${agentLines.length} всего`;
                            hdr.style.color = counts.broken ? '#ef4444' : counts.waiting ? '#f59e0b' : '#a78bfa';
                        }
                        const counts = agentSummary.counts;
                        const summary = document.createElement('div');
                        summary.dataset.agentSummary = '1';
                        summary.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8;display:flex;gap:10px;flex-wrap:wrap';
                        const countText = _agentCountText(counts);
                        summary.innerHTML = `<span style="color:#4ade80">${countText[0]}</span><span style="color:${counts.waiting ? '#f59e0b' : '#64748b'}">${countText[1]}</span><span style="color:${counts.broken ? '#ef4444' : '#64748b'}">${countText[2]}</span>`;
                        lastTool.insertBefore(summary, container);
                        const attention = agentSummary.agents.filter(agent => agent.status === 'waiting' || agent.status === 'broken');
                        if (attention.length) {
                            const attentionEl = document.createElement('div');
                            attentionEl.dataset.agentAttention = '1';
                            attentionEl.style.cssText = 'margin-top:4px;font-size:10px;color:#fbbf24';
                            attentionEl.textContent = `Требуют внимания: ${attention.map(agent => `${agent.name} — ${agent.status}`).join(', ')}`;
                            lastTool.insertBefore(attentionEl, container);
                        }
                        if (agentLines.length > PREVIEW_COUNT) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${agentLines.length - PREVIEW_COUNT} more`;
                            lastTool.appendChild(hint);
                            let _alExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _alExp = !_alExp;
                                container.querySelectorAll('[data-agent-row]').forEach((r, i) => {
                                    if (i >= PREVIEW_COUNT) r.style.display = _alExp ? 'block' : 'none';
                                });
                                hint.textContent = _alExp ? '▲ collapse' : `▼ ${agentLines.length - PREVIEW_COUNT} more`;
                            });
                        }
                        _appendToolTechnicalDetails(lastTool, content);
                        addTimestamp(lastTool, ts);
                        return;
                    }
                }
                if (lastTool.dataset.toolRawName === 'mcp__orchestra__get_worker_logs') {
                    const lines = clean.split('\n').filter(l => l.trim());
                    let workerName = '';
                    try { const ci = lastTool.dataset.toolContent.indexOf(':'); const cd = JSON.parse(lastTool.dataset.toolContent.slice(ci+1)); workerName = cd.name || ''; } catch {}
                    if (hdr) { hdr.textContent = `📋 ${workerName ? workerName+': ' : ''}${lines.length} log entries`; hdr.style.color = '#a78bfa'; }
                    if (lines.length > 0) {
                        const PREVIEW_LOG = 6;
                        const container = document.createElement('div');
                        container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:1px';
                        for (const [i, line] of lines.entries()) {
                            const row = document.createElement('div');
                            row.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:3px;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                            row.dataset.logRow = '1';
                            if (i >= PREVIEW_LOG) row.style.display = 'none';
                            if (line.startsWith('❌')) row.style.color = '#f87171';
                            else if (line.startsWith('👤')) row.style.color = '#818cf8';
                            else if (line.startsWith('🔧')) row.style.color = '#38bdf8';
                            row.textContent = line;
                            row.title = line;
                            container.appendChild(row);
                        }
                        lastTool.appendChild(container);
                        if (lines.length > PREVIEW_LOG) {
                            const hint = document.createElement('div');
                            hint.className = 'text-xs mt-1';
                            hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                            hint.textContent = `▼ ${lines.length - PREVIEW_LOG} more`;
                            lastTool.appendChild(hint);
                            let _logExp = false;
                            lastTool.style.cursor = 'pointer';
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _logExp = !_logExp;
                                container.querySelectorAll('[data-log-row]').forEach((r, i) => { if (i >= PREVIEW_LOG) r.style.display = _logExp ? 'block' : 'none'; });
                                hint.textContent = _logExp ? '▲ collapse' : `▼ ${lines.length - PREVIEW_LOG} more`;
                            });
                        }
                    }
                    addTimestamp(lastTool, ts);
                    return;
                }
                const resultEl = document.createElement('div');
                resultEl.className = 'text-xs markdown-body';
                resultEl.style.cssText = 'margin-top:6px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
                resultEl.innerHTML = DOMPurify.sanitize(marked.parse(clean));
                lastTool.appendChild(resultEl);
                const resLines = clean.split('\n');
                if (resLines.length > 5) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                    hint.textContent = `▼ ${resLines.length - 5} more lines`;
                    lastTool.appendChild(hint);
                    let _orchExp = false;
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        _orchExp = !_orchExp;
                        resultEl.style.maxHeight = _orchExp ? 'none' : '90px';
                        resultEl.style.overflowY = _orchExp ? 'visible' : 'hidden';
                        hint.textContent = _orchExp ? '▲ collapse' : `▼ ${resLines.length - 5} more lines`;
                    });
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'Glob') {
                let _globPattern = '';
                try { const _gp = JSON.parse(lastTool.dataset.toolContent.slice(lastTool.dataset.toolContent.indexOf(':') + 1)); _globPattern = _gp.pattern || ''; } catch {}
                const globEl = renderGlobView(_globPattern, clean);
                if (globEl) {
                    lastTool.appendChild(globEl);
                    const hdr = lastTool.querySelector('.flex.items-center');
                    if (hdr) {
                        const count = clean.split('\n').filter(l => l.trim()).length;
                        hdr.textContent = `📂 Glob: ${_globPattern || '?'} (${count})`;
                    }
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        const rest = globEl.querySelector('[data-role="read-rest"]');
                        const more = globEl.querySelector('[data-role="read-more"]');
                        if (rest && more) {
                            const exp = rest.style.display !== 'none';
                            rest.style.display = exp ? 'none' : 'block';
                            const cnt = more.dataset.count;
                            more.textContent = exp ? `▼ ${cnt} more files` : '▲ collapse';
                        }
                    });
                } else {
                    const noMatch = document.createElement('div');
                    noMatch.className = 'text-xs';
                    noMatch.style.cssText = 'margin-top:4px;color:#64748b;font-style:italic';
                    noMatch.textContent = 'No files found';
                    lastTool.appendChild(noMatch);
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'Skill') {
                const resultEl = document.createElement('div');
                resultEl.className = 'text-xs';
                resultEl.style.cssText = 'margin-top:6px;overflow-wrap:anywhere;white-space:pre-wrap;color:#cbd5e1';
                resultEl.textContent = clean.length > 300 ? clean.slice(0, 300) + '…' : clean;
                if (clean.length > 5) lastTool.appendChild(resultEl);
                addTimestamp(lastTool, ts);
                return;
            }
            const isWebFetchResult = lastTool.dataset.toolRawName === 'WebFetch' || lastTool.dataset.toolRawName === 'mcp__websearch__web_fetch';
            if (isWebFetchResult) {
                const bodyEl = document.createElement('div');
                bodyEl.className = 'text-xs markdown-body';
                bodyEl.style.cssText = 'margin-top:6px;line-height:1.5;color:#cbd5e1;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word';
                bodyEl.innerHTML = DOMPurify.sanitize(marked.parse(clean));
                lastTool.appendChild(bodyEl);
                const fetchLines = clean.split('\n');
                if (fetchLines.length > 5) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                    hint.textContent = `▼ ${fetchLines.length - 5} more lines`;
                    lastTool.appendChild(hint);
                    let wfExpanded = false;
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        wfExpanded = !wfExpanded;
                        bodyEl.style.maxHeight = wfExpanded ? 'none' : '90px';
                        bodyEl.style.overflowY = wfExpanded ? 'visible' : 'hidden';
                        hint.textContent = wfExpanded ? '▲ collapse' : `▼ ${fetchLines.length - 5} more lines`;
                    });
                }
                addTimestamp(lastTool, ts);
                return;
            }
            const isWebSearch = lastTool.dataset.toolRawName === 'mcp__websearch__search' ||
                                lastTool.dataset.toolRawName === 'mcp__websearch__search_web' ||
                                lastTool.dataset.toolRawName === 'WebSearch';
            if (isWebSearch) {
                const wsEl = renderWebSearchResults(content);
                if (wsEl) {
                    const sep = document.createElement('div');
                    sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
                    sep.appendChild(wsEl);
                    lastTool.appendChild(sep);
                    addTimestamp(lastTool, ts);
                    return;
                }
            }
            if (lastTool.dataset.isBash) {
                // harness bash (#369) prefixes the result with "exit_code=N" — surface it as a
                // status mark in the header instead of a glued first output line.
                let resText = clean;
                const rcMatch = resText.match(/^exit_code=(-?\d+)[ \t]*\r?\n?/);
                if (rcMatch) {
                    const rc = parseInt(rcMatch[1], 10);
                    const hdrEl = lastTool.querySelector('.flex.items-center');
                    if (hdrEl) {
                        const st = document.createElement('span');
                        st.textContent = rc === 0 ? '✓ 0' : `✗ exit ${rc}`;
                        st.style.cssText = `font-size:10px;font-weight:normal;margin-left:auto;color:${rc === 0 ? '#4ade80' : '#f87171'}`;
                        hdrEl.appendChild(st);
                    }
                    if (rc === 0) resText = resText.slice(rcMatch[0].length);
                }
                const sep = document.createElement('div');
                sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
                const resLines = resText.split('\n');
                const BASH_PREVIEW = 5;
                const resWrap = document.createElement('div');
                resWrap.className = 'diff-view';
                const previewPre = document.createElement('pre');
                previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none';
                previewPre.textContent = resLines.slice(0, BASH_PREVIEW).join('\n');
                resWrap.appendChild(previewPre);
                if (resLines.length > BASH_PREVIEW) {
                    const restPre = document.createElement('pre');
                    restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;display:none';
                    restPre.dataset.role = 'bash-result';
                    restPre.textContent = resLines.slice(BASH_PREVIEW).join('\n');
                    resWrap.appendChild(restPre);
                    const resHint = document.createElement('div');
                    resHint.className = 'diff-file';
                    resHint.dataset.role = 'bash-result-hint';
                    resHint.dataset.count = resLines.length - BASH_PREVIEW;
                    resHint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                    resHint.textContent = `▼ ${resLines.length - BASH_PREVIEW} more lines`;
                    resWrap.appendChild(resHint);
                }
                sep.appendChild(resWrap);
                lastTool.appendChild(sep);
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.isGrep) {
                const grepEl = renderGrepResults(clean, lastTool.dataset.grepPattern);
                if (grepEl) {
                    lastTool.appendChild(grepEl);
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', () => {
                        const restEl = grepEl.querySelector('[data-role="read-rest"]');
                        const moreEl = grepEl.querySelector('[data-role="read-more"]');
                        if (restEl && moreEl) {
                            const showing = restEl.style.display !== 'none';
                            restEl.style.display = showing ? 'none' : 'block';
                            moreEl.textContent = showing ? `▼ ${moreEl.dataset.count} more lines` : `▲ collapse`;
                        }
                    });
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.isRead) {
                delete lastTool.dataset.lastTool;
                const readContainer = lastTool.querySelector('.diff-view');
                if (readContainer) {
                    const skeletonEl = readContainer.querySelector('[data-role="read-skeleton"]');
                    if (skeletonEl) skeletonEl.remove();
                    const readPath = readContainer.dataset.readPath || '';
                    if (/\.md$/i.test(readPath)) {
                        const mdClean = clean.replace(/^\s*\d+\t/gm, '');
                        readContainer.style.overflowX = 'hidden';
                        readContainer.style.maxWidth = '100%';
                        const mdEl = document.createElement('div');
                        mdEl.className = 'markdown-body';
                        mdEl.style.cssText = 'padding:6px 8px;font-size:11px;overflow-wrap:anywhere;word-break:break-word;overflow-x:hidden;max-width:100%;max-height:90px;overflow-y:hidden';
                        mdEl.innerHTML = DOMPurify.sanitize(marked.parse(mdClean), {ADD_TAGS: ['input'], ADD_ATTR: ['checked', 'disabled', 'type']});
                        const MD_PREVIEW_H = 90;
                        readContainer.appendChild(mdEl);
                        const moreEl = document.createElement('div');
                        moreEl.className = 'diff-file';
                        moreEl.dataset.role = 'read-more';
                        moreEl.dataset.count = '0';
                        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                        moreEl.textContent = '▼ more';
                        readContainer.appendChild(moreEl);
                        requestAnimationFrame(() => {
                            if (mdEl.scrollHeight <= MD_PREVIEW_H + 4) {
                                moreEl.style.display = 'none';
                                mdEl.style.maxHeight = 'none';
                                mdEl.style.overflowY = 'visible';
                            }
                        });
                        let mdExpanded = false;
                        const toggleMd = () => {
                            mdExpanded = !mdExpanded;
                            mdEl.style.maxHeight = mdExpanded ? 'none' : MD_PREVIEW_H + 'px';
                            mdEl.style.overflowY = mdExpanded ? 'visible' : 'hidden';
                            moreEl.textContent = mdExpanded ? '▲ collapse' : '▼ more';
                        };
                        lastTool.style.cursor = 'pointer';
                        lastTool.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleMd(); });
                        addTimestamp(lastTool, ts);
                        return;
                    }
                    if (/\.(png|jpg|jpeg|gif|webp|svg)$/i.test(readPath)) {
                        const img = document.createElement('img');
                        img.src = `/api/files/raw?path=${encodeURIComponent(readPath)}&t=${Date.now()}`;
                        img.loading = 'lazy';
                        img.style.cssText = 'max-height:200px;border-radius:8px;cursor:pointer;margin-top:6px;display:block';
                        img.addEventListener('click', () => openImageLightbox(img.src));
                        readContainer.appendChild(img);
                        addTimestamp(lastTool, ts);
                        return;
                    }
                    const lines = clean.split('\n').map(l => l.length > 200 ? l.slice(0, 200) + '…' : l);
                    const PREVIEW = 5;
                    const previewL = lines.slice(0, PREVIEW);
                    const restL = lines.slice(PREVIEW);
                    for (const line of previewL) {
                        const row = document.createElement('div');
                        row.className = 'diff-line diff-line-ctx';
                        const gutter = document.createElement('span');
                        gutter.className = 'diff-gutter';
                        gutter.textContent = ' ';
                        const code = document.createElement('span');
                        code.className = 'diff-code';
                        code.textContent = line;
                        row.append(gutter, code);
                        readContainer.appendChild(row);
                    }
                    if (restL.length > 0) {
                        const restEl = document.createElement('div');
                        restEl.dataset.role = 'read-rest';
                        restEl.style.display = 'none';
                        for (const line of restL) {
                            const row = document.createElement('div');
                            row.className = 'diff-line diff-line-ctx';
                            const gutter = document.createElement('span');
                            gutter.className = 'diff-gutter';
                            gutter.textContent = ' ';
                            const code = document.createElement('span');
                            code.className = 'diff-code';
                            code.textContent = line;
                            row.append(gutter, code);
                            restEl.appendChild(row);
                        }
                        readContainer.appendChild(restEl);
                        const moreEl = document.createElement('div');
                        moreEl.className = 'diff-file';
                        moreEl.dataset.role = 'read-more';
                        moreEl.dataset.count = restL.length;
                        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                        moreEl.textContent = `▼ ${restL.length} more lines`;
                        readContainer.appendChild(moreEl);
                    }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            let _resultJsonParsed = null;
            try { _resultJsonParsed = JSON.parse(content); } catch {}
            if (_resultJsonParsed && typeof _resultJsonParsed === 'object' && !Array.isArray(_resultJsonParsed)) {
                let data = _resultJsonParsed;
                if (data.result !== undefined && Object.keys(data).length === 1) {
                    if (typeof data.result === 'string') {
                        try { data = JSON.parse(data.result); } catch { data = null; }
                    } else if (typeof data.result === 'object' && data.result !== null) {
                        data = data.result;
                    } else { data = null; }
                }
                if (data && typeof data === 'object' && !Array.isArray(data)) {
                    const hdr = lastTool.querySelector('.flex.items-center');
                    const hasErr = data.error || data.Error;
                    if (hdr && hasErr) {
                        hdr.textContent = `❌ ${DOMPurify.sanitize(String(data.error || data.Error)).slice(0, 80)}`;
                        hdr.style.color = '#ef4444';
                    } else if (hdr && !hdr.textContent.includes('✅') && !hdr.textContent.includes('❌')) {
                        hdr.textContent = hdr.textContent.replace(/⏳.*$/, '✅ Done');
                    }
                    lastTool.dataset.toolContent += '\n\n' + content;
                    const gridWrap = document.createElement('div');
                    gridWrap.style.cssText = 'margin-top:4px';
                    _renderJsonGrid(data, gridWrap);
                    lastTool.appendChild(gridWrap);
                    addTimestamp(lastTool, ts);
                    return;
                }
            }
            lastTool.dataset.toolContent += '\n\n' + content;
            const oldCopy = lastTool.querySelector('.copy-btn');
            if (oldCopy) oldCopy.remove();
            addCopyBtn(lastTool, lastTool.dataset.toolContent);

            const resultEl = document.createElement('div');
            resultEl.className = 'text-xs result-body';
            resultEl.style.cssText = 'white-space:pre-wrap;margin-top:6px';
            resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
            lastTool.appendChild(resultEl);
            if (full) {
                const rHint = document.createElement('div');
                rHint.className = 'text-xs mt-1 result-hint';
                rHint.style.cssText = 'color:#38bdf8;cursor:pointer';
                rHint.textContent = `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
                lastTool.appendChild(rHint);
                let rExpanded = false;
                const toggleResult = () => {
                    rExpanded = !rExpanded;
                    resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(rExpanded ? full : preview, {ADD_ATTR: ['target']});
                    rHint.textContent = rExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
                };
                lastTool.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleResult(); });
            }
            addTimestamp(lastTool, ts);
            return;
        }

        const wsStandalone = renderWebSearchResults(content);
        if (wsStandalone) {
            const sep = document.createElement('div');
            sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
            sep.appendChild(wsStandalone);
            div.appendChild(sep);
            addTimestamp(div, ts);
            const wasAtBottom = _chatAtBottom(chat);
            _insert(div);
            if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
            return;
        }

        let _standaloneJson = null;
        try { _standaloneJson = JSON.parse(content); } catch {}
        if (_standaloneJson && typeof _standaloneJson === 'object' && !Array.isArray(_standaloneJson)) {
            let sData = _standaloneJson;
            if (sData.result !== undefined && Object.keys(sData).length === 1) {
                if (typeof sData.result === 'string') { try { sData = JSON.parse(sData.result); } catch { sData = null; } }
                else if (typeof sData.result === 'object' && sData.result !== null) sData = sData.result;
                else sData = null;
            }
            if (sData && typeof sData === 'object' && !Array.isArray(sData)) {
                const gridWrap = document.createElement('div');
                gridWrap.style.cssText = 'margin-top:4px';
                _renderJsonGrid(sData, gridWrap);
                div.appendChild(gridWrap);
                addTimestamp(div, ts);
                const wasAtBottom = _chatAtBottom(chat);
                _insert(div);
                if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
                return;
            }
        }
        const resultBody = document.createElement('div');
        resultBody.style.whiteSpace = 'pre-wrap';
        resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
        div.appendChild(resultBody);
        if (full) {
            const sHint = document.createElement('div');
            sHint.className = 'text-xs mt-1';
            sHint.style.cssText = 'color:#38bdf8;cursor:pointer';
            sHint.textContent = `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
            div.appendChild(sHint);
            let sExpanded = false;
            const toggleStandalone = () => {
                sExpanded = !sExpanded;
                resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(sExpanded ? full : preview, {ADD_ATTR: ['target']});
                sHint.textContent = sExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
            };
            div.style.cursor = 'pointer';
            div.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleStandalone(); });
        }
    }
    else if (type === 'error') {
        if (/rate.?limit/i.test(content)) {
            div.textContent = '⏳ Rate limit — Anthropic временно ограничил запросы (это НЕ лимит твоей подписки). Orchestra автоматически повторит.';
            div.className = div.className.replace('text-red-400', 'text-amber-400');
        } else {
            div.textContent = content;
        }
    }
    else {
        div.innerHTML = DOMPurify.sanitize(marked.parse(content));
        _markUnexecutedToolCall(div, content);
        const agentColor = agentColors[selectedAgent];
        if (agentColor) div.style.borderLeft = `3px solid ${agentColor}`;
        renderImages(div, content);
    }

    addCopyBtn(div, content);
    addTimestamp(div, ts);
    const wasAtBottom = _chatAtBottom(chat);
    _insert(div);
    _trimChatNodes(chat);
    if (type === 'tool') _adoptOrphanResults(chat, div.dataset.toolUseId);
    if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
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
        if (!_tasksTabActive && !_jobsTabActive) {
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
        _onServerOk();

        _renderSessionsAndStats(sessions, stats);
        snapshotSave(`sessions:${capturedScope}`, {sessions, stats});
        _clearStaleNotice('sessions');

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
            _onFetchFail(e);
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
        _showErrorNotice('sessions', 'Список агентов не загрузился', error);
        return;
    }
    _renderSessionsAndStats(snapshot.data.sessions, snapshot.data.stats);
    _showStaleNotice('sessions', snapshot.ts);
}

// === API ===
// Таймаут и число попыток — из замеров perf через канал юзера. Сломанный ответ не приходит
// НИКОГДА: между сервером и юзером сидит посредник, который подтверждает нам 165 КБ, а до
// браузера доносит 19–23 КБ. Каждая попытка падает с вероятностью ~0.48, три попытки
// опускают «сломано навсегда» с 48% до ~5%.
// Величина таймаута — цена ожидания перед повтором, и она снижена с 3.5 с до 2 с: замер с
// ноутбука юзера через зеркало показал, что самое тяжёлое приезжает быстрее — `logs/sync`
// 130 КБ за 0.72–1.33 с, `app.js` 382 КБ за 0.75–0.98 с, обычный API 0.2–0.7 с. Двойка
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

let _apiActiveGets = 0;
const _apiGetQueue = [];

function _apiAcquireGetPermit(signal) {
    return new Promise((resolve, reject) => {
        const waiter = {signal, resolve, reject, cancelled: false, onAbort: null};
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
        if (_apiActiveGets < _API_MAX_CONCURRENT_GETS) waiter.grant();
        else _apiGetQueue.push(waiter);
    });
}

function _apiReleaseGetPermit() {
    _apiActiveGets--;
    while (_apiActiveGets < _API_MAX_CONCURRENT_GETS && _apiGetQueue.length) {
        const waiter = _apiGetQueue.shift();
        if (waiter.cancelled || waiter.signal?.aborted) {
            waiter.cancelled = true;
            waiter.onAbort && waiter.signal.removeEventListener('abort', waiter.onAbort);
            continue;
        }
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
    const attempts = (isGet && opts.timeoutMs === undefined) ? _API_ATTEMPTS : 1;
    const pollKey = opts.pollKey;
    const requestOpts = {...opts};
    delete requestOpts.pollKey;
    for (let attempt = 1; ; attempt++) {
        const releaseGetPermit = isGet ? await _apiAcquireGetPermit(opts.signal) : null;
        let data;
        let error;
        try {
            try {
                const timeout = AbortSignal.timeout(opts.timeoutMs ?? (isGet ? _API_TIMEOUT_MS : _API_MUTATION_TIMEOUT_MS));
                const signal = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;
                const resp = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...requestOpts, signal });
                if (!resp.ok) {
                    const text = await resp.text();
                    // Отказ на время перезапуска — штатный и повторяемый: вызов отклонён ДО
                    // побочного эффекта. Юзер до этого получал в чат сырой служебный JSON.
                    if (_restartPendingFromBody(resp.status, text)) {
                        _setRestartPending(true);
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
                _hideNetFailBanner(url);
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
            if (broken && attempts > 1) _showNetFailBanner(url, attempts);
            throw error;
        }
        const pause = Math.round(Math.random() * _API_RETRY_JITTER_MS);
        console.warn(`api ${url}: попытка ${attempt}/${attempts} — ${error.name}, пауза ${pause} мс`);
        await new Promise(resolve => setTimeout(resolve, pause));
    }
}

// После исчерпания попыток юзер должен видеть причину, а не пустой экран: обрыв происходит
// МЕЖДУ браузером и сервером, сервер при этом жив, поэтому оверлей «сервер перезагружается»
// тут врал бы. Снимает баннер успех ТОГО ЖЕ пути, а не любой: посредник режет крупные
// ответы, мелкие при этом ходят нормально и стёрли бы сообщение через миллисекунды —
// замерено, в первом прогоне баннер не доживал до конца окна.
let _netFailPath = null;

function _showNetFailBanner(url, attempts) {
    _netFailPath = url.split('?')[0];
    const banner = document.getElementById('net-fail-banner');
    if (!banner) return;
    banner.classList.remove('hidden');
    banner.classList.add('flex');
    banner.innerHTML = `📡 <b>Ответ не дошёл</b> — ${escHtml(_netFailPath)}: ${attempts} попытки по ${(_API_TIMEOUT_MS / 1000).toFixed(1)} с. <span class="text-red-300/70">Обрыв между браузером и сервером; сервер отвечает. Повторим на следующем обновлении.</span>`;
}

function _hideNetFailBanner(url) {
    if (!_netFailPath || url.split('?')[0] !== _netFailPath) return;
    _netFailPath = null;
    const banner = document.getElementById('net-fail-banner');
    if (!banner) return;
    banner.classList.add('hidden');
    banner.classList.remove('flex');
}

// === Полоса «показано из кеша» / «не загрузилось» (#197) ===
// Строится в JS, а не в шаблоне: шаблон отдаётся главным чекаутом и доехал бы до юзера
// только рестартом. Полос две по СМЫСЛУ, а не по вкусу: «данные старые, но они есть» и
// «данных нет вовсе» лечатся по-разному, и путать их — то же, что молчащий catch.
function _noticeStrip() {
    let strip = document.getElementById('stale-notice-strip');
    if (strip) return strip;
    strip = document.createElement('div');
    strip.id = 'stale-notice-strip';
    strip.className = 'flex flex-col';
    const usageBar = document.getElementById('usage-bar');
    if (usageBar?.parentNode) usageBar.parentNode.insertBefore(strip, usageBar);
    else document.body.prepend(strip);
    return strip;
}

function _noticeRow(key) {
    const strip = _noticeStrip();
    let row = document.getElementById(`notice-${key}`);
    if (!row) {
        row = document.createElement('div');
        row.id = `notice-${key}`;
        row.className = 'flex items-center justify-center gap-2 px-4 py-1 text-xs border-b';
        strip.appendChild(row);
    }
    return row;
}

// Данные на экране есть, но они из снимка. Жёлтый: работать можно, доверять частично.
function _showStaleNotice(key, ts) {
    const row = _noticeRow(key);
    row.className = 'flex items-center justify-center gap-2 px-4 py-1 text-xs border-b '
        + 'bg-amber-500/10 border-amber-500/30 text-amber-200';
    row.dataset.staleKey = key;
    row.textContent = `🕒 ${key}: показано из кеша — ${snapshotAgeLabel(ts)}. Обновим, как только ответ дойдёт.`;
}

// Данных нет и подставить нечего. Красный, и с КЛАССОМ исключения: «не загрузилось»
// без причины отправляет юзера гадать, а причины у обрыва и у 500 разные.
function _showErrorNotice(key, what, error) {
    const row = _noticeRow(key);
    row.className = 'flex items-center justify-center gap-2 px-4 py-1 text-xs border-b '
        + 'bg-red-500/10 border-red-500/30 text-red-200';
    delete row.dataset.staleKey;
    const reason = error?.status
        ? `сервер ответил ${error.status}`
        : `${error?.name || 'Error'}: ${error?.message || 'без текста'}`;
    row.textContent = `⚠ ${what} — ${reason}`;
}

function _clearStaleNotice(key) {
    document.getElementById(`notice-${key}`)?.remove();
}

// === Usage Bar ===

// === Перезапуск Orchestra (#270) ===
// Во время перезапуска сервер ЖИВ и отвечает на чтения — немеют только мутирующие вызовы,
// и юзер узнавал об этом сырым служебным JSON в чате. Признак ловим на существующем пути
// ответов (503 + `error.code = restart_pending`), своего опроса не заводим.
let _restartPending = false;
let _restartPendingSince = 0;
// Перезапуск может не состояться: preflight не смог слить хвост мутаций и молча
// переоткрыл приём, не сказав об этом ни одному клиенту. Без потолка полоса висела бы вечно.
const _RESTART_PENDING_MAX_MS = 120000;

function _restartPendingFromBody(status, text) {
    if (status !== 503) return false;
    try { return JSON.parse(text)?.error?.code === 'restart_pending'; } catch { return false; }
}

// Полосу строим в JS: шаблон отдаётся из главного чекаута и доехал бы до юзера только
// рестартом — тем самым, про который она и рассказывает.
function _restartBanner() {
    let banner = document.getElementById('restart-banner');
    if (banner) return banner;
    banner = document.createElement('div');
    banner.id = 'restart-banner';
    // Тот же язык, что у соседних полос, и намеренно НЕ красный: перезапуск штатен.
    banner.className = 'hidden items-center justify-center gap-2 px-4 py-2 bg-amber-500/15 border-b border-amber-500/40 text-amber-200 text-xs';
    banner.innerHTML = '⏳ <b>Orchestra перезапускается</b> — отправка на паузе, вызовы отклоняются ДО изменений. ' +
        '<span class="text-amber-400/70">Вернётся сама, перезагружать страницу не нужно.</span>';
    const anchor = document.getElementById('rate-limit-banner');
    if (anchor) anchor.parentNode.insertBefore(banner, anchor);
    else document.body.prepend(banner);
    return banner;
}

function _setRestartPending(on) {
    if (on) _restartPendingSince = Date.now();   // каждый новый отказ продлевает окно
    if (on === _restartPending) return;
    _restartPending = on;
    const banner = _restartBanner();
    banner.classList.toggle('hidden', !on);
    banner.classList.toggle('flex', on);
    updateInputState();
}

// === Reboot Overlay ===
let _rebootOverlay = null;
let _rebootFails = 0;
let _wasDown = false;   // был ли хоть один отказ с прошлого успешного ответа

function _showRebootOverlay() {
    if (_rebootOverlay) return;
    _rebootOverlay = document.createElement('div');
    _rebootOverlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:99999;color:white;font-family:system-ui,sans-serif';
    const spinner = document.createElement('div');
    spinner.style.cssText = 'font-size:48px;animation:spin 1.5s linear infinite';
    spinner.textContent = '🔄';
    const msg = document.createElement('div');
    msg.style.cssText = 'font-size:18px;margin-top:16px';
    msg.textContent = 'Сервер перезагружается...';
    const sub = document.createElement('div');
    sub.style.cssText = 'font-size:14px;color:#94a3b8;margin-top:8px';
    sub.textContent = 'Автоматическое переподключение...';
    const close = document.createElement('button');
    close.style.cssText = 'margin-top:24px;padding:8px 20px;border:1px solid #475569;border-radius:8px;background:transparent;color:#cbd5e1;font-size:14px;cursor:pointer';
    close.textContent = 'Закрыть и продолжить работу';
    close.onclick = _dismissRebootOverlay;
    _rebootOverlay.append(spinner, msg, sub, close);
    document.body.appendChild(_rebootOverlay);
    const style = document.createElement('style');
    style.textContent = '@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}';
    _rebootOverlay.appendChild(style);
    _pollReconnect();
}

// Escape hatch: if the overlay ever appears wrongly, the user must be able to get out of it
function _dismissRebootOverlay() {
    if (_rebootOverlay) _rebootOverlay.remove();
    _rebootOverlay = null;
    _rebootFails = 0;
}

async function _pollReconnect() {
    while (_rebootOverlay) {
        await new Promise(r => setTimeout(r, 2000));
        if (!_rebootOverlay) return;  // dismissed mid-sleep — must not recover behind the user's back
        try {
            const r = await fetch('/api/models', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
            if (r.status < 502) { _onServerOk(); return; }
        } catch {}
    }
}

// Сервер снова отвечает. Раньше здесь была location.reload(), и это оказалось дорогим
// способом сделать то, что уже умеет зеркало журнала из #8: историю догоняет одна дельта,
// чат перерисовывается локально. Замер (docs/tasks/15/research.md): сама перезагрузка стоит
// полсекунды, но клиент замечает возврат сервера через 1.7-159 с, медиана 23 с — платить
// ещё и за перезагрузку незачем. Свежесть версии фронта перезагрузка всё равно не давала:
// JS брался из кеша без обращения к серверу.
let _recovering = false;
async function _recoverAfterOutage() {
    if (_recovering) return;   // _onServerOk зовут и heartbeat, и refreshSessions, и опрос
    _recovering = true;
    try {
        _dismissRebootOverlay();
        _setRestartPending(false);   // перезапуск состоялся и кончился — пауза больше не нужна
        // Неподтверждённое серверу выбрасываем: рестарт мог потерять ход, и какой пузырь
        // чей — надёжно не определить. Перезагрузка делала это молча, теперь делаем явно.
        localMessages.clear();
        pendingUserMsgs = [];
        pendingBubble = null;
        _finalizedBubble = null;
        if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
        streamBubble = null;
        streamContent = '';
        streamPending = '';
        _streamDeferredFinal = null;
        await _storeSync();
        if (selectedAgent && currentScope) await _showChatFor(selectedAgent, currentScope);
        refreshSessions();
        loadOrchestrators();
    } finally {
        _recovering = false;
    }
}

// Two consecutive failures before showing overlay — one transient error shouldn't panic the UI
function _onServerError() {
    _rebootFails++;
    _wasDown = true;
    if (_rebootFails >= 2) _showRebootOverlay();
}

// A timed-out request means the server is SLOW, not gone — under disk pressure /api/models
// takes over 2s from a perfectly healthy server. A server that is actually down refuses the
// connection (TypeError) or answers 502+ through the proxy, and both still raise the overlay.
function _onFetchFail(e) {
    if (e.name === 'TimeoutError' || e.name === 'AbortError') return;
    _onServerError();
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

// Единственное место, где ловится переход «был недоступен → отвечает». Зовётся из
// heartbeat, из refreshSessions и из опроса под оверлеем — потому восстановление и
// защищено флагом, иначе чат перерисуется столько раз, сколько источников успело.
function _onServerOk() {
    _rebootFails = 0;
    if (!_wasDown) return;
    _wasDown = false;
    _recoverAfterOutage();
}

// Версия фронта, с которой загружена эта страница. HTML отдаётся с no-cache (#9),
// значит значение всегда свежее — в отличие от самого JS, который браузер берёт из кеша.
const _pageBuild = document.body.dataset.build || '';
let _buildBannerShown = false;

// Сервер уехал вперёд. Перезагружать страницу за юзера НЕ будем: измерено, что reload
// берёт JS из кеша и новую версию всё равно может не привезти, а решение перезагрузить
// чужую вкладку — не наше. Говорим и уходим.
function _showBuildBanner(serverBuild) {
    if (_buildBannerShown) return;
    _buildBannerShown = true;
    console.warn(`[build] страница собрана на ${_pageBuild}, сервер отдаёт ${serverBuild}`);
    const el = document.createElement('div');
    el.id = 'build-banner';
    el.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:16px;z-index:99998;' +
        'display:flex;align-items:center;gap:10px;padding:8px 14px;border-radius:10px;' +
        'background:#1e293b;border:1px solid #f59e0b66;color:#fde68a;font-size:12px;' +
        'font-family:system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.4)';
    el.innerHTML = '<span>Сервер обновился — обнови страницу, чтобы взять новую версию</span>';
    const btn = document.createElement('button');
    btn.style.cssText = 'padding:3px 10px;border:1px solid #475569;border-radius:6px;' +
        'background:transparent;color:#cbd5e1;cursor:pointer;font-size:12px';
    btn.textContent = 'Скрыть';
    btn.onclick = () => el.remove();
    el.appendChild(btn);
    document.body.appendChild(el);
}

async function _heartbeatProbe() {
    try {
        const r = await fetch('/api/models', { cache: 'no-store', signal: AbortSignal.timeout(2000) });
        // Заголовок появится с серверной частью #269 и делает состояние однозначным в обе
        // стороны. Пока его нет — снимаем паузу либо возвратом сервера, либо по потолку.
        const restarting = r.headers.get('X-Orchestra-Restarting');
        if (restarting !== null) _setRestartPending(restarting === '1');
        else if (_restartPending && Date.now() - _restartPendingSince > _RESTART_PENDING_MAX_MS) {
            console.warn('[restart] перезапуск не наступил за 2 минуты — снимаю паузу');
            _setRestartPending(false);
        }
        if (r.status < 502) {
            _pollNoteSuccess('heartbeat');
            _onServerOk();
            // Сверяем ПОСЛЕ _onServerOk: он снимает оверлей ребута, а баннер под
            // полноэкранным оверлеем был бы невидим.
            const serverBuild = r.headers.get('X-Orchestra-Build');
            if (serverBuild && _pageBuild && serverBuild !== _pageBuild) _showBuildBanner(serverBuild);
        } else {
            _pollNoteFailure('heartbeat', {name: 'TypeError'});
            _onServerError();
        }
    } catch (e) { _pollNoteFailure('heartbeat', e); _onFetchFail(e); }
}

function initHeartbeat() {
        _pollRegister('heartbeat', _heartbeatProbe, 8000);
}

// === Tasks Panel ===
let _tasksTabActive = false;

let _jobsTabActive = false;

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
    if (tasksPanel) tasksPanel.classList.toggle('hidden', tab !== 'tasks');
    if (jobsPanel) jobsPanel.classList.toggle('hidden', tab !== 'jobs');
    _tasksTabActive = tab === 'tasks';
    _jobsTabActive = tab === 'jobs';
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

async function showTaskDetail(par) {
    try {
        const scope = currentScope ? `?scope=${encodeURIComponent(currentScope)}` : '';
        const r = await fetch(`/api/tm/tasks/${par}${scope}`);
        const t = await r.json();
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
        html += '</div>';
        bodyEl.innerHTML = html;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
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

    const band = [], line = [];
    for (let i = 0; i <= 100; i++) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(t * 100)}`); }
    for (let i = 100; i >= 0; i--) { const t = i / 100; band.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule))}`); }
    for (let i = 0; i <= 100; i++) { const t = i / 100; line.push(`${_qlX(t)},${_qlY(_qlLimitAt(t, rule))}`); }
    p.push(`<polygon class="ql-band" points="${band.join(' ')}"/>`);
    p.push(`<line class="ql-diag" x1="${_qlX(0)}" y1="${_qlY(0)}" x2="${_qlX(1)}" y2="${_qlY(100)}"/>`);
    p.push(`<polyline class="ql-gated" points="${line.join(' ')}"/>`);

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
  if ($('#catalog-free')?.checked && !(m.price_prompt === 0 && m.price_completion === 0)) return false;
  if ($('#catalog-tools')?.checked && !m.supports_tools) return false;
  if ($('#catalog-image')?.checked && !(m.input_modalities || []).includes('image')) return false;
  return true;
}

function _fmtPrice(p) { return p == null ? '—' : (p === 0 ? 'free' : `$${p}/M`); }

function _catalogToggle(flag, m) {
  const label = document.createElement('label');
  label.className = 'text-[10px] text-slate-400 flex items-center gap-1 cursor-pointer';
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.setAttribute('data-flag', flag);
  box.dataset.id = m.id;
  box.checked = !!m.flags[flag];
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
  metaEl.textContent = `${m.id} · ${Math.round(m.context_length / 1000)}k · ${_fmtPrice(m.price_prompt)} in / ${_fmtPrice(m.price_completion)} out · ${m.runtime}`;
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
