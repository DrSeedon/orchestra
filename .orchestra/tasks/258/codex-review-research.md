## Summary

The pidfd ordering is sound: opening the pidfd before `/proc` validation prevents the eventual signal from being redirected by PID reuse. However, the proposed stored identity is not necessarily a coherent snapshot, and the argv contract remains too vague for implementation.

Evidence line from the artifact:

> “Cgroup подтверждает общий контур Orchestra, но не конкретный runtime и не конкретную жизнь PID.”

## Findings

**blocking:** `backend_type` is not captured with `cli_pid` and `cli_started_at`, so the proposed DB tuple is not guaranteed to describe one process generation. `save_handover_state()` writes only PID and start time; `backend_type` is independently mutable session state. After backend replacement or switching, one query can therefore return an old PID/start time paired with a newer runtime. The claim that the existing three columns are sufficient without migration is load-bearing and currently unsupported. Persist the runtime alongside the handover identity atomically, or prove and enforce that `backend_type` cannot change while those identity fields remain populated.

**suggestion:** Specify positional argv predicates rather than merely “runtime-specific token combinations.” For the observed Codex wrapper, `app-server` plus `--stdio` does not establish that the Node script is `/usr/bin/codex`; an unrelated Node command can use those tokens. Grok’s `agent`, `--always-approve`, and `stdio` are similarly reproducible. The contract should state which executable/script positions are checked and how configured paths, symlinks, and the Node shebang transformation are normalized.

**suggestion:** Make validation failure containment explicit. `process_start_time()` can raise `ValueError` while parsing malformed or transient `/proc/<pid>/stat`, and an exception escaping the helper would abort the sweep after closing one FD, leaving later legitimate orphans untouched. Each candidate should fail loudly without signalling, close its pidfd in `finally`, and allow the sweep to continue; only `ESRCH` should be treated as an ordinary already-exited result.

**suggestion:** The proposed oracle is adequate only if it asserts the identity helper was reached on the negative arm. Closing the FD and leaving the foreign process alive can also result from never entering the signal path. Require an exact refusal reason or a spy proving `pidfd_open`/validation was invoked for that candidate. Keep the stated `os.kill` mutation: if changing only the helper does not make the foreign process die, the test never exercised the safety boundary.

## Verdict

CHANGES REQUESTED — one blocking flaw in the proposed persisted identity contract; pidfd-before-validation itself is sound.

## Author response before round 2

Finding verified against `save_handover_state`, runtime-switch persistence, and `save_session`:
ACK. `research.md` no longer trusts `backend_type`; the coherent snapshot is only PID/starttime,
and orphan runtime is recognized by explicit positional Codex/Grok argv shapes. The three
suggestions were also folded into F5, per-candidate failure containment, and the production-path
oracle. Attempt 2 started after the prose changed.

## Round (2026-08-13T08:18:34Z)

## Summary

All four prior findings are closed. The revised contract is coherent and preserves both safety and legitimate orphan cleanup.

Quoted evidence:

> “Первоначальное предложение читать три существующие колонки как одну identity было неверным.”

## Findings

- **FIXED — coherent identity:** identity is now atomically stored `(pid, cli_started_at)`; mutable `backend_type` is explicitly excluded.
- **FIXED — argv predicates:** Codex and Grok now have exact positional shapes with configured-executable `realpath` normalization.
- **FIXED — error containment:** failures are per-candidate, pidfds close in `finally`, and only `ESRCH` is treated as normal termination.
- **FIXED — oracle reachability:** the negative arm proves pidfd/helper validation was reached and retains the `os.kill` mutation.
- No new blocking findings.

## Verdict

APPROVED.
