/* tool-renderers.js — diff view, grep results, web search, tool icons. Loaded before app.js. */

const TOOL_ICONS = {
    'Bash': '🖥', 'Read': '📖', 'Write': '✏️', 'Edit': '✏️', 'file': '📄',
    'FileChange': '📝', 'Sleep': '⏱️',
    'Glob': '🔎', 'Grep': '🔎', 'WebSearch': '🌐', 'WebFetch': '🌐',
    'ViewImage': '🖼️', 'ImageGeneration': '🎨',
    'Agent': '🤖', 'Task': '🤖', 'TodoWrite': '📝', 'NotebookEdit': '📓',
    'ToolSearch': '🔍', 'AskUserQuestion': '❓', 'SendMessage': '💬',
};
const MCP_ICONS = {
    'orchestra': '🎼', 'websearch': '🌐', 'kesha': '🦜',
    'yougile': '📋', 'pandoc': '📄', 'aperant': '🏠',
    'github': '🐙', 'serena': '🧠', 'mailru': '📧',
    'openaiDeveloperDocs': '📚',
};

function canonicalToolName(name) {
    const clean = String(name || '').trim();
    if (!clean || clean.startsWith('mcp__')) return clean;
    return clean.includes('__') ? `mcp__${clean}` : clean;
}

function toolIcon(name) {
    name = canonicalToolName(name);
    if (name.startsWith('mcp__')) {
        const server = name.split('__')[1];
        return MCP_ICONS[server] || '🔌';
    }
    for (const [key, icon] of Object.entries(TOOL_ICONS)) {
        if (name === key || name.startsWith(key)) return icon;
    }
    return '🔧';
}

function toolShortName(name) {
    name = canonicalToolName(name);
    if (name.startsWith('mcp__')) {
        const parts = name.split('__');
        return parts.length >= 3 ? parts[2] : name;
    }
    return name;
}

function codexWebSearchSpec(raw) {
    let data = raw;
    if (typeof raw === 'string') {
        try { data = JSON.parse(raw); } catch { return null; }
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) return null;

    const action = data.action && typeof data.action === 'object' ? data.action : {};
    const actionType = action.type || (Array.isArray(action.queries) ? 'search' : '');
    const queryCandidates = Array.isArray(action.queries) ? action.queries
        : Array.isArray(data.queries) ? data.queries
        : [];
    const queries = queryCandidates
        .map(query => String(query || '').trim())
        .filter(Boolean);
    const singleQuery = String(action.query || data.query || '').trim();
    if (!queries.length && singleQuery) queries.push(singleQuery);

    return {
        type: actionType,
        queries,
        url: String(action.url || action.pageUrl || data.url || '').trim(),
        pattern: String(action.pattern || action.text || data.pattern || '').trim(),
        status: String(data.status || '').trim(),
    };
}

function codexWebSearchCompactLabel(spec) {
    if (!spec) return '🌐 Web search';
    if (spec.queries.length === 1) return `🌐 ${spec.queries[0]}`;
    if (spec.queries.length > 1) return `🌐 ${spec.queries[0]} +${spec.queries.length - 1}`;
    if (spec.type === 'openPage') {
        try { return `🌐 Open ${new URL(spec.url).hostname}`; } catch { return '🌐 Open page'; }
    }
    if (spec.type === 'findInPage') return `🌐 Find ${spec.pattern || 'in page'}`;
    return '🌐 Web search';
}

