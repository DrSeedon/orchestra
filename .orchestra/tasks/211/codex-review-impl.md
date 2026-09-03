# Codex implementation review

## Round 1 — 2026-08-12

The Codex reviewer completed and returned a substantive verdict, but Orchestra's artifact
finalizer then exited 2 because its stale invocation omitted newly required usage arguments.
The original reviewer output is preserved below from background job `bg-6bd28cd28b`; platform
bug reported separately.

> Verdict: blocking. Identity and arming checks are fail-closed, but the freeze-marker protocol
> can incorrectly claim and later thaw an externally owned cgroup freeze.
>
> - [P1] Avoid thawing freezes not proven to be guard-owned —
>   `scripts/orchestra_process_guard.py:321-327`
>   blocking: Freeze ownership is not atomic: another actor can freeze the cgroup after
>   `_frozen()` returns false but before or after this marker is created, after which `hold()`,
>   startup recovery, or `ExecStopPost` treats the marker as proof of ownership and writes
>   `cgroup.freeze=0`. This can release an operator/system freeze that the guard did not
>   establish, violating the external-freeze safety requirement; the ownership protocol must
>   fail closed unless it can verify that this invocation caused the 0→1 transition.

Evidence criterion: the finding quotes the reviewed `_frozen()` call and marker protocol and
points to the exact executable hunk. The finding is accepted: cgroup v2's shared freeze bit is
not reference-counted, so a marker outside the cgroup cannot prove ownership of a transition on
the service cgroup.

## Round 2 — 2026-08-12

The same stale Orchestra finalizer again exited 2 after the reviewer completed; the substantive
output from background job `bg-ac6f847d27` is preserved verbatim:

> APPROVED. Prior finding is FIXED: ownership is confined to a unique marked child cgroup, and
> cleanup never thaws the parent. Verbatim executable line:
> `self._move_pid(candidate.pid, child_dir)`

Evidence verified locally: that exact line exists in `scripts/orchestra_process_guard.py`.
Final verdict: **APPROVED**. Rounds used: 2 of the executable-artifact ceiling of 3.
