"""Разбор одного прогона A/B #77 → одна TSV-строка.

Идиому отката берём ТОЛЬКО из аргументов инструментов (Bash.command, Edit/Write),
никогда из текста ассистента: текст цитирует само правило, в котором `git show`
и `git stash` присутствуют, и grep по всему транскрипту даёт ложные срабатывания
(поймано на пилоте a-0).
"""

import json
import re
import sys
from pathlib import Path

run = Path(sys.argv[1])
arm, no = sys.argv[2], sys.argv[3]

cmds: list[str] = []
edits = 0
for line in (run / "transcript.jsonl").read_text(errors="replace").splitlines():
    try:
        d = json.loads(line)
    except ValueError:
        continue
    msg = d.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, list):
        continue
    for c in content:
        if c.get("type") != "tool_use":
            continue
        if c["name"] == "Bash":
            cmds.append(c["input"].get("command", ""))
        elif c["name"] in ("Edit", "Write", "NotebookEdit"):
            edits += 1

blob = "\n".join(cmds)
idiom = [
    name
    for name, pat in (
        ("checkout", r"git checkout"),
        ("show", r"git show \S+:"),
        ("stash", r"git stash"),
        ("commit", r"git commit"),
        ("cp/mv", r"(^|\s|&&|;)(cp|mv)\s"),
    )
    if re.search(pat, blob, re.M)
]

tests_run = sum(1 for c in cmds if "run_tests" in c or "pytest" in c)
saw_red = int(bool(re.search(r"\bfailed\b", (run / "transcript.jsonl").read_text(errors="replace"))))
lost = int((run / ".ab_lost").exists())
guard = (run / "app/guard.py").read_text(errors="replace")
final_anchor = int("MYFIX-ANCHOR" in guard)
final_fix = int("if not text:" in guard)

leftover = int(bool(list(run.rglob("*.bak")) + list(run.rglob("*.orig"))))

print(
    "\t".join(
        [
            arm,
            no,
            f"lost={lost}",
            f"bak={leftover}",
            f"anchor={final_anchor}",
            f"fix={final_fix}",
            f"tests={tests_run}",
            f"red={saw_red}",
            f"edits={edits}",
            "idiom=" + (",".join(idiom) or "none"),
        ]
    )
)
