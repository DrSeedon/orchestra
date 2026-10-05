#!/usr/bin/env bash
set -euo pipefail

ROOT=/mnt/data/Apps/orchestra-video
MANIM="$ROOT/orchestra-manim"
TTS="$ROOT/orchestra-tts"
export PATH="$HOME/.local/bin:$PATH"
export UV_CACHE_DIR="$ROOT/uv-cache"

mkdir -p "$ROOT" "$MANIM/bin" "$TTS"
mkdir -p "$HOME/.local/share"
if [[ ! -e "$HOME/.local/share/orchestra-manim" && ! -L "$HOME/.local/share/orchestra-manim" ]]; then
  ln -s "$MANIM" "$HOME/.local/share/orchestra-manim"
fi
if [[ ! -e "$HOME/.local/share/orchestra-tts" && ! -L "$HOME/.local/share/orchestra-tts" ]]; then
  ln -s "$TTS" "$HOME/.local/share/orchestra-tts"
fi

if [[ ! -x "$MANIM/bin/micromamba" ]]; then
  curl -sSfL https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xj -C "$MANIM" bin/micromamba
fi
if [[ ! -x "$MANIM/env/bin/manim" ]]; then
  MAMBA_ROOT_PREFIX="$MANIM/mamba" "$MANIM/bin/micromamba" create -y -p "$MANIM/env" \
    -c conda-forge python=3.12 manim=0.20.1
fi
"$MANIM/env/bin/manim" --version

TEX_ARCHIVE="$ROOT/TinyTeX.tar.xz"
if [[ ! -x "$MANIM/tex/bin/x86_64-linux/tlmgr" ]]; then
  curl -sSfL --retry 5 --retry-all-errors -o "$TEX_ARCHIVE" \
    https://github.com/rstudio/tinytex-releases/releases/download/v2026.10/TinyTeX-1-linux-x86_64-v2026.10.tar.xz
  mkdir -p "$MANIM/tex-unpack"
  tar -xJf "$TEX_ARCHIVE" -C "$MANIM/tex-unpack"
  mv "$MANIM/tex-unpack/.TinyTeX" "$MANIM/tex"
  rmdir "$MANIM/tex-unpack"
  rm "$TEX_ARCHIVE"
fi
TEX_BIN="$MANIM/tex/bin/x86_64-linux"
"$TEX_BIN/tlmgr" install standalone preview dvisvgm babel-english babel-russian cyrillic lh \
  doublestroke setspace rsfs relsize ragged2e microtype wasysym physics jknapltx wasy mathastext \
  --repository https://mirror.ctan.org/systems/texlive/tlnet
"$TEX_BIN/latex" --version | head -1
"$TEX_BIN/dvisvgm" --version

cd "$TTS"
if [[ ! -x venv/bin/python ]]; then uv venv --python 3.12 venv; fi
uv pip install --python venv/bin/python vosk-tts
uv pip install --python venv/bin/python \
  ruaccent==1.5.8.3 transformers==4.57.1 tokenizers==0.22.2 huggingface-hub==0.36.0
RUACCENT_MODEL="$TTS/ruaccent-model"
RUACCENT_ARCHIVE="$ROOT/ruaccent-model.tar"
RUACCENT_REQUIRED=(
  dictionary/omographs.json.gz
  dictionary/yo_words.json.gz
  dictionary/accents.json.gz
  dictionary/accents_nn.json.gz
  dictionary/yo_homographs.json.gz
  dictionary/rule_engine/accents.json
  dictionary/rule_engine/forms.json
  nn/nn_accent/model.onnx
  nn/nn_stress_usage_predictor/model.onnx
  nn/nn_yo_homograph_resolver/model.onnx
  nn/nn_omograph/turbo3.1/model.onnx
)
RUACCENT_MODEL_READY=1
for file in "${RUACCENT_REQUIRED[@]}"; do
  [[ -s "$RUACCENT_MODEL/$file" ]] || RUACCENT_MODEL_READY=0
done
if [[ "$RUACCENT_MODEL_READY" != 1 ]]; then
  [[ -s "$RUACCENT_ARCHIVE" ]] || {
    echo "RUAccent model archive is missing: $RUACCENT_ARCHIVE" >&2
    exit 1
  }
  tar -xf "$RUACCENT_ARCHIVE" -C "$TTS"
fi
for file in "${RUACCENT_REQUIRED[@]}"; do
  [[ -s "$RUACCENT_MODEL/$file" ]] || {
    echo "RUAccent model file is missing: $RUACCENT_MODEL/$file" >&2
    exit 1
  }
done
RUACCENT_PACKAGE="$(venv/bin/python -c 'import inspect; from pathlib import Path; from ruaccent import RUAccent; print(Path(inspect.getfile(RUAccent)).parent)')"
KOZIEV_DIR="$RUACCENT_PACKAGE/koziev"
KOZIEV_ARCHIVE="$ROOT/ruaccent-koziev.tar"
KOZIEV_REQUIRED=(
  rulemma/rulemma.py
  rulemma/rulemma.dat
  rupostagger/rupostagger.py
  rupostagger/rupostagger.config
  rupostagger/rupostagger.model
  rupostagger/ruword2tags.dat
  rupostagger/rusyllab.py
  rupostagger/database/ruword2tags.db
)
KOZIEV_READY=1
for file in "${KOZIEV_REQUIRED[@]}"; do
  [[ -s "$KOZIEV_DIR/$file" ]] || KOZIEV_READY=0
done
if [[ "$KOZIEV_READY" != 1 ]]; then
  [[ -s "$KOZIEV_ARCHIVE" ]] || {
    echo "RUAccent koziev archive is missing: $KOZIEV_ARCHIVE" >&2
    exit 1
  }
  tar -xf "$KOZIEV_ARCHIVE" -C "$RUACCENT_PACKAGE"
fi
for file in "${KOZIEV_REQUIRED[@]}"; do
  [[ -s "$KOZIEV_DIR/$file" ]] || {
    echo "RUAccent koziev file is missing: $KOZIEV_DIR/$file" >&2
    exit 1
  }
done
if [[ ! -d "$TTS/vosk-model-tts-ru-0.9-multi" ]]; then
  curl -sSfL --retry 10 --retry-all-errors --retry-delay 2 --continue-at - \
    -o "$ROOT/vosk-model-tts-ru-0.9-multi.zip" \
    https://alphacephei.com/vosk/models/vosk-model-tts-ru-0.9-multi.zip
  unzip -q "$ROOT/vosk-model-tts-ru-0.9-multi.zip" -d "$TTS"
  rm "$ROOT/vosk-model-tts-ru-0.9-multi.zip"
fi

cd "$TTS"
mkdir -p en
if [[ ! -x en/venv/bin/python ]]; then uv venv --python 3.12 en/venv; fi
uv pip install --python en/venv/bin/python kokoro-onnx soundfile
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [[ ! -s "en/$f" ]]; then
    curl -sSfL --retry 10 --retry-all-errors --retry-delay 2 -o "en/$f" \
      "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"
  fi
done

PLAYWRIGHT="$ROOT/playwright"
if [[ ! -x "$PLAYWRIGHT/bin/python" ]]; then uv venv --python 3.12 "$PLAYWRIGHT"; fi
uv pip install --python "$PLAYWRIGHT/bin/python" playwright==1.61.0
PLAYWRIGHT_BROWSERS_PATH="$ROOT/ms-playwright" \
  "$PLAYWRIGHT/bin/python" -m playwright install chromium

du -sh "$MANIM" "$TTS" "$UV_CACHE_DIR"
