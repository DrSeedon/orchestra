# V-686 — media for the README: the real dashboard, a GIF, and a narrated video

Owner request (voice message, 03.10): a GIF and possibly a video with sound for the GitHub README. The real dashboard instead of the mock-up, on a test stand with fake data, with English animations. Do not touch the README and publish nothing.

Nothing was published: `README.md`, `docs/` and GitHub are untouched, and nothing was pushed or uploaded.

## 1. Can a video with sound go into a README

Yes, but only through an upload via the GitHub web interface.

- Changelog 13.05.2021 (https://github.blog/changelog/2021-05-13-video-uploads-now-generally-available/): "Video upload is now supported everywhere you can author Markdown in GitHub… as well as on repository Markdown files such as READMEs."
- Documentation (https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files): `.mp4`, `.mov` and `.webm`. Videos are limited to "10MB … on a free GitHub plan" and "100MB … on a paid GitHub plan"; GIFs and images to 10 MB.
- Community thread https://github.com/orgs/community/discussions/19403 (user reports, no staff answer; tier 4):
  - the player appears for a URL of the form `https://github.com/user-attachments/assets/<UUID>`;
  - `…/raw/main/…/demo.mp4` and `<video src="images/video.mp4">` pointing to a file in the repo do NOT play;
  - the UUID is only issued on drag-and-drop in the web editor, so this step cannot be automated.
- Sound: the upload is an ordinary video player with controls. It does not autoplay; sound plays after a click. I could not verify this on our repo because doing so means publishing the file.
- GIF, APNG, animated WebP and SVG have no sound by format. A GIF autoplays in the README and loops.
- The plan of the account behind the token could not be determined (`gh api user --jq .plan` → empty). So I assumed the 10 MB limit and made a GitHub copy of the video under it.

Owner's step (I did not do it): open README.md on github.com → pencil → drag `media/orchestra-tour-github.mp4` into the text → GitHub inserts a `user-attachments/assets/…` line → keep it as a separate paragraph. Details and both variants are in `readme-draft.md`.

## 2. Test stand: the real dashboard on fake data

How it is built: `stand/stand.py`, `stand/seed.py`, `stand/run-stand.sh`.

- The code is a `git archive HEAD` of this branch into `/home/kesha/readme-stand-V686/orchestra`, outside the repo and the worktree. There is no `.env` (checked by an assert at startup).
- The launch passes `env -i` with `HOME=/srv/demo`. There are no TG, Anthropic, OpenAI or Deepgram variables.
- The stand has its own `ORCHESTRA_DB_PATH`, task store, `ORCHESTRA_PROJECT_CATALOG` and `ORCHESTRA_PROJECT_CATALOG_ROOT` in a fresh `state-HHMMSS` directory. Port 8897.
- The production `lifespan` is replaced with a minimal one: `init_db`, `sync_catalog` over a one-project catalog, the task store, and the seed. It does not run:
  - `load_dotenv`;
  - the V-576/V-621 migrations and project layout migrations;
  - `auto_resume_all`, the bootstrap orchestrator, the TG bridge, and recovery of deliveries and bg jobs.
- There are no real CLI sessions. The agents are rows in the stand's DB, and the live part is DB inserts plus the stream broker.
- The routers, templates and JS/CSS are the current branch code, unchanged.
- The demo project is `/srv/demo/acme-shop`: a small git repo with a fake TS project. `/srv/demo` was created via `sudo mkdir` + `chown kesha`.
- After the work:
  - `git status` of the main repo is clean, and `.orchestra/projects.yaml` in it is unchanged;
  - the worktree contains only my changes;
  - the stand server is stopped.

What the stand fakes:

- Agents, chat, tasks: `seed.py`.
  - One orchestrator (Opus 5.5) and five workers: Sonnet 5.5, GPT-6 Luna, Haiku 4.5.
  - Statuses: running/idle/waiting, with cost, context and progress.
  - The scenario: a customer double charge after a Stripe SDK upgrade, plus rate limiting.
  - Seven tasks across the In progress / Done / New columns.
- Quotas: the stand has no provider credentials, so `stand.py` puts fake numbers into the real caches (`_usage_cache`, `_codex_usage_cache` and `_grok_usage_cache` in `app/routes/system.py`). The real code draws the quota bar and the gate pill from them: Claude 34/58 %, Codex 22/41 %, Grok 12 %.
- Two cosmetic substitutions, both stand-only:
  1. `runtime_connection` for rows. A live agent shows "event reader active"; a DB row would show "runtime not loaded".
  2. The lane label `LANE_LABELS["claude"]`. The server returns the Russian "Claude-воркеры" even in the English UI. This is a real gap in the product; it is recorded in `TODO.md`.
- `POST /stand/live` is a scripted move: the worker reports DONE, the orchestrator streams text, runs the tests, merges, and task #2 moves to Done. The DB rows reach the page through the regular SSE (`/api/sessions/{name}/stream`) and the `/api/sessions` poll.
- A stand bug, fixed: without `broker.clear_accum` the stream text was replayed at the bottom of the chat after a page reload. The live runtime clears it itself.

## 3. Files (all in `.orchestra/tasks/V-686/media/`)

| file | what it is | size |
|---|---|---|
| `dashboard-real.png` | the dashboard after the merge: the worker's report, tests 48/48, "Merged #2", agents panel, quotas. 3200×1880 (1600×940 @2x). Candidate to replace `docs/dashboard.png` | 0.51 MB |
| `dashboard-real-status.png` | the same before the merge: the orchestrator's status for the owner | 0.55 MB |
| `dashboard-worker.png` | a worker's chat: Read/Edit with a diff, tests, branch `task-2/fix-double-charge` | 0.47 MB |
| `dashboard-tasks.png` | the task board | 0.60 MB |
| `dashboard-quota.png` | **pass 2:** the quota panel expanded — Claude/Codex/Grok windows and the Claude and Codex history charts. 3200×1880 | 0.65 MB |
| `dashboard-spend.png` | **pass 2:** the 📊 Usage Analytics modal, 30 days: pools, totals, the stacked daily-spend chart. 3200×1880 | 0.32 MB |
| `dashboard-live.gif` | **pass 2:** 41 s cut from the video (steps 6–14) with English captions: open a worker → DONE → streamed review + tests → merge → task board → quota panel unfolds → quota history → 📊 spend → 30 days / agents. 880×417, 8 fps, endless loop | **4.5 MB** |
| `dashboard-live-silent.mp4` | the same 41 s as H.264, 1280 px, no sound | 1.5 MB |
| `orchestra-tour.mp4` | **pass 2:** narrated English video, 84.9 s, 1920×1080, 17 steps — the master copy for Telegram | 9.3 MB |
| `orchestra-tour-github.mp4` | the same at CRF 27 + AAC 96k, under the 10 MB free-plan limit | **5.1 MB** |

Other files:

- `voices/*.ogg` — the same phrase in five Kokoro voices, so the owner can choose. The video uses `af_heart`.
- `video/orchestra-tour.html` — the scene. `video/img/` holds its screenshots. Also `*-contact.png`, `*.check.json` and `*.timing.json`.

How the GIF is made (pass 2): a crop of the stage + caption from the rendered video → 8 fps, 880 px → a 96-colour palette with `stats_mode=diff`, Bayer dither. A 960-px 10-fps variant was 7.1 MB. Pass 1 cut the GIF from a raw screencast (`stand/record.py`); animated WebP of that clip came out at 18 MB.

## 4. Narrated video

- The scene is html-motion with the real stand screenshots. A "camera" zooms into regions of the dashboard, with a gold frame and dimming around it. 14 steps.
- Voice: Kokoro-82M, voice `af_heart`, tempo 1.1. It is a local voice with no cloud and no paid API.
- Deepgram nova-2 `en` on the finished MP4:
  - minimum per-phrase recall is 0.89;
  - the largest audio-start offset is 0.03 s;
  - the two shortfalls are spelling, not slurred speech: "Codex" was transcribed as "codecs", and "OK" as "okay".
- Claims in the voiceover are checked against the product:
  - worktree/branch per worker, squash merge per task;
  - the quota gate (`app/quota_gate.py`);
  - Claude/Codex/Grok in the quota bar;
  - AGPL-3.0 (`LICENSE`).
- "Anything risky … waits for your OK" is the orchestrator's behaviour under the approval rules, not a separate product button.

## 5. Change to the explainer-video tool

`make.py --lang en --voice <voice>` plus `tts_worker_en.py`.

- Kokoro lives in its own venv at `~/.local/share/orchestra-tts/en/`.
- Licences: `kokoro-onnx` is MIT and the Kokoro-82M weights are Apache 2.0. Piper and Silero were rejected earlier over licences (V-681).
- For `en`, `say` is rejected only if it contains Cyrillic; Kokoro reads digits and names itself.
- The phrase cache key includes the engine and the voice.
- Deepgram runs with `language=en`.
- Russian videos are unchanged: `--lang ru` is the default.
- Updated: the skill (`.orchestra/pipelines/default/prompts/skills/explainer-video.md`, a section plus installation), `CHANGELOG.md`, and the test `tests/test_explainer_video.py::test_english_voice_reads_latin_and_digits_but_rejects_cyrillic`.

Checks:

- `uv run --frozen python -m pytest tests/test_explainer_video.py -q` → 5 passed;
- `scripts/check_instruction_contract.py` → OK;
- the full video build ran through the updated `make.py`.

## 6. How it looks in GitHub's render: what is verified and what is not

- Verified:
  - the frames themselves (contact sheet, several full-size frames);
  - the GIF size and its frame after quantisation, where the text is readable;
  - the MP4 sizes against the documented limits.
- Not verified, because it requires publishing:
  - the actual GitHub player for the `user-attachments` URL;
  - how the GIF renders through camo.
- The README column on github.com is about 830–1000 px wide:
  - the 1280-px GIF is scaled down there, so small dashboard text will be hard to read; a click opens the original;
  - `dashboard-real.png` (3200 px) stays sharp on Retina.

## 7. Leftovers outside the repository

- `/home/kesha/readme-stand-V686/` (291 MB): the stand copy, its states, raw recording frames, the video build directory and the voice samples. Not needed for the result; it can be removed.
- `/srv/demo/acme-shop`: the demo project.
- `~/.local/share/orchestra-tts/en/` (~355 MB): the English voice, needed for future English videos.

## 8. Pass 2 (owner feedback 04.10): faster highlights, cost charts, more live UI

Feedback (voice, 04.10 10:11): the highlight animations were too slow and lagged behind the voice; show the cost charts and the Codex panel expanding; more live visual moments.

### 8.1 The camera now lands before the phrase

Cause in pass 1: the player animates numeric attributes over the WHOLE step (`t1 = s.d`) with a spring, so the camera/frame reached ~87% only at mid-step, i.e. 2–3 s after the voice had named the region.

Fix in the scene (`video/orchestra-tour.html`): every camera id (layers, `hl`, `hole`, `dim`) gets a window `w = [-CAM_PRE/d, CAM_POST/d]` with `CAM_PRE = 0.45 s`, `CAM_POST = 0.22 s`. The move starts during the previous step's closing pause (after its phrase has ended: that gap is 0.55/1.1 = 0.50 s) and is finished 0.22 s into the step; the voice enters at 0.32 s.

Measured on the final MP4 (`video/check_camera.py` → `video/orchestra-tour.camera.json`; voice onset = planned start + the onset offset Deepgram found): the camera lands **0.11–0.13 s before** the voice in all 17 steps; worst margin +0.111 s.

### 8.2 Live clips instead of stills, with a drawn cursor

Steps 6–14 now play real recordings of the stand on a canvas inside the same camera: switching workers, typing + DONE + streamed review + tests + merge, the task board, the quota panel unfolding (Claude and Codex history, flipping the Claude 7-day chart to last week and back), the 📊 modal opening with Chart.js bars growing, switching to 30 days, then the Agents view.

- Seeded data (`stand/seed.py::_usage`): 14 days of `turn_usage` rows (Claude and Codex, ~2,300 priced turns, $700 / 30 days) and 7 days of `usage_snapshots` built through the product's own `_provider_usage_snapshot`, ending at exactly the numbers the live quota bar shows (Claude 34%/58%, Codex 22%/41%). `OWNER_MODE=1` on the stand, because the history is an owner view.
- Recording (`stand/clips.py`): on this VPS a 2400×1410 capture takes 0.5–1.5 s and `Page.startScreencast` only returns 1600×940, so the first two recordings came out at 3–5 fps. The fix is slow motion: the page runs 10× slower (an init script dilates `Date`, `performance.now`, rAF timestamps, `setTimeout`/`setInterval`; CDP `Animation.setPlaybackRate(0.1)` slows CSS; `/stand/live?slow=10` stretches the scripted turn), the recorder captures with `Page.captureScreenshot` at scale 1.5 as fast as it can, and all logged times are divided back. Result: 546 frames over 57 page-seconds, median 0.089 s between frames (~11 fps) at 2400×1410.
- Headless Chromium draws no cursor, so the recorder logs the mouse track and clicks (`cursor.json`) and the scene draws a smooth arrow and a click ripple on top of the clip.
- `video/build-clips.sh` cuts the recording into JPEG sequences + `clips/clips.js` (frame counts, cursor tracks). The sequences (≈360 MB) are git-ignored; rebuild them from the recording.
- `P.seek` returns a promise while a clip frame is still decoding, and `make.py` awaits `page.evaluate`, so no frame is captured blank.

### 8.3 Stand changes, still isolated

- `PATH` of the stand is now a directory with only `git`, `sh`, `bash`, `env`, `cat`, `ls`; `stand.py` asserts that `claude`, `codex` and `grok` are not reachable. Before, `/usr/bin/codex` was on the stand's PATH and an expired quota cache could have spawned the real Codex CLI.
- The recording browser maps the hard-coded `'ru-RU'` locale to `en-US` (cosmetic, browser-only). The product formats dates and money in Russian even in the English UI ("вт, 6 окт.", "$212,8") — recorded in `TODO.md`.
- After the work: the stand is stopped, port 8897 is free, the main repo's `git status` is clean, `.orchestra/projects.yaml` untouched.

### 8.4 Voice check

Deepgram nova-2 `en` on the final MP4: 15 of 17 phrases at recall ≥ 0.89; "Claude and Codex stacked" came back as "clawed in codec stacked" (0.77) — the same spelling class as "codecs" in pass 1, the audio is intact. Largest first-word offset 0.18 s, audio-start offset 0.03 s.
