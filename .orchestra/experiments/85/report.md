# Experiment #85 — Can Haiku extract rules from user corrections?

## Hypothesis (restated)
Haiku (`claude-haiku-4-5`) can extract a concrete, actionable rule ("When X → do Y, not Z")
from a `(agent_output, user_correction)` pair with **useful quality on >70%** of the pairs
a simple regex gate let through.

## Method (what was actually done)
- **Data:** Orchestra `logs` DB (read-only). 1154 `user_message` rows; a regex gate flagged
  **253** as "corrections"; **225** of those had a usable preceding `type='text'` agent output.
- **Sample:** 30 real pairs (deterministic, session-spread) + 5 labelled synthetic = **35 pairs**.
- **Extraction:** each pair → Haiku via `claude-agent-sdk` (`ClaudeSDKClient`,
  `model=claude-haiku-4-5`) through `HTTPS_PROXY=127.0.0.1:12340`. Fixed prompt asking for JSON
  `{trigger, action, avoid, category, confidence}` or `null` for one-offs. **2 runs/pair** (70 calls).
- **Scoring:** gate precision hand-labelled on 50 random gate-positives; rule quality hand-scored
  per pair as useful / vague / wrong / null.
- **Robustness note:** the Orchestra server restarted ~5× mid-run (SIGINT-killed the job each time).
  Added an md5-keyed JSONL checkpoint so the run resumed without recomputation. **No data lost,
  no pass/fail criteria changed.** (One bug found & fixed mid-run — see below.)

## Results (numbers)

### Regex gate — LOOSE, low precision
| metric | value |
|--------|-------|
| gate positives (full corpus) | 253 / 1154 (22%) |
| **precision** (hand-labelled, n=50) | **0.42** (21 real corrections / 50 flagged) |
| recall (negatives missed, n=60) | 0 → recall ≈ **high** (~1.0 on sample) |

The gate catches corrections **but floods with false positives**: task assignments
("Перепиши 5 объявлений…"), DONE-reports, and pasted UI/chat dumps all contain trigger
words (`переделай`, `нет`, profanity).

### Haiku extraction — quality depends entirely on input cleanliness
| Scope | useful | wrong | correct-null | quality |
|-------|--------|-------|--------------|---------|
| **All 30 real gate-positives** | 14 | 12 | 4 | **47% useful** |
| **Genuine corrections only (18)** | 14 | 0 | 4 | **100% correct** (14 useful + 4 right-null) |
| Synthetic (5 clean corrections) | 5 | 0 | 0 | **100% useful** |

- Parse reliability: **0 JSON parse errors / 70 calls**. Output format is rock-solid.
- All 12 `wrong` cases share one cause: the **input was a gate false-positive** (a task or
  DONE-report, not a correction). Haiku **invented a plausible-but-unfounded rule** instead of
  returning null — it does not detect "this isn't actually a correction."
- Run-to-run stability: 31/35 non-null on both runs (19/31 identical category); 1 stable null;
  **3 null-flips** (returned a rule one run, null the other) — all on ambiguous/borderline inputs.
- Confidence: mean 0.89, range 0.70–0.95 — **does not discriminate** good from bad
  (hallucinated rules from tasks also scored 0.85–0.95).
- Latency: median 7.7s/call (one 326s outlier from a proxy stall).

## Verdict

| Framing | Result vs >70% bar |
|---------|--------------------|
| As literally stated (quality over **gate-passed** pairs) | **REFUTED** — 47% < 70% |
| Conditional on input being a real correction | **CONFIRMED** — 100% |

**Overall: REFUTED as a one-stage pipeline; CONFIRMED for the extraction step in isolation.**
Confidence: medium-high (n=30 real, single model, hand-scored by one rater).

The hypothesis blamed the wrong component. **Haiku is not the bottleneck — the regex gate is.**
Haiku extracts excellent rules from genuine corrections (14/14) and correctly nulls true one-offs
(4/4). But it has **no defense against a bad gate**: feed it a task and it fabricates a rule with
high confidence.

## Surprises
1. **Haiku never self-rejects non-corrections.** Expected it to null some tasks; it nulled 0/12.
   The `null` branch only fires on rambling/ambiguous text, not on "this is a task not a correction."
2. **Confidence is useless as a filter** — fabricated rules scored as high as real ones.
3. Regex gate precision (0.42) was worse than expected because Orchestra's user_messages mix
   corrections, task assignments, and pasted UI dumps in the same channel.

## Implications for the project (MVP self-learning, #84)
- **Do NOT ship a single regex-gate → Haiku pipeline.** At 0.42 gate precision, ~53% of
  "learned rules" would be hallucinations from non-corrections — worse than no learning.
- **Two cheap fixes, in priority order:**
  1. **Add a classification step** (not just regex): one Haiku/cheap call "is this a correction
     of the agent's previous output? yes/no" BEFORE extraction. The extraction prompt already
     proves Haiku understands corrections; just ask it to gate first. This likely lifts effective
     precision toward the 100% seen on genuine corrections.
  2. **Tighten the regex** to exclude obvious non-corrections (messages starting with `DONE`,
     `СРОЧНО:`, `Задача:`, `новая задача`, or containing UI-dump markers). Cheap, removes the
     bulk of FPs.
- **Two-stage gate (regex prefilter → Haiku is-correction classifier → Haiku extract)** is the
  recommended MVP shape. Extraction quality is already proven; invest the next effort in the gate.
- **Don't trust `confidence`** for filtering — it doesn't separate signal from hallucination.

## Reproduce
```bash
HTTPS_PROXY=http://127.0.0.1:12340 EXP85_SAMPLE=30 \
  uv run python docs/tasks/85/experiment.py
# → docs/experiments/85/results.json (+ resumable results.jsonl checkpoint)
```

## Bug found & fixed during the run
- `pair_key()` initially used Python `hash()` for the checkpoint key. `hash()` is salted per
  process (`PYTHONHASHSEED`), so the resume cache never matched across the (frequent) server
  restarts → duplicate recomputation. Switched to `hashlib.md5`. After the fix, resume worked
  (13 cached pairs skipped on the successful run). Not an Orchestra platform bug — experiment code.
