## Summary

The implementation does not yet satisfy #230 safely. The census cleanup is structurally sound, and Claude’s unsupported handover degrades through the existing `stop()` path without creating a half-state. However, Codex handover has four blocking ownership/continuity defects, especially across a second restart.

## Findings

blocking: `app/fdstore.py:72` — `acquire_fds()` collapses duplicate `FDNAME`s into a dictionary, while each adopted descriptor is submitted to `FDSTORE=1` again on every shutdown. Since systemd retains stored descriptors across restart, a second consecutive restart can accumulate duplicate names; the comprehension silently selects one copy and leaks the rest until `FileDescriptorStoreMax` is exhausted → reject duplicate names loudly and define explicit store ownership across generations, removing/replacing retained entries instead of blindly adding another copy.

blocking: `app/manager.py:2001` — the two descriptor submissions are not transactional. If storing stdin succeeds and storing stdout or DB state fails, `_hand_over_backend()` returns `False` and stops the CLI, but the first descriptor remains in systemd. On startup the half-pair is not adoptable, and `sweep_orphan_fds()` preserves it because the session still exists → add rollback using `FDSTOREREMOVE=1` for every name already submitted, or use a protocol that commits/removes the pair atomically.

blocking: `app/session.py:896` — persisted `leftover` is assigned to `_adopted_leftover` but never consumed anywhere. If the former `StreamReader` had already buffered the beginning of a JSONL frame, the adopted reader receives only the remainder; `_read_stdout()` treats it as invalid JSON and drops that event, potentially including the terminal event → prepend the saved bytes to the adopted reader before `_read_stdout()` starts, preserving bytes rather than decoding/re-encoding them through a DB `TEXT` field.

blocking: `app/manager.py:2003` — handover snapshots `leftover` while the old `_read_stdout` task and pipe transport remain active. Between this snapshot and supervisor exit, the reader can pull additional bytes from the kernel into the dying process or consume complete notifications into an in-memory queue that is never transferred → first quiesce/detach the reader without closing the underlying descriptors, then snapshot its stable buffer and transfer ownership.

blocking: `app/backend_codex.py:846` — `disconnect()` immediately returns for an adopted backend because both `_proc` and `_scope_unit` are `None`. Consequently `_refresh_stale_backend()` drops its reference and starts a fresh CLI, while the adopted reader task, transports, descriptors, and original CLI remain alive. This creates an unowned duplicate process at the first post-restart turn boundary → implement adopted-backend teardown that cancels `_reader_task`, closes both transports/descriptors, and terminates the recorded CLI process before replacing it.

blocking: `app/backend_codex.py:450` — adoption never restores `cli_pid` into `_adopted_pid`, despite `pid` explicitly relying on that field. The next handover therefore overwrites `sessions.cli_pid` with `0`, so orphan cleanup can no longer terminate the surviving CLI after two restart generations → load `cli_pid` from the row, pass it through `AgentSession.adopt_backend()`/`CodexBackend.adopt()`, validate process identity before signaling, and retain it across every generation.

suggestion: `app/fdstore.py:65` — empty entries in `LISTEN_FDNAMES` are filtered before validating count. This turns a positional protocol error into only a generic count mismatch and loses evidence about which slot lacked a name → preserve the split list exactly, reject empty names explicitly, then validate uniqueness and count.

## Verdict

CHANGES REQUIRED. The current implementation can lose buffered turn events, leak descriptors on every restart, and leave the adopted Codex CLI running alongside a newly spawned replacement. These are blocking lifecycle defects for the ticket’s zero-interruption contract.

## Round (2026-08-12T16:27:32Z)

## Round 2

### Re-review status

1. Duplicate `FDNAME` accumulation — FIXED. Replacement is ordered remove→store, and duplicate inherited names now fail loudly.

2. Non-transactional pair — FIXED. Successfully submitted names are tracked and removed before falling back to `stop()`.

3. Leftover never consumed — FIXED. Bytes remain base64 and are fed into the new reader before pipe input begins.

4. Snapshot racing the reader — STILL BROKEN. Cancellation stabilizes the `StreamReader` buffer, but `_read_stdout()` always executes its `finally`; because `_disconnecting` remains false, cancellation injects a synthetic `_process/exited` notification. The active consumer can therefore observe a false process death and finish the surviving turn during handover.

5. Adopted `disconnect()` no-op — STILL BROKEN. Process termination is now attempted, but only the writer transport is closed. The read transport returned by `connect_read_pipe()` is discarded, so its stdout descriptor remains open.

6. `cli_pid` lost after adoption — STILL BROKEN for scoped Codex. The value is propagated correctly, but the spawned `_proc.pid` can be the `systemd-run --scope` launcher rather than the Codex process inside the scope. After the launcher exits, the persisted PID cannot reap the actual surviving CLI.

