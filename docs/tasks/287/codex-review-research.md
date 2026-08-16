## Summary

The artifact is evidence-rich and most current-code claims check out: history import behavior, `truncated=11915`, `last_summary`/`runtime_handoff`, Seedon’s delayed context failure, #283’s separate startup seams, V1 invalidity, V2 cell counts, hidden-CoT boundary, and the external `kesha-tg-bot` current-vs-proposal distinction.

However, three load-bearing conclusions are not supported strongly enough for Phase 2:

- H2 is declared refuted despite its preregistered falsifier not being met.
- Target synthesis is simultaneously rejected as universally necessary and mandated for every cross-provider switch.
- The canonical schema can label transcript-derived constraints as `system|repo` authority without recording a server-verifiable authority origin, creating a privilege-injection boundary defect.

## Findings (blocking/suggestion/question)

### BLOCKING

blocking: [research.md:257](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:257) — **H2’s “REFUTED” verdict does not satisfy its own falsifier and materially overstates what V2 tested.**

The preregistered falsifier requires native resume to be “systematically worse than every portable arm” on the same provider, absent overflow/compatibility failure ([line 20](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:20)). The reported aggregates do not meet that condition:

- Codex native `0.741` equals raw and target-summary `0.741`, and is only slightly below source-summary `0.768`.
- Grok native `0.778` equals raw and target-summary and exceeds source-summary `0.768`.
- Only packet/hybrid outperform it.
- There is one replicate, and the “native” arm is a synthetic seed turn followed by resume—not an observation of opaque long-lived provider state.

The evidence supports “native resume is not a canonical truth layer and is not guaranteed to dominate packet on this exact-ID task,” but not “H2 refuted as semantic upper bound.” This matters because it is used to demote native continuity in the mechanism verdict. Classify H2 as inconclusive/unsupported by V2 while retaining the independent live evidence that native resume needs fit checks.

blocking: [research.md:383](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:383) — **The target-synthesis trigger contradicts both H5’s result and the stated recommendation.**

The artifact says:

- synthesis is not always needed ([lines 27–29](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:27));
- H5 is refuted because packet-only matched hybrid more cheaply ([line 260](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:260));
- synthesis is “conditional” in the external comparison ([line 202](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:202));
- yet the decision tree mandates it whenever the switch is cross-provider ([line 385](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:385));
- the confidence table repeats “any cross-provider switch” despite calling it non-universal ([line 432](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:432)).

No experiment tested an actual schema/capability mismatch, and packet-only was the cheaper perfect arm in the exploratory corpus. “Cross-provider” by itself is therefore not an evidence-backed mandatory trigger. This reverses the practical recommendation by adding a probabilistic, costly model turn to every cross-provider switch.

Make cross-provider status a reason to evaluate compatibility, not an automatic synthesis trigger. Mandatory synthesis is supported only when an actual mismatch, ambiguity, oversized delta, or unsupported ingress form is established.

blocking: [research.md:320](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:320) — **The canonical packet lacks a server-verifiable authority provenance field, allowing untrusted history to be relabelled as privileged constraints.**

The schema permits:

```json
{"authority": "user|system|repo", "source_event_ids": ["..."]}
```

But an event reference and server-authored serialization do not prove that the referenced text originated in the current system prompt, repository policy, or an authorized user instruction. Raw assistant/tool text can itself claim “system policy” or quote repository instructions. If the projector promotes that claim into `authority: "system"` or `"repo"`, the supposedly canonical packet launders untrusted content across the privilege boundary.

This conflicts with the artifact’s own rule that raw logs/tool outputs remain untrusted and never gain developer authority. Integrity hashing proves bytes were unchanged; it does not prove authority.

The schema must distinguish server-verified origin from semantic content—for example, origin class plus immutable source/fingerprint—and forbid deriving `system|repo` authority from transcript text or model synthesis. Otherwise the proposed truth layer creates the privilege-injection failure it is intended to prevent.

### SUGGESTION

