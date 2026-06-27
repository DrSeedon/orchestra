# Experiment #85 — Hypothesis

## Hypothesis (one sentence)
Haiku (`claude-haiku-4-5`) can extract a concrete, actionable rule of the form
"When X → do Y, not Z" from a `(agent_output, user_correction)` pair with useful
quality on **>70%** of the pairs that a simple regex gate let through.

## Background (real data verified)
- DB: `/mnt/data/Projects/Python/orchestra/data/orchestra.db`, table `logs`
  (columns: `id, session_id, ts, type, content`).
- 1117 `user_message` rows. ~228 contain coarse correction signals
  (`хуйня/хуит/не так/переделай/неправильно/еблан/блять/нахуй/сука/делегир/нет`),
  spread over 11 sessions with strong signals.
- Pairing is feasible: for a correction at log id N, the preceding `type='text'`
  row in the same `session_id` with `id < N` is the agent output being corrected.
- Haiku reachable via `claude-agent-sdk` (`ClaudeSDKClient`, `model='claude-haiku-4-5'`)
  through `HTTPS_PROXY=http://127.0.0.1:12340` — verified end-to-end (returned `HAIKU_OK`).
- No `anthropic` python SDK and no `ANTHROPIC_API_KEY`; the project SDK uses Claude CLI
  subscription auth. This is the intended path (task says "Haiku via SDK").

## Method (exact steps)
1. **Dataset build** (`build_pairs()` in `experiment.py`):
   - Pull all `user_message` rows.
   - Classify each with a **regex gate** (correction vs not).
   - For every gate-positive message, fetch the nearest preceding `type='text'` in the
     same session as `agent_output`. Drop pairs with no usable preceding output.
   - Target: ≥10–15 real pairs. If <10 usable, top up with clearly-labelled `synthetic`
     pairs modelled on observed patterns (delegation, redo, factual, scope).
2. **Regex gate evaluation**:
   - Hand-label a balanced **audit sample** of user_messages (all gate-positives capped at
     ~40 + a random 40 gate-negatives) as correction / not-correction.
   - Compute TP / FP / FN → precision & recall of the gate.
3. **Haiku extraction**: for each gate-positive pair, send to Haiku with a fixed prompt
   asking for JSON `{trigger, action, avoid, category, confidence}` or `null` for one-offs.
   `category ∈ {delegation, revision, style, factual, scope, process}`.
   Run each pair **2 times** (temperature default) to check stability; keep run 1 for scoring,
   note disagreements.
4. **Quality scoring**: each extracted rule labelled (by rubric, in-script heuristic +
   manual review in report) as:
   - `useful` — concrete & actionable
   - `vague` — too abstract ("be more careful")
   - `wrong` — misread the correction
   - `null` — correctly returned null for a true one-off

## Metrics collected
- Regex gate: precision, recall, TP/FP/FN counts.
- Haiku: counts of useful / vague / wrong / null; **quality rate = useful / (gate TP pairs)**.
- Run-to-run stability (same category & non-null on both runs).
- Per-call latency and rough token use.

## Pass/Fail criteria (fixed before running)
- **CONFIRMED** if Haiku quality rate (useful / TP pairs sent) **> 70%**.
- **REFUTED** if quality rate **< 50%**.
- **INCONCLUSIVE** if 50–70%, or if usable real-pair sample < 10 (low confidence).
- Regex gate is reported as supporting context, not a pass/fail gate itself
  (secondary target: precision ≥ 0.6 to be worth keeping).

## Controls
- Constant: same Haiku model, same extraction prompt, same DB snapshot, same proxy.
- Variable: only the input pair.
- No Orchestra code touched — read-only DB access; all artifacts under `docs/`.

## Deliverables
- `docs/tasks/85/experiment.py` — reproducible script.
- `docs/experiments/85/raw-data.md` — raw outputs (Phase 2).
- `docs/tasks/85/experiment-results.md` + `docs/experiments/85/report.md` — final (Phase 3).
