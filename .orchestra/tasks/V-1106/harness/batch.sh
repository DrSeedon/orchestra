#!/bin/bash
cd "$(dirname "$0")"
python3 - "$@" <<'PY' | xargs -P 6 -L 1 python3 run.py
import sys, scenarios as S
for rep in sys.argv[1].split():
    for sid, s in S.S.items():
        for arm in ("base", s["rule"]):
            print(sid, arm, rep)
PY