function renderCodexWebSearchActivity(spec) {
    const wrapper = document.createElement('div');
    wrapper.className = 'codex-search-activity';

    if (spec && spec.queries.length) {
        const list = document.createElement('div');
        list.className = 'codex-search-query-list';
        spec.queries.forEach((query, index) => {
            const row = document.createElement('div');
            row.className = 'codex-search-query';
            const number = document.createElement('span');
            number.className = 'codex-search-index';
            number.textContent = String(index + 1).padStart(2, '0');
            const text = document.createElement('span');
            text.textContent = query;
            row.append(number, text);
            list.appendChild(row);
        });
        wrapper.appendChild(list);
        return wrapper;
    }

    const detail = document.createElement('div');
    detail.className = 'codex-search-detail';
    if (spec?.type === 'openPage') {
        detail.textContent = spec.url ? `Open page · ${spec.url}` : 'Open page';
    } else if (spec?.type === 'findInPage') {
        detail.textContent = spec.pattern ? `Find in page · ${spec.pattern}` : 'Find in page';
    } else if (spec?.type) {
        detail.textContent = 'Browser action';
    } else {
        detail.textContent = 'Waiting for query details…';
    }
    wrapper.appendChild(detail);
    return wrapper;
}

function updateCodexWebSearchActivity(card, spec) {
    const previous = card.querySelector('.codex-search-activity');
    const next = renderCodexWebSearchActivity(spec);
    if (previous) previous.replaceWith(next);
    else card.appendChild(next);
}

function setCodexToolTitle(header, text, icon = '') {
    let title = header.querySelector('.codex-tool-title');
    if (!title) {
        header.textContent = '';
        if (icon) {
            const iconEl = document.createElement('span');
            iconEl.className = 'codex-tool-icon';
            iconEl.textContent = icon;
            header.appendChild(iconEl);
        }
        title = document.createElement('span');
        title.className = 'codex-tool-title';
        header.appendChild(title);
    }
    title.textContent = text;
}

function decorateCodexToolCard(card, header, family = '') {
    card.classList.add('codex-tool-card');
    if (family) card.classList.add(`codex-tool-card-${family}`);
    if (header) {
        header.classList.add('codex-tool-header');
        if (!header.querySelector('.codex-tool-title')) {
            const title = document.createElement('span');
            title.className = 'codex-tool-title';
            while (header.firstChild) title.appendChild(header.firstChild);
            header.appendChild(title);
        }
    }
    if (!card.querySelector('.codex-tool-state')) {
        const state = document.createElement('span');
        state.className = 'codex-tool-state';
        state.textContent = 'running';
        card.appendChild(state);
    }
    card.dataset.toolState = 'running';
}

function completeCodexToolCard(card, ok = true) {
    if (!card?.classList.contains('codex-tool-card')) return;
    card.dataset.toolState = ok ? 'done' : 'failed';
    const state = card.querySelector('.codex-tool-state');
    if (state) state.textContent = ok ? 'done' : 'failed';
}

// Returns null when lines are too different (< 40% common chars) — fall back to plain del/add
// rather than showing character-level diff noise on completely replaced lines.
function _inlineDiff(oldLine, newLine) {
    const dmp = new diff_match_patch();
    const diffs = dmp.diff_main(oldLine, newLine);
    dmp.diff_cleanupSemantic(diffs);
    let common = 0, total = 0;
    for (const [op, text] of diffs) { total += text.length; if (op === 0) common += text.length; }
    if (total === 0 || common / total < 0.4) return null;
    let delHtml = '', addHtml = '';
    for (const [op, text] of diffs) {
        const esc = _escHtml(text);
        if (op === 0) { delHtml += esc; addHtml += esc; }
        else if (op === -1) delHtml += `<span style="background:rgba(239,68,68,0.35);border-radius:2px">${esc}</span>`;
        else addHtml += `<span style="background:rgba(34,197,94,0.35);border-radius:2px">${esc}</span>`;
    }
    return { delHtml, addHtml };
}

