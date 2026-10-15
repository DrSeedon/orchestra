# V-878 result
Real 4-step Tera build (rate 1.0, outside cgroup): exit 0, 18.0 s MP4. Silence runs >=0.25 s measured on the voice track (threshold |s|<300, 20 ms windows): comma pauses 0.36 s (at 2.5 s) and 0.38 s (6.86 s), sentence pause 0.70 s (8.56 s), silent step 1.10 s hold inside a 1.86 s gap (10.54 s). Matches 0.33 / 0.63 s design.
Fixes found during build: stress patch must target the imported normalizer's globals (`tts_worker_tera.patch_wordwise_stress`); explicit `[sec]` bounded 0.05..10; cache key bumped (audio-v2).
Unverified: CMU Serif is not installed (fc-match falls back to DejaVu Sans; Latin Modern present); Deepgram check skipped (no key). Raw media not committed.
