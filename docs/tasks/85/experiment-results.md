# Experiment #85 — Results

> Full analysis: `docs/experiments/85/report.md` · Raw data: `docs/experiments/85/raw-data.md`
> · Script: `docs/tasks/85/experiment.py` · Machine results: `docs/experiments/85/results.json`

## TL;DR
- **Regex gate precision: 0.42** (loose — floods with task/DONE/UI false positives).
- **Haiku quality over all gate-passed pairs: 47% useful** → **below the 70% bar → REFUTED** as a
  single-stage pipeline.
- **Haiku quality on genuine corrections: 100%** (14/14 useful + 4/4 correct-null) → the
  extraction step itself **CONFIRMED**. The bottleneck is the gate, not Haiku.

## Verdict
| Framing | vs >70% bar | Verdict |
|---------|-------------|---------|
| Quality over **gate-passed** pairs (as stated) | 47% | **REFUTED** |
| Quality conditional on input being a real correction | 100% | **CONFIRMED** |

## Numbers
**Gate (hand-labelled, n=50 gate-positives):** TP=21, FP=29 → precision **0.42**; recall ~1.0
(0/60 negatives missed). 253/1154 user_messages flagged (22%).

**Haiku extraction (35 pairs, 2 runs = 70 calls):**
| scope | useful | wrong | correct-null | quality |
|-------|--------|-------|--------------|---------|
| all 30 real gate-positives | 14 | 12 | 4 | **47% useful** |
| genuine corrections (18) | 14 | 0 | 4 | **100% correct** |
| synthetic (5) | 5 | 0 | 0 | **100% useful** |

- **0 JSON parse errors / 70 calls** — output format reliable.
- All 12 `wrong` = gate false-positives (tasks/DONE-reports). Haiku **fabricated a rule** instead
  of nulling — it has no built-in "this isn't a correction" defense.
- `confidence` (mean 0.89) does **not** separate good from hallucinated rules.
- Stability: 3/35 null-flips between runs (borderline inputs); latency median 7.7s/call.

## Per-pair table (run 0)
| # | src | log_id | input is real correction? | extracted | quality |
|---|-----|--------|---------------------------|-----------|---------|
| 1 | real | 182045 | no (task) | NULL | null ✅ |
| 2 | real | 189308 | no (task) | process | wrong |
| 3 | real | 195172 | yes | delegation | useful ✅ |
| 4 | real | 178579 | yes | factual | useful ✅ |
| 5 | real | 187563 | yes | process | useful ✅ |
| 6 | real | 185430 | yes | scope | useful ✅ |
| 7 | real | 194771 | no (task) | scope | wrong |
| 8 | real | 195030 | no (task) | process | wrong |
| 9 | real | 191323 | yes | factual | useful ✅ |
| 10 | real | 191935 | yes | revision | useful ✅ |
| 11 | real | 196082 | no (one-off) | NULL | null ✅ |
| 12 | real | 195392 | no (decision) | process | wrong |
| 13 | real | 179027 | yes | process | useful ✅ |
| 14 | real | 186620 | no (task) | process | wrong |
| 15 | real | 194553 | yes | factual | useful ✅ |
| 16 | real | 185383 | borderline | NULL | null ✅ |
| 17 | real | 187769 | no (task) | process | wrong |
| 18 | real | 191847 | no (DONE) | revision | wrong |
| 19 | real | 178597 | yes | factual | useful ✅ |
| 20 | real | 183136 | yes | scope | useful ✅ |
| 21 | real | 192630 | yes | process | useful ✅ |
| 22 | real | 189965 | no (task) | process | wrong |
| 23 | real | 191661 | yes | revision | useful ✅ |
| 24 | real | 179007 | yes | process | useful ✅ |
| 25 | real | 196437 | yes | process | useful ✅ |
| 26 | real | 182759 | no (DONE) | process | wrong |
| 27 | real | 187651 | no (idea) | delegation | wrong |
| 28 | real | 181789 | no (task) | process | wrong |
| 29 | real | 186880 | no (spec note) | delegation | wrong |
| 30 | real | 195313 | no (help req) | NULL | null ✅ |
| 31–35 | synthetic | — | yes (clean) | del/rev/fact/scope/fact | all useful ✅ |

## Recommendation: build MVP, but TWO-STAGE gate
A single regex→Haiku pipeline would emit ~53% hallucinated rules. **Recommended MVP shape:**
1. Tighten regex (exclude `DONE`/`СРОЧНО:`/`Задача:` prefixes + UI-dump markers) — cheap.
2. Add a Haiku **is-this-a-correction?** classifier before extraction — Haiku clearly understands
   corrections, just needs to gate first. Expected to push effective precision toward the 100%
   seen on genuine corrections.
3. Keep the extraction prompt as-is (proven 14/14). **Do not use `confidence` as a filter.**