// LCS-based diff — Uint16Array saves memory vs plain Array for large files.
// Walks the DP table backwards to reconstruct the edit sequence.
function buildDiffLines(oldStr, newStr) {
    const a = oldStr.split('\n'), b = newStr.split('\n');
    const n = a.length, m = b.length;
    const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
    for (let i = 1; i <= n; i++)
        for (let j = 1; j <= m; j++)
            dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
    const raw = [];
    let i = n, j = m;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && a[i-1] === b[j-1]) { raw.push({type:'ctx', text: a[i-1]}); i--; j--; }
        else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) { raw.push({type:'add', text: b[j-1]}); j--; }
        else { raw.push({type:'del', text: a[i-1]}); i--; }
    }
    raw.reverse();
    const result = [];
    let idx = 0;
    while (idx < raw.length) {
        if (raw[idx].type === 'del' && idx + 1 < raw.length && raw[idx+1].type === 'add') {
            const inline = _inlineDiff(raw[idx].text, raw[idx+1].text);
            if (inline) {
                result.push({type:'del', html: inline.delHtml});
                result.push({type:'add', html: inline.addHtml});
            } else {
                result.push({type:'del', html: _escHtml(raw[idx].text)});
                result.push({type:'add', html: _escHtml(raw[idx+1].text)});
            }
            idx += 2;
        } else {
            result.push({type: raw[idx].type, html: _escHtml(raw[idx].text)});
            idx++;
        }
    }
    return result;
}

function _buildDiffEl(lines) {
    const el = document.createElement('div');
    for (const line of lines) {
        const row = document.createElement('div');
        row.className = `diff-line diff-line-${line.type}`;
        const gutter = document.createElement('span');
        gutter.className = 'diff-gutter';
        gutter.textContent = line.type === 'del' ? '−' : line.type === 'add' ? '+' : ' ';
        const code = document.createElement('span');
        code.className = 'diff-code';
        code.innerHTML = line.html;
        row.append(gutter, code);
        el.appendChild(row);
    }
    return el;
}

function renderEditDiff(body) {
    let data;
    try { data = JSON.parse(body); } catch { return null; }
    const isWrite = data.content !== undefined && data.old_string === undefined;
    if (!isWrite && data.old_string === undefined && data.new_string === undefined) return null;

    const PREVIEW_LINES = 5;
    const lines = isWrite
        ? data.content.split('\n').map(l => ({type: 'add', html: _escHtml(l)}))
        : buildDiffLines(data.old_string || '', data.new_string || '');
    const fp = data.file_path || '';
    const shortPath = fp.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || fp;

    const container = document.createElement('div');
    container.className = 'diff-view';

    const fileEl = document.createElement('div');
    fileEl.className = 'diff-file';
    fileEl.textContent = shortPath;
    fileEl.title = fp;
    container.appendChild(fileEl);

    const previewLines = lines.slice(0, PREVIEW_LINES);
    const restLines = lines.slice(PREVIEW_LINES);

    container.appendChild(_buildDiffEl(previewLines));

    if (restLines.length > 0) {
        const restEl = _buildDiffEl(restLines);
        restEl.style.display = 'none';
        container.appendChild(restEl);

        const moreEl = document.createElement('div');
        moreEl.className = 'diff-file';
        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
        moreEl.textContent = `▼ ${restLines.length} more lines`;
        moreEl.dataset.count = restLines.length;
        container.appendChild(moreEl);
    }

    return container;
}

function _unifiedDiffLines(diff) {
    return String(diff || '').split('\n').filter((line, idx, lines) => {
        return !(idx === lines.length - 1 && line === '');
    }).map(line => {
        let type = 'ctx';
        if (line.startsWith('+') && !line.startsWith('+++')) type = 'add';
        else if (line.startsWith('-') && !line.startsWith('---')) type = 'del';
        const text = line.startsWith('@@') ? `⋯ ${line}` : line;
        return {type, html: _escHtml(text)};
    });
}

