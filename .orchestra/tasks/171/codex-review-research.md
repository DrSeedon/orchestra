# #171 — adversarial research review

- **Review mode:** strict Sol self-review
- **External verdict:** unavailable
- **Attempted:** 2026-08-10

The required `codex_review(mode="exec")` call was made for `docs/tasks/171/research.md`. Orchestra rejected the worker turn before review execution:

```text
weekly_quota_upgrade_required: New Codex worker turn blocked: the FastAPI readiness server does not provide worker-weekly-v1. Deploy the compatible FastAPI server before this MCP client; stop/model change remain available.
```

Per the task constraint, this was not bypassed with another backend and no provider account was used. The checks below are a same-model adversarial self-review, not an independent cross-LLM verdict.

## Review target

Try to falsify four load-bearing conclusions:

1. Claudexor cannot preserve Orchestra's persistent Claude SDK/Codex app-server semantics.
2. Claudexor is not a public secretless OAuth/account transport broker.
3. Automatic quota-triggered multi-account rotation is provider-compliance-blocked or needs written approval.
4. No runtime adoption, with only bounded ideas reused, has the lowest current risk.

## Findings

**SUGGESTION (fixed) — migration estimates needed a derivation.** The original 32–55/15–25/10–20 day ranges were labeled low-confidence but were not auditable. The research now decomposes every range into control, semantic-parity, migration, security, and test work packages. They remain estimates, not measured delivery times.

**SUGGESTION (fixed) — one integration claim needed a more exact source.** The claim that Ouroboros best-effort enables `profileLimitAction=rotate` cited a general integration-source group. Source S7 now links `ouroboros/claudexor_daemon.py:409-430` directly.

**SUGGESTION (fixed) — install-script scope needed an explicit negative check.** The report covered the pinned runtime supply chain but did not state whether npm lifecycle hooks existed. A manifest search found no top-level/package `preinstall`/`install`/`postinstall`/`prepare` key at the inspected commit; the report now records that result, the explicit global harness/plugin mutation surface, and the limitation that transitive dependencies were not audited.

**CHALLENGE (resolved) — durable Claudexor threads could look equivalent to persistent provider sessions.** They are not equivalent at the control boundary: native sessions are lane caches under `(thread,harness,profile)`, profile rotation starts a fresh provider session, follow-ups serialize as later runs, Codex uses `codex exec`, and the public control API has no active-turn steer or manual compact operation. The report therefore distinguishes durable logical continuity from native conversational continuity instead of claiming that Claudexor has no continuity.

**CHALLENGE (resolved) — ordinary subscription automation could be mistaken for prohibited automation.** Official Anthropic and Cursor documentation supports ordinary third-party/non-interactive CLI use, and the report says so. The adverse conclusion is limited to quota-triggered cross-account pooling. OpenAI's primary consumer terms expressly prohibit circumventing rate limits/restrictions; Anthropic is phrased as LIKELY/MEDIUM-HIGH and Cursor as UNCERTAIN/MEDIUM, both requiring written authorization rather than claiming a categorical textual ban.

**CHALLENGE (resolved) — a private filesystem integration might still make a transport adapter technically possible.** It is possible only by coupling Orchestra to Claudexor's private profile directories or exposing credential material/new upstream APIs. The conclusion is therefore “not available in the current public API,” not “impossible to build.” This keeps the architecture claim source-bounded.

**NO BLOCKER — security conclusion is proportional to evidence.** The report credits loopback binding, bearer checks, env scrubbing, safe extraction, fsync, and redaction; it does not claim a discovered unauthenticated RCE/SSRF. It treats the added same-UID daemon capability, plaintext stores, update lifecycle, and unproven network isolation as threat-model regressions, with open issues used only as current counter-evidence.

**NO BLOCKER — final decision survives counter-evidence.** Claudexor has stronger one-shot durability/idempotency than Orchestra's backend start boundary and could be a delegated-run prior art. That does not satisfy the acceptance bar for long-lived active-turn steering, native stream/tool fidelity, compaction, provider compliance, or reduced lifecycle ownership.

## Verdict

**SELF-REVIEW PASS; EXTERNAL VERDICT UNAVAILABLE.** No unsupported load-bearing claim was found after the three traceability corrections. Confidence remains HIGH for technical non-replacement and OpenAI's prohibition, MEDIUM-HIGH for Anthropic risk, MEDIUM for Cursor risk, and LOW-MEDIUM for effort ranges.
