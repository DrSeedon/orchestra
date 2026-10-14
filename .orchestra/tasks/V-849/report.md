# V-849: subtitle and Vosk punctuation fixes

## Cause and fix

Both caption paths applied the stress-marker cleanup to `(sub ?? say)`. That removed literal plus signs from explicit screen text such as `W·X + b`. `caption_text()` now removes `+` only when falling back to TTS `say`; HTML `VOICE_JS` uses the same null-aware rule, so an explicit `sub` is left verbatim.

The installed Russian TTS package splits punctuation in `vosk_tts/synth.py:g2p_multistream` with `(...|- |[ ,.?!;:"()])`; its phoneme map has the corresponding ASCII punctuation, and `synth_audio` separately normalizes only em dash. Guillemets, typographic quotes, most Unicode dash variants, and the Unicode ellipsis therefore reach word-to-phoneme conversion as part of a word. `normalize_vosk_text()` maps those forms to ASCII quotes, a spaced hyphen, and `...`; NBSP, narrow NBSP, and thin spaces become ordinary spaces. Other unrecognized symbols fail in `check_steps()` before RUAccent or TTS starts, with step number and offending glyph. `say` and `sub` remain unchanged in timing/check records; only `_tts_text` sent to Russian speech is normalized.

## Real build

Built [symbol-demo.mp4](video/symbol-demo.mp4), 8.03 s, 174,355 bytes, H.264 video plus AAC audio. Its two Russian phrases include `«…» — …` and `…`; the on-screen subtitle visibly retains `W·X + b`. The make command completed RUAccent, Vosk synthesis, HTML frame rendering, mux, and MP4 output; it skipped Deepgram because this was a synthesis regression check (`--no-check`). Peak RSS was 2,272,868 KiB, measured in the SSH user slice (`video/make.time`).

## Verification

`~/.local/bin/uv run --frozen python -m pytest tests/test_video_artifact.py -q` → **24 passed**. Tests exercise the Manim caption helper, the injected HTML caption path in Playwright, typographic quote/dash/ellipsis normalization, and early unsupported-glyph errors.

Mutation checks were run against the committed tests and each mutation made its test fail: restoring plus stripping on `sub` failed the caption helper test; restoring blanket HTML plus stripping failed the Playwright caption test; bypassing Vosk character translation failed the normalization test; removing early `check_steps()` validation failed the unsupported-symbol test. Each mutation was restored, then the complete suite passed again.

Manim render and Deepgram recognition were not part of this short HTML MP4 check. The new MP4 is under 10 MB; no paid API was called.
