#!/bin/bash
# Snapshots = parent of the commit that added the real research/fix, so the report and the fix are absent.
# Usage: build_fixtures.sh <repo-checkout> <out-dir>
set -e
SRC=$1; OUT=$2
cd "$SRC"
mk() { n=$1; c=$2; mkdir -p "$OUT/fx/$n"; git archive "$c^" app scripts tests pyproject.toml | tar -x -C "$OUT/fx/$n"; }
mk S01 f2ce77eb   # #30
mk S02 10d1a858   # #61
mk S03 ef9c8057   # #62
mk S04 262b38b5   # #71
mk S05 9764b850   # #97
mk S06 8239760c   # #416
mk S07 0d3975b0   # #56
mk S08 0c3c0fcb   # V-575
mk S09 0f973de2   # V-620
mk S10 b2f143da   # V-648
mk S11 951d0d47   # V-680
mk S12 57474dec   # #93
