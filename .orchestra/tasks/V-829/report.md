# V-829 — Restore Manim voice-scene builds

The failure was exactly one missing indentation in `VoiceScene.setup()`: the assignment reading
`VIDEO_ARTIFACT_VOICE` was at column zero, outside the method. The remaining setup body was already
indented correctly.

Compared the V-819 file at `577a8393` with the preceding implementation in
`scripts/explainer_video/manim_voice.py` at `46eb8fda` (the source file did not exist at
`577a8393^`). The intended V-819 differences were the video-artifact name and environment-variable
renames plus the moved font path. The only functional difference was the lost indentation on that
assignment; the rest of the 111-line class matches the prior implementation.

Added a regression test that compiles all 8 Python files recursively under `scripts/video_artifact/`,
including `sound/`. This catches syntax failures without importing optional runtimes.

Verification:

- `python3 -c "import ast; ast.parse(open('scripts/video_artifact/manim_voice.py').read())"` — passed.
- `uv run --frozen python -m pytest tests/test_video_artifact.py -q` — 16 passed.
- Manim Community v0.20.1 real smoke render — `Smoke.mp4` produced at 480p15, 30,335 bytes; four
  animations rendered, including the `VoiceScene.setup()` path.
- No Orchestra restart is needed; this is a local render-script fix.
