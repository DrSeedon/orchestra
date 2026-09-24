"""V-634: migrate old-layout worker worktrees in place on the laptop, preserving dirty state.

Run from the laptop checkout: .venv/bin/python migrate_worktrees.py <name>=<worktree> ...
Per worktree: tag HEAD, park untracked files under docs/ outside the repo, run the
canonical migrate_project_layout(_allow_dirty=True), put the parked files back at the
mapped path (still untracked), then compare mapped status before/after.
"""
import json, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app import orchestra_layout as L

PARK = Path("/mnt/data/tmp/v634-park")


def git(wt, *a, check=True):
    return subprocess.run(["git", "-C", str(wt), *a], text=True, capture_output=True, check=check).stdout


def records(wt):
    return sorted((r["xy"], L._map_legacy_path(r["path"])) for r in L._status_records(wt))


out = {}
for arg in sys.argv[1:]:
    name, wt = arg.split("=", 1)
    wt = Path(wt)
    res = {"head_before": git(wt, "rev-parse", "HEAD").strip()}
    tag = f"preserve/v634-{name}"
    if not git(wt, "tag", "-l", tag).strip():
        git(wt, "tag", tag, "HEAD")
    res["tag"] = tag
    before = records(wt)
    untracked = [r["path"] for r in L._status_records(wt) if r["xy"] == "??" and r["path"].startswith("docs/")]
    parked = []
    for rel in untracked:
        src = wt / rel
        dst = PARK / name / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        parked.append(rel)
    try:
        r = L.migrate_project_layout(wt, _allow_dirty=True)
        res.update(status=r["status"], commit=r.get("commit"), managed=r.get("managed_paths"),
                   ownership_changed=r.get("ownership", {}).get("changed"))
    finally:
        for rel in parked:
            dst = wt / L._map_legacy_path(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(PARK / name / rel), str(dst))
    after = records(wt)
    res["dirty_preserved"] = before == after
    if before != after:
        res["before"], res["after"] = before, after
    L.require_project_layout(wt)
    res["layout"] = "current"
    res["diff_vs_tag_only_renames"] = git(wt, "diff", "--name-status", "-M100%", tag, "HEAD").splitlines()
    out[name] = res
    print(json.dumps({name: res}, ensure_ascii=False), flush=True)
