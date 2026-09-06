"""#490 — prove no rule disappeared from any role prompt. Reproducible, no dumps committed.

Both slices are rendered here, by the code Orchestra itself uses
(:func:`app.pipeline.build_system_prompt`, ``app/pipeline.py:583``):

- BEFORE — the prompt tree at ``--base-ref`` (default: the merge-base pin below), extracted to a
  temp dir with ``git archive``; ``pipeline.PIPELINES_DIR`` is repointed at it for the render.
- AFTER  — the working tree as it is right now, so editing a module and re-running is the check.

Then two passes per role:

1. VERBATIM — every unit (top-level bullet / paragraph, >40 chars) of the BEFORE prompt must be
   present character-for-character (whitespace-normalised) in the AFTER prompt.
2. REWORDED — the units that legitimately changed are enumerated in :data:`REWORDED`. Each carries
   literal anchors that must all appear in the AFTER prompt: the machine check that the rule
   survived the move/translation instead of vanishing.

A BEFORE unit that is neither verbatim-present nor listed in REWORDED fails the run.

Run (from the repo root, one command, no arguments needed):

    uv run --frozen python .orchestra/tasks/490/check_no_rule_lost.py

Exit code 0 = PASS. Per-role byte size and sha256 of both slices are printed, so a divergence is
caught by comparing hashes against ``no-rule-lost.txt`` without re-reading either text.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile

# Merge-base of task-520/merge-prompt-modules with main — main as it stood before this task.
BASE_REF = "a1fd56bb9adb2799d197d5a5ce67776a225d136a"
PIPELINE = "default"
ROLES = ["orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"]
REPO = pathlib.Path(__file__).resolve().parents[3]  # .orchestra/tasks/490/<this file>

# BEFORE-unit prefix → anchors that must survive in the AFTER prompt.
# Each entry is a rule this task deliberately moved, retagged or translated.
REWORDED: list[tuple[str, list[str]]] = [
    # base.md <project-memory> → modules/knowledge-and-context.md (retagged only)
    ("<project-memory>", [
        "Canonical project memory lives in `.orchestra/kb/`.",
        "Task artifacts are supporting evidence, not a second memory store.",
    ]),
    # base standard rule → communication-style (widened to the user-facing voice)
    ("- Respond in the same language", [
        "respond in the same language the user communicates in",
    ]),
    # splitter artifact: the bullet is verbatim, only the closing tag after it changed
    ("- Workers: no narration between tool calls.", [
        "Workers: no narration between tool calls. One line before your first action, "
        "one at blockers, and the DONE report. Your thinking block does reasoning — "
        "don't duplicate in chat",
    ]),
    # base <communication-style> header → module header + language carve-out
    ("<communication-style>", [
        "## Communication style (all agents)",
        "this block applies to working comms — reports, status, agent↔agent. NOT to "
        "`.orchestra/tasks/*.md` (research/plans stay full), NOT to the orchestrator's "
        "user-facing chat voice.",
    ]),
    # ── <user-values>: Russian → English, meaning preserved 1:1 ──────────────
    ("<user-values>", [
        "## Owner values — in force in ALL projects",
    ]),
    ("Это решения владельца", [
        "These are the owner's decisions, not agent preferences.",
        "outrank any local project agreement",
        "may narrow them for its own specifics, but cannot cancel them",
        "approved each of them by name on 04.09.2026",
    ]),
    ("- **Реализацию начинает его слово", [
        "Implementation starts with his word; research an agent starts on its own.",
        "The right to decide\n  what gets done at all belongs to him",
        "he pays for every worker and every burned subscription",
        "Research is the exception — it does not change system state and therefore goes "
        "without asking.",
        "Silence is not consent anywhere except a live incident.",
    ]),
    ("- **Архитектурная развилка", [
        "An architectural fork goes to him BEFORE implementation, on any path of work.",
        'Not "I did it,\n  now look", but "here is the fork, here is the price of each '
        'branch, decide".',
        "It binds beyond the\n  research role: an ordinary change that silently picks an "
        "architecture violates it the same way.",
        'Research ending in "we must do X" is a proposal, not a mandate.',
    ]),
    ("- **При живой поломке", [
        "On a live breakage, restore work first and polish later.",
        "Fast recovery matters more than\n  elegance and more than a complete proof.",
        "Evidence and analysis come AFTER everything works again,\n  not instead of the fix.",
    ]),
    ("- **Он обязан ПОНИМАТЬ", [
        "He is obliged to UNDERSTAND what is happening, not to receive a finished result.",
        "Explaining,\n  showing, and making sure he understood is part of the work, not a "
        "courtesy",
        "an agent right on the\n  merits that did not carry understanding through has not "
        "done the work",
        "an agent seeing an error in his decision must name it and show the basis, not\n"
        "  silently comply.",
    ]),
    ("- **Найденный в собственных логах", [
        "A key found in our own logs and data is a working tool, not an incident.",
        "Only proven access by\n  OUTSIDERS raises an alarm",
        "it got into git, went to a public remote, was handed outside",
        '"The\n  secret exists" and "the secret leaked" are different statements',
        "work is not stopped and he is not\n  disturbed over the first.",
    ]),
]


def _render(pipelines_dir: pathlib.Path) -> dict[str, str]:
    """Assemble every role prompt with Orchestra's own builder against ``pipelines_dir``."""
    sys.path.insert(0, str(REPO))
    from app import pipeline as P

    original = P.PIPELINES_DIR
    P.PIPELINES_DIR = pipelines_dir
    try:
        return {role: P.build_system_prompt(PIPELINE, role) for role in ROLES}
    finally:
        P.PIPELINES_DIR = original


