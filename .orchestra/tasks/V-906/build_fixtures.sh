#!/bin/bash
# Snapshots = parent of the fixing commit (app scripts tests pyproject.toml), no .git/.orchestra/reports.
# Usage: build_fixtures.sh <orchestra-main-checkout> <out-dir>
set -e
SRC=$1; OUT=$2
cd "$SRC"
mk() { n=$1; c=$2; mkdir -p "$OUT/fx/$n"; git archive "$c" app scripts tests pyproject.toml | tar -x -C "$OUT/fx/$n"; }
mk T1 8239760c^
mk T2 bec4f378^
mk T3 e86fc63f^
mk T4 fbc9e40d^
mk T5 10698051^
mk T6 17a7d398^
mk T7 d1bd9580^
mk T8 495eb220^
mk K1 4b185fdc^
mk K2 16ebb5e1^
mk K3 a43f2686^
mk K4 cb96eb6f^
for k in C1 C2 C3 C4; do mkdir -p "$OUT/fx/$k"; done
