## Summary

Naturally, one JSON field is expected to prove both product identity and future server behavior. 🙃

The artifact directly supports a narrower conclusion: for one measured **X Premium+ unified-billing account**, `/v1/billing?format=credits` returned a **10% snapshot** inside a server-declared **7-day weekly reporting period** with a reported end timestamp.

It does not establish that the same result applies to **SuperGrok**, nor that enforcement actually resets at that timestamp. The `x-ratelimit-*` conclusion is appropriately limited to “not observed/not usable”; it does not claim absence.

No credential, token, account identifier, email, or direct PII is present. Subscription tier, timezone, and detailed usage timestamps are sensitive telemetry but not secrets.

## Findings

### [blocking] Do not generalize X Premium+ measurements to SuperGrok

[docs/tasks/96-grok-quota/research.md:5](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:5)

Every presented live measurement identifies the account as `XPremiumPlus` / `X Premium+`; the artifact provides no direct measurement or evidence showing that SuperGrok uses the same billing configuration. Writing “SuperGrok/X Premium+” conflates two subscription products and leaves the task’s headline verdict unsupported for SuperGrok. Either scope the conclusion explicitly to X Premium+ or repeat the experiment using a confirmed SuperGrok account.

### [blocking] Distinguish a reported period end from an observed reset

[docs/tasks/96-grok-quota/research.md:24](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:24)

The response proves an `end` timestamp, and the TUI labels it `Next reset`, but no transition across that boundary was observed. The artifact later admits this at lines 170–172, contradicting the unqualified “конец / следующий сброс” in the verdict. The defensible claim is “server-reported period end / expected reset”; actual reset timing, enforcement, and post-boundary behavior remain unverified.

### [suggestion] Do not classify the period as discrete

[docs/tasks/96-grok-quota/research.md:184](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:184)

Stable `start/end` values establish a fixed reporting envelope during the observation interval, but the 12%→10% decrease prevents inferring a discrete fixed bucket or its accounting semantics. A rolling component, expiry, delayed reconciliation, or repricing remain compatible with the measurements. Rename this to “server reports a stable weekly interval; underlying accounting semantics are uncertain.”

### [suggestion] Narrow the `x.ai/billing` availability claim

[docs/tasks/96-grok-quota/research.md:311](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:311)

One `grok agent --no-leader stdio` invocation returning `-32601` proves that the method was unavailable in that tested mode and configuration, not that it is categorically TUI-only. Client capabilities, launch mode, profile, or initialization metadata could affect registration. The implementation conclusion—Orchestra cannot simply call it through its current backend—is supported, but the protocol-level claim should be scoped to the tested invocation.

### [suggestion] Do not identify monthly `used` as model calls without evidence

[docs/tasks/96-grok-quota/research.md:535](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:535)

The monthly response exposes only opaque `used` and `monthlyLimit` values; nothing in the included evidence defines their unit as Grok Build model calls or correlates `used` changes with measured calls. The artifact correctly separates monthly and weekly metrics, but it should call the monthly value an opaque monthly counter until its unit is directly measured.

### [suggestion] Avoid asserting an additive `productUsage` contract from one sample

[docs/tasks/96-grok-quota/research.md:146](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:146)

`isUnifiedBillingUser=true` supports describing this as a unified-billing account, and the four displayed percentages happen to sum to 10%. A single snapshot does not prove that `productUsage` always decomposes `creditUsagePercent` additively. Preserve the observed equality, but avoid presenting it as an established accounting contract without another snapshot showing coordinated changes.

### [question] Preserve the raw evidence behind the secondary CONFIRMED claims

[docs/tasks/96-grok-quota/research.md:546](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:546)

The 39-record history, concurrent response headers, endpoint matrix, and complete ACP exchange are referenced only through ephemeral `/tmp` files; the artifact contains summaries rather than auditable sanitized transcripts. The embedded credits JSON is sufficient for the narrow weekly-reporting observation, but the missing raw request/response evidence prevents independently validating several secondary `CONFIRMED` claims, especially the protocol result and “all 39” assertion.

## Verdict

**Not supported as written.**

The evidence supports a server-reported weekly credit snapshot for one X Premium+ account: 10%, a declared weekly type, and an exactly seven-day interval. It does not prove applicability to SuperGrok or an actual reset at the reported boundary. Fixed-versus-rolling semantics remain intentionally unresolved, and the rate-limit experiment correctly establishes only that those headers were unusable under the tested load.

The endpoint supplied a timetable, not footage of the quota actually resetting on schedule.

## Round (2026-07-28T10:20:46Z)

## Summary

All prior load-bearing findings are resolved. The revised document consistently scopes results to the tested OAuth account and separates measured server fields from unobserved enforcement behavior.

No secret or direct PII leakage found.

## Findings

### [suggestion] Make concurrent execution independently auditable

[docs/tasks/96-grok-quota/research.md:599](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/grok-quota/docs/tasks/96-grok-quota/research.md:599)

E2 preserves all 20 responses but no timestamps, durations, or overlap indicator. It therefore proves the header values, not that requests were concurrent—the property intended to rule out fast refill. Adding start/end timestamps or maximum in-flight count would close this minor evidence gap. It does not undermine the narrow verdict because hourly-window absence is explicitly not claimed.

No blocking findings.

## Verdict

**Supported.**

The embedded evidence establishes that the tested account received:

- `USAGE_PERIOD_TYPE_WEEKLY`;
- `creditUsagePercent: 10.0`;
- an interval exactly 604,800 seconds long;
- an end boundary rendered by the CLI as `Next reset`.

The document correctly leaves actual reset behavior, fixed-versus-rolling accounting, other subscription types, and undiscovered hourly guardrails unresolved.

The calendar is finally presented as a calendar, not sworn testimony from the future.
