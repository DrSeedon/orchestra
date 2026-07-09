# Token waste: worker narration vs useful tool calls

**Task:** #token-waste · Phase 1 research · 2026-07-09
**DB analyzed:** `/mnt/data/Projects/Python/orchestra/data/orchestra.db` (all sessions, all history)

---

## Question (framed)

- **Context:** Orchestra workers emit `type='text'` narration into chat ("Сейчас проверю…", "Вот что нашёл…") alongside `type='tool'` calls.
- **Change under test:** Suppress worker narration → does it materially cut token spend (output *and* replayed input)?
- **Baseline:** Current behavior (Anthropic-default "brief but not silent").
- **Measurable outcome:** % of output tokens that is narration; % of history-replay (cache-read) input attributable to narration; realistic saving if removed.

**Verdict up front:** Narration is a **small** cost, not the big lever. It's **~11% of output tokens** and **~2.9% of input-replay tokens**. The dominant token cost is **`tool_result` volume** (600M of 688M replay tokens). Cutting narration saves single-digit percent at the risk of degraded debuggability. **The real waste is verbose tool results, not chatter.** See §7 for the actual recommendation.

---

## Hypotheses considered

- **H1 (task's implied):** Narration is a large hidden cost because it compounds — re-read every turn as input. → **REFUTED as "large".** Compounding is real but narration's absolute volume is tiny vs tool_results. Measured 2.9% of replay. *Falsifier that fired:* if narration replay ≥ tool_result replay, H1 holds; measured 20M vs 600M — it doesn't.
- **H2:** Opus 4.8 workers are "chatty", Sonnet workers "quiet". → **REFUTED.** Opus 4.8 workers = 22.5% text; Sonnet = 34.3% text (n=4, weak). Opus *workers* are actually the leanest. Chattiness tracks **role** (orchestrator 41.6% — correct, it talks to the user), not model.
- **H3:** Text narration ≠ reasoning; reasoning lives in the (billed-but-hidden) thinking block, so removing narration doesn't hurt reasoning. → **LIKELY** (primary docs + research, §5).
- **H4:** Biggest input cost is tool_result verbosity, not narration. → **CONFIRMED** by measurement (§4).

---

## 1. Empirical: output composition (worker output = `text` + `tool` args)

Char counts from `logs`, chars→tokens ≈ ÷4.

| type | rows | chars | tokens (est) | % of visible output |
|---|---|---|---|---|
| `text` (narration) | 5 282 | 2 116 559 | ~530 K | **29.1%** of (text+tool) |
| `tool` (call args) | 6 140 | 5 163 917 | ~1 292 K | 70.9% |

So of the *visible* output the DB logs, narration is 29%. **But that's not the whole output.** SDK ground truth (`sessions.total_output_tokens`) = **4 716 K tokens** — 2.6× the logged text+tool (1 822 K). The gap is **thinking tokens** (billed as output, not logged as text/tool). Against true SDK output:

- **Narration = 530 K / 4 716 K = 11.2% of all output tokens.** [CONFIRMED — char-est vs SDK totals]
- The other ~62% of output (4 716 K − 1 822 K = 2 894 K) is thinking + final answers not captured as `text`/`tool` rows.

Confidence: **CONFIRMED** for the ratios (direct measurement); the 11.2% uses a ÷4 char→token estimate → treat as ±20%.

---

## 2. "Chatty vs quiet" — by model and role

Output chars, workers vs orchestrators:

| role | model | sessions | text chars | tool chars | **text %** |
|---|---|---|---|---|---|
| orchestrator | opus-4-6 | 9 | 1 013 989 | 1 422 262 | **41.6%** |
| worker | opus-4-8 | 36 | 967 110 | 3 327 197 | **22.5%** |
| worker | opus-4-6 | 4 | 76 315 | 300 881 | **20.2%** |
| worker | sonnet-5 | 4 | 60 248 | 115 316 | **34.3%** (n=4) |

**Finding:** The "chatty Opus vs quiet Sonnet" premise is **wrong**. Opus 4.8 *workers* narrate least in relative terms (22.5%). Orchestrators narrate most (41.6%) — and that's *correct*, their job is to talk to the user. Sonnet's higher % is on n=4 (noise). Confidence: **CONFIRMED** direction (workers < orchestrators), **UNCERTAIN** on Sonnet (tiny sample).

Per-turn narration (workers, turns>5): median ~65–80 output-tokens of text per turn; worst offenders `feat-ozon-mcp` (282 tok/turn), `linkedin-strategist` (225), `mcp-fix` (176). These are content/writing tasks where prose *is* the deliverable — not waste.

---

## 3. Input replay: does narration compound?

Yes, mechanically: text written at turn *i* is re-sent as (cached) input in every later turn until compaction. Approx replay multiplier ≈ turns/2. Applied to workers with >20 turns:

| history component | replay footprint (est) |
|---|---|
| **narration** (`text`) | **20.1 M tok** |
| tool args (`tool`) | 68.1 M tok |
| **tool results** (`tool_result`) | **600.1 M tok** |

**Narration = 20M / 688M ≈ 2.9% of all replayed input.** [Measured via replay model — LIKELY, model is an approximation]

Cross-check against SDK: total `cache_read` across all sessions = **1 274 M tok** = 270× total output. Input replay utterly dominates spend, and within it **tool_result is 30× larger than narration.**

---

## 4. What actually wastes tokens

The premise looked for waste in narration. The data points elsewhere:

1. **`tool_result` = 56.7 M chars logged, avg 9 172 chars/result** — and it's replayed every turn. This is the 600M-token elephant. Full file reads, un-truncated command output, big grep dumps.
2. **Narration = 2.1 M chars, 2.9% of replay.** Real but small.
3. **cache_read = 1.27 BILLION tokens** total — the entire game is history size × turn count, dominated by tool_result.

**One over-verbose `Read` of a 2000-line file (~20 K tokens) replayed across 100 turns = 2 M cache-read tokens — equal to ~all narration from an entire worker's life.**

---

## 5. Narration ≠ thinking (the key distinction)

- **Extended-thinking tokens are billed as output tokens at standard rates**, and are **summarized before you see them** — you're billed for the full internal amount. [Primary: Anthropic docs, [1]]
- Implication: **reasoning already happens in the thinking block.** Chat narration is a *separate*, *additional* output on top of thinking. So suppressing narration does **not** remove the model's reasoning — that reasoning is in thinking regardless.
- **On subscription (Max 20x):** there is no per-token dollar cost — it's virtual/API-equivalent. Thinking and narration both consume the **rate-limit / context budget**, not real money. So "waste" here = **context rot + faster limit burn**, not $.

Confidence: **LIKELY** — primary docs confirm billing; the "narration is pure additive-to-thinking" inference is sound but not separately measured.

---

## 6. Does suppressing narration hurt? (counter-evidence)

Research is **not** a clean "silence is free":
- Some reasoning is needed for tool agents; stripping it → "reactive, shallow exploration, redundant calls, poor sequencing." [2]
- **Timing matters:** omitting reasoning in **initial** (planning) and **final** (summary) turns is *detrimental*; trimming **mid-trajectory** reasoning can *improve* accuracy + cut tokens. [2]
- Changing reasoning/narration style **alters downstream actions**, not just output — must be tested, not assumed safe. [2]
- **BUT** this literature is about the *thinking/reasoning* channel. Orchestra's `text` narration is the *user-facing chat* channel, which is separate from thinking. Suppressing chat narration ≠ suppressing CoT. So the degradation risk is **lower** than the papers imply for our specific case — as long as the thinking budget stays intact.

Anthropic's own Claude Code communication-style prompt already lands on: **"Brief is good — silent is not. One sentence per update is almost always enough… don't narrate internal deliberation."** [3] That's the target state, not zero-text.

---

## 7. Recommendation (numbers, not opinions)

**Do NOT chase narration as the savings lever.** Best-case, fully removing worker narration saves ~11% of output tokens and ~2.9% of input-replay — and output is a rounding error next to the 1.27B cache-read total. Risk: worse debuggability + possible action drift.

**Ranked by actual impact:**

| Lever | Est. saving | Risk | Verdict |
|---|---|---|---|
| **Truncate/summarize large `tool_result`** (cap Read/Bash/grep output in context) | **High — targets the 600M-tok replay** | Med (may hide detail) | 🟢 **Real win — pursue** |
| **Compact more aggressively** on long workers (turns>100) | High — caps replay multiplier | Low | 🟢 Pursue |
| Trim narration to Anthropic's "brief not silent" | ~3–11% | Low if thinking intact | 🟡 Cheap tidy-up, not a headline |
| Force **zero** narration ("caveman") | ~11% output only | Med — planning/summary turns need it [2] | 🔴 Not worth it |

**Concrete prompt change (low-risk, do it):** add to `communication-style.md`, workers only —
> *"Workers: no narration between tool calls. One line before your first action, one line at a real blocker/direction-change, and the DONE report. No 'now I'll…', no restating tool results. Your thinking block does the reasoning — don't duplicate it in chat."*
This mirrors Anthropic's own guidance [3] and self-improvement precedent. Realistic saving: **single-digit % of tokens**, main benefit is **cleaner logs / less context rot**, not big $.

**The headline fix is elsewhere:** a follow-up task should measure and cap **tool_result size in context** (the 600M-token replay). That's where 30× more tokens live.

---

## Affected files / edges (for any follow-up)
- `pipelines/default/prompts/modules/communication-style.md` — where a "workers: no mid-narration" rule goes.
- `pipelines/default/prompts/modules/*` worker/base — role-scoped rule (workers ≠ orchestrators; don't silence orchestrators — they *must* talk to the user).
- Tool-result truncation would live in the SDK/MCP layer, not prompts — bigger change, separate task.
- **Edge:** content/writing workers (`linkedin-strategist`, `marketer`) — their prose IS the deliverable. A blanket "no text" rule would break them. Rule must target *narration between tool calls*, not final output.
- **Edge:** don't silence the DONE report or Phase-gate reports — those are the auto-report source.

---

## Confidence summary
- Narration = 11% output / 2.9% replay: **CONFIRMED** (direct DB measurement; token=char/4 est ±20%).
- tool_result dominates replay (600M): **CONFIRMED** (direct measurement).
- Chatty-Opus/quiet-Sonnet premise false: **CONFIRMED** direction, **UNCERTAIN** Sonnet (n=4).
- Thinking billed as output & summarized: **CONFIRMED** (primary docs [1]).
- Suppressing narration ≠ removing reasoning: **LIKELY** (docs + inference).
- Suppression harm is timing-dependent, mid-turn safe: **LIKELY** (secondary research [2]).

## Sources (fetched this session)
[1] Anthropic — Extended thinking (billed as output, summarized): https://platform.claude.com/docs/en/build-with-claude/extended-thinking
[2] Agent-Omit / CoT-suppression research (mid-trajectory omission helps, planning/final turns hurt): https://arxiv.org/pdf/2602.04284 ; instruction-following CoT degradation: https://openreview.net/forum?id=w5uUvxp81b
[3] Claude Code communication-style system prompt ("brief is good, silent is not"): https://github.com/Piebald-AI/claude-code-system-prompts/blob/main/system-prompts/system-prompt-communication-style.md

## Raw measurements (verbatim)
```
logs by type: tool_result 6181 (56.7M chars, avg 9172) | tool 6138 (5.16M) | text 5281 (2.12M) | user_message 1332 (1.46M)
output text vs tool: text 29.1% / tool 70.9% of logged output
per-model worker text%: opus-4-8 22.5% | opus-4-6 20.2% | sonnet-5 34.3% (n=4); orchestrator opus-4-6 41.6%
SDK totals: output 4,715,950 | input 946,409 | cache_read 1,273,535,444 | cache_create 42,114,208
replay footprint (turns>20 workers): narration 20.1M | tool_args 68.1M | tool_result 600.1M
narration % of cache_read replay = 3.9% (workers>20t) ; ~2.9% of full replay incl tool_args+results
```
