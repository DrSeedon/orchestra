"""V-613: сколько DONE-отчётов воркеров ушли без прошедшей проверки после последней правки кода.

Считаем по снимку orchestra.db (backup()). Окно = от предыдущего DONE этой сессии (или начала)
до текущего DONE. Правка кода = Edit/Write/MultiEdit/NotebookEdit/FileChange/apply_patch/edit
по файлу с кодовым расширением. Проверка = Bash/bash-команда из списка ниже, результат без ошибки.
"""
import json, re, sqlite3, sys
from collections import Counter

DB = sys.argv[1]
CODE = re.compile(r"\.(py|js|mjs|cjs|ts|tsx|jsx|css|html|sh|go|rs|sql|java|kt|swift|c|cc|cpp|h|rb|php|vue|svelte)$")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "FileChange", "apply_patch", "edit", "write_file", "file"}
SHELL = {"Bash", "bash", "run_terminal_command", "shell"}
CHECK = re.compile(r"\b(pytest|unittest|npm (run )?test|pnpm (run )?test|yarn test|vitest|jest|tsc\b|ruff|eslint|mypy|pyright|go test|cargo (test|check|build)|node --test|playwright test|make (test|check)|py_compile|check_instruction_contract|npm run (build|lint|check)|node --check)")
SHELL_WRITE = re.compile(r"(sed -i|cat\s*>|tee\s|>\s*\S+\.(py|js|ts|css|html|sh))")

def name_of(row):
    n = row["tool_name"]
    if n:
        return n
    c = row["content"]
    i = c.find(":")
    return c[:i] if 0 < i < 60 else ""

def paths(name, content):
    body = content.split(":", 1)[1] if ":" in content else content
    if name == "file":
        return [body.strip().split(" ", 1)[-1]]
    try:
        d = json.loads(body)
    except Exception:
        return re.findall(r'"(?:file_path|path|notebook_path)":\s*"([^"]+)"', body)
    if isinstance(d, dict):
        if "changes" in d:
            return [ch.get("path", "") for ch in d["changes"] if isinstance(ch, dict)]
        for k in ("file_path", "path", "notebook_path"):
            if k in d:
                return [d[k]]
    return []

def command(content):
    body = content.split(":", 1)[1] if ":" in content else content
    try:
        d = json.loads(body)
        return d.get("command", "") if isinstance(d, dict) else str(d)
    except Exception:
        return body

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
sessions = {r["id"]: dict(r) for r in conn.execute("select id,name,scope,role,is_orchestrator,backend_type from sessions")}
stats = Counter()
examples = []
by_backend = Counter()
for sid, s in sessions.items():
    if s["is_orchestrator"]:
        continue
    rows = conn.execute(
        "select id,ts,type,content,tool_use_id,tool_name,tool_is_error from logs where session_id=? and type in ('tool','tool_result') order by id",
        (sid,),
    ).fetchall()
    results = {}
    for i, r in enumerate(rows):
        if r["type"] == "tool_result" and r["tool_use_id"]:
            results[r["tool_use_id"]] = r
    last_edit = None; checked_after = False; strict_after = False; edited_orch_only = True; last_paths = []
    for i, r in enumerate(rows):
        if r["type"] != "tool":
            continue
        n = name_of(r)
        if n in EDIT_TOOLS:
            ps = [p for p in paths(n, r["content"]) if CODE.search(p or "")]
            if ps:
                last_edit = r; checked_after = False; strict_after = False
                last_paths = ps
                edited_orch_only = edited_orch_only and all("/.orchestra/" in p for p in ps)
        elif n in SHELL:
            cmd = command(r["content"])
            if SHELL_WRITE.search(cmd) and CODE.search(cmd.split()[-1] if cmd.split() else ""):
                last_edit = last_edit or r
            if CHECK.search(cmd):
                res = results.get(r["tool_use_id"]) if r["tool_use_id"] else None
                if res is None and i + 1 < len(rows) and rows[i + 1]["type"] == "tool_result":
                    res = rows[i + 1]
                ok = res is not None and not res["tool_is_error"]
                if ok:
                    checked_after = True
                    if not re.search(r"\|\s*(tail|head|grep)|\|\|\s*true|;\s*echo", cmd):
                        strict_after = True
        elif n == "mcp__orchestra__send_message":
            body = r["content"]
            m = re.search(r'"message":\s*"(DONE[^"]{0,80})', body)
            if not m:
                continue
            stats["done_total"] += 1
            by_backend[(s["backend_type"], "done")] += 1
            if last_edit is None:
                stats["done_no_code_edit"] += 1
            else:
                stats["done_with_code_edit"] += 1
                by_backend[(s["backend_type"], "edit")] += 1
                if edited_orch_only:
                    stats["edit_only_in_.orchestra"] += 1
                if not checked_after:
                    stats["no_check_after_last_edit"] += 1
                    by_backend[(s["backend_type"], "nocheck")] += 1
                    if any('/.orchestra/' not in p and '/docs/' not in p for p in last_paths):
                        stats['no_check_last_edit_outside_orchestra_docs'] += 1
                    examples.append((s["scope"].split("/")[-1], s["name"], r["ts"][:16], m.group(1)[:70]))
                if not strict_after:
                    stats["no_strict_check_after_last_edit"] += 1
            last_edit = None; checked_after = False; strict_after = False; edited_orch_only = True
print(dict(stats))
print(dict(by_backend))
print("scopes of no-check:", Counter(e[0] for e in examples).most_common(10))
for e in examples[-15:]:
    print(e)

if len(sys.argv) > 2:
    print("orchestra no-check examples:")
    for e in examples:
        if e[0] == "orchestra":
            print(e)
