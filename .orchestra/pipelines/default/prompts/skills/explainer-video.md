---
name: explainer-video
description: "A 30–90 s MP4 explainer in the style of 3Blue1Brown: an html-motion animated diagram or Manim chart/animation with local Russian (Vosk) or English (Kokoro) voice-over, phrase synchronization, recognition checks, and Telegram video delivery."
---

# Explainer Video

A video is a scene voiced step by step: `html-motion` for diagrams or Manim for charts and
mathematics in motion. For html-motion, take the scene rules, player scaffold, and `STEPS` from
the `html-motion` skill (load it); this skill adds only audio and the 16:9 frame. Numbers and
facts come from a source (report, data, or code), as in every artifact.

**Voice sets the timing.** Each step has a `say` phrase; the tool synthesizes all phrases first,
then sets step duration to intro + phrase + pause (0.35 and 0.55 s divided by `--rate`, default
1.15; `hold: seconds` replaces 0.55 on the last step to allow viewing). Do not write `d` in
steps: it is replaced. State changes are constructed to begin with the phrase. The phrase fills
almost the whole step, so `w: {id: [a, b]}` approximates its fraction: an object mentioned in
the middle uses `[.4, .6]`. For a second precise accent, split the phrase into two steps rather
than tuning windows.

- **Scene:** use the complete `html-motion` scaffold, `<svg id="stage" viewBox="0 0 1200 520">`.
  Immediately after `STEPS`, include `STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);` — without it the tool stops. The video label is subtitles (Telegram's feed plays without sound): use `say`; if it contains transliteration or numbers written as words, use `sub` with the screen form (for example "Together", "7 680"); `t` is a short step heading.
- For `along` with a `w` window, also set the markup attribute (`<circle along="path">`): before
  the window the scaffold uses the initial value and otherwise falls back to `getPointAtLength`.
- **The tool sets frame and style:** dark `#0b0e14` background, no buttons, Manrope and JetBrains
  Mono, 1920×1080. SVG text without `fill` is light. Palette: panel `#151a24`, lines `#2a3142`,
  muted `#8b93a7`, blue `#58c4dd`, green `#83c167`, red `#fc6255`, gold `#f0ac5f`. Scene font
  size is at least 15 because the video is watched on phones.
- **As in 3Blue1Brown:** one step, one idea; objects persist, then build and recolor; a number
  appears when spoken; highlight with color and borders, not a new paragraph; the final frame is
  a silent-readable conclusion. Build repeated structures (grid, bar row) with a JS loop up to
  `STEPS`, and generate steps.
- **`say` phrase:** Russian voice uses Cyrillic and punctuation only. Digits and Latin make
  synthesis fail in advance, so spell them out (for example «семь тысяч шестьсот восемьдесят»,
  «Дип Инфра», «опен роутер»), while the screen keeps digits and original names. Use 1–2
  sentences, 2–6 s at rate 1.15, and 30–90 s total. Avoid officialese; write as spoken.
- **English video:** `make.py … --lang en` uses Kokoro-82M instead of Vosk and Deepgram with
  `language=en`. English `say` may contain digits, names, and `#2`; Kokoro reads them, rejecting
  only Cyrillic. Voice `--voice af_heart` (default, female) or `am_michael` (male); five tested
  voices were recognized verbatim by Deepgram (V-686). `--rate 1.1` sounds more natural than 1.25.

## Second engine: Manim

Manim is the library used by 3Blue1Brown. Grant works on ManimGL; use Community Edition
(ManimCE 0.20.1, MIT), which is more stable and documented at docs.manim.community. A scene is a
Python class, Cairo renders frames, and Manim writes the video.

**What to choose.** Use html-motion for diagrams, flow diagrams, tables, text, and existing HTML
artifacts; it is fast to edit and can capture any frame. Use Manim for mathematics and data in
motion: axes and function plots (`Axes`, `plot`), drawn curves (`Create`), changing numbers
(`ValueTracker` + `always_redraw`), shape transformations (`Transform`), polar/radial charts,
and LaTeX formulas with substituted values. Choose Manim for smooth morphing and growing charts.

**Scene:** a `.py` file with one `VoiceScene` subclass from
`scripts/explainer_video/manim_voice.py` (beside `make.py`). The contract is the same as
html-motion: `STEPS` with `t`/`say`/`sub`/`hold`, and the same `say` rules. Each step is a
`with self.step(i):` block containing ordinary `self.play(...)`. Set animation durations as
fractions of the remaining step, `run_time=self.left() * 0.4`, so phrase and rate changes stay
synchronized; overrunning a step stops the build with a clear error. `VoiceScene` draws heading
and subtitles; style comes from its constants and `text()` (`BLUE_`, `GOLD_`, `PANEL`,
Manrope/JetBrains Mono). Minimal example:

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
without voice with `manim -ql scene.py Class` and
`PYTHONPATH=/home/kesha/orchestra/scripts/explainer_video`; 480p takes about one minute.

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
   python /home/kesha/orchestra/scripts/explainer_video/make.py scene.html --out <folder>'
```

Always use `bg_create(type="run")`: a 69 s video took 9.5 min (model loading ~2 min, six
parallel Chromium frame writers via `--jobs`; one thread took 25 min). Phrases cache in
`<folder>/.tts-cache`; changing the scene without changing `say` does not reload the model.
`--stills` skips video and produces phrase timing/contact sheets; `--check-only` checks an
existing MP4. `--speaker` 1 is the default (owner choice on 2026-10-04 in V-690); 0–2 are
female and 3–4 male. `--rate` defaults to 1.15 (1.5 was too fast on 2026-10-03; 1.25 also too
fast on 2026-10-04; speech and pauses shorten together; recognition at 1.25–1.5 matched 1.0 in
V-684); 1.0 is slow.

RUAccent marks Russian phrases before Vosk synthesis using versions from `setup-laptop.sh`. If a
word keeps the wrong stress, put `+` before the stressed vowel (`лим+ита`): the manual form wins
over automation and the marker is hidden from captions. `--no-stress` explicitly disables RUAccent.

**Check stress yourself before the build.** RUAccent makes mistakes: in V-696 it marked
«посл+е» instead of «по́сле» once in five edits. The owner hears every such word. Before a full
build, run `make.py scene.html --out <folder> --stress-only`: it takes seconds and synthesizes
nothing. Read every phrase in the output (also `<folder>/<name>.stress.txt`) and check every `+`
against Russian pronunciation. Pay attention to homographs («за́мок/замо́к», «уже́»), loanwords,
terms («репозито́рий», «оркестра́тор»), and names. Fix likely errors manually in scene `say` with
`+`; repeat `--stress-only` until every `+` is correct, then build. Report the words changed.

Output: `<name>.mp4`, `<name>.timing.json`, `<name>-contact.png` (last frame of each step), and
`<name>.check.json` (Deepgram nova-2 recognition per phrase and its start offset from the plan).

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

`~/.local/share/orchestra-tts/`: `venv` (`uv venv --python 3.12 venv && uv pip install --python
venv/bin/python vosk-tts`) and `vosk-model-tts-ru-0.9-multi` (Apache 2.0, 782 MB zip from
alphacephei.com/vosk/models). Paths use `ORCHESTRA_TTS_HOME`, `ORCHESTRA_TTS_PYTHON`, and
`ORCHESTRA_TTS_MODEL`. Silero and Piper are rejected for NC licenses; cloud TTS is paid. Details:
`.orchestra/tasks/V-681/report.md`.

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
  "$P/bin/python" /home/kesha/orchestra/scripts/explainer_video/make.py scene.html --out video
```

If `/mnt/data` is unavailable or lacks space, choose another storage location for
`PLAYWRIGHT_BROWSERS_PATH`; the browser directory may occupy hundreds of megabytes.
