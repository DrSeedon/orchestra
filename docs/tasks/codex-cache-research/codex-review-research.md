# Adversarial review: Codex cache research

Reviewed `docs/tasks/codex-cache-research/research.md` against the current official OpenAI prompt-caching and Codex pricing documentation, installed Codex CLI `0.144.5` source at `87db9bc18ba5bc82c1cb4e4381b44f693ee35623`, upstream source at `5c0e582c59892dbec89af78ae62c784d3da6c9cb`, local rollout metadata/token events, `~/.codex/models_cache.json`, and Orchestra's current `app/backend_codex.py` / `app/session.py` implementations.

## Findings

### 1. Do not present the API TTL as guaranteed on ChatGPT-auth Codex

**blocking:** `research.md:72-79,167,173` — The official prompt-caching guide does establish that GPT-5.6 API requests use `prompt_cache_options.ttl = "30m"` by default and that this is a minimum lifetime. It does not establish the same contractual guarantee for the ChatGPT-auth Codex backend. The installed CLI omitting a TTL override only proves that this private surface chooses its server default; it does not prove that its default is the public API default. The single 31.2-minute hit shows that one prefix survived that long, not that every eligible Codex subscription prefix is guaranteed for 30 minutes. This distinction is acknowledged at line 167 but then lost in the recommendation `guaranteed_min_ttl=1800` and the unconditional dashboard state `hot 0–30m`. Change the recommendation to an explicitly assumed/observed policy (for example, `expected_min_ttl=1800`, with no guarantee in UI copy), or obtain a subscription-surface contract/controlled repeated test before calling it guaranteed. This changes the proposed dashboard semantics, so it is blocking.

