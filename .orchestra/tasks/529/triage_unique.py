#!/usr/bin/env python3
"""#529 — rank what `check_branch_unique_facts.py` could not prove `main` already knows.

The first script answers "is this text in `main`?" and, for four abandoned research
branches, the honest answer for most prose is no: a `research.md` narrates, and narration
never entered the knowledge base. 495 UNIQUE units is therefore a triage input, not a
finding.

This script sorts that input by the only signal that distinguishes a FACT `main` lacks from
a SENTENCE `main` lacks:

- Tier A — the unit lives in `.orchestra/kb/**`. Its own author already judged it a
  knowledge-base record, so it is read in full regardless of anchors.
- Tier B — the unit carries a literal anchor (symbol, path, file:line, «owner quote», date,
  number ≥ 3 digits) that appears NOWHERE in `main`'s prose or in `app/` and `scripts/`
  code. An anchor absent from the whole repository is the strongest available evidence that
  the observation behind it was never carried anywhere.
- Tier C — everything else: prose whose every anchor exists in `main`, i.e. it talks about
  things `main` already knows, in words `main` does not use. Counted, not printed.

Tier C is where a fact could still hide, and this script does not pretend otherwise; that
residual risk is stated in the report rather than hidden behind a green line.

Run:

    python3 .orchestra/tasks/529/triage_unique.py > /mnt/data/529-triage.txt
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cbuf", HERE / "check_branch_unique_facts.py")
cbuf = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(cbuf)


def run() -> int:
    corpus = cbuf.main_corpus()
    tier_a: list[tuple[str, str, str]] = []
    tier_b: list[tuple[str, str, str, list[str]]] = []
    tier_c = 0

    for branch in cbuf.BRANCHES:
        for path, unit in cbuf.branch_new_units(branch):
            if unit in corpus:
                continue
            own = cbuf.anchors(unit)
            missing = [a for a in own if a not in corpus]
            if path.startswith(".orchestra/kb/"):
                tier_a.append((branch, path, unit))
            elif missing:
                tier_b.append((branch, path, unit, missing))
            else:
                tier_c += 1

    print(f"TIER A (kb records): {len(tier_a)}")
    for branch, path, unit in tier_a:
        print(f"\n--- {branch} :: {path}\n{unit}")

    print(f"\n\nTIER B (anchor absent from all of main): {len(tier_b)}")
    for branch, path, unit, missing in sorted(tier_b, key=lambda r: -len(r[3])):
        print(f"\n--- {branch} :: {path}  [missing {len(missing)}: {missing[:8]}]\n{unit[:700]}")

    print(f"\n\nTIER C (every anchor already in main, prose only): {tier_c}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
