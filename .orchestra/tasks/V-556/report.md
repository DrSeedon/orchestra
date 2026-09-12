# V-556 — dashboard after-turn send

## Result

The dashboard now has a second `After turn` button. It sends `after_turn=true` to
the existing session route. If the selected agent is running/waiting, the route stores
the message in the existing durable `mailbox`; its turn manager drains that mailbox only
after the current turn has published its terminal idle transition. If the agent is idle,
the route falls through to the existing immediate `manager.send` path.

Queued dashboard messages are listed below the composer, survive a server restart in
SQLite, and can be cancelled while not yet claimed by the turn-end delivery. A claimed
message is shown as `доставляется`; cancellation then correctly loses the race instead
of falsely reporting success.

## Checks

- `python3 -m compileall -q app tests/test_mailbox.py` — passed.
- `node --check app/static/js/chat.js` — passed.
- `node --check app/static/js/app.js` — passed.
- `git diff --check` — passed.
- `python -m pytest` could not run in this worktree: `python` is absent and
  `/usr/bin/python3` has no `pytest` module. The focused tests added to
  `tests/test_mailbox.py` cover busy queueing, idle immediate delivery, and cancellation.
- A direct SQLite smoke check verified queue insertion, pending visibility, and cancellation.
- Mutation check: changing `mailbox.cancel` to require `claimed_at IS NOT NULL` made the
  direct cancellation assertion fail (`AssertionError: unclaimed queued message must cancel`);
  the mutation was reverted.

The executor-owned codex review was attempted after the commit but the review service refused
to start because its Orchestra database requires an offline schema migration. No substitute
reviewer was used.

## Pre-mortem

- A queued row could be lost on restart: the row remains in SQLite until
  `mark_delivered` runs; an in-flight claim is lease-reclaimable. The direct smoke check
  covered persistence, while a live process restart was not run.
- A cancel could race with turn-end delivery: the SQL update requires both
  `delivered_at IS NULL` and `claimed_at IS NULL`; the committed test covers the claimed
  negative shoulder.
- Existing agent-to-agent or immediate dashboard messages could be diverted: the new branch
  requires `after_turn=true` plus `channel=dashboard`; existing focused mailbox tests retain
  the default immediate path.
- The queue panel could show stale data after switching agents: refresh captures and checks
  the name/scope pair before rendering, and a five-second refresh removes delivered rows.

The existing full-suite red tests named by the task were not run.

## Deployment note

Python route/mailbox changes require the owner to restart Orchestra; dashboard JS/CSS and
the template are picked up hot. Orchestra was not restarted.