def render_before(base_ref: str, workdir: pathlib.Path) -> dict[str, str]:
    """Prompts as they stood at ``base_ref``, extracted read-only via ``git archive``."""
    archive = subprocess.run(
        ["git", "-C", str(REPO), "archive", base_ref, f".orchestra/pipelines/{PIPELINE}"],
        check=True, capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(workdir)], input=archive, check=True)
    return _render(workdir / ".orchestra" / "pipelines")


def render_after() -> dict[str, str]:
    """Prompts as the working tree stands right now."""
    return _render(REPO / ".orchestra" / "pipelines")


def units(text: str) -> list[str]:
    """Split into top-level bullets and paragraphs, keeping continuation lines."""
    out: list[str] = []
    cur: list[str] = []
    for line in text.splitlines():
        starts_unit = bool(re.match(r"^\s*[-*\d]", line)) or (
            line.strip() and not line.startswith((" ", "\t")) and cur and not cur[-1].strip()
        )
        if starts_unit and cur:
            out.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return [u for u in (u.strip() for u in out) if len(u) > 40]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def stamp(text: str) -> str:
    raw = text.encode()
    return f"{len(raw):6} B  sha256:{hashlib.sha256(raw).hexdigest()}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-ref", default=BASE_REF, help="ref holding the BEFORE prompt tree")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="check490-") as tmp:
        before = render_before(args.base_ref, pathlib.Path(tmp))
    after = render_after()

    print(f"BEFORE  git archive {args.base_ref[:12]} → build_system_prompt('{PIPELINE}', role)")
    print(f"AFTER   working tree                    → build_system_prompt('{PIPELINE}', role)\n")

    failures: list[str] = []
    for role in ROLES:
        after_n = norm(after[role])
        verbatim = reworded = 0
        for unit in units(before[role]):
            if norm(unit) in after_n:
                verbatim += 1
                continue
            match = next((r for r in REWORDED if unit.startswith(r[0])), None)
            if match is None:
                failures.append(f"{role}: LOST unit → {norm(unit)[:160]}")
                continue
            reworded += 1
            for anchor in match[1]:
                if norm(anchor) not in after_n:
                    failures.append(
                        f"{role}: anchor missing for {match[0][:40]!r} → {norm(anchor)[:120]}"
                    )
        print(f"{role}")
        print(f"  units   verbatim={verbatim:3}  reworded={reworded:3}")
        print(f"  before  {stamp(before[role])}")
        print(f"  after   {stamp(after[role])}")

    print()
    if failures:
        for f in failures:
            print("FAIL " + f)
        print(f"\nFAILED: {len(failures)} problem(s)")
        return 1
    print("PASS — no rule lost in any of the five role prompts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
