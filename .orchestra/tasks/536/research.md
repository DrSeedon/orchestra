# #536 — Codex writer conflicts after Orchestra restart

## Question
Context: detached Codex app-server sessions after supervisor restart. Change: observe native writer contention before durable admission and expose typed failure through the existing #380 protocol. Baseline: idle projection and asynchronously accepted QUEUED receipts. Outcomes: every known-conflict send is rejected, already accepted receipts become FAILED_BEFORE_SUBMIT with a typed reason, owned running turns keep steering, dead lock owners do not prevent reconnect.

## Hypotheses and falsifiers
- Stale files survive dead writers and block resume. Falsifier: an unlocked stale file can be acquired, or a reported incident still has a kernel lock owner.
- Surviving app-server owns the thread after the supervisor loses or releases its transport. Falsifier: no kernel lock owner exists at the same instant as conflict, or the owner exits but the conflict remains reproducible.
- The #380 terminal receipt remains the queue head. Falsifier: current `_TERMINAL_DELIVERY_STATES` excludes failed receipts and runner advances after failure.

## Findings
- CONFIRMED (tier 1): on 2026-09-07 the old voice-astra thread `01a0776b-d1b7-7b83-b4e9-e236d37340eb` still had kernel FLOCK `69: FLOCK  ADVISORY  WRITE 1169478 08:01:10487033 0 EOF`. `/proc/1169478/fd/32` pointed to that thread's lock. PID 1169478 was `codex ... app-server --stdio`, parent 1169464 was `node /usr/bin/codex`, whose parent was PID 1. Both started before the current supervisor. `systemctl show orchestra.service -p KillMode -p MainPID` returned `MainPID=1225105`, `KillMode=process`. This is a surviving process, not a lock without a process.
- CONFIRMED (tier 2): Codex 0.153.4 `writer_lock.rs` uses `File::try_lock()`. The exact conflict comes from `TryLockError::WouldBlock`; stale filenames alone do not block acquisition. The first acquisition cleans unlocked stale files under a coordination lock. Deleting a lock file held by another process would bypass this protection [1,2].
- CONFIRMED (tier 1+2): the journal contains `voice-astra ... adopted a live CLI; no turn was in flight`, followed by `releasing adopted CLI at the turn boundary so new tools and prompt take effect`, and then the active-writer failure. `app/session.py::_refresh_stale_backend` drops the adopted backend; `app/backend_jsonrpc.py::teardown_adopted` only signals a PID when one is recorded. The examined session row had `cli_pid=0, cli_started_at=0`. Successful fd adoption is not proof that teardown can terminate its writer.
- LIKELY (tier 1+2, historical metadata incomplete): lost/zero process identity during adoption allowed the old writer to remain when its transport was released. The current PID pair is alive, so even a wrapper-only signal cannot be assumed to have happened in this incident. No unobserved kill is asserted.
- CONFIRMED (tier 2): `publish_backend_fds` publishes pipes but does not save PID identity; graceful `handover_session` saves PID and start time separately. `KillMode=process` intentionally permits descendants to survive. A correct fd handoff and a correct identity handoff are separate requirements.
- CONFIRMED (tier 2): `thread/unsubscribe` is not an immediate release mechanism: upstream documentation says unloading occurs only after 30 minutes with neither subscribers nor activity [3]. No unsubscribe-based recovery was implemented.
- CONFIRMED (tier 1+2): current #380 already excludes FAILED_BEFORE_SUBMIT from queue heads and advances past terminal failures. The examined voice-astra receipt history had two typed generic FAILED_BEFORE_SUBMIT records. This snapshot does not prove the reported repeated QUEUED rows never happened; it does refute treating the old terminal-head predicate as the current defect. Acceptance is intentionally asynchronous, so a 202 QUEUED response alone does not prove a silent loss.

## Decision and safety
Use the existing #380 admission and failure envelopes, not another delivery queue or quarantine table. Read native kernel lock ownership only for detached Codex sessions. Never acquire/unlink a native lock to diagnose it, and never signal an owner found by lock inspection. An attached live backend bypasses the contention projection and keeps native steering. Failed native resume gets CODEX_WRITER_CONFLICT and remains visibly broken until a successful reconnect or a different thread. A released owner no longer blocks admission; native resume owns recovery and preserves history.

No automatic writer killing is safe on this evidence: a surviving app-server can still be doing useful work. No restart-cli or change_worker_model changes. No service restart.

## Counter-evidence and limits
The five original workers are no longer all in their failed state: two are archived and model switching changed native thread IDs. The current incident snapshot proves one surviving old owner, not the cause of all five original failures. A process holding a lock is not proof that a model turn is progressing. `/proc/locks` is Linux-local observation; unavailable observations fall back to the native protocol. A competing writer may start after preflight: that receipt must fail through the existing runner after native resume rejects it. Detached state reconstructed after restart uses the native lock, not a new persistent error column.

## Sources
1. Tier 2, fetched this session: https://raw.githubusercontent.com/openai/codex/rust-v0.153.4/codex-rs/thread-store/src/local/writer_lock.rs
2. Tier 2, fetched this session: https://raw.githubusercontent.com/openai/codex/rust-v0.153.4/codex-rs/thread-store/src/local/writer_lock_tests.rs
3. Tier 2, fetched this session: https://raw.githubusercontent.com/openai/codex/rust-v0.153.4/codex-rs/app-server/README.md
4. Prior art, user report rather than proof of our mechanism: https://github.com/openai/codex/issues/38144 (opened this session).
5. Tier 1: read-only SQLite session/receipt queries, `/proc/locks`, `/proc/1169478/{cmdline,cgroup,fd}`, `ps`, `systemctl show`, and journalctl filtered to voice-astra, 2026-09-07. No production data was mutated.
6. Tier 2: current `app/message_deliveries.py`, `app/session.py`, `app/manager.py`, `app/backend_jsonrpc.py`, and `.orchestra/tasks/380/research.md`.