// Codex app-server provides ready-made unified diffs instead of Claude's
// old_string/new_string pair. Render every changed file without reparsing source files.
function renderCodexFileChange(body) {
    let data;
    try { data = typeof body === 'string' ? JSON.parse(body) : body; } catch { return null; }
    const changes = data && Array.isArray(data.changes) ? data.changes : [];
    if (!changes.length) return null;

    const root = document.createElement('div');
    root.className = 'codex-file-change';
    for (const change of changes) {
        const block = document.createElement('div');
        block.className = 'diff-view';
        const fp = String(change.path || '');
        const shortPath = fp.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || fp;
        const fileEl = document.createElement('div');
        fileEl.className = 'diff-file codex-diff-file';

        const path = document.createElement('span');
        path.textContent = shortPath || 'file';
        path.title = fp;
        const rawKind = typeof change.kind === 'object' && change.kind
            ? change.kind.type
            : change.kind;
        const changeKind = String(rawKind || 'update');
        const kind = document.createElement('span');
        kind.className = `codex-change-kind codex-change-${changeKind.toLowerCase().replace(/[^a-z0-9_-]/g, '-')}`;
        kind.textContent = changeKind;
        fileEl.append(path, kind);
        block.appendChild(fileEl);

        const lines = _unifiedDiffLines(change.diff);
        const preview = lines.slice(0, 8);
        const rest = lines.slice(8);
        block.appendChild(_buildDiffEl(preview));
        if (rest.length) {
            const restEl = _buildDiffEl(rest);
            restEl.dataset.role = 'codex-diff-rest';
            restEl.style.display = 'none';
            block.appendChild(restEl);
            const more = document.createElement('div');
            more.className = 'diff-file codex-diff-more';
            more.textContent = `▼ ${rest.length} more lines`;
            more.addEventListener('click', (event) => {
                event.stopPropagation();
                const expanded = restEl.style.display !== 'none';
                restEl.style.display = expanded ? 'none' : 'block';
                more.textContent = expanded ? `▼ ${rest.length} more lines` : '▲ collapse';
            });
            block.appendChild(more);
        }
        root.appendChild(block);
    }
    return root;
}

// Renders a placeholder skeleton while the tool_result (file content) is still in flight.
// The skeleton gets replaced by actual content when the SSE stream delivers tool_result.
function renderReadView(body) {
    let data;
    try { data = JSON.parse(body); } catch { return null; }
    if (!data.file_path) return null;

    const fp = data.file_path || '';
    // Strip worktree prefix — full absolute paths are too noisy for the UI
    const shortPath = fp.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || fp;
    const offset = data.offset || 0;
    const limit = data.limit || '';

    const container = document.createElement('div');
    container.className = 'diff-view';
    container.dataset.readPath = fp;

    const fileEl = document.createElement('div');
    fileEl.className = 'diff-file';
    fileEl.textContent = `${shortPath}${offset ? ` :${offset}` : ''}${limit ? ` (${limit} lines)` : ''}`;
    fileEl.title = fp;
    container.appendChild(fileEl);

    const skeleton = document.createElement('div');
    skeleton.className = 'read-skeleton';
    skeleton.dataset.role = 'read-skeleton';
    for (let i = 0; i < 3; i++) {
        const row = document.createElement('div');
        row.className = 'read-skeleton-line';
        skeleton.appendChild(row);
    }
    container.appendChild(skeleton);

    return container;
}

const _GLOB_FILE_ICONS = {
    py:'🐍', js:'📜', ts:'📜', jsx:'📜', tsx:'📜',
    md:'📝', txt:'📝', rst:'📝',
    png:'🖼', jpg:'🖼', jpeg:'🖼', svg:'🖼', gif:'🖼', webp:'🖼',
    json:'⚙️', yaml:'⚙️', yml:'⚙️', toml:'⚙️', ini:'⚙️',
    html:'🌐', css:'🎨', sh:'🖥', sql:'🗃',
};

