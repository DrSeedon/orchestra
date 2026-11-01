# V-1086 — ElevenLabs narration, worker return

Worker corrections complete; **host acceptance and live audio remain with Root; canonical skill edits are assigned to native worker feat-video-sound, V-1088**.
This is a source-only hub copy without `.git`, credentials, `app`, installed renderers or ffmpeg.
No real provider API, `.env`, production log or private hub data was read. No services were restarted.
The platform commits/imports the result on `task-V-1086/feat-elevenlabs-tts` after this turn;
the worker did not run git commit/push/clone.

## Result and source paths

- `scripts/video_artifact/make.py`: default engine `elevenlabs` for RU and EN,
  both HTML and Manim. Local Tera/Vosk/Kokoro choices remain explicit. ElevenLabs
  bypasses local stress dictionary/RUAccent/normalizer. Existing WAV-based timing,
  rendering callbacks and sound pipeline are reused. `--check-only` now loads the
  existing timing file without generating speech or submitting it again; text mismatch fails.
- `scripts/video_artifact/elevenlabs_tts.py`: shared HTTP/cache/decode implementation
  and direct `--text` / UTF-8 `--file` CLI. Uses existing `httpx` and `python-dotenv` dependencies;
  no lock/dependency changes or provider SDK. Output is PCM WAV, 48 kHz, mono, signed 16-bit.
  API output explicitly `mp3_44100_128`, decoded as MP3 by ffmpeg, not relabelled WAV.
  Missing ffmpeg refuses before a paid request. Bounded connect/read/write/pool and decoder timeouts.
- `scripts/video_artifact/README.md`: commands, configuration, canonical source paths,
  timing/pauses, cache recovery, pricing sources and live-verification limits.
- `tests/test_elevenlabs_tts.py`: offline behavioral tests, MockTransport only.
- `tests/test_video_artifact.py`: legacy Vosk cache tests explicitly select Vosk;
  old default-Tera/Kokoro tests now verify explicit local choices. The pause-error expectation
  now checks `SystemExit` without pinning localized error wording, as does the new missing-timing
  check-only test. Their behavior checks remain intact, including the synthesize prohibition.
  No supplied frozen tests were identified or weakened.
- `CHANGELOG.md`: resulting default, safety/recovery and verification limits.

Canonical renderer paths were inspected in the copied source:
`scripts/video_artifact/make.py`, `manim_voice.py`, `manim_timing.py`,
`tts_worker.py`, `tts_worker_en.py`, `tts_worker_tera.py` and `video_text.py`.
`manim_voice.py` and `manim_timing.py` require no change: the existing duration contract fits the new WAV clips.

## Selected model, voice, price evidence

Root supplied non-secret account verification during this turn:

- `eleven_flash_v2_5`: `can_do_text_to_speech=true`,
  `model_rates.character_cost_multiplier=0.5`, `cost_discount_multiplier=1.0`.
  `token_cost_factor=1.0` is **not** the character price.
- Owner explicitly selected their saved **Sergey - Rich, Engaging and Captivating**,
  `XuEV9VY3VUASYgJVNBh0`. Root found one matching saved voice, confirmed Flash
  fine-tuning, `sharing.rate=1.0`, `financial_rewards_enabled=false`.
- Starter active; no credit-limit extension allowed according to Root.
  No balance or credentials were requested or needed.

Sergey is now the default for both languages. `--voice` overrides
`ELEVENLABS_VOICE_ID`, then the configured default applies. No automatic EN substitution.
Only the approved Flash model is accepted by this implementation; there is no alternate paid model path.
Model cost is based on Root's current metadata, not a stale documentation calculation.

Official sources checked on 2026-10-25:

- [Flash announcement](https://elevenlabs.io/blog/meet-flash): Flash v2.5, 1 credit per 2 characters.
- [Models](https://elevenlabs.io/docs/overview/models): RU/EN coverage and 40000-character Flash limit.
- [Convert](https://elevenlabs.io/docs/api-reference/text-to-speech/convert): endpoint, headers,
  `language_code`, voice settings and Starter-compatible MP3 format; PCM/WAV 44.1 kHz needs Pro.
- [Voice metadata](https://elevenlabs.io/docs/api-reference/voices/get): fine-tuning and sharing fields.
- [Custom rates / credit multipliers](https://elevenlabs.io/docs/help-center/product/voices/voice-library/what-are-custom-rates-and-credit-multipliers):
  some shared Professional Voice Clones have owner-set custom rates and cost extra.
  Root's supplied no-reward/rate=1.0 metadata is consistent with standard voice pricing;
  the public schema itself does not define `sharing.rate` as the model character multiplier.
  The worker did not independently query account-specific pricing. Changing the voice requires rechecking its rate.
- [Default voices](https://elevenlabs.io/docs/help-center/product/voices/my-voices/what-are-default-voices):
  old Default voices only for pre-March-2026 accounts and scheduled to expire 2026-12-31.
  This is why an unverified historical Rachel/George default was not shipped.

No sample was generated or heard. Russian/English accent, pronunciation and subjective quality of Sergey remain for Root's short live acceptance.

## Cache, errors and recovery

Keys cover model, voice, settings (including speed), language, text, requested audio format
and processing version. No API key in keys, payload cache, status markers or error text.
Per-key `flock` serializes concurrent callers; WAVs/MP3s are atomically installed.

Before POST, a durable `.request.json` intent marker is written/fsynced and its directory synced.
On timeout, transport errors, 5xx, redirect or malformed successful response, a later run
refuses another paid POST. The marker is deliberately conservative after a process interruption.
Explicit 400/401/402/403/404/422/429 refusals release the marker so corrected input/key/access/quota
can be tried by a later invocation; no invocation retries them automatically.
Authentication, quota/rate limits (including `quota_exceeded` in a 401 response), voice absence,
malformed audio and decode errors have safe messages without provider response bodies.

Received MP3 bytes are committed before decode; fixing a missing/failing decoder uses the
same response without another API charge, including after restart and without a key.
A corrupt cached WAV fails closed without resubmission. Existing Tera/local cache entries are retained.
Cache protection is scoped to the selected cache directory: deleting it or choosing another
directory loses reuse/uncertain-submission evidence. `--cache` permits explicit reuse for ordinary narration.
Ambiguous recovery is operator-assisted through Root/provider history; no automatic marker deletion.

Each explicit `[seconds]` pause is local PCM silence, including leading/trailing pauses.
Speech segments on either side are cached independently, so changing only a pause reuses speech.
No sentence splitting/extra paid requests beyond explicit pause segments. Literal pause lengths
remain fixed with `--rate`; existing LEAD/GAP scale with speech rate, `hold` does not.
Whole-input segment and setting validation precedes paid submission.

## Verification actually run

Required runner was present and used throughout:
`$HOME/.local/share/orchestra/tools/uv/0.11.28/bin/uv`, version 0.11.28.
Every Python shell prepended that directory to PATH. `.venv` remained at its default location;
uv installed locked project dependencies without changing `uv.lock`.

1. Required-style command:

   `uv run --frozen python -m pytest tests/test_video_artifact.py -q --basetemp=.orchestra/tasks/V-1086/pytest-tmp`

   Result: **55 setup errors, 9 skipped**, because `tests/conftest.py` session fixtures import
   missing `app` (`ModuleNotFoundError: No module named 'app'`). Log: `required-tests.txt`.
   The copied `app` package is absent, so its absolute imported path cannot be reported.
   No substitute interpreter or fake `app` package was used.

2. Same real uv, isolated from unavailable global fixtures:

   `uv run --frozen python -m pytest tests/test_elevenlabs_tts.py tests/test_video_artifact.py -q --noconftest --basetemp=.orchestra/tasks/V-1086/isolated-tmp`

   Initial result: **86 passed, 10 skipped, 10 failed**. Eight failures require missing
   Playwright Chromium, one also selected browser-related test needs the absent
   `html-artifacts/references/animation.md`, and one was the stale pause-error string and was corrected.
   These failures were inspected rather than declared successful. Log: `isolated-tests.txt`.

3. Final isolated regression run, same command with `--basetemp=.orchestra/tasks/V-1086/final-tmp`
   and explicit `-k` exclusion of the nine known unavailable-environment checks below:
   **95 passed, 10 skipped, 9 deselected**. Log: `final-tests.txt`.
   Ten skips are pre-existing Manim/sound installation checks plus the added real MP3 decoder check,
   which needs ffmpeg. The behavioral decoder-command/format/atomic-output test ran with a mock;
   actual ffmpeg decoding is not claimed.

   Excluded names: `manual_stress_marker_is_removed_from_scene_caption`,
   `video_frame_defaults_to_paper_theme_and_dark_stays_selectable`,
   `paper_kit_is_pure_in_time_and_miniature_lands_on_the_zoomed_original`,
   `text_change_ghost_follows_the_moved_label`,
   `bundled_scenes_stand_on_supports_and_zoom_onto_the_diagram`,
   `support_check_reports_an_object_floating_beside_its_support`,
   `vertical_format_renders_1080x1920_with_caption_in_safe_area_and_landscape_stays_default`,
   `vertical_caption_too_long_for_the_safe_area_fails_the_build_check`,
   `hook_shows_in_the_first_frame_inside_the_safe_area_and_fades_out`.

4. Both CLI `--help` commands executed through uv without loading `.env` or requesting speech.
   All `scripts/video_artifact/**/*.py` compiled using uv's Python; `runtime-check.txt` records:
   interpreter `<WORKSPACE>/.venv/bin/python3`,
   helper `<WORKSPACE>/scripts/video_artifact/elevenlabs_tts.py`,
   `app` spec `None`.

5. Final standalone ElevenLabs suite, same provisioned uv with `--noconftest`:
   **49 passed, 1 skipped** (`elevenlabs-tests.txt`). Lightweight credential-shape scan of
   the owned sources/reports: PASS (`secret-shape-check.txt`), without loading any real secrets.
   Repository publication scanner cannot be imported because `app` is missing;
   Root must still use the normal publication gate before merge. Generated pytest scratch
   directories were removed; only text evidence and documentation remain under this task.

6. After Root's review, removed the two requested localized `pytest.raises(..., match=...)`
   expectations; the tests still require `SystemExit`, and check-only's synthesize mock fails
   immediately if invoked. Repeated the same isolated regression selection with the provisioned
   uv and task-local temp directories: **95 passed, 10 skipped, 9 deselected** (`correction-tests.txt`).
   Normal fixture imports and actual renderer/decoder limitations remain unchanged.

## Publication delivery

Raw stdout and the original report have been preserved in the current hub copy under
`private/raw/` relative to this task directory, protected by `private/.gitignore`.
This is intentional private evidence, **not a tracked/public attachment**. If sync-back excludes
that private folder, the originals remain here; Root should retain this worker copy until any
required private recovery is complete, rather than assuming the raw files were transferred.
No attempt was made to bypass any private-folder or `.codex` transfer guard.

Tracked `.txt` evidence and this report are publication derivatives. Workspace, home,
hub user, host and copy identifiers are replaced with stable descriptive placeholders;
commands, assertions, diagnostics, test totals and results are retained. This does not change
what checks passed or what remained blocked. Original absolute interpreter/module locations
are retained only in the private raw runtime record and original report.
`publication-manifest.json` records each original's relative private path, byte length and
SHA-256 alongside the published derivative's length and SHA-256. The report derivative also
includes these review corrections and current task ownership; the manifest says so explicitly.
The lightweight publication check records no secret-value inventory and does not print matches.

All new behavior is exercised offline with HTTPTransport blocked and MockTransport substitutes:
RU/EN and HTML/Manim dispatch, default Sergey/model, configurable voice/settings,
cache hits across key changes and misses on config/text changes, concurrent callers,
intent-before-POST, restart/timeout/server/malformed-response refusal to replay, auth/quota,
decoder recovery from saved bytes, corrupt cache, missing key/decoder, stress cleanup,
literal pause samples and duration plan, no paid/local fallback, preview and check-only without synthesis,
safe canonical dotenv loading and text/file CLI.

## Missing scope, remaining work and useful findings

The requested `.codex/skills/video-artifact` and `explainer-craft` are **not in this copy**;
`.codex` itself is absent. Hidden-file search found no supplied `SKILL.md` anywhere in scope.
The worker did not invent replacement skills or overwrite unseen instructions.
Root confirmed that `.codex` directories are intentionally blocked in both transfer directions;
that guard remains intact. Canonical skill edits belong to native `feat-video-sound`, **V-1088**.
`skill-updates.md` is a prepared handoff for that worker, not a replacement for the canonical skills.
There is no pending request to transfer the blocked skill files into this hub copy.
`scripts/check_instruction_contract.py` and the full-suite runner are also not supplied;
the instruction contract/full suite could not run. `CLAUDE.md` is absent in the initial copy,
not removed by the worker.

Non-obvious findings relevant to acceptance:

- Old `--lang en` unconditionally bypassed `--tts-engine` and chose Kokoro; default dispatch now checks ElevenLabs first.
- Russian `apply_stress_dictionary` previously ran regardless of engine and could reject unmarked homographs;
  it is now confined to local RU voices.
- Generic `check_steps(..., engine=None)` rejected `[seconds]` before the engine-specific validation;
  generic validation now permits these markers while still checking their numeric range.
- Existing `--check-only` reached synthesis. Loading prior timing avoids a newly billable request
  after switching the default or losing a cache.
- Starter audio format and MP3 decoding must be explicit; an API MP3 is not raw PCM/WAV.

Root should run the normal target tests with `app` present, full required repository checks,
actual ffmpeg decoder test, HTML and Manim rendering/timing acceptance, coordinate V-1088's real
skill updates, and perform the separately authorized short RU/EN Sergey live audio check.
No deployment/restart follows from this result. Worker implementation/correction status: **DONE**;
host and live acceptance are deliberately not represented as completed.
