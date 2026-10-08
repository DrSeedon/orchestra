import collections
import json
import re
import sqlite3
from pathlib import Path

from app.backend_claude import (
    _BASH_CLASSIFIER_MAX_BYTES,
    _classify_bash_payload,
    _classify_unparsed_bash,
)


START = "2026-10-01T08:42:47+00:00"
END = "2026-10-08T08:42:47+00:00"
DATABASE = "/home/kesha/orchestra/data/orchestra.db"


def main():
    db = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    rows = db.execute(
        "select l.ts,l.content,s.cwd from logs l left join sessions s on s.id=l.session_id "
        "where l.ts >= ? and l.ts < ? "
        "and l.type='tool' and lower(coalesce(l.tool_name,''))='bash'",
        (START, END),
    )
    counts = collections.Counter()
    new_signatures = collections.Counter()
    unparseable = parsed = total = 0
    for _ts, content, cwd in rows:
        total += 1
        try:
            payload = json.loads(content.partition(": ")[2])
        except Exception:
            unparseable += 1
            continue
        command = payload.get("command") if isinstance(payload, dict) else None
        if not isinstance(command, str):
            continue
        parsed += 1
        if len(command.encode("utf-8", errors="replace")) > _BASH_CLASSIFIER_MAX_BYTES:
            classification = "command_too_large"
        else:
            try:
                classification = _classify_bash_payload(payload, cwd=cwd)
            except Exception:
                classification = _classify_unparsed_bash(command)
        if classification:
            counts[classification] += 1
            if classification == "find_delete":
                find_command = re.search(r"(?:^|[;&|]\s*)(find\b[^;&|\n]*)", command)
                signature = "find <target> [options] -delete"
                if find_command and "-name '*.jpg'" in find_command.group(1):
                    signature = "find <target> -name '*.jpg' -delete"
                new_signatures[(classification, signature)] += 1
            elif classification == "unparsed_rm":
                new_signatures[(classification, "rm -i <selected files> <<< y")] += 1
            elif classification == "rmdir_parents":
                new_signatures[(classification, "rmdir -p <path outside the session worktree>")] += 1
            elif classification not in {"recursive_rm", "regex_blowup", "world_writable", "curl_pipe_shell"}:
                new_signatures[(classification, classification)] += 1

    output = Path(__file__).with_name("weekly-bash-blocks.md")
    with output.open("w") as f:
        f.write(
            f"# Bash-команды, которые блокировал бы новый классификатор\n\n"
            f"Окно UTC: {START} — {END}. Bash rows: {total}; разобрано command: "
            f"{parsed}; неразобранный content: {unparseable}. Полные tool payloads "
            "не выгружаются в отчёт; список ниже содержит только сигнатуры новых правил.\n\n"
        )
        f.write("Классификация и число вызовов:\n")
        for name, count in sorted(counts.items()):
            f.write(f"- {name}: {count}\n")
        f.write("\nНовые блокируемые сигнатуры с числом вызовов:\n")
        for (name, signature), count in sorted(new_signatures.items()):
            f.write(f"- {name} × {count}: {signature}\n")
    print(
        json.dumps(
            {
                "window_utc": [START, END],
                "bash_rows": total,
                "parsed_commands": parsed,
                "unparseable_log_payloads": unparseable,
                "would_block_calls": sum(counts.values()),
                "new_rule_signatures": len(new_signatures),
                "classification_counts": counts,
                "analysis_file": str(output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
