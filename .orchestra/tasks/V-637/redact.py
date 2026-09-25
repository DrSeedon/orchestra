"""Mask secret-looking values in raw logs before commit (an audit worker's `ps e` dumped real env keys)."""
import re, sys
from pathlib import Path
PAT = re.compile(r"((?:[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS)[A-Z0-9_]*)=)[^\s\\\"']{6,}")
for p in Path(sys.argv[1]).rglob("*.json"):
    s = p.read_text(); n = PAT.sub(r"\1<redacted>", s)
    if n != s:
        p.write_text(n); print("redacted", p)
