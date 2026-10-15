# V-885: Tera raw phrases clip

Cause (confirmed): TeraTTS `generate_speech` returns float samples beyond ±1.0; `write_wav` in the pinned snapshot does `np.clip(samples,-1,1)` → int16, so every overshoot is a flat-topped full-scale sample. No headroom was left by `tts_worker_tera.py`.

Fix: `level_phrase()` in `tts_worker_tera.py` scales each phrase to RMS -20 dBFS, but never above a -3 dBFS peak (gain = min of the two). Cache key `audio-v2` → `audio-v3`, so clipped clips are not reused. Kokoro/Vosk unchanged (measured below, no clipping).

Measurement, 4 real phrases on the VPS (voice ru_m1, rate 1.0), full-scale samples = |int16| >= 32767:

| | before (peak / full-scale / RMS) | after |
|---|---|---|
| p0 | -0.00 dBFS / 203 / -14.5 dB | -3.00 / 0 / -20.2 |
| p1 | -0.00 / 150 / -14.9 | -3.22 / 0 / -20.0 |
| p2 | -0.00 / 57 / -14.0 | -4.24 / 0 / -20.0 |
| p3 (short exclamations) | -0.00 / 130 / -15.6 | -3.00 / 0 / -22.3 (peak-limited) |

Inter-phrase RMS spread before 1.6 dB (compressed by clipping), after 0.2 dB for p0–p2; p3 stays 2.3 dB quieter because its peak, not RMS, is binding. A peak-only attenuation was tried first: it gave a 3.5 dB spread, hence the RMS leveling.

Kokoro (af_heart) 4 phrases: 0 full-scale, peaks -1.97..-6.42 dBFS. Vosk (speaker 1) 4 phrases: 0 full-scale, peaks -4.44..-5.71 dBFS. No fix needed. Sample is small (4 phrases per engine); University's 45-phrase measurement was Tera only.

Test: `test_tera_level_phrase_removes_overs_and_evens_levels` (runs in the Manim env for numpy; skips without it). Not covered by test: the call-site wiring in `synthesize`, verified only by the real run above.
