/* utils.js — pure helpers, marked setup, autolink. Loaded before app.js. */

const CUR = document.body.dataset.currency || '₽';
const $ = (s) => document.querySelector(s);
const taskNum = (par) => String(par || '').replace(/^[A-Z]+-/, '');

function _escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function _stripXmlTags(text) {
    return text.replace(/<\/?[a-z][a-z0-9_-]*(?:\s[^>]*)?\s*>/gi, '');
}

marked.setOptions({ breaks: true, gfm: true });

DOMPurify.addHook('uponSanitizeElement', (node) => {
    if (['STYLE', 'HTML', 'HEAD', 'BODY', 'META', 'LINK', 'TITLE', 'SCRIPT'].includes(node.tagName)) node.remove();
});

const _autolinkRe = /(?<!\w)((?:https?:\/\/|ftp:\/\/)[^\s<>\]\)]+|(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:\/[^\s<>\]\)]*)?)(?!\w)/g;
function autolinkText(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const walk = (node) => {
        if (node.nodeType === 3) {
            const t = node.textContent;
            if (!_autolinkRe.test(t)) return;
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
marked.parse = (src, ...args) => {
    const escaped = src.replace(/(?<!\~)\~(?!\~)/g, '\\~');
    const html = _origMarkedParse(escaped, ...args);
    return autolinkText(html);
};

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
