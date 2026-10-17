---
name: video-artifact
description: "Create and deliver a 30–90 s MP4 explainer in the light paper style (painted opening/closing pictures, large real numbers on flat diagrams, a quiet music bed), using an animated HTML scene or Manim with local Russian or English voice-over, phrase synchronization, and checks."
---

# Explainer Video

A video is a scene voiced step by step: load `html-artifacts` and read its
`references/animation.md` for HTML diagrams, or use Manim for charts and mathematics in motion.
This skill adds voice, the 16:9 frame,
and video-specific checks. Numbers and facts come from a source (report, data, or code), as in
every artifact.

**Voice sets the timing.** Each step has a `say` phrase; the tool synthesizes phrases in parallel
with one loaded TTS model, then sets step duration to intro + phrase + pause (0.35 and 0.55 s
divided by `--rate`, default 1.0; `hold: seconds` replaces the default end pause on any step to give the viewer time). Do not write `d` in
steps: it is replaced. State changes are constructed to begin with the phrase. The phrase fills
almost the whole step, so `w: {id: [a, b]}` approximates its fraction: an object mentioned in
the middle uses `[.4, .6]`. For a second precise accent, split the phrase into two steps rather
than tuning windows. HTML renders each ordered step as soon as its phrase is ready; Manim waits
for all phrases because `construct()` needs the complete timing plan.

