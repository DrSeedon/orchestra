// Live activity in the chat (V-831): the tool call the model is still writing, running
// tools with an elapsed/timeout clock, and live output of shell tasks. Everything here is
// ephemeral DOM state fed by SSE partials; the persisted rows replace it when they land.

// Incremental reader of a tool call's JSON arguments. The model streams raw JSON in tiny
// fragments; showing it raw turns a 40 KB script into one line of `\n` escapes, so string
// values are unescaped as they arrive and top-level keys become `key: value` labels.
class LiveArgsDecoder {
    constructor() {
        this.text = '';
        this._depth = 0;
        this._inString = false;
        this._isKey = false;
        this._expectKey = false;
        this._escape = false;
        this._unicode = null;
        this._raw = false;
    }

    // Replay of a long call carries only its tail, which starts mid-JSON: fall back to
    // plain escape replacement instead of misparsing it.
    feedTail(tail) {
        this._raw = true;
        this.feed(tail);
    }

    feed(chunk) {
        if (this._raw) {
            this.text += chunk.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
                .replace(/\\"/g, '"').replace(/\\\\/g, '\\');
            return;
        }
        let out = '';
        for (const ch of chunk) {
            if (this._inString) {
                if (this._unicode !== null) {
                    this._unicode += ch;
                    if (this._unicode.length === 4) {
                        const code = parseInt(this._unicode, 16);
                        if (Number.isFinite(code)) out += String.fromCharCode(code);
                        this._unicode = null;
                    }
                } else if (this._escape) {
                    this._escape = false;
                    if (ch === 'u') this._unicode = '';
                    else out += ({n: '\n', t: '\t', r: '', b: '', f: ''})[ch] ?? ch;
                } else if (ch === '\\') {
                    this._escape = true;
                } else if (ch === '"') {
                    this._inString = false;
                    if (this._isKey && this._depth === 1) out += ': ';
                    else if (this._depth > 1) out += '"';
                } else {
                    out += ch;
                }
                continue;
            }
            if (ch === '"') {
                this._inString = true;
                this._isKey = this._expectKey;
                this._expectKey = false;
                if (this._depth === 1 && this._isKey && this.text.length + out.length > 0) out += '\n';
                else if (this._depth > 1) out += '"';
                continue;
            }
            if (ch === '{' || ch === '[') {
                this._depth += 1;
                if (this._depth === 1) { this._expectKey = ch === '{'; continue; }
            } else if (ch === '}' || ch === ']') {
                this._depth -= 1;
                if (this._depth === 0) continue;
            } else if (ch === ',' && this._depth === 1) {
                this._expectKey = true;
                continue;
            } else if (ch === ':' && this._depth === 1) {
                continue;
            } else if (/\s/.test(ch) && this._depth <= 1) {
                continue;
            }
            out += ch;
        }
        this.text += out;
    }
}

// Bash: `timeout` in ms, default 2 min, capped at 10 min; a background call returns at once.
function liveToolTimeoutMs(rawName, input) {
    if (!input || typeof input !== 'object') return 0;
    if (rawName === 'Bash' || rawName === 'BashTool') {
        if (input.run_in_background) return 0;
        const asked = Number(input.timeout);
        return Number.isFinite(asked) && asked > 0 ? Math.min(asked, 600000) : 120000;
    }
    return 0;
}

function liveFormatClock(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = String(total % 60).padStart(2, '0');
    return hours ? `${hours}:${String(mins).padStart(2, '0')}:${secs}` : `${mins}:${secs}`;
}

function liveRunLabel(elapsedMs, timeoutMs) {
    return timeoutMs
        ? T('⏳ running {elapsed} of {timeout}', {elapsed: liveFormatClock(elapsedMs), timeout: liveFormatClock(timeoutMs)})
        : T('⏳ running {elapsed}', {elapsed: liveFormatClock(elapsedMs)});
}

// ── Tool call being written ──

const _liveToolInputCards = new Map();
const _LIVE_TOOL_INPUT_TAIL = 20_000;

function _liveToolInputStats(card) {
    const chars = card._chars || 0;
    const elapsed = card._elapsedMs || 0;
    const parts = [T('{n} chars', {n: chars.toLocaleString()})];
    if (elapsed >= 500) parts.push(T('{n} chars/s', {n: Math.round(chars / (elapsed / 1000)).toLocaleString()}));
    parts.push(liveFormatClock(elapsed));
    return parts.join(' · ');
}

// `insert` is addChatEntry's insertion helper, so the card obeys the chat's follow rules.
function liveRenderToolInput(payload, content, insert) {
    const id = payload.tool_use_id || '';
    if (!id) return;
    let card = _liveToolInputCards.get(id);
    if (card && !card.isConnected) {
        _liveToolInputCards.delete(id);
        card = null;
    }
    const chat = $('#chat');
    if (!card) {
        // The persisted call already rendered (replay racing the final row) → nothing live.
        if (chat.querySelector(`[data-tool-use-id="${CSS.escape(id)}"]`)) return;
        card = document.createElement('div');
        card.className = 'live-tool-input-card';
        card.dataset.liveToolInput = id;
        const head = document.createElement('div');
        head.className = 'live-tool-input-head';
        const dot = document.createElement('span');
        dot.className = 'live-dot';
        const title = document.createElement('span');
        const name = payload.short_name || payload.tool_name || 'tool';
        title.textContent = T('✍ {tool} · writing call', {tool: typeof toolShortName === 'function' ? T(toolShortName(canonicalToolName(name))) : name});
        const stats = document.createElement('span');
        stats.className = 'live-tool-input-stats';
        head.append(dot, title, stats);
        const body = document.createElement('pre');
        body.className = 'live-tool-input-body';
        card.append(head, body);
        card._decoder = new LiveArgsDecoder();
        card._chars = 0;
        card._elapsedMs = 0;
        _liveToolInputCards.set(id, card);
        insert(card);
    }
    if (payload.replace) {
        card._decoder = new LiveArgsDecoder();
        if ((payload.chars || 0) > content.length) card._decoder.feedTail(content);
        else card._decoder.feed(content);
    } else if (content) {
        card._decoder.feed(content);
    }
    card._chars = payload.chars ?? (card._chars + content.length);
    card._elapsedMs = payload.elapsed_ms ?? card._elapsedMs;
    const body = card.querySelector('.live-tool-input-body');
    const wasAtBottom = typeof _chatAtBottom === 'function' ? _chatAtBottom(chat) : false;
    body.textContent = card._decoder.text.slice(-_LIVE_TOOL_INPUT_TAIL);
    body.scrollTop = body.scrollHeight;
    card.querySelector('.live-tool-input-stats').textContent = _liveToolInputStats(card);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

function liveRemoveToolInput(id) {
    const card = _liveToolInputCards.get(id);
    if (card) card.remove();
    _liveToolInputCards.delete(id);
}

function liveClearToolInputs() {
    for (const card of _liveToolInputCards.values()) card.remove();
    _liveToolInputCards.clear();
}

// ── Running tool clock ──

const _LIVE_CLOCK_MAX_AGE_MS = 2 * 3600 * 1000;
let _liveAgentStatus = '';

function _liveToolInput(content) {
    const colon = content.indexOf(':');
    try { return JSON.parse(colon > 0 ? content.slice(colon + 1).trim() : ''); } catch { return null; }
}

// Called for every rendered tool call; history rows of a finished turn never start a clock
// because the stream handshake reports the agent idle and stops them (liveAgentStatus).
function liveStartToolClock(card, rawName, content, ts) {
    if (!card || card.dataset.toolDone || card._liveClockId) return;
    const timeoutMs = liveToolTimeoutMs(rawName, _liveToolInput(content));
    if (timeoutMs) card.dataset.toolTimeoutMs = String(timeoutMs);
    // No ts = a re-render of an old call (expanding a compact line), never a live one.
    const started = ts ? new Date(ts).getTime() : NaN;
    if (!Number.isFinite(started) || Date.now() - started > _LIVE_CLOCK_MAX_AGE_MS) return;
    if (_liveAgentStatus && _liveAgentStatus !== 'running') return;
    const clock = document.createElement('span');
    clock.className = 'tool-run-clock';
    const header = card.querySelector('.flex.items-center') || card;
    header.appendChild(clock);
    card.classList.add('tool-running');
    const tick = () => {
        if (!card.isConnected) return liveStopToolClock(card);
        clock.textContent = liveRunLabel(Date.now() - started, timeoutMs);
    };
    tick();
    card._liveClockId = setInterval(tick, 1000);
}

function liveStopToolClock(card) {
    if (!card) return;
    card.dataset.toolDone = '1';
    card.classList.remove('tool-running');
    if (card._liveClockId) {
        clearInterval(card._liveClockId);
        card._liveClockId = null;
    }
    card.querySelector('.tool-run-clock')?.remove();
}

function liveAgentStatus(status) {
    const previous = _liveAgentStatus;
    _liveAgentStatus = status;
    if (status === 'running' || previous === status) return;
    // Turn over: an unanswered call is interrupted, not running; an unfinished write is void.
    for (const card of document.querySelectorAll('#chat .tool-running')) {
        if (card._liveClockId) clearInterval(card._liveClockId);
        card._liveClockId = null;
        card.classList.remove('tool-running');
        card.querySelector('.tool-run-clock')?.remove();
    }
    liveClearToolInputs();
    if (typeof _removeCodexThinkingLive === 'function') _removeCodexThinkingLive();
}

function liveResetActivity() {
    liveClearToolInputs();
    _liveAgentStatus = '';
}

// ── Live shell-task output (server tails the CLI task file) ──

function liveRouteTaskOutput(payload, content) {
    const chat = $('#chat');
    const id = payload.tool_use_id || '';
    const call = id ? chat.querySelector(`[data-tool-use-id="${CSS.escape(id)}"]:not([data-tool-done])`) : null;
    if (call) {
        if (payload.replace) call.querySelector('.codex-live-output')?.remove();
        _applyCodexToolUpdate(call, 'tool_stream', content);
        return true;
    }
    // Background call: the Bash card already holds "running in background", so the output
    // belongs to the task card, visible without expanding it.
    const task = payload.subagent_id
        ? chat.querySelector(`[data-subagent-id="${CSS.escape(payload.subagent_id)}"]`)
        : null;
    if (!task || task.dataset.subagentDone) return false;
    let pre = task.querySelector(':scope > .codex-live-output');
    if (!pre) {
        pre = document.createElement('pre');
        pre.className = 'codex-live-output';
        task.appendChild(pre);
    }
    pre.textContent = ((payload.replace ? '' : pre.textContent) + content).slice(-20_000);
    pre.scrollTop = pre.scrollHeight;
    return true;
}
