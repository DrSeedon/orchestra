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
