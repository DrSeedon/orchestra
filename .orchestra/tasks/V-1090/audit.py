"""Offline integrity, publication-boundary shape scan and artifact-link checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile

TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
EVIDENCE = TASK / "evidence"
UPSTREAM = EVIDENCE / "stale-docs-data-fa3c8b8a3347b11e7d4faa073af2b210a1b037e3"


def public_files():
    """Prune task-private evidence before traversal, hashing or publication scanning."""
    for base, directories, files in os.walk(TASK, topdown=True, followlinks=False):
        if Path(base) == TASK:
            directories[:] = [name for name in directories if name != "private"]
        for name in sorted(files):
            path = Path(base) / name
            assert not path.is_symlink(), "Public artifacts must not depend on transport symlinks"
            yield path


tree = json.loads((EVIDENCE / "github-pinned-tree.json").read_text())
commit = json.loads((EVIDENCE / "github-main.json").read_text())
assert tree["truncated"] is False
assert commit["sha"] == "fa3c8b8a3347b11e7d4faa073af2b210a1b037e3"
assert tree["sha"] == commit["commit"]["tree"]["sha"]
blobs = [item for item in tree["tree"] if item["type"] == "blob"]
for item in blobs:
    data = (UPSTREAM / item["path"]).read_bytes()
    assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == item["sha"], item["path"]
with tarfile.open(EVIDENCE / "author-archive.tar.gz") as archive:
    members = archive.getmembers()
    assert all(not m.issym() and not m.islnk() and not m.isdev() for m in members)
    assert all(not m.name.startswith("/") and ".." not in Path(m.name).parts for m in members)
print("PASS upstream pinned commit/tree and", len(blobs), "Git blob hashes; archive has no links/devices/traversal")
local = json.loads((EVIDENCE / "orchestra-source-sha256.json").read_text())
for name, digest in local.items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
print("PASS", len(local), "captured Orchestra rule/checker files unchanged")
utilities = ("recount.py", "capture.py", "audit.py", "prepare_publication.py")
for name in utilities:
    compile((TASK / name).read_text(), str(TASK / name), "exec")
print("PASS syntax of all", len(utilities), "task-local research utilities")
assert "/private/" in (TASK / ".gitignore").read_text().splitlines()
assert not (TASK / "pytest-tmp").exists()
receipt = json.loads((TASK / "preservation-manifest.json").read_text())
if (TASK / "private").exists():
    assert receipt == json.loads((TASK / "private/preservation-manifest.json").read_text())
    for entry in receipt["entries"]:
        path = TASK / entry["preserved"]
        body = os.fsencode(os.readlink(path)) if entry["kind"] == "symlink-target" else path.read_bytes()
        assert len(body) == entry["bytes"] and hashlib.sha256(body).hexdigest() == entry["sha256"]
    print("PASS targeted preservation check:", len(receipt["entries"]), "original file/link payloads; private excluded from public walk")
else:
    print("Private originals unavailable in this transport; preservation receipt retained; native owner must verify custody")
print("PASS public fixture directory absent; task .gitignore declares /private/; native Git ignored status not checked without .git")
report = (TASK / "report.md").read_text()
local_links = []
for target in re.findall(r"\]\(([^)]+)\)", report):
    if "://" in target or target.startswith("#"):
        continue
    path = target.split("#")[0]
    if path:
        if path != "artifact-sha256.json":
            assert (TASK / path).exists(), path
        local_links.append(path)
patterns = {
    "native-home-literal": re.escape(str(Path.home())),
    "native-workspace-literal": re.escape(str(ROOT)),
    "private-key-block": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "vendor-key-shape": r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b",
    "bearer-value": r"\bBearer\s+[A-Za-z0-9_.-]{30,}",
    "credential-url": r"https?://[^\s/:]+:[^\s/@]+@",
    "telegram-token-shape": r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",
    "assigned-secret-value": r'''(?i)\b(?:api_key|access_token|refresh_token|client_secret|password)\b\s*[=:]\s*["'][A-Za-z0-9_./+=-]{20,}["']''',
}
hits = []
scanned = 0
for path in sorted(public_files()):
    if path.suffix.lower() in {".pdf", ".gz", ".pyc"}:
        continue
    try:
        text = path.read_text()
    except UnicodeError:
        continue
    scanned += 1
    for label, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            hits.append((str(path.relative_to(TASK)), text[:match.start()].count("\n") + 1, label))
print("publication-boundary scan:", scanned, "UTF-8 files; hits (paths/lines/shapes only):", hits)
assert not hits
print("PASS named credential shapes absent; heuristic scan is not a proof of arbitrary-secret absence")
manifest = {str(path.relative_to(TASK)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(public_files())
            if path not in {TASK / "artifact-sha256.json", EVIDENCE / "audit.txt"}}
assert not any(name.startswith(("private/", "pytest-tmp/")) for name in manifest)
(TASK / "artifact-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("wrote artifact-sha256.json:", len(manifest), "files (self manifest and audit output excluded)")
assert all((TASK / path).exists() for path in local_links)
print("PASS", len(local_links), "local report links resolve")
