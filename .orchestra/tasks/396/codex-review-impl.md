<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The finite-rate arithmetic is dimensionally correct, and the single-event-loop production case does not have an active lock race. I found four issues: renderer lifecycle leaks, unsafe loop rebinding outside the production assumption, duplicated arithmetic between card and Telegram text, and synchronous SQLite work in an async hot path.

## Findings

- suggestion: `app/limits_card.py:314-318` — rebinding on a different event loop replaces the lock and clears browser/playwright globals without closing the old driver; an in-flight renderer can then race with the new renderer’s globals → keep renderer state per loop or explicitly close the old browser/playwright before rebinding.

- suggestion: `app/limits_card.py:308-318` — the persistent Playwright driver/browser is never closed during application shutdown. The `RuntimeError: Event loop is closed` from `BaseSubprocessTransport.__del__` is shutdown noise in the sense that the OS will reclaim the child, but it is also evidence of a real lifecycle leak and makes tests noisy → add FastAPI shutdown cleanup that closes the browser and stops Playwright on its owning loop.

- suggestion: `app/limits_card.py:168-176`, `app/routes/system.py:1127-1136`, `app/tg_bridge.py:3489-3494` — the picture recomputes `left` from `rate` and current weekly usage, while Telegram uses the separately computed and rounded `windows_left`; rounding `rate` to four decimals before the card calculation can make the displayed values diverge at boundaries → compute the window count once and have both consumers use that canonical value.

- suggestion: `app/routes/system.py:1119-1136` — `_quota_headroom()` performs a potentially multi-row SQLite read and timestamp/float processing synchronously inside the async `/api/usage` route, which is polled frequently and also reused by Telegram; history failures are caught, but the event loop can still be blocked → cache the measurement briefly or move the synchronous history calculation off-loop.

The week formula itself is correct: `rate * 100` is weekly percentage cost per 5-hour window, and positive finite rates prevent division by zero or negative results. However, `bool` values pass `isinstance(..., (int, float))`; `True` is accepted as a rate. This is malformed-input tolerance rather than a current division bug. Non-finite values are also not explicitly rejected.

## Verdict

Needs work: no production single-loop lock race found, but shutdown cleanup and arithmetic ownership should be fixed before merge.
