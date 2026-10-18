# V-943 — the "add sound to motion video" prompt vs our video-artifact sound layer

Class B research: findings only, nothing in the skill or scripts was changed. The post (t.me/vibecoding_tg/4121) could not be fetched (Telegram serves only page chrome to a non-browser client), so the six points are taken from the orchestrator's summary of it. Where I say "the post claims", I mean that summary.

## Short verdict

| # | Point | Verdict | Price of porting |
|---|---|---|---|
| 1 | Licensed music only, source and licence stated, no programmatic music/SFX | **Already have** (stricter on SFX, one gap on music) | ~0.5 h to close the gap |
| 2 | librosa beat grid checked against the <120 Hz waveform | **Don't take as a default**, take only as an opt-in tool for a rhythmic user track | ~0.5 day |
| 3 | Align cuts/titles to beats (change animation or shift music start) | **Don't take** for our voice-driven timeline; the cheap half (music start offset) already exists | 0 / ~1 day for real alignment |
| 4 | One ready-made SFX file per cut/motion from the project library first | **Already have**, ours is larger and with a gain solver | 0 |
| 5 | Voice loudest, music ducked, SFX above music, ≈−16 LUFS, peak <−4 dBFS, measured on the MP4 | **Already have** the mechanism and the MP4 measurement; the numbers differ by choice | 0 (a preset line if the owner wants −16) |
| 6 | Frames before/after each SFX, waveform from the MP4, 5 timestamps for a headphone check, never claim "sounds good" | **Partly have**; take the frame crops and the 5 timestamps | ~0.5 day |

## Evidence per point

### 1. Licensed music, no generated sound

- Ours: SFX library is CC0 only — 1 140 catalogued recordings, 20 types, Kenney packs and Freesound CC0 (`scripts/video_artifact/sound/sfx.py:8`, `:292` requests `license="cc0"` from the search API; credits written by `sfx.py:402-425`; kit credits file `~/.local/share/orchestra-sfx/CREDITS.md`). The skill forbids synthesizing hits, clicks and whooshes (`.orchestra/pipelines/default/prompts/skills/video-artifact.md:271`). Source and licence are recorded per file in the kit's `CREDITS.md` and `catalog.json`.
- Music: the default bed is one CC0 Freesound track, "Long Ambient Pad" by indigo.cloud (`make.py:512-520` `default_bed`; skill lines 257-260); `--music path` takes another CC0 or owner-provided bed (`make.py:1023`); `--no-music` for voice only.
- Gap, small: `mix.py:22-24,69` still allows `synth:pluck` / `synth:bell` ("musical accents only"). That is programmatic generation, narrower than the post's ban; it is off the hit/click/whoosh path. Whether to ban it is an owner call; I did not check whether any shipped video uses it.
- The "source and licence stated" requirement is satisfied for the kit and for the default bed (credit string in `catalog.json`), but for a `--music` file nothing forces the author to state source and licence; `make.py` only checks that the file exists (`make.py:1091-1092`).

What Mixkit and HyperFrames actually are (fetched 2026-10-18):

- **HyperFrames** (heygen-com/hyperframes): HTML → MP4 renderer, code under Apache-2.0 (`LICENSE`, README). It has no SFX library of its own at the top level; audio sourcing is the `/media-use` skill. Its bundled SFX is **21 mp3 files** in `skills/media-use/audio/assets/sfx/` (chime, click, click-soft, error, glitch-1..3, impact-bass-1/2, key-press, notification, ping, pop, riser (10.03 s), sparkle, typing, whoosh, whoosh-short, whoosh-cinematic) with a `manifest.json` (duration + description per file). Their `CREDITS.md` states all of them come from Pixabay under the **Pixabay Content License** (commercial use, no attribution). Verified by reading that CREDITS.md; I did not read the Pixabay licence text itself. With a HeyGen credential, SFX is instead retrieved from HeyGen's online library (`/v3/audio/sounds`, min_score 0.4); music via `/media-use` retrieve or generate (Lyria recipe in the repo); the skill says "never generation" for SFX but allows generated BGM. Their recommended SFX volume is 0.35, under voice and BGM (`references/sfx.md`).
- **Mixkit**: free stock site (Envato). Sound effects are under the separate "Mixkit Sound Effects Free License": commercial and personal use, no attribution required, but no re-registration/claiming and no redistribution without significant changes; stock music, video and templates have different licences. This comes from Mixkit's own pages as summarised by the search tool; the licence text page returned no terms to the fetcher, so the exact wording is unverified. Mixkit is not CC0: files may not be redistributed as-is, which matters because our kit is stored outside git and never redistributed, so it would work, but our "CC0 everywhere" statement would stop being true.
- Consequence: HyperFrames' 21 files add nothing to a 1 140-file CC0 kit; Mixkit would be a weaker licence than what we use.

