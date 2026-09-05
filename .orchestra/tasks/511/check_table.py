"""Mechanical completeness checks for the README status table (#511).

Run: python3 .orchestra/tasks/511/check_table.py
Exit 0 = all checks pass. Every failure prints the offending row.
"""
import pathlib, re, subprocess, sys

root = pathlib.Path(__file__).resolve().parents[3]

# Both showcase versions are checked. `README.ru.md` (#512) carries the same table with the
# same anchors; a guard that only ever read the English file would let the Russian one rot
# into a second, quietly disagreeing owner.
VERSIONS = {"README.md": "## Features", "README.ru.md": "## Возможности"}

text = (root / "README.md").read_text()
block = text.split("<a id=\"comparison\"></a>")[1].split("## Features")[0]
rows = [r for r in block.split("\n") if r.startswith("|") and not set(r) <= set("|- ")]
# The status table is the one before the first `###` subsection. Selecting it by column
# count alone was wrong: the head-to-head table added in #512 also has three columns, so
# every one of its rows was demanded to carry ✅/🚧/🚫 and the whole check went red.
status_block = block.split("\n### ")[0]
status_rows = [r for r in status_block.split("\n")
               if r.startswith("|") and not set(r) <= set("|- ") and r.count("|") == 4][1:]

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

# 3. every file:line anchor resolves AND the named symbol is really there.
# A non-blank line proves nothing: code moves, and a stale anchor lands on some other
# non-blank line while the README keeps citing it as proof. Measured 2026-09-05 (#512):
# 8 of the 17 anchors in this section had drifted and this script passed on all of them.
# So the rule is: the row must name at least one backticked symbol/literal, and that
# token must appear within ±2 lines of the anchor. Known limit — one token of the row
# satisfying one of the row's anchors is enough, so a row whose tokens are substrings of
# each other is checked more weakly than a row with distinct ones.
ANCHOR_RE = re.compile(r"`((?:app|scripts)/[\w/]+\.(?:py|js)):(\d+)`")


def row_tokens(row: str) -> list[str]:
    """Backticked pieces of a row that are candidates for a symbol, not paths."""
    out = []
    for tok in re.findall(r"`([^`]+)`", row):
        if ANCHOR_RE.fullmatch(f"`{tok}`") or re.fullmatch(r"[\w/]+\.(py|js|md)", tok):
            continue
        out.append(tok)
    return out


def comparison_block(name: str) -> str:
    body = (root / name).read_text()
    return body.split("<a id=\"comparison\"></a>")[1].split(VERSIONS[name])[0]


all_rows = []
for name in VERSIONS:
    for row in comparison_block(name).split("\n"):
        if row.startswith("|") and not set(row) <= set("|- "):
            all_rows.append((name, row))

for name, row in all_rows:
    anchors = ANCHOR_RE.findall(row)
    if not anchors:
        continue
    tokens = row_tokens(row)
    for path, line in anchors:
        f = root / path
        if not f.exists():
            fail.append(f"{name}: missing file {path}")
            continue
        lines = f.read_text().split("\n")
        n = int(line)
        if n > len(lines) or not lines[n - 1].strip():
            fail.append(f"{name}: anchor {path}:{line} points at nothing")
            continue
        if not tokens:
            fail.append(f"{name}: anchor {path}:{line} cites a line but the row names no symbol")
            continue
        window = "\n".join(lines[max(0, n - 3):n + 2])
        if not any(tok in window for tok in tokens):
            fail.append(
                f"{name}: anchor {path}:{line} supports none of the row's symbols {tokens}; "
                f"line reads: {lines[n - 1].strip()[:70]!r}"
            )

# 4. bare file anchors exist
for path in set(re.findall(r"`(app/[\w/]+\.py)`", block)):
    if not (root / path).exists():
        fail.append(f"missing file {path}")

# 5. the review claim must stay true: the merge path refuses without coverage.
out = subprocess.run(["grep", "-c", "RECORD_REVIEW_THEN_NEW_OPERATION", "app/merge_operations.py"],
                     cwd=root, capture_output=True, text=True).stdout.strip()
if out == "0":
    fail.append("README claims merge refuses without a review receipt; the marker is gone")

# 6. The bounded-startup claim counts both the owner and its native Claude adapter.
# The pilot was about 10 KiB; 16 KiB allows edits while catching re-injection of the archive.
size = sum((root / name).stat().st_size for name in ("AGENTS.md", "CLAUDE.md"))
if size >= 16 * 1024:
    fail.append(f"shared startup instructions exceed documented 16 KiB: {size} bytes")
if "@AGENTS.md" not in (root / "CLAUDE.md").read_text().splitlines():
    fail.append("CLAUDE.md no longer imports the shared instruction owner")

# 7. the two versions must cite the SAME anchors — one showcase, not two.
anchor_sets = {n: set(ANCHOR_RE.findall(comparison_block(n))) for n in VERSIONS}
en, ru = anchor_sets["README.md"], anchor_sets["README.ru.md"]
for missing in sorted(en - ru):
    fail.append(f"README.ru.md is missing anchor {missing[0]}:{missing[1]} that README.md cites")
for extra in sorted(ru - en):
    fail.append(f"README.ru.md cites anchor {extra[0]}:{extra[1]} that README.md does not")

# 8. the language switch must work in both directions.
if 'href="README.ru.md"' not in text:
    fail.append("README.md has no link to the Russian version")
if 'href="README.md"' not in (root / "README.ru.md").read_text():
    fail.append("README.ru.md has no link back to the English version")

print(f"rows checked: {len(status_rows)}; anchors checked: "
      f"{sum(len(v) for v in anchor_sets.values())} across {len(VERSIONS)} versions")
for f_ in fail:
    print("FAIL:", f_)
sys.exit(1 if fail else 0)
