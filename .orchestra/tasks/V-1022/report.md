# V-1022 — red browser tests on main 34e78f83

Not run (hub cannot run Playwright); fixed by reading the code.

## test_grok_usage_frontend::test_usage_control_keeps_spark_and_adds_grok_third_column
`usage.js` always renders `<section data-usage-provider="hub">` after claude/codex/grok (V-1012, and
`test_usage_analytics_frontend.py:913` asserts it), so the hub pool is a deliberate 4th column; OpenRouter
is only rendered when `_usageData.openrouter` exists (absent in this harness). Test now asserts the exact
ordered list `["claude", "codex", "grok", "hub"]` (stricter than a count). No markup change.

## test_frontend timeline tests (0 markers / KeyError 'tall')
Cause: `_tagChatTimelineNode` (app.js, inside the `_chatTimelineObserver`…`_prepareChatAnchorRestore` slice)
calls `orchLocale()` (utils.js global, added with the i18n formatters) when a timestamp is given. The bare
harness defines `$` and `T` but not `orchLocale`, so the first `addTimelineEntry`/`addSized` threw
ReferenceError, the script aborted before `initChatTimeline()`, giving 0 markers (and no rows → KeyError 'tall').
Fix: both harnesses now stub `const orchLocale = () => 'en-US'` next to `$`/`T` (same treatment as the other
cross-file globals). App code untouched; assertions unchanged. `git log -p` was unavailable in this copy
(no .git); the cause is confirmed by the code, please confirm by the test run.
