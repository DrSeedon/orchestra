## Summary

The report does not establish its final recommendation. Its only load-bearing quantitative argument—“Codex cache hit 48.3% vs Opus 97.3%, therefore keep the orchestrator on Opus”—compares provider-specific counters without first proving they have identical semantics. Until that mapping is demonstrated, both the cache-hit comparison and “735k uncached input tokens/turn” are uninterpretable.

The merge result is statistically inconclusive, the sleep-polling test uses an invalid proxy, the workload shift contaminates per-turn metrics, and D1’s causal attribution is not established by the cited evidence alone.

There are no blocking product defects here; these are research-validity suggestions. I could not independently query the report or `/tmp/orch-175.db` because every local command failed before execution with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. Consequently, I cannot certify the report’s remaining tables, command coverage, or prose/table consistency beyond the claims supplied for review.

## Findings

### suggestion — The cross-provider cache comparison is not a valid measurement as presented

`turn_usage.cache_read_tokens / input_tokens` can only be compared across Anthropic and Codex if the report establishes that both backends populate both columns with the same:

- unit and tokenizer;
- inclusion rule—whether cached tokens are included in or additional to `input_tokens`;
- scope—last request, whole turn, or cumulative thread usage;
- treatment of tool definitions, system prompts, compaction, and repeated context;
- timing and delta semantics.

The report apparently establishes none of these. Anthropic prompt-cache accounting and Codex CLI usage telemetry are different interfaces, not interchangeable measurements merely because Orchestra stores them under common column names.

“735k uncached input tokens/turn” is especially suspicious given the stated effective Codex context of roughly 258k. It may be legitimate aggregation over multiple model calls, but then it is not a per-request uncached prompt size and cannot directly diagnose poor cache reuse. It could also result from cumulative usage being recorded repeatedly. The report must trace the raw provider event through each backend’s normalization code and verify several rows manually before interpreting this field.

Bluntly: without semantic equivalence, 48.3% versus 97.3% is an apples-to-oranges ratio. The final recommendation currently collapses because its stated decisive evidence has not been validated.

A defensible comparison would use a provider-neutral outcome such as elapsed latency, quota consumed per matched task, completed tasks per quota point, or independently reconstructed repeated-prefix tokens.

### suggestion — H1 was not falsified by searching for the literal substring `sleep`

“One `sleep` among 241 bash calls versus seven among 396” measures spelling, not sleep-polling behavior. Waiting or polling can occur through:

- repeated `git status`, job-status, process, or log queries;
- tool-native wait/status operations;
- blocking shell commands;
- repeated API calls;
- loops that do not contain the literal word `sleep`.

The report’s own count of 19 repeated `git status` calls is a direct warning that the chosen operationalization misses relevant behavior. Those calls do not automatically prove polling—some may follow real state changes—but they are plausible polling under another name.

H1 should therefore be marked unresolved, not falsified. Test it using temporal sequences: repeated equivalent observations, unchanged result, short intervals, and no intervening user input or state-changing action. Classify behavior rather than command substrings.

### suggestion — The merge comparison is compatible with ordinary sampling noise

Opus succeeded in 108/129 merges, so its observed success probability is:

`108 / 129 = 0.8372`

If Codex had exactly that same underlying success probability, the probability of observing eight successes in eight attempts would be:

`(108 / 129)^8 = 0.2415`

Thus an 8/8 result occurs about 24% of the time under the Opus observed rate. That is nowhere near conventional statistical significance.

Equivalently, Codex’s 8/8 estimate has a very wide exact confidence interval; it remains compatible with a materially nonzero failure rate. Different task composition further weakens the comparison.

“Codex is objectively better at merges” is unsupported. The defensible statement is: “No Codex merge failed in eight observed attempts; the sample is too small to establish a difference from Opus.”

### suggestion — The workload and quota transition confound per-turn metrics too

Acknowledging a sevenfold workload drop does not neutralize it. Normalizing by turns only removes exposure count; it does not make turns exchangeable.

If the Codex era contained fewer but larger, more investigative, or more autonomous tasks, it would mechanically change:

- tool calls per turn;
- bash calls and repeated status checks;
- tokens per turn;
- cache behavior;
- merge opportunity and difficulty;
- defect exposure;
- duration per turn.

The switch being triggered at Claude 7-day usage near 97% introduces selection bias as well: the surrounding operational behavior and task allocation were not sampled independently of runtime.

