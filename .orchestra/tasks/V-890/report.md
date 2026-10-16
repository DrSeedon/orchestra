# V-890: Tera whole-sentence synthesis

Change: `split_pause_segments` cuts only at `[seconds]` markers and sentence ends (`.!?…` followed by whitespace/end; decimals like 2.5 and the abbreviations т.д./т.е./см./г./single-letter initials stay inside). Commas, colons, semicolons, dashes go to the model. A `("gap", None)` piece between sentences is sized in `compose_audio`: `0.42/rate` minus the generated chunk's trailing silence (|x|<=160/32768), floor 0. Sentences with <=3 vowels are glued to the next one. Cache key `audio-v3` -> `audio-v4`. Explicit `[sec]` stays literal silence.

Measurement (VPS, ru_m1, rate 1.0, 3 phrases of 2 sentences each with 4-6 commas/colons/semicolons; silences >= 0.15 s inside the speech span, per minute of speech):

| | pauses/min (>=0.15 s) | median | pause list, s |
|---|---|---|---|
| before (V-878, pieces + fixed 0.33/0.63) | 26.0 | 0.39 | 0.45 0.33 0.69 0.39 0.46 0.37 0.35 0.72 0.34 0.39 0.36 0.39 0.34 0.75 |
| after (whole sentences) | 7.1 | 0.45 | 0.45 0.45 0.47 |

After: exactly the three sentence boundaries carry a pause (0.42 + the model's own tail ≈ 0.45 s); no comma produced a silence >= 0.15 s. Speech span for the same text fell from 32.3 s to 25.3 s. University's V-23 sample (rate 1.2, variant 4) found 17.2 pauses >= 0.15 s per minute with a less comma-dense text; my count is lower, so the model's own comma pausing is text-dependent and small here. Only 3 phrases, one voice, one rate, no listening — measurement, not a quality verdict.

Tests (committed, tests/test_video_artifact.py): split at sentence ends/markers incl. decimals and abbreviation; short-sentence glue; gap size vs rate and vs tail silence incl. floor 0 (Manim env for numpy); explicit pause literal.

## Correction after review: the `("gap", None)` synthesis bug

Defect (commit 82da06cc, found by the orchestrator): `main().synthesize` skipped only `kind == "pause"`, so the `("gap", None)` piece went to `generate_speech("<ru>None</ru>")`. `compose_audio` ignores the value of a gap and sizes it from rate and tail silence, so the generated "None" audio was discarded — which is why my first measurement, which ran the real `main()` through the worker directly, looked correct: no audible "None", durations unchanged, but one wasted model call per sentence boundary and a shifted seed on later segments. Not detectable from the output audio or timing, only from the call log.

Fix (614bf66b): the loop moved into module-level `render_phrase(model, job)`; only `kind == "text"` reaches `generate_speech`. Committed test `test_tera_render_phrase_synthesizes_each_sentence_once_and_never_the_gap` drives `render_phrase` with a fake model on a two-sentence-plus-marker phrase: exactly one call per text piece, none containing "None", exact output length. Mutation check: restoring `kind != "pause"` makes that test fail (1 failed, 42 passed).

Re-measurement through `make.py` (the real worker path: make.py → tts_worker_tera.py via the Tera venv, `--timing-only --rate 1.0`, raw worker output `.tts-cache/*.raw.wav`, same 3 phrases; "e" replaced by «экспоненты» because make.py rejects Latin letters). Before = make.py from commit 025e19a4 (V-885, before V-890), after = current tree:

| | speech span | pauses >= 0.15 s per min | median | pauses, s |
|---|---|---|---|---|
| before | 32.5 s | 25.8 | 0.39 | 14 pauses, 0.33–0.75 |
| after | 25.6 s | 7.0 | 0.45 | 0.44 0.45 0.47 |

Planned video length 37.3 s -> 30.1 s. The numbers match the first, direct-worker measurement, as expected given the discarded gap audio.
