# Orchestra Bug Reports — Moved Out of This File

This file is no longer live. `report_bug` writes to an inbox outside the working tree,
so a bug report neither dirties the checkout nor blocks merges.

## How to view reports

- **By notification** — when a report is filed, the orchestrator for that scope receives
  a message (#56, 04.08.2026). Authors are not notified about their own reports.
- **By endpoint** — `GET /api/report_bug` returns the entire inbox as one Markdown document
  (legacy content plus every report). This is the store's ONLY reader: nothing calls it
  internally, but no other endpoint exposes these data, so do not remove it.

There is no longer a dashboard notice: the “🐛 New bug reports” banner with its “Read”
button and the `GET /api/report_bug/status` endpoint were removed on 04.08.2026 (#53) at
the owner's direct request. It was a persistent distraction and polled every 30 seconds;
the orchestrator notification replaced it. This was the cost of having no reader: seven
reports from four agents sat in the store for two days, while half of one report had
already been fixed on `main`.

## Where reports are stored

The state root depends on whether the systemd unit defines `StateDirectory`:

| Condition | Inbox path |
|---|---|
| The unit defines `StateDirectory=orchestra` (VPS, `deploy/orchestra.service.template`) | `/var/lib/orchestra/bug-inbox/` |
| No `StateDirectory` → fall back to XDG (local machine) | `$XDG_STATE_HOME/orchestra/bug-inbox/`, defaulting to `~/.local/state/orchestra/bug-inbox/` |

To check a particular machine: `systemctl cat orchestra | grep StateDirectory`.

Inside the inbox:
- `legacy.md` — a snapshot of this file at migration time (341 lines, everything still open
  on 01.08.2026). It is immutable and read first.
- `records/*.md` — one file per report, named `<UTC-timestamp>-<uuid>.md`.

Git retains this file's history: `git log -- BUGS.md`; the last live entry is `d1429b1`.