Consequently, per-turn differences cannot be attributed to the model without task matching or adjustment for task type, size, phase, duration, and merge opportunity. The report can describe this era, but it cannot estimate a Codex-versus-Opus causal effect from the aggregate split.

### suggestion — D1’s symptoms do not establish the claimed version-skew cause

Eighteen tool results beginning with `weekly_quota_` establish repeated quota-related failures. They do not, by themselves, establish that MCP-versus-FastAPI version skew caused them.

Genuine quota exhaustion is a live alternative because the era reportedly coincided with Claude 7-day usage reaching 100%. Other alternatives include stale runtime state, incompatible response parsing, or a provider-side quota response.

To establish D1’s causal chain, the report needs evidence such as:

- the exact request and response showing the contract mismatch;
- the two deployed versions and their incompatible schemas;
- timestamps connecting deployment, first failure, synchronization, and recovery;
- recovery after version alignment while the quota condition remained unchanged;
- exclusion of genuine quota enforcement using successful comparable requests during the same interval.

Until then, “single most damaging finding” overstates the evidence. The defensible claim is that a roughly 24-hour `codex_review` outage was observed and version skew is a plausible diagnosis.

### question — What does “cache hit” mean in each backend’s raw telemetry?

The report should show at least one raw Anthropic usage payload and one raw Codex usage event, followed through the normalization code into `turn_usage`. In particular:

- Does `input_tokens` include or exclude `cache_read_tokens`?
- Does Codex report a request delta or cumulative thread totals?
- Can several model calls contribute to one `turn_usage` row?
- Is the reported percentage `cache_read / input`, or `cache_read / (cache_read + input)`?

Without those answers, even each provider’s percentage may be incorrectly calculated, independently of the cross-provider comparison.

### question — Unsupported claims and internal contradictions could not be fully audited

Because local reads were blocked by the sandbox failure, I could not check every prose number against its table or confirm that every conclusion has a reproducible command. This portion of the requested audit remains unverified; absence of additional findings must not be read as confirmation.

## Verdict

The report supports a descriptive conclusion that the Codex era differed operationally and that a serious `codex_review` failure occurred. It does not support the causal recommendation to keep the orchestrator on Opus.

The weakest and most consequential claim is the cache comparison. Unless identical counter semantics are demonstrated from raw telemetry through storage, the 48.3% versus 97.3% result and “735k uncached tokens/turn” should be removed from the verdict, not merely caveated. Once removed, the remaining evidence is confounded, underpowered, or based on inadequate behavioral proxies, so the runtime recommendation should be recorded as unresolved.

## Round (2026-08-11T08:14:08Z)

## Summary

All major prior findings are adequately addressed. Local verification still failed with `bwrap: loopback: Failed RTM_NEWADDR`, so this review is based on the supplied evidence, not direct file/DB inspection.

## Findings

### suggestion — D1 causality accepted

I accept the D1 refutation; quota exhaustion cannot produce that exact error from a branch determined solely by readiness-policy version mismatch.

### suggestion — Cache normalization is now semantically correct

Given the established backend semantics:

- Codex hit: `cache_read / input`
- Codex fresh: `input - cache_read`
- Claude hit: `cache_read / (input + cache_read + cache_create)`
- Claude fresh: `input + cache_create`

These are aligned definitions: cached tokens divided by total processed prompt tokens, and tokens newly processed/written.

The remaining caveat is that absolute token counts use different provider tokenizers and potentially different prompt envelopes. Thus 47.5k versus 44.3k should not be treated as a precise cross-provider efficiency difference. The revised conclusion—no demonstrated runtime difference, especially with overlapping daily ranges—is appropriately conservative.

### suggestion — Weakest remaining claim: “~2.4 calls/turn attributable to runtime”

The same-day `claude_post` control substantially improves the comparison, but it does not isolate runtime causally. “Research-heavy” is not necessarily matched for task size, phase, autonomy, or required operations. Zero native Read/Edit calls provides a credible runtime mechanism, but the residual should be described as “associated with runtime/tool-interface differences” or “consistent with a runtime effect,” not numerically attributed to runtime.

The revised H1 wording is reasonable: the behavioral evidence rejects loop-style polling in the examined shell probes while acknowledging about 5% redundant probes.

## Verdict

The rewritten verdict is correctly calibrated overall: the Opus recommendation is unresolved, merge superiority is withdrawn, cache accounting is corrected, and workload confounding is acknowledged.

Only the causal wording around the residual `~2.4` tool calls per turn remains slightly stronger than the evidence supports. No new blocking findings.
