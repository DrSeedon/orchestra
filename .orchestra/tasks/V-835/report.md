# V-835: quick video draft and early checks

## Sample and baseline

Used `/home/kesha/projects/University/semester-3/Applied-Data-Analysis/module2-index/video/v2/index_story.py` read-only. It has 39 voice steps and 91 `self.play` calls; `index_story.py` SHA-256 was `f454d64e0827af12fbd4a1825c854b9b2aeb9357d5cf1125dd7ceb3dc1c83e44` before and after the checks. Manim was Community v0.20.1. New heavy runs used the host user slice through SSH, and no run changed the sample source.

The baseline contact sheet required `make.py ... --stills --no-check`, which rendered the entire 39-step scene before it produced a draft: **237.34 s**, peak RSS **2,275,824 KiB** (`before/stills.time`). The baseline timing check ran Manim `--dry_run` on the same scene: **198.35 s**, peak RSS **274,944 KiB** (`before/timing.time`).

## After

`--preview-range 4:6` produced a three-frame low-quality contact sheet in **22.66 s** (about 10× faster than waiting for the full old contact sheet); `--preview-step 6` took **8.31 s**. The three selected frames show the data split, histogram, and overlap annotation. The draft is [index_story-preview-contact.png](after/index_story-preview-contact.png). It was also queued to the owner for delivery before any full render. The HTML preview path was separately smoke-tested on V-824's four-step scene with `--preview-range 1:2 --lang en`.

`--timing-only --no-check` completed in **21.07 s**, peak RSS **2,278,680 KiB** (RUAccent process included). It reused the existing speech cache via a symlink to the baseline cache; the cache contents are not copied. The static checker evaluated all **39/39** steps, found **zero overruns**, and reported a minimum remaining animation budget of **0.0731 s** (step 28); see `after/index_story.timing-check.json`. This replaces the scene-wide frame-producing dry run on scenes the AST analyzer can model. Unsupported control flow keeps the `--dry_run` fallback.

## Implementation and verification

- `--preview-step N` and `--preview-range A:B` skip TTS and render selected HTML/Manim stop frames; Manim animation-number ranges are indexed from the scene AST. The preview suppresses `VoiceScene`'s trailing hold so Manim can stop at the selected animation.
- `--timing-only` plans from cached or newly synthesized voice clips, checks statically modeled Manim animation times before frame rendering, writes a timing-check report, and returns without video/mux/Deepgram work.
- `build_lock()` uses host-wide `flock` at `~/.cache/orchestra-video-artifact/build.lock`; a waiting build prints the current build name and PID. Voice, HTML-frame, and Manim-step output includes `n/N` and an ETA.
- Deepgram matching normalizes common Russian and English cardinal words (including composite values and two-and-a-half thousand) to the same numeric token as digits. Skipped numerals are reported in `numeric_recall` but do not lower lexical recall; missing ordinary words still lower the check. Tests cover both cases.
- `~/.local/share/orchestra` source project was not edited. University sample SHA stayed unchanged. Full MP4 rendering and Deepgram recognition were not run for this workflow change.

Checks: `~/.local/bin/uv run --frozen python -m pytest tests/test_video_artifact.py -q` → **21 passed**. The suite compiles every `.py` under `scripts/video_artifact/` (including `sound/`) and covers remaining-budget timing/overrun detection, spoken-number equivalence with strict ordinary-word matching, and two-build lock serialization/wait messaging. The shared video-artifact prompt is **16,226 bytes**, below its 16 KiB limit.
