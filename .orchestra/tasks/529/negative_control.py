"""Negative control: point the corpus at a ref that PREDATES the facts and the gate must flip."""
import importlib.util
spec = importlib.util.spec_from_file_location("c", ".orchestra/tasks/529/check_branch_unique_facts.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
BASE = m.git("merge-base", "main", "task-510/audit-workers-state").strip()

def corpus_at(ref):
    parts = []
    for path in m.git("ls-tree", "-r", "--name-only", ref).splitlines():
        if m.is_prose(path) or (path.endswith(".py") and path.startswith(("app/", "scripts/"))):
            parts.append(m.show(ref, path))
    return m.norm(" ".join(parts))

for label, ref in (("main", "main"), (f"pre-#508 base {BASE[:8]}", BASE)):
    corpus = corpus_at(ref)
    for branch in ("task-510/audit-workers-state",):
        v = u = 0
        for _, unit in m.branch_new_units(branch):
            if unit in corpus: v += 1
            else: u += 1
        print(f"corpus={label:24} {branch}: verbatim={v} not-verbatim={u}")
