"""Recover the five authorized sources using pinned public bytes and producer delta."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".orchestra/tasks/V-1259"
EVIDENCE = ROOT / ".orchestra/tasks/V-1257/recovery-conflict-evidence.json"


def sha(body):
    return hashlib.sha256(body).hexdigest()


def snapshot():
    files = {}
    for directory, dirs, names in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {
            ".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
        } and Path(directory, d) != OUT)
        for name in sorted(names):
            path = Path(directory, name)
            rel = path.relative_to(ROOT).as_posix()
            files[rel] = ("symlink:" + os.readlink(path) if path.is_symlink()
                          else sha(path.read_bytes()))
    return files


def main():
    evidence = json.loads(EVIDENCE.read_text())
    before_path = OUT / "before-manifest.json"
    assert not before_path.exists(), "Recovery is single-use; preserve original evidence"
    before_path.write_text(json.dumps(snapshot(), indent=2) + "\n")
    pinned = []
    for item in evidence["files"]:
        rel = item["path"]
        url = item["source"]
        assert url.startswith("https://raw.githubusercontent.com/DrSeedon/orchestra/"
                              + evidence["canonical_main_head"] + "/")
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read()
        assert sha(body) == item["canonical_sha256"], rel
        pinned.append((item, body))
    # Fetch and validate every canonical file before changing any source.
    for item, body in pinned:
        for kind, payload in (("before", (ROOT / item["path"]).read_bytes()),
                              ("canonical", body)):
            path = OUT / kind / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        (ROOT / item["path"]).write_bytes(body)
    patch = ROOT / ".orchestra/tasks/V-1257/recovery-against-d95.patch"
    command = ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(patch)]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (OUT / "phase-a-apply.log").write_text(run.stdout + run.stderr
                                           + f"\nEXIT_CODE={run.returncode}\n")
    assert run.returncode == 0, "Minimal producer delta did not apply"
    diffs = []
    result = []
    for item, canonical in pinned:
        rel = item["path"]
        original = (OUT / "before" / rel).read_bytes()
        final = (ROOT / rel).read_bytes()
        assert sha(final) == item["final_sha256"], rel
        diffs.extend(difflib.unified_diff(original.decode().splitlines(True),
                     final.decode().splitlines(True), fromfile="a/" + rel,
                     tofile="b/" + rel))
        result.append({"path": rel, "before_sha256": sha(original),
                       "canonical_sha256": sha(canonical), "final_sha256": sha(final),
                       "changed": original != final,
                       "equals_canonical": final == canonical})
    (OUT / "five-file.patch").write_text("".join(diffs))
    (OUT / "five-file-manifest.json").write_text(json.dumps({
        "canonical_main_head": evidence["canonical_main_head"], "files": result,
        "broker_import_head": None, "git_directory_present": (ROOT / ".git").exists(),
    }, indent=2) + "\n")
    assert len(result) == 5 and all(item["changed"] for item in result)
    print("PASS: all five authorized files changed; pinned final SHA-256 matched")


if __name__ == "__main__":
    main()