### 2. librosa beat grid + <120 Hz waveform check

- Ours: no beat analysis anywhere (`rg -i "librosa|beat grid|bpm|tempo"` over `scripts/video_artifact` and the skill finds only three Freesound titles in `library.json`). Our default bed is a calm pad.
- HyperFrames' own `music-to-video` skill uses librosa in a single analyzer `analyze-beatgrid.py` and itself says the `bpm`/`beats_sec` are reliable "only when the music is genuinely rhythmic; on calm music the grid is a metronome the tracker imposed" (SKILL.md, "One analyzer, and you trust it"). So the premise of the post's check — a rhythmic track — is not our default case.
- Probe on our only music bed (46.0 s, CC0 pad; `beat_probe.py`, `beat_probe.json`, `beat_probe.png`): librosa returns 47.9 BPM, 31 beats at a median interval 1.254 s; the plot shows an irregular, holey grid over noise-like onset strength (onset-envelope coefficient of variation 0.27, 67 low-band flux peaks with no periodicity). Beat-to-nearest-<120 Hz-peak offset: median 0.00 s, p10 −0.325 s, p90 +0.348 s, only 25.8 % within 50 ms. Reading: there is no rhythm to align to, so the check has no signal on our bed. The 0.22 s offbeat shift the post describes **cannot occur or be detected here**; it was **not reproduced** on our tracks.
- Because our bed has no rhythm, I also ran the same method on two rhythmic CC0 loops from our own library list (Freesound previews, known BPM; `loop_probe.py/json/png`), tiled to 30 s:
  - "90 bpm funky break" (known 90 BPM, loop 10.667 s = 16 beats): librosa 89.1 BPM, beat period 0.673 s vs true 0.667 s. The plot shows kicks every 2.667 s; librosa lines land on them within ≈0.05 s, no 0.22 s shift.
  - "108_trance_loop" (known 108 BPM, loop 8.889 s = 16 beats): librosa reported **143.6 BPM** (beat period 0.418 s vs true 0.556 s), a 4:3 metrical-level error — a wrong grid, not a shifted one.
  Coverage: 2 loops, a crude nearest-peak offset statistic (25–35 % within 50 ms, which mostly reflects off-kick beat lines, not a shift); not a benchmark. It shows that a librosa grid can be wrong in tempo as well as phase, which supports the post's "check against the waveform" instinct for rhythmic tracks, and gives no evidence for a systematic 0.22 s shift.
- Verdict: don't add a beat grid to the default pipeline (nothing to align on the calm bed). If the owner starts supplying rhythmic tracks, take a small opt-in `--analyze-music` script: librosa grid + low-band onset overlay plot + global offset estimate (median of nearest low-band onset − beat) + a hard refusal to trust the grid when tempo-gram confidence is low. Price ≈ one ~60-line `uv run --script` file next to `qa.py` (the `# /// script` header pattern already used by `mix.py`/`qa.py`; librosa and 35 packages resolved in ~0.1 s from cache, ≈ 0.5 day including one rhythmic test track and its QA plot).

### 3. Align scene changes and titles to beats

- Ours: step durations are set by the voice (`make.py` `plan`: intro + phrase + pause, divided by rate), so the picture follows speech, not music. Music only has `start_s` (`mix.py:54`, default 0; `make.py:545`) and a 1 s crossfaded loop (`mix.py:298-304`).
- Measured on `.orchestra/tasks/V-937/scene.mp4` (16 steps, cuts at `step_start + pre(0.4 s)`; the 46 s bed loops with period 45.016 s, so cut times were folded into the bed): distance from each cut to the nearest librosa beat −2.53…+0.56 s, median |0.414| s, **1 of 16 within 100 ms**; mean |distance| 0.55 s. The half beat interval is 0.627 s, so a cut can be at most 0.63 s from a regular grid; our cuts sit about where random placement would. Expected for a voice-timed film on an unmetered bed; it is not a defect, because the bed has no beat to miss. A distance from an *imposed* grid is not evidence of mis-sync.
- Verdict: don't take. Changing animation timing to beats would fight the voice-driven plan; shifting the music start is possible today by `start_s` but pointless on a pad. Real beat alignment for a rhythmic track would require the opposite design (music sets timing, voice fits) — an architectural fork, not a port; it needs the owner's decision first.

