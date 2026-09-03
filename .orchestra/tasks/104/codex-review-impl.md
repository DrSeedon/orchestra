The patch treats image-lane admission as successful delivery and bypasses both the durable text fallback and mirror delivery. The focused test suite passes, but it does not exercise asynchronous image failure or configured mirrors.

Full review comments:

- [P1] Preserve text until image delivery succeeds — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:3056-3061
  When Telegram fails after the asynchronous handoff—such as a marker timeout, media-edit failure, reset, or cancellation—`_ImageSubmission(True)` only means the image was accepted into the lane; its `completion` may still resolve to `None`. Continuing here permanently suppresses the textual tool result, leaving either no result or only the `🖼` placeholder.

- [P2] Keep mirrored tool results when suppressing primary text — /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:3056-3061
  When an orchestrator has a configured mirror and a result image is accepted, this `continue` skips the `_mirror_send` below. `_send_result_image` sends only to the primary group, so the mirror receives the tool invocation but deterministically loses every successfully rendered Read/Grep/Bash/Glob result.

## Round (2026-07-30T04:18:11Z)

Naturally, “accepted” means “the queue owns the problem now.” 🖼️

### Re-review status

- **P1 — RESOLVED BY CONTRACT.** Accepted handoff intentionally suppresses primary text immediately at [app/tg_bridge.py:3057](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:3057). Media-edit failure retains the pre-sent marker; completion failure is telemetry, not a second fallback trigger.
- **P2 — FIXED.** Execution now reaches `_mirror_send` for both accepted and rejected submissions at [app/tg_bridge.py:3073](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-speed/app/tg_bridge.py:3073).

### New findings

None in the requested scope.

### Verdict

**APPROVED.** Six focused tests passed, including accepted/rejected mirror delivery and asynchronous marker/media failure contracts.

The mirror now gets dinner even when the primary chat orders the picture menu.
