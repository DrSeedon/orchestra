## Review protocol

- Attempt 1: tool preflight rejected the request before Codex started because the required
  structured PROJECT CONTEXT block was absent; no review text, round not consumed.
- Attempt 2: completed; prose round 1 of 2.

## Summary

Addendum correctly narrows authority to direct orchestrator authorization, keeps the received acceptance oracle unconditionally immutable, and requires worker-only ownership plus assembled-prompt non-leakage. It also correctly falsifies the broader claim: direct worker assignments such as #235 are unblocked, while `full-cycle` delegation remains outside this fix because its payload and acceptance policy still prohibit all test-layer changes.

Evidence read: “Триггером служит только прямой текст задания оркестратора.”

## Findings

No blocking issues or suggestions.

The planned source-ownership assertion, assembled-role checks, and separate immutable-guard test cover all required mutations, including role removal combined with `base.md` injection. The planned scope also preserves existing immutable-oracle lines and avoids leaking the exception into `full-cycle`, `orchestrator`, or `sub-orchestrator`.

## Verdict

APPROVED — research is sufficient to proceed to the implementation gate.
