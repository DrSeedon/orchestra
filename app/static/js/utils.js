/* utils.js — pure helpers, marked setup, autolink. Loaded before app.js. */

// Client task/payment amounts use the configured billing currency; model costs are stored in USD.
const CUR = document.body.dataset.currency || '₽';
const MODEL_COST_CURRENCY = '$';
const $ = (s) => document.querySelector(s);
const taskNum = (par) => String(par || '').replace(/^[A-Z]+-/, '');

function _escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
// DOM-based escaping is safer than regex — handles all edge cases without a lookup table
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// Claude injects XML-style tags (e.g. <thinking>) — strip them before markdown render to avoid display noise
function _stripXmlTags(text) {
    return text.replace(/<\/?[a-z][a-z0-9_-]*(?:\s[^>]*)?\s*>/gi, '');
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