function renderGlobView(pattern, resultText) {
    const files = resultText.split('\n').map(l => l.trim()).filter(Boolean);
    if (!files.length) return null;

    const PREVIEW = 8;
    const container = document.createElement('div');
    container.className = 'grep-results';
    container.style.marginTop = '6px';

    const headerEl = document.createElement('div');
    headerEl.className = 'grep-result-row';
    headerEl.style.cssText = 'color:#38bdf8;font-size:11px;font-weight:600;padding:4px 8px;border-bottom:1px solid #1e293b';
    headerEl.textContent = `📂 ${files.length} files`;
    container.appendChild(headerEl);

    function buildRow(path) {
        const short = path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '');
        const ext = path.includes('.') ? path.split('.').pop().toLowerCase() : '';
        const icon = _GLOB_FILE_ICONS[ext] || '📄';
        const row = document.createElement('div');
        row.className = 'grep-result-row';
        const meta = document.createElement('span');
        meta.className = 'grep-meta';
        meta.style.minWidth = '20px';
        meta.style.maxWidth = '20px';
        meta.textContent = icon;
        const code = document.createElement('span');
        code.className = 'grep-code';
        code.style.color = '#94a3b8';
        code.textContent = short;
        row.append(meta, code);
        return row;
    }

    const previewFiles = files.slice(0, PREVIEW);
    const restFiles = files.slice(PREVIEW);

    for (const f of previewFiles) container.appendChild(buildRow(f));

    if (restFiles.length > 0) {
        const restEl = document.createElement('div');
        restEl.dataset.role = 'read-rest';
        restEl.style.display = 'none';
        for (const f of restFiles) restEl.appendChild(buildRow(f));
        container.appendChild(restEl);

        const moreEl = document.createElement('div');
        moreEl.dataset.role = 'read-more';
        moreEl.dataset.count = restFiles.length;
        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px;padding:4px 0';
        moreEl.textContent = `▼ ${restFiles.length} more files`;
        container.appendChild(moreEl);
    }

    return container;
}

function renderGrepResults(raw, pattern) {
    const lines = raw.split('\n').filter(l => l.trim());
    if (!lines.length) return null;

    const PREVIEW = 5;

    function highlightPattern(text) {
        if (!pattern) return _escHtml(text);
        try {
            const escaped = _escHtml(text);
            const re = new RegExp(pattern, 'gi');
            return escaped.replace(re, s => `<span style="background:rgba(234,179,8,0.3);color:#fef08a;border-radius:2px">${s}</span>`);
        } catch { return _escHtml(text); }
    }

    function parseLine(text) {
        const m = text.match(/^(.+?):(\d+):(.*)$/);
        if (m) return { file: m[1], line: m[2], content: m[3] };
        const m2 = text.match(/^(\d+):(.*)$/);
        if (m2) return { file: null, line: m2[1], content: m2[2] };
        return { file: text, line: null, content: null };
    }

    function buildRow(text) {
        const p = parseLine(text);
        const row = document.createElement('div');
        row.className = 'grep-result-row';

        if (p.content !== null) {
            const meta = document.createElement('span');
            meta.className = 'grep-meta';
            if (p.file) {
                const shortFile = p.file.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '');
                meta.textContent = `${shortFile}:${p.line}`;
                meta.title = `${p.file}:${p.line}`;
            } else {
                meta.textContent = p.line;
            }
            const code = document.createElement('span');
            code.className = 'grep-code';
            code.innerHTML = highlightPattern(p.content.trimStart());
            row.append(meta, code);
        } else {
            const meta = document.createElement('span');
            meta.className = 'grep-meta';
            meta.textContent = '';
            const code = document.createElement('span');
            code.className = 'grep-code';
            code.style.color = '#38bdf8';
            const shortFile = p.file.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '');
            code.textContent = shortFile;
            row.append(meta, code);
        }
        return row;
    }

    const container = document.createElement('div');
    container.className = 'grep-results';
    container.style.marginTop = '6px';

    const previewLines = lines.slice(0, PREVIEW);
    const restLines = lines.slice(PREVIEW);

    for (const l of previewLines) container.appendChild(buildRow(l));

    if (restLines.length > 0) {
        const restEl = document.createElement('div');
        restEl.dataset.role = 'read-rest';
        restEl.style.display = 'none';
        for (const l of restLines) restEl.appendChild(buildRow(l));
        container.appendChild(restEl);

        const moreEl = document.createElement('div');
        moreEl.dataset.role = 'read-more';
        moreEl.dataset.count = restLines.length;
        moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px;padding:4px 0';
        moreEl.textContent = `▼ ${restLines.length} more lines`;
        container.appendChild(moreEl);
    }

    return container;
}

