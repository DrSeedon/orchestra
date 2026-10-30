# V-1137 report

Removed the composer "Message queue" panel (div#queued-messages), refreshQueuedMessages/render/cancel code, the 5 s timer, the two per-selection calls and the post-send refresh, plus 9 obsolete i18n keys.
Generation counter renamed `_chatViewGeneration`; `_resetChatView()` keeps the saved-draft capture. The `restoredGeneration` update moved from the refresh into `_noteDraftRestored()`, called at the end of `restoreDraft()` (app.js).
Backend/API/mailbox untouched.

Tests: tests/queued_messages_v1134_* keep the seven send/draft race scenarios. Per orchestrator review the queue_panel_absent scenario and the source-identifier test were deleted (no absence test). The harness now loads the production `saveDraft`/`restoreDraft` from app.js by bounded regex extraction (Node: node.cjs; browser: `_draft_functions()` in the pytest file) and `switchView` calls them, so the real `_noteDraftRestored()` invocation is exercised.
Mutation: deleting the production `_noteDraftRestored();` line in app.js fails `accepted_saved_draft_aba`; restored afterwards.
Ran (uv 0.11.28 frozen, `--noconftest`): 7 Node scenarios passed. Imported `app` is the namespace dir of this partial copy (no routes/mailbox/quota_gate).
Not run: Chromium variants (no browser fixture here; browser harness changed but unexecuted), backend tests (cannot import app.mailbox here; unchanged). `node --check` passed earlier on chat.js, app.js, i18n.js.
