# V-871: proposal cards

## Changes

Removed the two-line clamp from `.task-proposal-summary` and enabled wrapping of long words. The rule lives in `style.css`, not Tailwind, so the generated Tailwind stylesheet did not need rebuilding.

Both owner decisions now use the durable message-delivery path to the proposing orchestrator. Rejection sends `владелец отклонил: <название>`; approval keeps its existing `владелец одобрил: <название> — <суть>` text. An optional reason/instruction is appended to either message. The decision action and exact message are persisted before delivery, so repeats reuse the same receipt and cannot send a duplicate or change a pending decision. Known-unsent changed messages rotate to a new delivery ID. Existing in-flight approvals are migrated to the approval message they used before this change. No decision creates a worker.

The card's right-side «Причина» button opens an optional text field. Its draft survives INFO-panel polling, and retrying a pending decision reuses the persisted message. Rejection cards now show that the message reached the chat.

## Verification

- Core, route, and generated-CSS checks: `uv run --frozen python -m pytest tests/test_task_proposals_v858.py tests/test_routes_surface.py tests/test_tailwind_css.py -q` — 13 passed. This includes one-message rejection/no worker, optional reason for approval and rejection, unchanged no-reason approval text, and migration of a legacy in-flight approval.
- Browser suite: `uv run --frozen python -m pytest -m browser tests/ -q` — 199 passed, 7 skipped, 4439 deselected.
- Rendered the actual dashboard template, CSS, and JS with fixture data in Chromium at 1440×1000 and 390×844. The long summary measured 101 px high on desktop and 113 px on mobile, with `scrollHeight == clientHeight` in both; the mobile document stayed 390 px wide. The optional reason field rendered, and approve/reject clicks both sent the entered text in the request body.
- Screenshots: [before desktop](before-desktop.png), [after desktop](after-desktop.png), [before mobile](before-mobile.png), [after mobile](after-mobile.png).

Python routes and the SQLite schema migration changed. The running service needs an owner-initiated restart; none was performed.