suggestion: [research.md:246](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:246) — Clarify that “Successful task paths” means transport-successful (`exit_code=0`), not semantically successful. The Grok packet row counts two successful paths while one is a preregistered critical failure. The adjacent critical column preserves the raw fact, but the heading is easy to misread.

suggestion: [research.md:256](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:256) — Weaken H1 from “SUPPORTED” to “supported only for exact-schema retention in this exploratory fixture.” The packet input schema closely matches the answer schema, a limitation already acknowledged at line 439. The experiment demonstrates reliable extraction of preregistered IDs, not yet durable-state superiority on production-shaped questions.

suggestion: [research.md:258](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:258) — Describe H3 as “not supported / inconclusive on this corpus,” rather than globally “refuted.” Tools were disabled, only six successful raw action cells carried the malicious fixture, and the output flag was self-reported. The text mostly supplies these caveats already; the verdict label is stronger than the measurement.

suggestion: [research.md:414](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:414) — Separate “ingress canary” from “first useful target turn.” A tools-disabled canary can establish parse/context acceptance, but it does not demonstrate tool capability, side-effect continuity, or full working-state use. Seedon supports delaying commit until the first model call fits; it does not establish that one synthetic canary proves the whole handoff.

suggestion: [research.md:379](/home/kesha/orchestra/worktrees/home-kesha-orchestra/research-runtime-handoff/docs/tasks/287/research.md:379) — “No pending/unknown side effects” is a safe conservative policy but was not validated experimentally: V2 disabled tools and did not exercise receipts or idempotency. Label this as a safety invariant/design choice rather than an experimental conclusion.

### Verified without blocking findings

- The `truncated=11915` explanation matches current renderer behavior: initial source-row truncation count plus dropped rendered tool items, with possible double counting.
- Seedon causality is carefully bounded: `thread/resume` accepted history structurally, the first model turn exposed `258400/258400`, `_history_import` had already been cleared, and the existing fallback catches only connect/import failure. The document correctly leaves the internal reason for the fresh retry thread uncertain.
- #283 correctly separates AGENTS truncation, trust warning, bwrap fallback, timeout, and MCP cancellation. It does not claim the entire Orchestra system/developer prompt disappeared.
- V2 contains exactly 57 cells: Codex 30/30 successful, Grok 22/27 successful, with five recorded 402 failures. The mechanism-level path denominators are internally consistent.
- The artifact correctly states V1 is invalid for comparative retention and V2 is post-hoc exploratory with one replicate and no Claude target.
- The external `kesha-tg-bot` section distinguishes verified current code from unimplemented cursor/capsule/pending-handoff proposals.
- Hidden chain-of-thought is correctly excluded and is not reconstructed.
- Raw history/tool outputs are consistently described as untrusted data rather than privileged instructions.

## Verdict

**NEEDS REVISION — 3 BLOCKING findings.**

The live failure diagnosis and current-code survey are strong enough to retain. Before Phase 2, the artifact should:

1. change H2 from refuted to inconclusive/narrowly unsupported;
2. remove cross-provider status as an automatic synthesis mandate;
3. make authority provenance server-verifiable in the canonical packet rather than inferable from transcript content.

## Round (2026-08-16T10:07:28Z)

## Summary

All three prior BLOCKING findings are substantively closed. The revisions preserve the evidence boundaries and introduce no new blocking contradiction.

## Findings

- H2: **CLOSED** — now correctly INCONCLUSIVE; the unmet preregistered falsifier and synthetic one-replicate limitation are explicit.
- Target synthesis: **CLOSED** — cross-provider switching now triggers deterministic negotiation, while compatible packet-only ingress remains allowed.
- Authority provenance: **CLOSED** — privileged constraints require server-verifiable origin metadata; transcript/model text and unverifiable legacy rows remain untrusted.
- New BLOCKING findings: **none**.

The suggestion-level corrections are also consistent: table denominators are explicit, H1/H3 are narrowed, canary scope is bounded, and the side-effect stop is labeled a safety invariant rather than experimental evidence.

## Verdict

**APPROVED — no blocking findings remain.**
