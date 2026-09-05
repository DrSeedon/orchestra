"""Классификация вызовов по содержимому команды.

ПРАВИЛО ОТНЕСЕНИЯ (дословно, для перепроверки):
  Класс определяется ПЕРВЫМ сработавшим правилом из списка ниже, сверху вниз.
  Проверка идёт по строке команды, приведённой к нижнему регистру, с схлопнутыми
  пробелами. Ни одна команда не попадает в два класса.

   1 llm-cli     : есть 'claude -p' | 'codex exec' | 'codex_review' | 'gemini -' | ' llm '
   2 deps        : есть 'pip install' | 'uv sync' | 'uv pip' | 'npm install' | 'npm ci'
                   | 'apt-get' | 'apt install' | 'playwright install' | 'uv venv'
   3 tests       : есть 'pytest' | 'jest' | 'vitest' | 'go test' | 'unittest' | 'npm test'
   4 media       : есть 'ffmpeg' | 'pdftoppm' | 'pdftotext' | 'yt-dlp' | 'imagemagick'
                   | 'convert -' | 'magick '
   5 wait-loop   : есть 'sleep ' (как отдельное слово) ИЛИ ('pgrep' И 'seq ')
   6 net         : есть 'curl ' | 'wget ' | 'ssh ' | 'nc -' | 'git clone' | 'git fetch'
                   | 'git push' | 'git pull' | 'http://' | 'https://'
   7 git         : есть 'git ' (остальные, локальные операции)
   8 inline-code : есть 'python3 -c' | 'python -c' | "<<'py'" | '<<py' | "<<'eof'"
                   | 'python3 - <<' | 'python - <<' | 'node -e' | 'sqlite3 ' с '<<'
   9 search-read : есть 'rg ' | 'grep' | 'cat ' | 'head ' | 'tail ' | 'find ' | 'ls '
                   | 'wc -' | 'sed -n' | 'awk ' | 'jq '
  10 other       : всё остальное

  Порядок выбран так, чтобы САМАЯ ДОРОГАЯ по природе часть составной команды
  забирала строку: `timeout 500 uv run pytest ... > log` -> tests, а не search-read;
  `sleep 420; grep ...` -> wait-loop, а не search-read.
  Известное следствие порядка: `ssh ... 'pytest'` уходит в tests (правило 3 раньше 6),
  а `for i in $(seq 1 11); do ... pytest ...` — тоже в tests, а не в wait-loop.
  Пересечения классов посчитаны отдельно (raw/13-class-overlap.txt).
"""
import re
import sqlite3
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DBF = os.path.join(HERE, "..", "raw", "calls.sqlite")

RULES = [
    ("llm-cli", ["claude -p", "codex exec", "codex_review", "gemini -", " llm "]),
    ("deps", ["pip install", "uv sync", "uv pip", "npm install", "npm ci",
              "apt-get", "apt install", "playwright install", "uv venv"]),
    ("tests", ["pytest", "jest", "vitest", "go test", "unittest", "npm test"]),
    ("media", ["ffmpeg", "pdftoppm", "pdftotext", "yt-dlp", "imagemagick",
               "convert -", "magick "]),
    ("wait-loop", ["__SLEEP__", "__PGREP_SEQ__"]),
    ("net", ["curl ", "wget ", "ssh ", "nc -", "git clone", "git fetch",
             "git push", "git pull", "http://", "https://"]),
    ("git", ["git "]),
    ("inline-code", ["python3 -c", "python -c", "<<'py", "<<py", "<<'eof",
                     "python3 - <<", "python - <<", "node -e"]),
    ("search-read", ["rg ", "grep", "cat ", "head ", "tail ", "find ", "ls ",
                     "wc -", "sed -n", "awk ", "jq "]),
]

SLEEP_RE = re.compile(r"\bsleep\s")


def classify(cmd):
    s = re.sub(r"\s+", " ", cmd.lower())
    for name, pats in RULES:
        for p in pats:
            if p == "__SLEEP__":
                if SLEEP_RE.search(s):
                    return name
            elif p == "__PGREP_SEQ__":
                if "pgrep" in s and "seq " in s:
                    return name
            elif p in s:
                return name
    return "other"


def main():
    c = sqlite3.connect(DBF)
    try:
        c.execute("alter table calls add column cls text")
    except sqlite3.OperationalError:
        pass
    rows = list(c.execute("select tool_id, tool_name, cmd from calls"))
    upd = []
    for tid, name, cmd in rows:
        if name in ("Bash", "bash", "run_terminal_command"):
            upd.append((classify(cmd) if cmd else "other", tid))
        else:
            upd.append(("nonbash:" + name, tid))
    c.executemany("update calls set cls=? where tool_id=?", upd)
    c.execute("create index if not exists i4 on calls(cls)")
    c.commit()
    print("classified:", len(upd))


if __name__ == "__main__":
    main()
