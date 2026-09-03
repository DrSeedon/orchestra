"""#27 — СУХОЙ ПРОГОН уборки веток adhoc-*. Ничего не удаляет и не может удалить.

Печатает по каждой ветке вердикт и ПРИЧИНУ. Удаление — решение человека по этому списку.

Критерии «безопасно к удалению» (все одновременно):
  1. не выкачена ни в одном worktree;
  2. на неё не ссылается неархивная сессия в БД;
  3. содержимое доказано в базовой ветке ПО ДЕРЕВЬЯМ (`git merge-tree --write-tree`),
     а не по `--is-ancestor`: у нас squash-мержи, и предок после squash не сохраняется;
  4. последний коммит старше 14 суток — заведомо больше прежнего цикла имён 11.57 суток.

Запуск: uv run python docs/tasks/27/adhoc-cleanup-dryrun.py [repo] [base]
"""
import subprocess
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

REPO = sys.argv[1] if len(sys.argv) > 1 else "/home/kesha/orchestra"
BASE = sys.argv[2] if len(sys.argv) > 2 else "main"
DB = "/home/kesha/orchestra/data/orchestra.db"
AGE_LIMIT = timedelta(days=14)


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def checked_out_branches():
    out = git("worktree", "list", "--porcelain").stdout
    return {line.split("refs/heads/")[-1].strip()
            for line in out.splitlines() if line.startswith("branch ")}


def live_session_branches():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT branch FROM sessions WHERE COALESCE(status,'') != 'archived' AND branch != ''"
    ).fetchall()
    con.close()
    return {r[0] for r in rows}


def content_is_in_base(branch):
    """Дерево слияния base+branch совпадает с деревом base → содержимое уже в базе."""
    merged = git("merge-tree", "--write-tree", BASE, branch)
    if merged.returncode not in (0, 1):
        return None, f"merge-tree не отработал: {merged.stderr.strip()[:60]}"
    if merged.returncode == 1:
        return False, "конфликт с базой"
    tree = merged.stdout.splitlines()[0].strip()
    base_tree = git("rev-parse", "--verify", f"{BASE}^{{tree}}").stdout.strip()
    result_tree = git("rev-parse", "--verify", f"{tree}^{{tree}}").stdout.strip()
    return (result_tree == base_tree), ""


def main():
    checked_out = checked_out_branches()
    live = live_session_branches()
    branches = [b.strip() for b in git(
        "branch", "--list", "adhoc-*", "--format=%(refname:short)").stdout.splitlines() if b.strip()]
    now = datetime.now(timezone.utc)
    safe, kept = [], []
    for b in branches:
        reasons = []
        if b in checked_out:
            reasons.append("выкачена в worktree")
        if b in live:
            reasons.append("на неё ссылается живая сессия")
        in_base, err = content_is_in_base(b)
        if err:
            reasons.append(err)
        elif not in_base:
            reasons.append("содержимого нет в базе (несмерженная работа)")
        when = git("log", "-1", "--format=%cI", b).stdout.strip()
        age = None
        if when:
            age = now - datetime.fromisoformat(when)
            if age < AGE_LIMIT:
                reasons.append(f"моложе 14 суток ({age.days} сут)")
        else:
            reasons.append("дата последнего коммита недоступна")
        line = f"  {b:36} {('возраст ' + str(age.days) + ' сут') if age else 'возраст ?':>16}"
        if reasons:
            kept.append(f"{line}  ← {'; '.join(reasons)}")
        else:
            safe.append(line)

    print(f"Репозиторий {REPO}, база {BASE}, веток adhoc-*: {len(branches)}\n")
    print(f"НЕ трогать ({len(kept)}):")
    print("\n".join(kept) or "  —")
    print(f"\nКандидаты на удаление ({len(safe)}) — удаление НЕ выполняется:")
    print("\n".join(safe) or "  —")
    print("\nЭтот скрипт не удаляет ветки. Решение — человеческое, по списку выше.")


main()
