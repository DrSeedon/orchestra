"""Preserve local originals privately and create labelled public path substitutions once."""
import hashlib
import json
import os
from pathlib import Path
import shutil

TASK = Path(__file__).resolve().parent
WORKSPACE = TASK.parents[2]
PRIVATE = TASK / "private"
assert not PRIVATE.exists(), "Preservation already exists; inspect it instead of replacing originals"
PRIVATE.mkdir(mode=0o700)
raw = PRIVATE / "raw"
raw.mkdir()
originals = ["report.md", "evidence/audit-first.txt", "evidence/instruction-contract.txt",
             "evidence/pytest-instruction-contract.txt", "evidence/python-environment.txt",
             "artifact-sha256.json"]
entries = []
for name in originals:
    body = (TASK / name).read_bytes()
    destination = raw / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    assert destination.read_bytes() == body
    entries.append({"original": name, "preserved": str(destination.relative_to(TASK)),
                    "kind": "file", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
fixtures = TASK / "pytest-tmp"
assert fixtures.is_dir()
shutil.move(str(fixtures), str(PRIVATE / "pytest-tmp"))
for base, directories, files in os.walk(PRIVATE / "pytest-tmp", followlinks=False):
    for name in sorted(directories + files):
        path = Path(base) / name
        if path.is_symlink():
            body = os.fsencode(os.readlink(path))
            kind = "symlink-target"
        elif path.is_file():
            body = path.read_bytes()
            kind = "file"
        else:
            continue
        relative = path.relative_to(PRIVATE)
        entries.append({"original": str(relative), "preserved": str(path.relative_to(TASK)),
                        "kind": kind, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
manifest = {"format": 1, "meaning": "SHA256 and bytes of preserved file content, or symlink target bytes; no symlink target text published",
            "entries": entries}
serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
(PRIVATE / "preservation-manifest.json").write_text(serialized)
(TASK / "preservation-manifest.json").write_text(serialized)
for name in originals[:-1]:
    body = (raw / name).read_text()
    body = body.replace(str(WORKSPACE), "/home/<hub-user>/<hub-workspace>")
    body = body.replace(str(Path.home()), "/home/<hub-user>")
    notice = ("PUBLIC DERIVATIVE: native hub paths replaced by <hub-user>/<hub-workspace>; "
              "not verbatim. Original bytes are preserved under ignored private/raw; "
              "see preservation-manifest.json.\n\n")
    (TASK / name).write_text(notice + body)
print("preserved raw files:", len(originals))
print("preserved fixture regular files:", sum(e["kind"] == "file" for e in entries[len(originals):]))
print("preserved fixture symlinks:", sum(e["kind"] == "symlink-target" for e in entries))
print("labelled public derivatives:", len(originals) - 1)
print("public receipt: preservation-manifest.json; originals: ignored private/")
