#!/bin/bash
# Pre-fix snapshots (app, scripts, pyproject only; no git history, no .orchestra, no CHANGELOG/tests of the fix).
# Usage: build_fixtures.sh <orchestra-main-checkout> <out-dir>
set -e
SRC=$1; OUT=$2
cd "$SRC"
for p in O1:86bb4e23 O2:84de265c O3:d5e33acf O4:095aef66 C1:a43f2686 C2:16ebb5e1 C3:7111f3c2 C4:9fdd0499; do
  n=${p%%:*}; c=${p##*:}
  mkdir -p "$OUT/fx/$n" "$OUT/ref/$n"
  git archive "$c^" app scripts pyproject.toml | tar -x -C "$OUT/fx/$n"
  git archive "$c"  app scripts pyproject.toml | tar -x -C "$OUT/ref/$n"
done
