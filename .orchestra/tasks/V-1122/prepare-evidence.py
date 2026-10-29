"""Line-preserving omission of upstream personal example paths in retained data.

This edits research snapshots only, never source files or fetched code execution.
Original numbered-output hashes and omitted line numbers are retained for audit.
"""

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(".orchestra/tasks/V-1122/evidence")
records = []
for path in sorted((ROOT / "public-code").glob("*.txt")):
    original = path.read_bytes()
    omissions = []
    lines = original.decode().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+", line):
            number = line.split("\t", 1)[0]
            lines[index] = number + "\t[omitted: upstream personal/example home path]\n"
            omissions.append(index + 1)
    if omissions:
        path.write_text("".join(lines))
    records.append({
        "file": path.name,
        "original_numbered_sha256": hashlib.sha256(original).hexdigest(),
        "retained_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "omitted_lines": omissions,
    })
print(json.dumps(records, indent=2))
