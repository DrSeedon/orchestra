# Codex review — plan

## Infrastructure result

The dedicated plan review was the third consecutive `codex_review` infrastructure failure:

```text
WebSocket: Connection refused
HTTPS fallback: error sending request
turn.failed
```

Codex produced no findings and no verdict. Per the `codex-debate` three-failure ceiling, no further retry was made. The platform failure was reported through `report_bug`.

## Adversarial self-review

### Finding 1 — helper must not remove the delete guard's timeout

`delete_session()` currently bounds its `git status` and `git rev-list` subprocesses to five seconds. Moving comparison into a synchronous helper via `asyncio.to_thread` without a subprocess timeout would avoid blocking the event loop but could leave the thread running indefinitely.

**Resolution:** the plan now requires bounded helper subprocesses and visible `TimeoutExpired` errors.

### Finding 2 — “driver overridden” needs a side-effect assertion

Checking only the result tree would prove that a custom driver did not create a false allow, but not that the repository-defined command was never executed.

**Resolution:** the plan now requires a temp-marker custom driver test and asserts that the configured command did not run.

### Finding 3 — `git config --get-regexp` exit `1` is normal

The effective-driver enumeration returns exit `1` when no keys match. Treating every non-zero result as an error would block ordinary repositories.

**Resolution:** the plan explicitly accepts exit `1` as “no custom drivers”; other non-zero statuses fail closed.

## Verdict

**SELF-REVIEW: READY FOR IMPLEMENTATION GATE.**

No external Codex verdict exists because the review transport failed three times. The one substantive partial Codex finding from research round 1 (custom merge drivers can create a false no-op) was independently reproduced and resolved in the plan.