Evidence: [official API retention semantics](https://developers.openai.com/api/docs/guides/prompt-caching#prompt-cache-retention); installed request construction sends `prompt_cache_key` but no `prompt_cache_options`.

### 2. First-call hits do not falsify an economic cold start

**suggestion:** `research.md:42,68,87,122` — The inference from `27/34` first calls with partial hits to “new thread is not cold” is too strong for an economics report. CLI `0.144.5` has a startup WebSocket prewarm path: it submits the prompt with `generate=false`, then the generated request can reuse `previous_response_id`; the installed `TokenUsage` protocol simultaneously lacks `cache_write_input_tokens`. A visible first generated call can therefore report cached input even if an earlier startup/prewarm step created or populated the reusable state at cold/write economics. The repeated `9,984`-token first-call hits in local fresh exec rollouts are consistent with this confounder. Keep the narrow observation (“the first emitted `token_count` often contains cached tokens”), but do not use it to refute lifecycle cold-start cost or infer cross-thread savings. A controlled comparison must capture cache-write tokens or rate-limit/credit deltas across the entire process startup, not only the generated call.

Evidence: [installed `client.rs`](https://github.com/openai/codex/blob/87db9bc18ba5bc82c1cb4e4381b44f693ee35623/codex-rs/core/src/client.rs) documents `generate=false` prewarm and reuse through `previous_response_id`; installed `TokenUsage` has no write counter.

### 3. Narrow the interpretation of the long-gap observations

**suggestion:** `research.md:51-55,77,166` — The table supports only a weak survival statement. The 31.2-minute same-thread hit is evidence that a matching prefix was reusable at that point. The 57.4-minute and 15.1-hour misses do not identify expiry, which the report correctly concedes. The 4.7-hour `9,984 / 61,258` partial hit also does not establish opportunistic retention of the previous long prefix: no serialized-prefix or breakpoint identity was recorded, and `9,984` is the same size repeatedly seen in fresh-start partial hits, so it may be a static/startup prefix rather than the old conversation prefix. With `N=2`, `N=1`, and `N=2` in the long buckets, the measurements are consistent with the API model but do not independently confirm its post-30-minute retention semantics. Rewrite “this confirms” as “this is consistent with,” and identify the 31.2-minute result as the only positive lower-bound observation.

### 4. Segment the measurements by subscription plan

**suggestion:** `research.md:4,19,31-55,124-130` — The snapshot is described as a Pro 5x environment, but the selected local Sol token events span both internal `plan_type=plus` and `plan_type=prolite`. In a reproduction of the stated filter before the cutoff, both plans contributed materially; the 57.4-minute pair even crosses from `plus` to `prolite`. That aggregate cannot test H4 or attribute a miss to TTL rather than the plan/account transition. The official Codex rate card supports the same token categories and rates, and the plan page supports the 5x quota multiplier, so the proposed “same cache policy until documented otherwise” default remains reasonable. Label it as documentation-based, not empirically confirmed by this mixed sample, and publish per-plan counts/ratios if the local data is retained as supporting evidence.

### 5. Distinguish native Codex compaction from Orchestra `compact_worker`

**suggestion:** `research.md:136-141,172-176` — The source mechanics cited here describe native Codex remote/auto compaction: the compact request can reuse the thread cache key and replaces history inside the same Codex thread. Orchestra's current manual `compact_worker` path is different. `app/session.py:656-812` asks the agent for a handoff summary, disconnects the backend, calls `_ensure_backend(force_fresh=True)`, and seeds a new session/thread with a summary preamble. Therefore statements about compact-request cache reuse do not describe the operation users trigger through Orchestra, and its extra summary/ack turns and fresh-thread startup must be included in the economics. The no-TTL-driven-precompact recommendation still looks correct—if anything, the generic path makes preventive compaction more expensive—but the report must state which compact mechanism each recommendation refers to.

### 6. Correct the native auto-compact threshold arithmetic

**suggestion:** `research.md:138` — `232,560` is not the threshold implied by the cited source and current Sol model metadata. Local model metadata gives raw `context_window=272,000`, `effective_context_window_percent=95`, and no explicit `auto_compact_token_limit`. Codex derives native auto-compact at 90% of the raw window, or `244,800`; the rollout/UI window is `272,000 × 95% = 258,400`, so the native threshold is about 94.74% of that displayed effective window. The cited `openai_models.rs` applies the 90% derivation to `resolved_context_window`, not to the already reduced `model_context_window` emitted to rollout consumers.

### 7. Describe the 84.69% figure as a modeled lower-bound reduction

**suggestion:** `research.md:113-122,168` — The 10x subscription input/read ratio and 12.5x API write/read ratio are arithmetically correct, as are the displayed lower-bound totals under the report's formula. However, “observed cache saved 84.69%” overstates what was observed: `W` is unavailable in CLI `0.144.5`, and startup/prewarm accounting is not isolated. The number is the reduction produced by Orchestra's current lower-bound model relative to a fully uncached counterfactual, before any unknown cache-write surcharge. The subscription comparison is separately valid under the published three-column Codex credit rate card, which has no cache-write category; it should not be presented as empirical evidence for API write economics.

Evidence: [Codex credit rate card](https://learn.chatgpt.com/docs/pricing#what-are-tokens-and-credits); [API pricing](https://developers.openai.com/api/docs/pricing); [cache-write usage semantics](https://developers.openai.com/api/docs/guides/prompt-caching#requirements).

### 8. Make the measurement reproducible

**suggestion:** `research.md:27-55,199` — Aggregate results are recorded, but the exact parser, file list, deduplication rule for repeated thread IDs across rollout files, plan segmentation, model-state tracking, and excluded-pair list are not. This matters because a straightforward reconstruction near the stated cutoff is sensitive to those choices and does not trivially reproduce the exact `140 / 1,896 / 34` counts. Add the read-only aggregation script or machine-readable manifest/output used for the snapshot. Do not include message content; the current metadata-only scope is sufficient.

### 9. Treat a missing write field as missing, not zero

**nit:** `research.md:42` — “Calls where CLI reported cache-write tokens: 0” reads as a measured zero. In `0.144.5` the field does not exist, so the accurate value is “not reported / unavailable (0 observable fields).” The later text gets this right.

## Conclusions that survived review

- The public GPT-5.6 API contract is a 30-minute minimum, not a fixed one-hour TTL, and may retain entries longer.
- Installed CLI source uses the thread ID as the default `prompt_cache_key`; resume preserves it, while a new thread gets a new ID. Resume remains the correct lifecycle choice because it also restores the transcript.
- The published arithmetic is correct: Codex subscription input versus cached input is 10x; API ordinary input versus cached read is 10x; API cache write versus cached read is 12.5x.
- A TTL-driven preventive compact is not supported by Codex mechanics. Compaction should remain a context-capacity/fidelity decision, after separating native Codex compaction from Orchestra's fresh-thread handoff implementation.
- The `backend_codex.py` accounting gap is real: `_codex_cost`, `_usage_breakdown`, `_usage_delta`, rollout readers, and emitted metadata omit cache writes, while upstream `5c0e582` exposes `cache_write_input_tokens` / `cacheWriteInputTokens`. Until the whole cumulative/delta path is upgraded and tested, API-equivalent dollars are a lower bound.

VERDICT: NEEDS CHANGES

## Round 2

Reconstructed the first review from this entire file, re-read the updated `research.md`, checked the installed `codex-cli 0.144.5` help, current Orchestra app-server/compaction/accounting paths, local Sol model metadata, the cited Codex source revisions available locally, and reran `measure_rollouts.py` with its default cutoff. The script reproduced its published `37 files / 1,970 calls / 35 sessions / 96.08%` snapshot and all published gap buckets exactly.

### Prior findings

1. **FIXED — ChatGPT-auth TTL is no longer presented as guaranteed.** The title result, H2, TTL finding, limitations, and dashboard recommendation now consistently distinguish the public GPT-5.6 API's 30-minute minimum from the unpublished ChatGPT-auth contract. The recommendation uses `contractual cache_ttl=null`, `api_min_ttl=1800`, and an empirical `observed_survival_lower_bound=1872s`; `recent <=30m` is explicitly an expectation rather than a promised hit. The prior blocking issue is resolved.

2. **FIXED — first-call hits no longer falsify an economic cold start.** The report now limits the observation to the first emitted `token_count`, describes the `generate=false` WebSocket prewarm/write-accounting confounder, and requires whole-process write counters or credit deltas before claiming startup savings.

3. **FIXED — long-gap observations are appropriately narrow.** Only the 31.2-minute hit is treated as a positive lower bound for one matching prefix. The misses and the 4.7-hour `9,984`-token partial hit are explicitly non-identifying, and the aggregate is described as consistent with, not confirmation of, API retention policy.

4. **FIXED — measurements are segmented by internal plan label.** The report publishes `plus` and `prolite` counts/ratios, warns that these are internal labels, identifies the `plus -> prolite` transition across the 57.4-minute pair, and keeps H4 documentation-based rather than empirically confirmed.

5. **FIXED — native Codex compaction and Orchestra `compact_worker` are separated.** The updated text correctly distinguishes same-thread native compact/key reuse from Orchestra's summary turn, backend disconnect, `_ensure_backend(force_fresh=True)`, new thread, and acknowledgement turn. The no-TTL-precompact recommendation remains supported.

6. **FIXED — auto-compact arithmetic is corrected.** With local metadata `context_window=272,000`, `effective_context_window_percent=95`, and no explicit model limit, the report now derives `244,800` as 90% of the raw window and correctly relates it to the displayed `258,400` effective window.

7. **FIXED — 84.69% is labeled as a modeled lower-bound reduction.** The report no longer calls it observed savings, separates subscription credit arithmetic from API cache-write economics, and states that unknown `W` makes Orchestra's API-equivalent dollars a lower bound.

8. **STILL BROKEN — the added parser is executable and reproduces the report, but its aggregation is not yet correct under its own stated rules.** Two concrete defects remain:

   - It has no event deduplication. The snapshot contains the exact same Sol `token_count` event twice at `2026-07-18T05:43:32.360Z` (`58,507` input, `47,872` cached, `527` output) in consecutive rows of `rollout-2026-07-18T12-43-29-019f73c0-48d6-7153-a263-580d12d7d400.jsonl`, so the published aggregate counts and sums it twice.
   - The claimed model-transition exclusion is ineffective. Calls are appended only while `model == "gpt-5.6-sol"`, and every appended record stores that same value; consequently `previous["model"] != current["model"]` can never be true. One actual Sol -> `gpt-5.3-codex-spark` -> Sol transition is joined into a synthetic Sol gap in the current sample.

   An independent metadata-only audit with exact-event deduplication and model/compaction epochs yields `1,969` calls, input/cached/output `241,677,391 / 232,209,664 / 848,289`, `prolite` `1,285` calls with `170,387,321 / 164,004,096` input/cached, and `<5m` `N=1,901`, `1,879` hits. The weighted ratio remains `96.08%`, and no long-gap result or research conclusion changes. Fix the parser and update `research.md:31-38,48,62,131,174,211,215`; the current claim that all prior review points were fixed is false.

9. **FIXED — missing cache-write usage is represented as unavailable, not zero.** The measurement table says the field is absent, and the accounting section separately explains why Orchestra currently emits `cache_create: 0` and why that is not a measured zero-write result.

### New blocking issues

No new cache-policy or TTL blocker was found. Finding 8 remains an approval blocker because the report labels the snapshot exact/reproducible and explicitly claims model-change exclusion while the supplied parser violates both claims. The numerical correction is small and does not change the recommendations, but a reproducibility artifact must not deterministically reproduce a known counting error.

VERDICT: NEEDS CHANGES

## Round 3

Re-read the Round 2 blocker, inspected the updated parser and research values, reran `python docs/tasks/codex-cache-research/measure_rollouts.py` at the fixed cutoff, and independently recalculated the API-equivalent and subscription-credit totals from the corrected token counts.

### Finding 8

**FIXED — the reproducibility parser now implements the rules claimed by the report.**

- Exact duplicate calls are keyed by timestamp plus cumulative input/cached/output/reasoning usage within each session. The previously duplicated event is removed and the output reports `duplicate_events_removed: 1`.
- Model events now advance `model_epoch`, compaction events advance `compact_epoch`, and gap pairs crossing either epoch are excluded. The former Sol -> `gpt-5.3-codex-spark` -> Sol synthetic gap is no longer counted.
- The rerun exactly produced `37` files, `1,969` calls, `35` sessions, input/cached/output `241,677,391 / 232,209,664 / 848,289`, `96.08%` weighted cache ratio, `prolite` `1,285` calls with `170,387,321 / 164,004,096` input/cached, and `<5m` `N=1,901` with `1,879` hits. Long-gap observations are unchanged.
- `research.md` contains the corrected call/token/plan/gap values and no stale Round 2 totals. Its recalculated `$188.892` lower bound, `$1,233.836` uncached counterfactual, `84.69%` modeled reduction, `4,722.30` credits, and `30,845.89` uncached credits agree with direct arithmetic.

### Remaining findings

**FIXED — all prior findings remain resolved.** In particular, the original blocking TTL distinction still holds: the report does not turn the public API's 30-minute minimum into a ChatGPT-auth guarantee, and the dashboard recommendation retains `contractual cache_ttl=null`.

No new blocking or non-blocking issue was found in the patch. The corrected measurement does not change the report's cache-lifecycle, compaction, or accounting recommendations.

VERDICT: APPROVED
