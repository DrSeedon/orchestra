"""Mechanical completeness checks for the README status table (#511).

Run: python3 .orchestra/tasks/511/check_table.py
Exit 0 = all checks pass. Every failure prints the offending row.
"""
import pathlib, re, subprocess, sys

root = pathlib.Path(__file__).resolve().parents[3]
text = (root / "README.md").read_text()

block = text.split("<a id=\"comparison\"></a>")[1].split("## Features")[0]
rows = [r for r in block.split("\n") if r.startswith("|") and not set(r) <= set("|- ")]
status_rows = [r for r in rows if r.count("|") == 4][1:]  # drop header

fail = []

# 1. every row carries exactly one of the three statuses, никогда прочерк
for r in status_rows:
    cells = [c.strip() for c in r.strip("|").split("|")]
    marks = [m for m in ("✅", "🚧", "🚫") if m in cells[1]]
    if len(marks) != 1:
        fail.append(f"status not exactly one of ✅/🚧/🚫: {cells[0][:60]}")
    if cells[2] in ("", "-", "—"):
        fail.append(f"empty anchor: {cells[0][:60]}")

# 2. banned formulations
for banned in ("5 593", "5593", "ahead of Orca", "beats Orca", "better than Orca"):
    if banned in block:
        fail.append(f"banned string present: {banned!r}")

# 3. every file:line anchor resolves and the file is non-empty at that line
for path, line in set(re.findall(r"`(app/[\w/]+\.py):(\d+)`", block)):
    f = root / path
    if not f.exists():
        fail.append(f"missing file {path}")
        continue
    lines = f.read_text().split("\n")
    if int(line) > len(lines) or not lines[int(line) - 1].strip():
        fail.append(f"anchor {path}:{line} points at nothing")

# 4. bare file anchors exist
for path in set(re.findall(r"`(app/[\w/]+\.py)`", block)):
    if not (root / path).exists():
        fail.append(f"missing file {path}")

# 5. the review claim in the table must stay true
out = subprocess.run(["grep", "-c", "review", "app/merge_operations.py"],
                     cwd=root, capture_output=True, text=True).stdout.strip()
if out != "0":
    fail.append(f"README claims `grep -c review app/merge_operations.py` -> 0, actual {out}")

# 6. the CLAUDE.md size claim must match reality
size = (root / "CLAUDE.md").stat().st_size
if f"{size:,}".replace(",", " ") not in block:
    fail.append(f"CLAUDE.md is {size} bytes, README states another number")

print(f"rows checked: {len(status_rows)}")
for f_ in fail:
    print("FAIL:", f_)
sys.exit(1 if fail else 0)
