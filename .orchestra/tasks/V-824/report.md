# V-824 — Sound layer for video-artifact

## Source and licensing

Integrated `sfx.py`, `mix.py`, `qa.py`, and `library.json` from
[Bodila51/opus-sound-layer](https://github.com/Bodila51/opus-sound-layer), commit
`52ac266a24b7dfd3cd06a28c34d5af360a8d7586`. The MIT license and attribution are included beside
the scripts in `scripts/video_artifact/sound/`. The only local behavior changes are the kit and
candidate defaults under `~/.local/share/orchestra-sfx/`, plus retaining complete Openverse API
responses under that data directory's `candidates/searches/`.

Installed kit data: 226 MB at `~/.local/share/orchestra-sfx/`, with 1,139 sounds in 19 types and
an 842-line `CREDITS.md`. The CC0 search preview and candidate derivatives add about 14 MB, so
that entire directory is 240 MB; all of it remains outside the repository. No kit sound files are
in git. Selected Openverse background:
“Room Tone - Empty room with AC & desktop computer running” by seventhsamurai, CC0,
https://freesound.org/people/seventhsamurai/sounds/332417; source audio and metadata remain under
`~/.local/share/orchestra-sfx/candidates/`. The source search response is preserved there.

Effects were selected from the kit by tag shortlist and inspected in waveform/spectrogram sheets:
`whoosh/fs-147285-fh-paper-swipe-surface2-shor-1` (broad upper-frequency swipe, >6 kHz energy)
and `thump/fs-389999-thump-cloth-1` (short low-mid attack and decay). A first low-mid whoosh
measured 1.49 dB under the audibility threshold after AAC encoding, so it was replaced by the
plotted upper-frequency candidate. These descriptions are based on the plots, not a human
listening review.

## Implementation

HTML and Manim `STEPS` can carry `events`, each with `sound` and optional `at`, `weight`, and
`visual`. `make.py` preserves these through step planning and maps `at` (seconds from that step)
to the absolute cue time and frame, including the video pre-roll. Events require `--music`; the
existing voice track and CC0 bed go to `mix.py`, which ducks the bed under speech, targets −18
LUFS for this calm mix, and limits true peak. The resulting WAV is muxed with the existing video.
`qa.py` runs automatically and checks the encoded MP4, cues, audio stems, and picture motion.
Scenes without events still use the pre-existing voice-only mux and Deepgram check path.

## Verification

- `uv run --frozen python -m pytest tests/test_video_artifact.py -q`: 15 passed. The cue test
  constructs timing via `plan()` and verifies the generated event time/frame against the planned
  step offset.
- `scripts/check_instruction_contract.py`: passed. The pipeline skill and active `.codex` copy
  match and are 15,669 bytes.
- Sound-enabled demo: `sound-demo.html`; `sound-demo.mp4` is 19.5 s, 1920×1080 H.264/AAC, 872,886
  bytes. Final `qa-report.json` has `passed: true`, 0 FAIL, and 1 WARN. Measured offset is 0 ms,
  integrated loudness −18.01 LUFS (target −18), true peak −2.03 dBTP, voice 14.9 LU above music,
  and no silence. Both cues have 0.00-frame audio sync error; effects stand out by 1.8 dB and
  2.0 dB. `land` passes: motion stops at frame 226 for cue frame 225. The remaining support-cue
  warning is `move` at frame 55 with the local motion peak at frame 52 (3 frames early).
- Verification iterations: the first scene's small marker did not exceed the picture-motion
  detector before landing, and a hero-body test missed by 0.2 dB. Enlarging the marker and making
  its approach visible resolved the hard `land` failure; the small event was correctly demoted to
  support. The next mix exposed the initial whoosh at 1.49 dB, just below the 1.5 dB audibility
  threshold; selecting the plotted upper-frequency swipe brought it to 1.8 dB.
- The build printed `no DEEPGRAM_API_KEY`; it used `--no-check`, so Deepgram did not run and speech
  recognition remains unverified. The existing Deepgram implementation was not changed. No paid
  API call was made.
