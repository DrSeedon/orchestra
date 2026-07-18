# Codex adversarial review — Deepgram research

Review date: 2026-07-18. Model: GPT-5.5 via local Codex CLI fallback. The `codex_review` MCP tool was not exposed in this worker session, so the research file was reviewed read-only with `codex exec`.

## Round 1

**Verdict:** NEEDS WORK.

### Findings

1. `blocking:` The visible Deepgram pricing extraction showed `$0.0048/$0.0058` and appeared to conflict with the research's `$0.0043/$0.0052` pre-recorded rates. Codex requested either recalculation or explicit account-observed wording.
2. `suggestion:` Replace “optimal” with “best current baseline” because WER was not measured.
3. `question:` Scope “no Codex MCP” to this local Codex installation, not the Codex product globally.
4. `suggestion:` State that `tag=orchestra-tg` fixes future attribution only and cannot split historical untagged spend.

Codex otherwise confirmed the local code/config claims: direct `/v1/listen`, `nova-3&language=ru`, LLM-only dashboard cost, and shared untagged credential.

## Verification and response

The pricing blocker was checked against stronger route-specific evidence:

- raw current `application/ld+json` names `$0.0048` as **Streaming Nova-3 Monolingual**, `$0.0043` as **Pre-Recorded Nova-3 Monolingual**, and `$0.0052` as **Pre-Recorded Nova-3 Multilingual**;
- Orchestra submits completed OGA files through the sync/pre-recorded endpoint;
- read-only account billing independently measured `sync::nova-3` at `$0.004400–$0.004423/min`.

The flattened rendered table mixed values from multiple tabs, so the Round 1 blocker was challenged rather than accepted. The three nonblocking wording findings were accepted.

## Round 2

**Verdict:** WITHDRAWN; no remaining blocker.

Codex agreed that the prior blocker read the streaming row as pre-recorded. It could not independently dump scripts from its sandbox because its shell network/proxies were unavailable, but concluded that the flattened table was weaker evidence than the explicitly route-specific structured offers plus measured `sync::nova-3` billing.

Codex accepted the planned corrections as sufficient:

- local installation scope for the MCP claim;
- “best current baseline,” not “optimal”;
- future-only attribution from tags, with no retroactive split.

## Additional counter-evidence folded into research

During review, an older local six-way proxy/direct experiment was found in `docs/research-deepgram.md`. It did not reproduce the commit's 9× latency gap and sometimes measured proxy faster. The research now recommends direct networking for fewer proxy failure modes and current stability, not as a universal latency guarantee.

## Final verdict

**APPROVED after wording corrections and resolved pricing dispute.** Core conclusions remain: no local Deepgram MCP, no Orchestra voice cost tracking, untagged shared-key history cannot be attributed exactly, and `nova-3&language=ru` is the best current baseline pending a real WER A/B.
