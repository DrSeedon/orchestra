# #292 report

Status: **DONE — procedural REJECT / inconclusive**.

Files added under `docs/tasks/292/`: frozen `protocol.json`, `prereg-lock.json`,
three capsules, handoff corpus, answer key, runner, blind scorer, aggregation
program, machine-readable evidence, stop record, research report, and Codex
review. No runtime/config files were touched.

Checks:

- `python3 -m py_compile docs/tasks/292/*.py` — passed.
- prereg lock created before model invocation — protocol SHA recorded.
- sealed-clone preflight — all three cases had named solution objects unreachable.
- first preregistered CLI cell `t241/P/r1` — aborted with `stream-json contained no result event`.
- exact usage/turn count — unavailable because no result event was emitted; recorded as null.
- replacement/fan-out/scoring — zero.
- independent Codex review — procedural stop accepted; audit limitations recorded in `research.md`.

No causal conclusion is licensed. Re-running would require a new, separately
preregistered pilot after fixing the audit issues; it is not part of #292.

Memory: updated — when a preregistered model CLI emits no parseable terminal
event, preserve the raw stream before raising; otherwise exact usage/turn
provenance is irrecoverable and the run must stop without replacement.
