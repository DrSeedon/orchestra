#!/bin/bash
# Snapshots for research tasks (parent of the commit that added the real report) + empty dirs for creative ones.
# Usage: build_fixtures.sh <orchestra-main-checkout> <out-dir>
set -e
SRC=$1; OUT=$2
cd "$SRC"
mk() { n=$1; c=$2; shift 2; mkdir -p "$OUT/fx/$n"; git archive "$c" "$@" | tar -x -C "$OUT/fx/$n"; }
mk R1 84d58f6a^ app scripts pyproject.toml CLAUDE.md CHANGELOG.md docs/tasks
mk R2 c4843b0c^ app scripts pyproject.toml CLAUDE.md
mk R3 6d7b5793^ app scripts tests pyproject.toml
for k in K1 K2 K3 K4 K5 K6; do mkdir -p "$OUT/fx/$k"; done
# R1 post-processing (done by hand): CHANGELOG.md line 5 (names task #52) removed
