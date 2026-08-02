# Q6 lock amendment 01 — `validate_artifacts.py` corpus constant

**Recorded because it changes a file covered by `preregistration-lock.json`.**
Disclosed rather than silently re-locked.

## What changed

```diff
-HOLDOUT_FIXTURES = 22
+HOLDOUT_FIXTURES = 21
```

One line, one file (`validate_artifacts.py`). Nothing else drifted — all other
13 locked sources still match the lock byte-for-byte.

## Why

`22` is a leftover from the Q5 corpus. Q6 has **21** holdout fixtures, because
two internally contradictory fixtures were removed and not replaced in kind.

The measured data was correct: 63 outputs per variant = 21 fixtures x 3
repetitions. The stale constant expected 66, so `validate_artifacts.py
generations` failed with `{'orchestra_current': 63, 'hot_state_ledger': 63}`.

The generation stages themselves succeeded before this: primary 126/126,
presave 6/6, recompact 4/4, scoring 4 modes — all exit 0.

## Why this does not compromise the preregistration

The constant is used **only** by the artifact validator's shape checks — that
per-variant counts are balanced, the blinding map is the expected size, and one
batch exists per fixture. It appears in no gate, no metric, no prompt, no
fixture, no scorer, and no interval. `analyze_results.py` does not import it.

Fixing it makes the validator agree with the corpus the protocol already
declares ("**21 Q6 holdout fixtures**", `protocol.md`). Leaving it would have
meant a validator that can never pass on the corpus it is validating.

The amendment was made **after generation and before judging**, so it could not
have influenced any generated output. Judging and analysis are unaffected either
way, since neither reads this constant.

## Integrity note

`validate_artifacts.py` will now mismatch the `source_sha256` recorded in
`preregistration-lock.json`. That is expected and is the honest state: the lock
records what was frozen at lock time, and this file documents the single
deviation. **The lock file is not being rewritten** — rewriting it would destroy
the evidence that anything changed.

Verified after the amendment: 13 of 14 locked sources unchanged; the 14th differs
by exactly the diff above.
