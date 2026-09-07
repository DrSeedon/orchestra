"""Mechanical completeness gate for research.md: every cited artifact and anchor must resolve.

Checks, all read-only:
1. every `raw/<file>` cited in research.md exists;
2. every table row's `repo` + `file:line` is present in the corresponding raw/rg-<repo>.txt;
3. the per-scope counts in the prose match raw/final-counts-and-markers.txt.
Exit 1 on the first non-empty failure list.
"""
import re
from pathlib import Path

TASK = Path(__file__).parent
report = (TASK / "research.md").read_text(encoding="utf-8")
failures: list[str] = []

# `raw/rg-<имя>.txt` is a template, not a citation; `orchestra-ro.db` is the deleted DB copy
# whose deletion the report states explicitly.
cited = sorted({
    m.group(0) for m in re.finditer(r"raw/[A-Za-z0-9_.\-]+", report)
    if report[m.end():m.end() + 1] not in "<*" and not m.group(0).endswith("orchestra-ro.db")
})
for rel in cited:
    if not (TASK / rel).exists():
        failures.append(f"cited artifact missing: {rel}")

rows = re.findall(r"^\| (orchestra|katya-work|kesha-tg-bot|kesha-bot) \| `([^`]+):(\d+)`", report, re.M)
roots = {
    "orchestra": "/home/kesha/orchestra",
    "katya-work": "/home/kesha/katya-work",
    "kesha-tg-bot": "/home/kesha/projects/kesha-tg-bot",
    "kesha-bot": "/opt/kesha-bot",
}
for repo, rel, line in rows:
    hits = (TASK / "raw" / f"rg-{repo}.txt").read_text(encoding="utf-8", errors="replace")
    anchor = f"{roots[repo]}/{rel}:{line}:"
    if anchor not in hits:
        failures.append(f"table row not backed by rg output: {repo} {rel}:{line}")

counts = (TASK / "raw" / "final-counts-and-markers.txt").read_text(encoding="utf-8")
measured = dict(
    (m.group(1), (int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"^(\S+) total=(\d+) outside_task_artifacts=(\d+)$", counts, re.M)
)
for m in re.finditer(r"^\| `?([^|`]+?)`? \| [^|]+ \| да \| (\d+) \| (\d+) \|$", report, re.M):
    name = m.group(1).strip().rstrip("/").split("/")[-1]
    if name not in measured:
        failures.append(f"scope row has no measured counts: {name}")
    elif measured[name] != (int(m.group(2)), int(m.group(3))):
        failures.append(
            f"count mismatch for {name}: report={(int(m.group(2)), int(m.group(3)))} "
            f"measured={measured[name]}"
        )

print(f"cited_artifacts={len(cited)} table_rows={len(rows)} scopes_measured={len(measured)}")
for item in failures:
    print("FAIL:", item)
print("RESULT=" + ("clean" if not failures else f"{len(failures)} failures"))
raise SystemExit(1 if failures else 0)