7. Empty inherited FD name — FIXED.

### New findings

blocking: `app/backend_jsonrpc.py:104` — `quiesce_for_handover()` cancels `_read_stdout`, whose `finally` enqueues `_process/exited` because this is not marked as an intentional pause → add a distinct handover-quiescing state that suppresses exit finalization while preserving buffered bytes and pending requests.

blocking: `app/backend_jsonrpc.py:116` — after one second, queued parsed events are explicitly declared lost but handover still succeeds. A queued `turn/completed`, final text, tool result, or usage event is then absent from the next generation, directly violating the zero-loss contract → if the queue cannot drain, refuse handover rather than reporting success, or serialize and replay the queued notifications alongside `leftover`.

blocking: `app/backend_jsonrpc.py:162` — `connect_read_pipe()`’s transport is not retained; `teardown_adopted()` clears the reader object but closes only `_adopted_writer` → store the read transport separately, close it during teardown, and await writer closure where supported.

blocking: `app/backend_jsonrpc.py:264` — PID validation is both too broad and disconnected from the expected runtime: `label` is ignored, and any command containing any of `codex`, `claude`, `opencode`, or `grok` is accepted. A reused PID for an unrelated command containing one marker can be killed, while scoped launches may persist the short-lived `systemd-run` PID and leave the real Codex orphan alive → persist a verified process identity, preferably PID plus `/proc/<pid>/stat` start time and runtime-specific executable/cgroup identity; for scoped Codex, resolve the actual scope member rather than the launcher.

suggestion: `app/session.py:894` — catching every `TypeError` from the new `adopt()` call and retrying the old signature can run adoption twice when a `TypeError` originates inside the implementation after descriptors were attached → inspect the callable signature or make the new keyword contract mandatory for adoptable runtimes.

### Verdict

CHANGES REQUIRED. The duplicate-store and leftover fixes are correct, but quiescing currently fabricates process death, knowingly permits parsed-event loss, and adopted teardown still leaks the read descriptor. The second-generation metadata path is otherwise preserved: turn ID and base64 leftover are rewritten rather than duplicated, and `cli_pid` is carried forward when it identifies the actual CLI.

## Round (2026-08-12T16:36:52Z)

## Round 3

### Re-review status

1. Quiesce fabricating process death — FIXED. `_handover_quiescing` is set before cancellation and suppresses `_process/exited`.

2. Queued parsed events lost — FIXED. `prefix + reader buffer` preserves stream order. Re-encoding parsed JSON is protocol-equivalent: key order, whitespace, Unicode escaping, and float spelling are not semantically significant to the JSON reader.

3. Read transport leaked — FIXED. Both adopted transports are retained and closed; the reader task is cancelled and awaited.

4. PID validation too broad — FIXED for direct-child runtimes. PID, start time, and runtime-specific marker are checked. The scoped-launcher limitation is correctly left open and currently inert.

5. Blanket `TypeError` fallback — FIXED. Adoption now has one mandatory signature and one execution.

### New findings

blocking: `app/backend_codex.py:933` — quiescing still completes every pending JSON-RPC request and compact future with a fabricated “app-server exited” exception. `_handover_quiescing` suppresses only the `_process/exited` notification; the preceding exception loop remains unconditional. A concurrent `turn/steer` or other request whose response has not arrived is failed locally even though the CLI survives, so an injected message can have an unknown outcome across restart → during handover, preserve pending request state and request IDs for the next generation, or refuse handover whenever `_pending_requests`/`_compact_future` are active. The safe minimal fix is fail-closed before cancelling the reader.

suggestion: `app/backend_jsonrpc.py:230` — `teardown_adopted()` clears PID but leaves `_adopted_started_at`, `_handover_quiescing`, and `_quiesced_prefix` populated. The backend object is normally discarded immediately, so this is not presently blocking, but teardown should reset all adopted-generation state to make reuse and diagnostics deterministic.

### Second-generation walk

Gen1→gen2→gen3 now preserves `active_turn_id`, base64 buffered bytes, carried parsed frames, PID, and start time without duplication. Replayed frames are consumed from the adopted reader before new kernel bytes; after consumption they are absent from the next snapshot. FD names are replaced rather than accumulated.

The remaining scoped-Codex limitation is accurately bounded: enabling user scopes can persist the launcher identity and leave the actual CLI orphaned, but the start-time/runtime checks prevent signaling an unrelated reused PID.

### Verdict

CHANGES REQUIRED: one blocking lifecycle hole remains for pending JSON-RPC requests during quiescing. Record it for the orchestrator if the three-round ceiling prevents another implementation pass.
