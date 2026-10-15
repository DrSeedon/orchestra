# V-858 implementation

## Behavior

- The first left-panel tab is INFO. Its width starts at 380 px, changes with a keyboard and pointer/touch resizer, and is saved in browser `localStorage`. On mobile, the existing narrow-screen-hidden panel opens from the dashboard header as a drawer.
- The width jump came from `switchLeftTab('jobs')` assigning `filePanel.style.width = '380px'` and clearing it on other tabs. The `#file-panel` CSS transition animated that change. Tab selection no longer sets width; the resize control owns it.
- Orchestrator MCP sessions create durable SQLite task cards through `propose_task`. The API checks MCP proof and the caller's stored role. Worker attempts return 403 with an orchestrator-only explanation. Approval uses a stable message-delivery ID and sends `владелец одобрил: <title> — <summary>` to that same orchestrator. Repeated clicks reuse the receipt; no worker is created or spawned. Rejection is durable.
- Worker `update_checklist(items, completed, current)` stores the ordered checklist under `(session_id, task_id)`, so `progress_pct` clearing at turn end does not clear task state. INFO shows full items and N из M; session list cards show the same count and a compact bar. Checklist updates reset the inactivity timer.
- The reminder fires at 300 seconds of checklist inactivity, once per turn. `checklist_reminder` and `checklist_update` journal rows share a turn key; `checklist_turns.updated_after_reminder_at` supports the effect count through `app.checklists.reminder_effect_counts()`. The experiment disables after 2026-10-22 UTC or earlier with `ORCHESTRA_CHECKLIST_REMINDERS=0`; the flag is documented in `.env.example`.

Width preference is browser-local and is not synchronized between devices. The mobile screenshot uses the responsive drawer.

## Verification

- Core/route tests: `tests/test_task_proposals_v858.py`, `tests/test_checklists_v858.py`, `tests/test_routes_surface.py`, `tests/test_attention_v576.py`, `tests/test_sessions_conditional.py`, and `tests/test_reducer_role.py` — 25 passed.
- Session lifecycle: `tests/test_session.py -k 'waiting_status_finishes_turn or reconnect_does_not_inject_into_newer_turn'` — 2 passed. This covers checklist persistence across `finish_turn_status` and the changed turn-start hook.
- Existing dashboard smoke tests: `tests/test_frontend.py -k 'dashboard_loads or sidebar_agents_visible or no_js_errors or agent_info_panel_exists'` — 4 passed, 118 deselected. `tests/test_i18n_dashboard.py` — 6 passed.
- A headless Chromium pass rendered the actual `dashboard.html`, `style.css`, Tailwind CSS and `app.js` with fixture API responses. At 1440×1050, the panel resized from 380 to 432 px, saved 432 to `localStorage`, and remained 432 when switching JOBS ↔ INFO. At 390×1000, the drawer opened/closed, document width stayed 390 px, mobile touch drag resized 351 to 331 px, and approve/reject controls changed their cards. No JavaScript errors or failed requests. Screenshots: `impl-desktop.png`, `impl-mobile.png`.
- `scripts/check_instruction_contract.py`, Python compilation, `node --check app/static/js/app.js`, and `git diff --check` passed.

## Operations

Python and SQLite startup code changed; a service restart is required before the feature is live. The additive tables are created in startup with `CREATE TABLE IF NOT EXISTS`; there is no offline migration. I did not restart the service. The full repository suite was not run.
