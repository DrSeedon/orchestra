#!/usr/bin/env python3
"""#529 — does an abandoned branch hold a fact that `main` does not?

The question is asked mechanically because we have already been wrong about it by eye:
a branch declared empty turned out not to be. Reading a diff and concluding "nothing new"
is exactly the judgement this script replaces.

Method, per branch:

- BRANCH corpus = every PROSE markdown file the branch added or changed against its own
  merge-base with `main`. Raw material is excluded by construction (see :data:`SKIP_PARTS`
  and :data:`PROSE_SUFFIX`): dumps, snapshots, JSON/JSONL datasets and scripts are evidence,
  not facts, and the task forbids carrying them.
- NEW units = units of the branch file MINUS units already present in that file at the
  merge-base. A unit the branch merely inherited is not a fact the branch contributes.
- MAIN corpus = every tracked `.md` in `main` outside the same excluded raw material, plus
  the tracked Python of `app/` and `scripts/`. Code is included on purpose: a research claim
  is frequently "answered" by an implementation rather than by a sentence, and a symbol name
  is the anchor that proves it.

A NEW unit clears one of two gates, both of them textual:

1. VERBATIM — present character-for-character (whitespace-normalised) in MAIN.
2. ANCHORED — every literal anchor it carries (backticked spans, «owner speech», bare
   repository paths, dates, `#task` refs, percentages, numbers of three digits or more) is
   present in MAIN, AND at least one of those anchors is a SIGNATURE anchor: one that occurs
   in exactly one NEW unit across all four branches. Without the signature requirement the
   gate degenerates — `#489` or `app/db.py` appear in dozens of units, so any of them could
   vanish unnoticed.

Everything else is printed as UNIQUE and must be read by a human. UNIQUE is not a verdict
that the fact is worth keeping; it is a verdict that a machine could not prove `main`
already has it. The reading decides, and the reasons are recorded in the report.

Run:

    python3 .orchestra/tasks/529/check_branch_unique_facts.py

Exit code is always 0: this script triages, it does not gate a merge. The count of UNIQUE
units is the output that matters.

Mutation check: add a sentence with an invented number to any branch file's prose and it
must appear in UNIQUE; that probe is recorded in `.orchestra/tasks/529/mutation-unique.txt`.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]

BRANCHES = [
    "task-477/audit-idle-workers",
    "task-489/knowledge-loop",
    "task-504/research-text-oracles",
    "task-510/audit-workers-state",
]

PROSE_SUFFIX = ".md"
# Raw material: never a fact, never carried. `eval/` and `raw/` hold dumps and datasets.
SKIP_PARTS = ("/raw/", "/eval/", "/runs/")

ANCHOR_PATTERNS = [
    r"`[^`]+`",
    r"«[^»]+»",
    r"(?:\.orchestra|docs|app|scripts|tests|deploy|data)/[^\s,;·)\]]*[./][^\s,;·)\]]+",
    r"\b\d{2}\.\d{2}\.\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"#\d+",
    r"\d+(?:[.,]\d+)?\s*(?:%|×|п\.п\.)",
    r"\b\d{3,}\b",
]
ANCHOR_RE = re.compile("|".join(ANCHOR_PATTERNS))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True,
    ).stdout


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def units(text: str) -> list[str]:
    """Top-level bullets and paragraphs, continuation lines kept with their bullet."""
    out: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        starts = bool(re.match(r"^\s*[-*] ", line)) or (
            line.strip() and not line.startswith((" ", "\t")) and current and not current[-1].strip()
        )
        if starts and current:
            out.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        out.append("\n".join(current))
    return [u for u in (norm(u) for u in out) if len(u) > 40]


def anchors(unit: str) -> list[str]:
    seen: list[str] = []
    for match in ANCHOR_RE.findall(unit):
        match = match.rstrip(".,;:")
        if " · " in match:
            continue
        if match and match not in seen:
            seen.append(match)
    return seen


def is_prose(path: str) -> bool:
    if not path.endswith(PROSE_SUFFIX):
        return False
    return not any(part in f"/{path}" for part in SKIP_PARTS)


def show(ref: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{ref}:{path}"],
        check=False, capture_output=True, text=True,
    )
    return completed.stdout if completed.returncode == 0 else ""


def main_corpus() -> str:
    parts: list[str] = []
    for path in git("ls-tree", "-r", "--name-only", "main").splitlines():
        if is_prose(path) or (
            path.endswith(".py") and path.startswith(("app/", "scripts/"))
        ):
            parts.append(show("main", path))
    return norm(" ".join(parts))


def branch_new_units(branch: str) -> list[tuple[str, str]]:
    base = git("merge-base", "main", branch).strip()
    changed = git("diff", "--name-only", base, branch).splitlines()
    found: list[tuple[str, str]] = []
    for path in changed:
        if not is_prose(path):
            continue
        before = set(units(show(base, path)))
        for unit in units(show(branch, path)):
            if unit not in before:
                found.append((path, unit))
    return found


def run() -> int:
    corpus = main_corpus()
    per_branch = {b: branch_new_units(b) for b in BRANCHES}

    counts: dict[str, int] = {}
    for pairs in per_branch.values():
        for _, unit in pairs:
            for anchor in anchors(unit):
                counts[anchor] = counts.get(anchor, 0) + 1

    print(f"MAIN corpus: {len(corpus)} chars (normalised)")
    total_new = total_unique = 0
    for branch, pairs in per_branch.items():
        verbatim = anchored = unique = 0
        lines: list[str] = []
        for path, unit in pairs:
            if unit in corpus:
                verbatim += 1
                continue
            own = anchors(unit)
            signature = [a for a in own if counts.get(a, 0) == 1]
            if own and signature and all(a in corpus for a in own):
                anchored += 1
                continue
            unique += 1
            missing = [a for a in own if a not in corpus]
            lines.append(f"  UNIQUE {path}\n    {unit[:400]}\n    missing anchors: {missing[:6]}")
        total_new += len(pairs)
        total_unique += unique
        print(
            f"\n=== {branch}: new units={len(pairs)} "
            f"verbatim={verbatim} anchored={anchored} UNIQUE={unique}"
        )
        for line in lines:
            print(line)
    print(f"\nTOTAL new units={total_new} UNIQUE={total_unique}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
