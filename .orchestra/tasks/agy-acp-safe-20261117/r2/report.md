# R4 exact correction wave — mock acceptance

VERDICT: six Astra findings and CEO CSS item addressed by scoped regressions.
This is MOCK-ONLY acceptance, with CEO image sign-off pending. Overall release gate
remains RED for native/live authorization, fixed-profile limits and legacy acceptance.
Base faabd24e5236833a8af238fad2e09aeb907d091c; branch agy-acp-safe.
Imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app/__init__.py.
This report and its evidence belong to the immutable local commit in the handoff.

## Exact changes

1. Ordered journal writes use a shielded predecessor for ordering only. Its exception
   is consumed by the successor; that successor still executes its own write. Its own
   failure propagates. The original failed write remains visible in failure telemetry.
   Regression: first of3 raises, second/third execute and persist, one failure recorded.
2. A confirmed aiogram TelegramRetryAfter updates the existing shared flood barrier and
   leaves the bound outbox chunk pending with next_attempt_at. Restart preserves pending;
   the same chunk retries only after the delay. Timeout/reset remain unknown and block
   blind replay. Rate admission remains before SENDING; no retrying transport wrapper.
3. get_logs_forward uses id > cursor ascending even for0. Legacy get_logs(0) remains a
   tail API. ACP TG drain and SSE follow use the explicit forward scan. Empty-attach
   regression delivers120 records in exact order across100+20, none skipped/duplicated.
4. ToolReducer emits immutable tool_update revisions on normalized input/name changes.
   Same tool_use_id; no second invocation count/header. UI replaces one keyed full card
   or updates one compact card, preserves terminal result, and handles input-before-call.
   TG sends one concise argument revision. Terminal metadata retains canonical tool_name
   and normalized raw_input. Nullable additive log column is exposed by history/sync;
   existing immutable rows and callers retain their prior shape. Mock body/metadata are
   redacted at the same adapter boundary. No production DB migration was executed.
5. ACP tool_stream carries explicit replace=true snapshots through AgentSession, broker
   cache/replay and JS renderer. A -> AB yields AB, non-prefix replaces, reconnect is
   idempotent. Existing no-flag stream deltas keep append semantics.
6. ACP stream/thinking nodes and buffers are keyed by item_id/event_id. Durable SSE rows
   expose the matching item_id. Late finalA is inserted/finalized without clearing liveB;
   reconnect snapshots replace. Durable DOM identity survives bounded map eviction.
   Legacy no-ID/non-ACP rendering stays on its existing single-buffer path.
7. Native request cards use existing dashboard surfaces/tokens: header, readable details,
   state badge, spaced controls and disabled styling. The fixture loads real
   design-system/style/tailwind CSS and dashboard dark body layout. Native details
   measured contrast13:1. Screenshot: ui-renderer.png, ready for CEO visual review.

## Checks (actual results, not summed across overlapping runs)

- Final new regression file:10 passed,0 failed,0 skipped,2 warnings,9.00s.
- Broader compatibility:298 passed,3 failed,0 skipped,2 warnings,74.10s.
  All3 failures are tests/test_logs_sync.py: TestLiveSessions::test_lists_every_session_including_archived,
  TestRoute::test_endpoint_clamps_arguments, TestRoute::test_chat_snapshot_is_never_served_from_http_cache.
  They hit the unchanged subprocess audit refusing git init, through the legacy
  task-runtime/full app lifespan fixtures (conftest.py589). They are NOT passed, skipped
  or weakened. No measured baseline rerun is claimed. Full stack retained in compatibility.log.
- Final headless UI: PASS, page_errors0, actual renderer + real mock-stdio journal replay,
  full/compact input updates, output snapshots/replay, text/thinking segmentation and
  stable DOM identity. Final log ui-final-identity.log; ui-check.json records assertions.
- Earlier UI fixture checks failed twice: missing actual app.js stamping helper, then
  exact text comparison against Markdown trailing newline. Helper loaded from real
  source; comparison corrected to rendered text semantics. Subsequent checks passed.
- Explicit negative controls:2 passed,3.83s. Google/TG DNS, external socket and real
  executable attempts denied before resolution/exec. No provider help/version probes.
- Instruction contract, Python AST, node --check, source diff and focused secret check PASS.
  Warnings are existing websockets deprecations. Exact commands/deadlines/exits are in
  commands.json, original raw log SHA256 and whitespace-only normalization documented.
- Historical frozen15F/18P/79E and the known Claude-policy compact fixture were not rerun.

## Isolation and cleanup

Existing kernel unshare --net (lo only, external_routes0), fake executable allowlist,
synthetic HOME/profile/SQLite, production/protected SQLite audit guards unchanged.
Fake Bot only; no real Google/account/OAuth/TG, credential/keyring/.env reads/copies,
real agy, paid fallback, provider/T3/proxy/billing changes or public publication.
UI used one owned headless Chromium with local/intercepted assets and endpoints.
Audit is not a general filesystem sandbox and is not inherited by the controlled fake;
the kernel network namespace still applies to that child. No security overclaim.
Owned fake/runner/UI/browser processes0 after completion. Main HEAD4e4e58dcb and its
three tracked dirty files preserved; unrelated untracked directories not read/modified.
No push, merge, deployment, restart or service activation. cleanup.json/source-checks.json.

## Pointers and remaining gates

All evidence under /home/kesha/orchestra-worktrees/agy-acp-safe/.orchestra/tasks/agy-acp-safe-20261117/r2/:
verification.json, acceptance-matrix.json, commands.json, report.md, ui-renderer.png,
ui-check.json, late-input-transcript.json, compatibility.log, r4-final.log, negative-controls.log.
Sources: app/session.py, acp_tg_delivery.py, acp_tools.py, db.py/schema.sql,
live_broker.py, routes/sessions.py, backend_antigravity.py, tg_bridge.py,
static/js/chat.js, static/css/style.css; regressions tests/test_antigravity_r4.py
and tests/antigravity_foreground_ui.py.

No real installed native CLI compatibility or account eligibility claim. Fixed-profile
binding only; same-HOME account-change detection unsupported. Existing capabilities,
receipt before-write/SUBMITTED-after-drain/UNKNOWN-no-replay, disabled/provenance guards,
permission lifecycle and no automatic account/model fallback remain unchanged.
Production/live activation requires later explicit authorization; screenshot approval
belongs to CEO, and the three broader fixture failures remain open in this strict runner.