function _wsCompactLinks(links) {
    const div = document.createElement('div');
    div.style.cssText = 'margin-top:6px;padding-top:6px;border-top:1px solid rgba(51,65,85,0.5)';
    for (const [i, r] of links.slice(0, 8).entries()) {
        const title = r.title || r.name || '';
        const url = r.url || r.link || r.href || '';
        if (!url) continue;
        let domain = '';
        try { domain = new URL(url).hostname.replace(/^www\./, ''); } catch {}
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.style.cssText = 'display:block;font-size:10px;margin-top:2px;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none';
        a.onmouseenter = () => a.style.color = '#94a3b8';
        a.onmouseleave = () => a.style.color = '#64748b';
        a.textContent = `[${i + 1}] ${title || domain}${title && domain ? ' — ' + domain : ''}`;
        div.appendChild(a);
    }
    return div.children.length > 0 ? div : null;
}

// Wraps web search results in a collapsible — search results can be very long,
// and most of the time the first 5 lines are enough to decide if the result is useful.
function _wsCollapsible(el) {
    const PREVIEW_LINES = 5;
    const PREVIEW_HEIGHT = PREVIEW_LINES * 18;
    const body = el.querySelector('.markdown-body');
    if (!body) return el;

    const wrapper = document.createElement('div');
    wrapper.className = 'websearch-results';
    while (el.firstChild) wrapper.appendChild(el.firstChild);

    body.style.cssText += ';max-height:' + PREVIEW_HEIGHT + 'px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word';

    const hint = document.createElement('div');
    hint.style.cssText = 'color:#38bdf8;font-size:10px;cursor:pointer;margin-top:4px';
    hint.textContent = '▼ expand';
    let expanded = false;

    const linksEl = wrapper.querySelector('[style*="border-top"]');

    // Hide citation links by default — they clutter the preview; shown only when expanded
    if (linksEl) linksEl.style.display = 'none';

    const toggleWs = () => {
        expanded = !expanded;
        body.style.maxHeight = expanded ? 'none' : PREVIEW_HEIGHT + 'px';
        body.style.overflowY = expanded ? 'visible' : 'hidden';
        hint.textContent = expanded ? '▲ collapse' : '▼ expand';
        if (linksEl) linksEl.style.display = expanded ? 'block' : 'none';
    };

    if (linksEl) wrapper.appendChild(linksEl);
    wrapper.appendChild(hint);
    wrapper.style.cssText = 'cursor:pointer;overflow-x:hidden;max-width:100%';
    wrapper.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleWs(); });

    // rAF defers height check until after the element is in the DOM and has a real offsetHeight
    requestAnimationFrame(() => {
        if (body.scrollHeight <= PREVIEW_HEIGHT + 4) {
            hint.style.display = 'none';
            body.style.maxHeight = 'none';
            body.style.overflowY = 'visible';
            if (linksEl) linksEl.style.display = 'block';
        }
    });

    return wrapper;
}

