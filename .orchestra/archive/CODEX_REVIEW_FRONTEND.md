# Codex Review: Frontend (app.js + style.css)

**Model**: GPT-5.5 via Codex CLI
**Date**: 2026-05-12
**Files**: `app/static/js/app.js` (~3200 lines), `app/static/css/style.css` (~120 lines)

## Summary

No P0 (crash/data-loss/security) or P1 (visible UX bugs) findings.
4 × P2 (real problems), 4 × P3 (suggestions).

---

## [P2] Stale async responses can write into the wrong current view

**Lines**: `app.js:196`, `app.js:318`, `app.js:779`, `app.js:2902`

`loadMoreLogs`, `openFilePreview`, `fetchAgentContext`, and `loadFileTree` all read global `selectedAgent/currentScope` or write shared DOM after awaits without confirming the user is still on the same agent/file/scope. Fast switching can prepend old logs, show the wrong file, or display old context.

**Fix**: capture `agent/scope/path` or a monotonically increasing request id before each fetch, then ignore results if it no longer matches. Abort previous file/tree loads where useful.

---

## [P2] Session names are not URL-encoded in most session path segments

**Lines**: `app.js:144`, `app.js:203`, `app.js:295`, `app.js:782`, `app.js:896`, `app.js:1056`

`compactAgent` encodes the name, but stream/logs/prompt/context/send/interrupt do not. Names containing `/`, `?`, `#`, etc. can break routing or target the wrong endpoint. The create form allows arbitrary names.

**Fix**: centralize a helper like `sessionPath(name) => /api/sessions/${encodeURIComponent(name)}` and use it everywhere.

---

## [P2] Streaming render reparses the entire response on every chunk

**Lines**: `app.js:1348-1361`

Each stream event appends to `streamContent`, then runs `marked.parse(streamContent)` and replaces `innerHTML`. Long responses become O(n²) work and can make the UI stutter/freeze.

**Fix**: throttle markdown rendering with `requestAnimationFrame` or a 100-200ms timer, render plain text while streaming, then do one final markdown parse on the closing `text` event.

---

## [P2] Edit diff rendering can freeze on large edits

**Lines**: `app.js:2720-2725`, `app.js:2778-2781`

`buildDiffLines` builds an LCS matrix for all old/new lines. Large Write/Edit tool calls can allocate huge matrices and block the main thread.

**Fix**: cap detailed diffing by line/character count. For large inputs, show file path plus first/last N lines or use a bounded diff algorithm/timeout.

---

## [P3] Image overlay leaks keydown listeners when closed by click

**Lines**: `app.js:1072-1080`

Clicking the overlay removes the DOM node but leaves the Escape listener attached until Escape is pressed later.

**Fix**: use a shared `cleanup()` that removes both overlay and listener, and call it from click and Escape.

---

## [P3] Chat trimming can remove the "Load more" control

**Lines**: `app.js:179-193`, `app.js:1343`, `app.js:2443`

When `MAX_CHAT_NODES` is exceeded, `removeChild(chat.firstChild)` can delete `#load-more-btn`; it is not recreated during normal append trimming, so older history becomes harder to reach.

**Fix**: preserve `#load-more-btn` during trimming or call `updateLoadMoreBtn()` after trimming.

---

## [P3] Markdown preview image click handling does not survive sanitization

**Lines**: `app.js:342-352`

The renderer emits inline `onclick="openFilePreview(...)"`, but DOMPurify strips event handlers. Relative markdown images render, but the intended click-to-preview behavior will not work.

**Fix**: render sanitized HTML, then attach click listeners to images programmatically, using the resolved file path/src.

---

## [P3] Code and diff CSS forces aggressive word breaking

**Lines**: `style.css:56-57`, `style.css:89`, `style.css:111`

`word-break: break-all` makes code, commands, and grep/diff output hard to read or copy accurately.

**Fix**: prefer `white-space: pre` or `pre-wrap` with `overflow-x: auto` for code/diff blocks, and keep aggressive wrapping only for prose containers.

---

*Verification: `node --check app/static/js/app.js` passes.*