**TeraTTSv2 weights have no declared license; check [the model-license discussion](https://huggingface.co/TeraSpace/TeraTTSv2/discussions/1) before preparing audio for public or commercial use.**

- **Scene:** for HTML, use the player scaffold in `html-artifacts`, with `<svg id="stage" viewBox="0 0 1200 520">`.
  Immediately after `STEPS`, include `STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);` — without it the tool stops. The video label is subtitles (Telegram's feed plays without sound): use `say`; if it contains transliteration or numbers written as words, use `sub` with the screen form (for example "Together", "7 680"); `t` is a short step heading.
- For `along` with a `w` window, also set the markup attribute (`<circle along="path">`): before
  the window the scaffold uses the initial value and otherwise falls back to `getPointAtLength`.
- **The tool sets frame and theme:** 1920×1080 (scene CSS 1280×720), no buttons, no step
  headings, Manrope and JetBrains Mono (`class="mono"`). The default theme is `paper` (below);
  `--theme dark` restores the former dark frame (`#0b0e14`, 3Blue1Brown palette) for old scenes.
  Do not override the theme with your own `!important` CSS. The theme styles only the scaffold
  (`.mv`, `.cap`, `#stage`): a scene with its own layout keeps its colors and gets only the
  progress bar; a scaffold scene drawn for the dark frame stays readable on paper but looks
  mixed, so build it with `--theme dark` or recolor it.
- Build repeated structures (grid, byte row) with a JS loop up to `STEPS`, and generate steps.

- **`say` phrase:** speak in Russian and write Latin names as Cyrillic pronunciation (for example
  «Дип Инфра», «опен роутер»); keep original names and digits in the screen subtitle. Tera expands
  numeric literals, but does not infer their grammatical case (`в 2026 году` becomes an uninflected
  «две тысячи двадцать шесть году»). Write Russian numbers as words with the required case for both
  Tera and Vosk (for example «в две тысячи двадцать шестом году»). Use 1–2 sentences, 2–6 s at
  rate 1.0, and 30–90 s total. Tera synthesizes each sentence whole, so the model itself
  intonates commas, colons and dashes; between sentences the tool adds only the missing silence up to 0.42 s divided
  by `--rate` (the model's own tail counts). A sentence of three vowels or fewer is glued to the next one. Add `[0.6]`
  in `say` for an explicit pause.
  A silent beat uses `say: ""` with a positive `hold`. Avoid officialese; write as spoken.
- **English video:** `make.py … --lang en` uses Kokoro-82M instead of Vosk and Deepgram with
  `language=en`. English `say` may contain digits, names, and `#2`; Kokoro reads them, rejecting
  only Cyrillic. Voice `--voice af_heart` (default, female) or `am_michael` (male); five tested
  voices were recognized verbatim by Deepgram (V-686). `--rate 1.1` sounds more natural than 1.25.

## Paper style (default)

Owner decision, 2026-10-17: after comparing the NIST-curves video with our demos (V-904, V-912)
the owner chose its light paper look as our standard style instead of the dark one. Source
analysis and before/after frames: `.orchestra/tasks/V-904/report.md`.

- **Two registers.** A painted picture opens and closes the story (a room, a desk, people:
  the human situation); everything in between is a flat diagram on the light background. The
  opening picture ends by pushing the camera into the object the diagram starts from (a
  monitor, a sheet), and the diagram appears at exactly that place: a match cut, not a jump.
- **Few objects, large.** Two or three objects in a frame. Data in JetBrains Mono at 32–40
  scene units (≈48–60 px in the video), labels at least 30 units; the caption is one line.
  Shorten rows instead of shrinking type: 8 bytes, not 16; one hex word, not a paragraph.
  When a new idea needs room, fade or move the previous block away first.
- **Two meaning colors only.** Blue `#0e5e9c` (tint `#d6e8f4`) = known, matched, confirmed;
  orange `#c9551b` (tint `#fde4d0`) = hidden, wrong, unexplained. Everything else is ink
  `#16171b`, muted `#6b7280`, cells `#eef0f3`, lines `#d9dce3` on background `#f6f7f9`.
  No green/red pair. The palette is also in `Paper.BLUE`, `Paper.ORANGE`, … .
- **Only real numbers.** Every value on screen comes from the source: real bytes, real sizes,
  real counts. A counter ticks through the real range in `draw`; never round for looks.
- **Order of presenting data:** show the raw value → split it into parts → highlight the one
  part that matters → verdict mark ✓ (blue) or ✗ (orange) → the next step reuses the
  marked part. Text appears by typing with a block cursor when a person or program "writes" it.
- **Motion is quiet.** Appearances fade (the caption blurs in by itself); objects move to
  their next place with the scaffold's spring; no bounces, spins or flying in.

**Paper kit** (`scripts/video_artifact/paper.js`, injected by `make.py`; pure functions of `t`,
call them from `draw(i, p, t)`):

```js
Paper.install();                                   // filters, gradients, markers #paper-arrow, #paper-arrow-orange
const pic = Paper.picture('room', {x: 96, y: 18, w: 1088, h: 556});   // torn edge, grain, vignette, wobble
const VIEW = {from: [640, 252], to: [640, 170], scale: 4.2};          // monitor centre → diagram centre
function draw(i, p, t) {
  const st = []; let at = 0; for (const s of STEPS) { st.push(at); at += s.d; }
  Paper.brush(pic, t, 0, 1.2);                                         // roller-stroke reveal
  Paper.camera(pic, t, {...VIEW, t0: .5 * STEPS[0].d, t1: st[1] - .15}); // push-in, done before step 2
  $('room').setAttribute('opacity', 1 - Paper.fade(t, st[1] - .1));    // crossfade into the diagram
  $('dia').setAttribute('opacity', Paper.fade(t, st[1] - .15));
  Paper.type($('alarm'), 'тревога → оркестратору', t, st[3] + .4, st[3] + 2.6);  // typing, block cursor
}
```

Call `Paper.install()` and `Paper.picture()` in the scene script after the SVG, before
`STEPS`; compute step starts in `draw` from `STEPS[k].d` as above (`P` does not exist yet
during the first `draw`). For the match cut, place a `<use href="#cards"
transform="${Paper.miniature(VIEW)}">` copy of the diagram inside the picture: after the zoom it
lands exactly on the original. Keep text inside that copy as large as the diagram's; small text
in the zoomed monitor is unreadable. The progress bar and caption blur are added by the tool. A
working scene with every technique: `.orchestra/tasks/V-917/demo/scene.html`.

## Second engine: Manim

Manim is the library used by 3Blue1Brown. Grant works on ManimGL; use Community Edition
(ManimCE 0.20.1, MIT), which is more stable and documented at docs.manim.community. A scene is a
Python class, Cairo renders frames, and Manim writes the video.

**What to choose.** Use animated HTML scenes for diagrams, flow diagrams, tables, text, and
existing HTML artifacts; they are fast to edit and can capture any frame. Use Manim for mathematics and data in
motion: axes and function plots (`Axes`, `plot`), drawn curves (`Create`), changing numbers
(`ValueTracker` + `always_redraw`), shape transformations (`Transform`), polar/radial charts,
and LaTeX formulas with substituted values. Choose Manim for smooth morphing and growing charts.

**Scene:** a `.py` file with one `VoiceScene` subclass from
`scripts/video_artifact/manim_voice.py` (beside `make.py`). The contract is the same as the
HTML scene: `STEPS` with `t`/`say`/`sub`/`hold`, and the same `say` rules. Each step is a
`with self.step(i):` block containing ordinary `self.play(...)`. Set animation durations as
fractions of the remaining step, `run_time=self.left() * 0.4`, so phrase and rate changes stay
synchronized; overrunning a step stops the build with a clear error. `VoiceScene` draws heading
and subtitles; style comes from its constants and `text()` (`BLUE_`, `GOLD_`, `PANEL`). `VoiceScene`
uses `MovingCameraScene`; its palette and font follow `--theme` (paper: Manrope on `#f6f7f9`
with the paper colors in `BLUE_`/`GOLD_`/`FG`; dark: CMU Serif on black, OFL fonts in `fonts/`);
captions wrap by measured width and an unknown font name fails the build; subclasses may override
`TEXT_FONT` and `BACKGROUND_COLOR`, or call `self.text(..., font="CMU Serif")`. Minimal example:

```python
from manim import *
from manim_voice import BLUE_, GOLD_, VoiceScene, text

class Growth(VoiceScene):
    STEPS = [
        {"t": "Growth", "say": "Квадрат растёт быстрее прямой.", "sub": "x² grows faster than x"},
        {"t": "Result", "say": "После единицы парабола уходит вверх.", "hold": 1.5},
    ]

    def construct(self):
        ax = Axes(x_range=[0, 3, 1], y_range=[0, 9, 3], x_length=7, y_length=4.5)
        with self.step(0):
            self.play(Create(ax), run_time=self.left() * 0.3)
            self.play(Create(ax.plot(lambda x: x, color=BLUE_)),
                      Create(ax.plot(lambda x: x * x, color=GOLD_)), run_time=self.left() * 0.6)
        with self.step(1):
            self.play(Indicate(text("x > 1", 30).next_to(ax, UP)), run_time=self.left() * 0.5)
```

Build with `make.py scene.py --out <folder>`; the engine is selected by extension. Preview
early with `--preview-step N` or `--preview-range A:B`; it writes a contact sheet without loading
TTS. Send that draft to the owner before starting the full build. Run
`--timing-only` next: voice durations and statically supported animation lengths are checked
before frames render; unsupported scenes use Manim `--dry_run`. Fix timing/layout issues, then build
the full video. Build output reports voice/frame/step counts and ETA; concurrent heavy builds queue
on a host-wide lock and print the current build they await.

**Formulas are LaTeX.** `MathTex` (math) and `Tex` (text with `$…$`) render through TeX and look
like textbook typesetting. `manim_voice` puts the project's TinyTeX on PATH and installs a
Cyrillic-capable template, so `\text{запись}` and Russian `Tex` work. Split formulas into parts
so they can be colored, bracketed, and transformed when numbers are substituted:

```python
f = MathTex(r"\Delta q", r"\approx", r"0{,}6", r"\cdot", r"W", font_size=64)
f[4].set_color(GOLD_)
note = Brace(f[2:5], DOWN)
g = MathTex(r"\Delta q", r"\approx", r"0{,}6", r"\cdot", r"0{,}362")
self.play(TransformMatchingTex(f, g), run_time=self.left() * 0.4)
```

Use `0{,}6` for a decimal comma; without braces TeX adds space after the comma. The first
formula in a build compiles in ~1–2 s, then `media/Tex` is cached. For `latex error converting to
dvi`, read the `!` line in the indicated `.log`: usually a missing package (`tlmgr install
<package>`, see Environment) or an unescaped `%`/`&` in `Tex`. Formula example:
`.orchestra/tasks/V-685/compact55.py`. Frame is 14.2×8 units centered at (0, 0); subtitles use
about one unit below and heading is upper-left: keep objects in y ∈ [−2.6, 3].

## Build

Run outside the platform cgroup (Chromium + TTS model need ~2 GB); pass the Deepgram key through
stdin so it does not appear in the command line:

```
printf '%s\n' "$DEEPGRAM_API_KEY" | ssh -o BatchMode=yes kesha@localhost \
  'read -r K; cd <work folder> && DEEPGRAM_API_KEY=$K uv run --frozen --project /home/kesha/orchestra \
   python /home/kesha/orchestra/scripts/video_artifact/make.py scene.html --out <folder>'
```

Always use `bg_create(type="run")`: a 69 s video took 9.5 min (model loading ~2 min, six
parallel Chromium frame writers via `--jobs`; one thread took 25 min). Phrases cache in
`<folder>/.tts-cache`; changing the scene without changing `say` does not reload the model.
`--stills` skips video and produces phrase timing/contact sheets; `--check-only` checks an
existing MP4. `--speaker` selects the Vosk voice (1 is its default; 0–2 are female and 3–4 male).
`--rate` defaults to 1.0; speech and standard punctuation pauses shorten together.

Russian video uses local TeraTTSv2 by default (`ru_m1`); choose a Tera voice with `--voice m1|m5|f1|f2` (`m1` is default, `f2` is the alternate female voice),
or pass `--tts-engine vosk` to use Vosk. TeraTTSv2 expands numbers in Russian tags and applies its
bundled RUAccent-derived stress pass. If a word needs correction, put `+` before the stressed vowel
(`лим+ита`): manual markers win for that word, while RUAccent still accents other words in the phrase.
`--stress-only` prints the normalized text before synthesis and warns when more than two numerals are
consecutive; `--no-stress` disables automatic stress but keeps manual markers. The existing
`--rate` maps to Tera's inverse `duration_scale`, so timing and pause semantics remain the same.

Vosk remains available as an explicit Russian fallback and keeps its separate RUAccent worker.
English video continues to use Kokoro.

If Tera's bundled stress pass or the Vosk RUAccent worker fails to load, stop and report the broken
TTS environment. Do not use `--no-stress` as a workaround for a broken requested build. Manual `+`
markers are targeted corrections for specific words the automatic pass marks incorrectly; do not
replace automatic stress with hand-marking.

**Check stress yourself before the build.** Automatic stress can make mistakes: in V-696 RUAccent marked
«посл+е» instead of «по́сле» once in five edits. The owner hears every such word. Before a full
build, run `make.py scene.html --out <folder> --stress-only`. Read every phrase in the output
(also `<folder>/<name>.stress.txt`) and check every `+`
against Russian pronunciation. Pay attention to homographs («за́мок/замо́к», «уже́»), loanwords,
terms («репозито́рий», «оркестра́тор»), and names. Fix likely errors manually in scene `say` with
`+`; repeat `--stress-only` until every `+` is correct, then build. Report the words changed.

Output: `<name>.mp4`, `<name>.timing.json`, `<name>-contact.png` (last frame of each step), and
`<name>.check.json` (Deepgram nova-2 recognition per phrase and its start offset from the plan).

## Sound layer

**A quiet music bed plays under the voice by default**: the first `bed` default of the sound
kit (`bed/fs-254856-long-ambient-pad`, "Long Ambient Pad" by indigo.cloud, CC0, Freesound
254856, first 2 s trimmed because it fades in). It loops with a crossfade and ducks during
speech. `--music path` uses another CC0 or owner-provided bed; `--no-music` builds voice only
(then without events). For a sound-enabled step,
declare real actions in `STEPS` as `events: [{id, at, sound, weight, visual}]`. `at` is seconds
from that step's start; `sound` is a picked kit id or layer expression, `weight` is `support` or
`hero`, and `visual` is `cut`, `move`, `land`, or `appear` only when the picture has that motion.
`make.py` maps the event through `timing.json` to its exact frame/time; never type frame numbers.
Events play over the bed; `--no-music` with events is rejected.

Install the kit only at `~/.local/share/orchestra-sfx/` with `uv run --script
scripts/video_artifact/sound/sfx.py kit`. Review candidates with `sfx.py browse --type <type>
--like "<material, weight, mood>"`; use `search`/`add` only for CC0 sources. Inspect the chosen
recordings' waveform and spectrogram. Never synthesize hits, clicks, or whooshes. Do not call a
sound good: report the measured `qa.py` checks and leave the final ear check to a person. The
sound scripts and MIT attribution are in `scripts/video_artifact/sound/`; downloaded sounds and
their `CREDITS.md` stay in the external kit directory. `make.py` runs sound QA automatically.

## Check before sending

- Open the contact sheet and inspect every frame: nothing is clipped or overlaid, the step result
  is visible, and text is readable. Inspect a doubtful `frames/<name>/stepNN.png` at full size.
- The build prints a short `check.json`. `onset_offset_max_abs_s` is where phrase audio actually
  begins in the MP4 versus the plan; it must be ≤ 0.1 s. `offset_s` is the first recognized-word
  start: ±0.3 s is normal; one large negative after a pause can be a Deepgram artifact stretching
  the first word into silence when audio started on time. `recall` is the share of phrase words
  found in recognition (from `say` or `sub`; Deepgram writes numbers as digits and names in
  Latin). Below 0.85, or a missing name/key word, means unclear synthesis: rephrase. A number
  written differently («два» → «2») is not a problem. Recognition does not score intonation.
- Send with `send_file(path_to_mp4)`; MP4 goes as an inline video.

## Environment (already on VPS; restore if missing)

TeraTTSv2 uses local CPU ONNX inference; the distilled sampler needs about 0.4 GB of weights.
The app pins revision `f05ea799094571a3553904a555df3834fb0b963b`, defaults to `ru_m1`, and loads
one model with six ONNX threads for two concurrent phrase workers. Model/code cache stays under
`~/.local/share/orchestra-tts/tera/`; once installed, synthesis uses local files only. Install an
isolated environment and fetch the pinned assets (including bundled Russian stress assets, but
excluding the unused teacher sampler):

```sh
T=~/.local/share/orchestra-tts/tera
uv venv --python 3.12 "$T/venv"
uv pip install --python "$T/venv/bin/python" torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python "$T/venv/bin/python" transformers==4.57.1 onnxruntime==1.23.2 \
  huggingface_hub==0.36.0 num2words==0.5.14 numpy
"$T/venv/bin/python" -c 'from pathlib import Path; from huggingface_hub import snapshot_download; p=snapshot_download(repo_id="TeraSpace/TeraTTSv2", revision="f05ea799094571a3553904a555df3834fb0b963b", cache_dir=str(Path.home()/".local/share/orchestra-tts/tera/hub"), allow_patterns=["README.md","config.json","configuration_teratts.py","modeling_teratts.py","teratts.py","teratts_ruaccent.py","RUACCENT_NOTICE.txt","unicode_indexer.json","models/duration_predictor.onnx","models/sampler_distilled_cfg3_8step.onnx","models/text_encoder.onnx","models/vocoder.onnx","styles/ru_m1/*","styles/ru_m5/*","styles/ru_f1/*","styles/ru_f2/*","ruaccent/**"]); print(p)'
```

Set `ORCHESTRA_TERA_HOME` or `ORCHESTRA_TERA_PYTHON` only when using a different default path.
Vosk remains in `~/.local/share/orchestra-tts/` (`venv` with `vosk-tts` and
`vosk-model-tts-ru-0.9-multi`, Apache 2.0); see `.orchestra/tasks/V-681/report.md`.

English voice: `~/.local/share/orchestra-tts/en/` (`ORCHESTRA_TTS_EN_HOME`), with `kokoro-onnx`
(MIT), `soundfile`, `kokoro-v1.0.onnx` (310 MB), and `voices-v1.0.bin` (28 MB; Kokoro-82M,
Apache 2.0) from `thewh1teagle/kokoro-onnx` release `model-files-v1.0`. Install:

```
D=~/.local/share/orchestra-tts/en; mkdir -p $D && cd $D && uv venv --python 3.12 venv
uv pip install --python venv/bin/python kokoro-onnx soundfile
for f in kokoro-v1.0.onnx voices-v1.0.bin; do curl -sSfL --retry 5 -o $f \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f; done
```

`~/.local/share/orchestra-manim/`: micromamba in `bin/`, `env/` with Python 3.12 and ManimCE
0.20.1 from conda-forge (Cairo, Pango, and ffmpeg included; apt/root unnecessary). The path is
`ORCHESTRA_MANIM_HOME`; if missing:

```
mkdir -p ~/.local/share/orchestra-manim/bin && cd ~/.local/share/orchestra-manim
curl -sSfL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C . bin/micromamba
MAMBA_ROOT_PREFIX=$PWD/mamba ./bin/micromamba create -y -p $PWD/env -c conda-forge python=3.12 manim=0.20.1
./env/bin/manim --version
```

This takes ~2 min and ~0.5 GB. On macOS/Windows use that platform's micromamba build instead of
`linux-64` (mamba.readthedocs.io); the rest is the same.

TinyTeX for `MathTex`/`Tex`: TeX Live 2026, 220 MB, in `~/.local/share/orchestra-manim/tex/`, no
apt/root. `manim_voice` uses it through `ORCHESTRA_MANIM_HOME`; if absent, it uses system `latex`
(the VPS has TeX Live 2023 from apt too). If neither exists:

```
cd ~/.local/share/orchestra-manim
curl -sSfL --retry 5 --retry-all-errors -o /tmp/tinytex.tar.xz \
  https://github.com/rstudio/tinytex-releases/releases/download/v2026.10/TinyTeX-1-linux-x86_64-v2026.10.tar.xz
mkdir tex-unpack && tar -xJf /tmp/tinytex.tar.xz -C tex-unpack && mv tex-unpack/.TinyTeX tex && rmdir tex-unpack
tex/bin/x86_64-linux/tlmgr install standalone preview dvisvgm babel-english babel-russian cyrillic lh \
  doublestroke setspace rsfs relsize ragged2e microtype wasysym physics jknapltx wasy mathastext
```

This takes ~1 min. Latest releases are at `rstudio/tinytex-releases`; GitHub can return 503, so
use `--retry`. Install another package with `tex/bin/x86_64-linux/tlmgr install <name>`. Installer
script and log: `.orchestra/tasks/V-685/install-tex.sh`.

### Chromium on Ubuntu 26.04

HTML builds need a Playwright browser. On Ubuntu 26.04, project Playwright 1.60.0 ends with
`Playwright does not support chromium on ubuntu26.04-x64`; Playwright 1.61.0 adds support. Keep
the project lockfile intact by using a separate environment and that Python for `make.py`; only
Playwright belongs to the calling environment, while TTS and Manim stay in theirs:

```
P=~/.local/share/orchestra-playwright
uv venv --python 3.12 "$P"
uv pip install --python "$P/bin/python" playwright==1.61.0
PLAYWRIGHT_BROWSERS_PATH=/mnt/data/orchestra-playwright \
  "$P/bin/python" -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=/mnt/data/orchestra-playwright \
  "$P/bin/python" /home/kesha/orchestra/scripts/video_artifact/make.py scene.html --out video
```

If `/mnt/data` is unavailable or lacks space, choose another storage location for
`PLAYWRIGHT_BROWSERS_PATH`; the browser directory may occupy hundreds of megabytes.
