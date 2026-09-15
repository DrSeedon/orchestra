"""V-577: prove that no rule category left any role prompt.

Rebuilds each role's prompt from BASE and from the working tree, then for every
sentence that disappeared checks whether an equivalent sentence (token Jaccard
>= 0.5) survives somewhere in the SAME role's prompt — i.e. the rule kept a home.
"""
import re, subprocess, sys
from pathlib import Path
import yaml

# Base ref = the commit this task started from, NOT HEAD: once the work is committed a
# HEAD comparison is empty and proves nothing.
BASE = sys.argv[1] if len(sys.argv) > 1 else "a3d8b8f4"
REL = ".orchestra/pipelines/default/prompts"
ROLES = ["orchestrator", "sub-orchestrator", "worker", "full-cycle", "reducer"]
manifest = yaml.safe_load(Path(".orchestra/pipelines/default/pipeline.yaml").read_text())
defaults = manifest["defaults"]

CATEGORIES = {
    "safety": "<safety>",
    "approval gate": "<approval-gate>",
    "git": "<git-workflow>",
    "worker lifecycle": "<worker-lifecycle>",
    "knowledge": "<knowledge>",
    "communication style": "<communication-style>",
    "model routing": "<model-routing>",
    "owner values": "<user-values>",
}


def layers(role):
    kind = manifest["roles"][role]["kind"]
    return [x.replace("{role}", role) for x in defaults["prompt_layers"][kind]]


def base(path):
    r = subprocess.run(["git", "show", f"{BASE}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def live(path):
    p = Path(path)
    return p.read_text() if p.is_file() else ""


def assemble(role, source):
    parts = [t for t in (source(f"{REL}/{l}") for l in layers(role)) if t]
    mods = [m for m in (source(f"{REL}/modules/{n}.md").strip()
                        for n in manifest["roles"][role].get("modules", [])) if m]
    if mods:
        parts.append("\n\n".join(mods))
    return "\n\n".join(parts)


def sentences(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "```", "|", "<")):
            continue
        for part in re.split(r"(?<=[.!?:])\s+", s.lstrip("-* ")):
            part = re.sub(r"\s+", " ", re.sub(r"[`*_]", "", part)).strip().lower()
            if len(part) >= 30:
                out.append(part)
    return out


def toks(s):
    return set(re.findall(r"[a-zа-я0-9]+", s))


# Manually reviewed paraphrases: a sentence whose wording changed enough to fall under
# the similarity threshold, together with the text that must still be in the same prompt.
PARAPHRASED = {
    "owneddirs — optional expected work areas for coordination, not permission boundaries.":
        "`owned_dirs` is optional coordination metadata, not an edit allowlist.",
    "coordinate actual overlapping edits and verify integration before merge.":
        "Check actual diffs and integration tests before merge",
    "not an edit allowlist; explicit task exclusions remain binding.":
        "Respect explicit task exclusions and explain unexpected changes.",
    "reproduce defects when practical; an already-green regression command is":
        "reproduce it and add a meaningful check",
    "resolve discoverable facts yourself; ask only about material":
        "Ask only when\nan unresolved choice changes scope, authority, material cost or an external contract.",
    "an already-green regression test is not a reason to stop investigating a reported defect.":
        "A green regression command does not settle an unreproduced defect.",
}

fail = False
for role in ROLES:
    before, after = assemble(role, base), assemble(role, live)
    nb, na = len(before.encode()), len(after.encode())
    print(f"\n=== {role}: {nb} -> {na} bytes ({na - nb:+d}, {100 * (na - nb) / nb:+.2f}%)")
    for name, anchor in CATEGORIES.items():
        was, now = anchor in before, anchor in after
        if was != now:
            print(f"    CATEGORY DELIVERY CHANGED: {name} {was} -> {now}")
            fail = True
    print("    categories present:",
          ", ".join(n for n, a in CATEGORIES.items() if a in after) or "none")
    after_sents = sentences(after)
    after_toks = [toks(s) for s in after_sents]
    for s in sentences(before):
        if s in after_sents:
            continue
        ts = toks(s)
        best, bestj = "", 0.0
        for cand, tc in zip(after_sents, after_toks):
            j = len(ts & tc) / len(ts | tc) if ts | tc else 0
            if j > bestj:
                best, bestj = cand, j
        if bestj >= 0.5:
            print(f"    [COVERED {bestj:.2f}] removed: {s[:110]}")
            print(f"                 kept as: {best[:110]}")
            continue
        home = PARAPHRASED.get(s)
        if home and home in after:
            print(f"    [REWORDED {bestj:.2f}] removed: {s[:110]}")
            print(f"                 home now: {home.splitlines()[0][:110]}")
            continue
        print(f"    [ORPHANED {bestj:.2f}] removed: {s[:110]}")
        fail = True
    rep = {}
    for t in re.findall(r"^<([a-z-]+)>$", after, re.M):
        rep[t] = rep.get(t, 0) + 1
    rep = {k: v for k, v in rep.items() if v > 1}
    print(f"    repeated wrapper tags: {rep or 'none'}")
    if rep:
        fail = True
print("\nRESULT:", "FAIL" if fail else "OK — every removed sentence has a surviving home")
sys.exit(1 if fail else 0)
