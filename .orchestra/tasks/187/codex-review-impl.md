# Attempt journal

- Attempt 1 completed: sighted review, `CHANGES REQUESTED`, two blocking findings.
- Attempt 2 started 2026-08-11 after both findings were fixed and mutation-tested.

## Summary

The implementation is inert and the named tests pass (`56 passed`), but two blocking correctness/security defects remain.

Verbatim reviewed quote: “Hold the policy lock until the caller durably queues or submits work.”

## Findings

- **blocking:** [app/runtime_router.py:373](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:373) — Latch admission is not linearizable across processes. The router reads latches before opening the decision transaction, while `commit_runtime_routing_decision()` checks only the policy revision. Another process can create a latch after this read; this process can then commit a stale `selected=claude` decision despite the window already being `reserve_only`. Make the latch snapshot part of the transactional compare-and-swap and recompute on mismatch. Add a two-connection race test where one admission latches the window before the other commits.

- **blocking:** [app/auth.py:59](/home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/auth.py:59) — The operator guard treats partial auth configuration as enabled. With `DASHBOARD_USER` set and `DASHBOARD_PASSWORD=""`, `validate_session()` accepts an HMAC made with a public empty key, so anyone who knows or guesses the username can forge the operator cookie and replace routing policy. Require both credentials to be non-empty before accepting operator authority, and test both partial configurations.

## Verdict

CHANGES REQUESTED — blocking latch-linearizability and operator-auth flaws.

## Round (2026-08-11T13:17:49Z)

## Summary

Both prior blockers are fixed. The transaction now rejects stale latch snapshots and admission recomputes; partial dashboard credentials cannot validate a session.

Verbatim artifact quote: “runtime routing latch snapshot changed before decision commit”

## Findings

- **FIXED — latch admission linearizability:** Comparison occurs under `BEGIN IMMEDIATE`; mismatch is translated and retried before any decision or latch persists.
- **FIXED — partial-credential cookie forgery:** `validate_session()` now requires both username and password.
- No new blocking findings.

## Verdict

APPROVED