### 4. A separate SFX per cut or motion, library first, otherwise ask

- Ours: `events: [{id, at, sound, weight, visual}]` in `STEPS` (skill lines 261-266), placed on the planned step timeline by `make.py:523-545` `sound_cues`; `mix.py` aligns each sound's peak to the cue (`mix.py:18-25,334-336`), solves a per-event gain against the music+voice bed in the sound's own band (`mix.py:27-32,366-372`), rotates a type's defaults for repeats (`mix.py:20,25`), layers sounds, and applies one shared short room. Library: `sfx.py browse/search/add`, 20 types (click, key, tick, tap, pop, thump, hit, boom, paper, swish, whoosh, transition, riser, reverse, glitch, ui, zap, chime, shimmer, bed). "Otherwise ask" = ours says search CC0 and review waveform/spectrogram (skill lines 268-271).
- Verdict: already have, richer than the post's flat 0.35 volume. HyperFrames' 21 files are a subset in kind.

### 5. Levels and measurement

- Ours: voice normalised to −16 LUFS (`mix.py:290`); music brought to −20 LUFS (calm −23) before ducking (`mix.py:309`); ducking default 10 dB with 80/250 ms attack/release under speech (`mix.py:16,322-323`); SFX gain solved so the 2–8 kHz lift is ≤4 dB and the peak ≤6 dB over the local bed (`mix.py:27-29`), so SFX end above the music; master target punchy −14 / calm −18 LUFS, look-ahead true-peak limiter at −2 dBTP (`mix.py:280,35-36,399`).
- QA on the **encoded MP4**: `qa.py:40` decodes the MP4 through ffmpeg; `qa.py:126-127` requires integrated loudness within 1 LU of target and true peak ≤ −1 dBTP; `qa.py:25` requires music ≥ 8 LU under the voice while it speaks; `make.py` runs it automatically (skill line 274).
- Measurement on `.orchestra/tasks/V-937/scene.mp4` with ffmpeg `ebur128=peak=true` (`scene-ebur128.txt`): **integrated −18.0 LUFS, LRA 2.6 LU, true peak −2.9 dBFS** — exactly the calm preset, inside our own checks.
- Differences from the post: ≈−16 LUFS vs our −14/−18; peak <−4 dBFS vs our −2 dBTP limiter and −1 dBTP gate. These are level choices, not missing mechanisms. I have no measured evidence that −16/−4 is better for our delivery (Telegram feed with subtitles, skill line 26); changing them would be an owner-set criterion without measured threat evidence. If asked, it is one `lufs` value in the cue sheet (`mix.py:51`) or a third preset.
- Verdict: already have.

### 6. Frames around each SFX, waveform from the MP4, 5 timestamps, no "sounds good"

- Ours: `qa.py:191-201` writes `qa.png` — waveform of the final MP4 audio, spectrogram, and picture motion with every cue marked; `qa.py` `picture` checks tie each cue to a hard frame change/motion peak/landing (`qa.py:16-18,55-79`). The skill forbids calling a sound good and leaves the ear check to a person (skill line 272).
- Missing: cropped frames before/after each cue, and a short list of timestamps for a headphone check. Both are cheap additions to `qa.py` (frames via the existing ffmpeg use at `qa.py:47`; timestamps = the hero cues plus the loudest ducking transition, capped at 5). Price ≈ 0.5 day with a test on a fixture MP4. Worth taking: it makes the human ear check targeted instead of open-ended.
- V-937 had no `events`, so there was no per-cue QA to inspect; this part of the audit is code reading only.

## What was run

- `ffmpeg … ebur128=peak=true` on V-937 `scene.mp4` (MP4 read from main, not modified).
- `beat_probe.py` (librosa beat grid, <120 Hz band flux, cut distances) on the default bed copy; heavy part via `ssh kesha@localhost 'choom -n 1000 -- nice -n 15 uv run --script …'`. First run mis-handled the loop (cuts beyond 46 s measured against the last beat: mean 12.3 s); fixed by folding cut times by the 45.016 s loop period, the numbers above are from the second run.
- `loop_probe.py` on two CC0 rhythmic loops.

## Not verified

- The post's exact text and its author's claims (not fetchable); the 0.22 s offset claim was not reproduced on three tracks, which is not a refutation.
- Pixabay and Mixkit licence texts (read through summaries / repository CREDITS, not the licence pages).
- Any ear judgement: none made.
- One scene, one bed; the loop probe is two loops.
