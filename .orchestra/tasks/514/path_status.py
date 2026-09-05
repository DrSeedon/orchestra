"""Read-only: for every rg hit line, extract the old docs/ path literal and stat it.

Input: raw/rg-<name>.txt files produced by the mandated rg command.
Output: TSV on stdout — repo, file, line, old_path, old_exists, orchestra_analog_exists.
Nothing is written outside this task directory.
"""
import re
import sys
from pathlib import Path

RAW = Path(__file__).parent / "raw"
OLD = re.compile(r"docs/(?:tasks|kb|workers|pipelines)[^\s\"'`,)\]}]*")

REPOS = {
    "orchestra": "/home/kesha/orchestra",
    "katya-work": "/home/kesha/katya-work",
    "kesha-tg-bot": "/home/kesha/projects/kesha-tg-bot",
    "seedon": "/home/kesha/projects/seedon",
    "cog-second-brain": "/opt/cog-second-brain",
    "kesha-bot": "/opt/kesha-bot",
    "VPN-Service": "/home/kesha/projects/VPN-Service",
    "dnd-game-master": "/home/kesha/projects/dnd-game-master",
    "University": "/home/kesha/projects/University",
}

print("repo\tfile\tline\told_path\told_exists\torchestra_analog_exists")
for name, root in REPOS.items():
    src = RAW / f"rg-{name}.txt"
    if not src.exists():
        continue
    rootp = Path(root)
    for raw_line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        head, sep, text = raw_line.partition(":")
        if not sep:
            continue
        lineno, sep2, body = text.partition(":")
        if not sep2 or not lineno.isdigit():
            continue
        rel = str(Path(head).relative_to(rootp)) if head.startswith(root) else head
        for m in OLD.finditer(body):
            old = m.group(0).rstrip(".")
            analog = ".orchestra/" + old[len("docs/"):]
            print(
                f"{name}\t{rel}\t{lineno}\t{old}\t"
                f"{(rootp / old).exists()}\t{(rootp / analog).exists()}"
            )
