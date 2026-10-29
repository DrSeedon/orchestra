# V-1131 — DONE

Updated only the canonical `worker-lifecycle.md` module and this report. The dated owner
decision requires every completed hub worker, regardless of label or specialization, to go
through `worker_wip` and `kill_worker` in the same completion handling after its result is
merged into `main` or research findings are saved, with no further explicitly assigned task.
It supersedes the earlier game-design exception and disallows warm-context, future-topic,
backlog, or 72-hour retention for hub workers. Native-worker retention remains separate.

The shared kill gate still protects uncommitted and unmerged work. Required validation,
acceptance, and unfinished assigned phases must finish promptly before completion. A research
status alone is insufficient, but accepted, saved research with no remaining phase qualifies.
Restart recovery and the assignment guidance remain unchanged.

Checks: reviewed the before/after diff and completion cases (assigned follow-up; pending
validation or acceptance; uncommitted or unmerged work; accepted saved research; legacy labels;
native-worker activity boundary). Checked module wrapper integrity and whitespace. No runtime
code, routing, root instructions, temporary rules, changelog, or other agents were changed.
No prose assertions or full test suite were added or run; this is a documentation-only change.
No Python or `app` import was needed. Host instruction/manifest validation, canonical merge,
removal of the superseded temporary rule in that same turn, and worker WIP/archive remain
with the parent; this copy cannot verify host prompt loading or live lifecycle enforcement.