// Multi-format parser: handles Perplexity sonar JSON, Brave/SerpAPI results arrays,
// raw text with embedded "Links: [...]" JSON, and Markdown-formatted search responses.
// Falls back gracefully — each branch returns null and the next tries.
function renderWebSearchResults(raw) {
    let data;
    try { data = JSON.parse(raw); } catch { data = null; }

    if (data) {
        if (data.result && typeof data.result === 'string') {
            const el = document.createElement('div');
            const body = document.createElement('div');
            body.className = 'text-xs markdown-body';
            body.style.cssText = 'line-height:1.5;color:#cbd5e1';
            body.innerHTML = DOMPurify.sanitize(marked.parse(data.result));
            el.appendChild(body);
            if (Array.isArray(data.citations) && data.citations.length > 0) {
                const links = data.citations.map((url, i) => ({ title: '', url }));
                const linksEl = _wsCompactLinks(links);
                if (linksEl) el.appendChild(linksEl);
            }
            return _wsCollapsible(el);
        }
        const results = data.results || data.web?.results || data.organic_results || null;
        if (Array.isArray(results) && results.length > 0) {
            const el = document.createElement('div');
            const body = document.createElement('div');
            body.className = 'text-xs markdown-body';
            body.style.cssText = 'line-height:1.5;color:#cbd5e1';
            const md = results.slice(0, 6).map((r, i) => {
                const title = r.title || r.name || '';
                const url = r.url || r.link || r.href || '';
                const snippet = r.snippet || r.description || r.body || '';
                const link = url ? `[${title || url}](${url})` : (title || '');
                return `**${i + 1}.** ${link}${snippet ? '\n' + snippet : ''}`;
            }).join('\n\n');
            body.innerHTML = DOMPurify.sanitize(marked.parse(md));
            el.appendChild(body);
            return _wsCollapsible(el);
        }
    }

    const linksIdx = raw.indexOf('Links: [');
    if (linksIdx >= 0) {
        const arrStart = raw.indexOf('[', linksIdx);
        let depth = 0, arrEnd = -1;
        for (let i = arrStart; i < raw.length; i++) {
            if (raw[i] === '[') depth++;
            else if (raw[i] === ']') { depth--; if (depth === 0) { arrEnd = i + 1; break; } }
        }
        if (arrEnd > arrStart) try {
            const links = JSON.parse(raw.slice(arrStart, arrEnd));
            if (Array.isArray(links) && links.length > 0) {
                const el = document.createElement('div');
                const textAfterLinks = raw.slice(arrEnd).trim();
                const body = document.createElement('div');
                body.className = 'text-xs markdown-body';
                body.style.cssText = 'line-height:1.5;color:#cbd5e1';
                if (textAfterLinks) {
                    body.innerHTML = DOMPurify.sanitize(marked.parse(textAfterLinks));
                } else {
                    const md = links.slice(0, 8).map((r, i) => {
                        const title = r.title || r.name || '';
                        const url = r.url || r.link || '';
                        return `**${i + 1}.** [${title || url}](${url})`;
                    }).join('\n\n');
                    body.innerHTML = DOMPurify.sanitize(marked.parse(md));
                }
                el.appendChild(body);
                const linksEl = _wsCompactLinks(links);
                if (linksEl) el.appendChild(linksEl);
                return _wsCollapsible(el);
            }
        } catch {}
    }

    const metaMatch = raw.match(/^_(.*?\|.*?tokens.*?\|.*?\$[\d.]+)_\s*/m);
    if (metaMatch || raw.match(/^#{1,3}\s/m)) {
        const el = document.createElement('div');
        if (metaMatch) {
            const meta = document.createElement('div');
            meta.style.cssText = 'font-size:10px;color:#64748b;margin-bottom:4px';
            meta.textContent = metaMatch[1].replace(/^_|_$/g, '').trim();
            el.appendChild(meta);
        }
        const text = metaMatch ? raw.slice(raw.indexOf(metaMatch[0]) + metaMatch[0].length).trim() : raw;
        const body = document.createElement('div');
        body.className = 'text-xs markdown-body';
        body.style.cssText = 'line-height:1.5;color:#cbd5e1';
        body.innerHTML = DOMPurify.sanitize(marked.parse(text));
        el.appendChild(body);
        return _wsCollapsible(el);
    }

    return null;
}
