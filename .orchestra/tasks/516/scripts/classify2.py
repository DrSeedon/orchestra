"""Классификатор v2 — по СЕГМЕНТАМ команды, а не по подстроке во всей строке.

Зачем v2. Классификатор v1 относил к классу любую команду, где слово встречалось
где угодно: `rg -n 'pytest' .github/workflows/ci.yml` попадал в 'tests', а
`ps -eo cmd | rg '[p]ytest'` — тоже. Замер контаминации: из 988 команд, отнесённых
v1 к полным прогонам, 559 длились меньше 5 секунд, то есть pytest в них НЕ
запускался (raw/15-fullsuite-samples.txt). Медиана класса из-за этого была ложной.

ПРАВИЛО ОТНЕСЕНИЯ v2 (дословно, для перепроверки):

  Шаг 1. Разворачиваем обёртку: ведущее `/bin/bash -lc '...'`, `/bin/bash -c "..."`,
         `bash -lc ...` снимается вместе с внешними кавычками.
  Шаг 2. Режем команду на СЕГМЕНТЫ по разделителям `;`  `&&`  `||`  `|`  и переводу
         строки. Сегмент — это одна исполняемая команда конвейера.
  Шаг 3. У каждого сегмента находим ГОЛОВУ — первое слово, которое не является:
         присваиванием переменной (`VAR=...`), ключевым словом оболочки
         (`do then else fi done if for while set cd exec time`), обёрткой запуска
         (`timeout <N>`, `nice -n <N>`, `env`, `sudo`, `xargs`, `command`, `stdbuf`),
         или менеджером окружения (`uv`, `uvx`, `poetry`, `npx`, `pdm`, `hatch`
         вместе с их флагами `run --frozen --active --no-project --with ...`).
         Из головы берём базовое имя файла: `/opt/py312/bin/python` -> `python`.
  Шаг 4. Голова + аргументы сегмента дают КЛАСС СЕГМЕНТА по таблице SEG_RULES.
         `python -m pytest` и `pytest` -> tests; `git` -> git/net по подкоманде;
         `rg|grep|cat|...` -> search-read; и т.д.
  Шаг 5. Класс вызова = сегментный класс с НАИВЫСШИМ приоритетом (список PRIORITY,
         сверху вниз). Слово внутри аргументов чужого сегмента (`rg 'pytest'`)
         классом больше не становится — это и есть исправление v1.
"""
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DBF = os.path.join(HERE, "..", "raw", "calls.sqlite")

WRAP = re.compile(r"^\s*(?:/bin/)?(?:ba)?sh\s+-[lic]*c\s+(['\"])(.*)\1\s*$", re.S)
SPLIT = re.compile(r"\s*(?:\|\||&&|[;|\n])\s*")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_KW = {"do", "then", "else", "elif", "fi", "done", "if", "for", "while", "set",
            "cd", "exec", "time", "{", "}", "(", ")", "!", "eval", "local", "export"}
WRAPPERS = {"timeout", "nice", "env", "sudo", "xargs", "command", "stdbuf", "nohup",
            "ionice", "unbuffer"}
ENVMGR = {"uv", "uvx", "poetry", "npx", "pdm", "hatch", "pipenv", "conda"}
ENVMGR_FLAG = re.compile(r"^(?:run|exec|--\S+|-\w)$")

SEARCH = {"rg", "grep", "egrep", "fgrep", "ag", "ack", "cat", "head", "tail", "less",
          "find", "ls", "wc", "sed", "awk", "jq", "nl", "sort", "uniq", "cut", "tr",
          "column", "diff", "stat", "du", "tree", "file", "strings", "xxd", "od"}
NETCMD = {"curl", "wget", "ssh", "scp", "rsync", "nc", "ncat", "telnet", "dig",
          "host", "nslookup", "ping", "sftp", "http", "httpie"}
MEDIA = {"ffmpeg", "ffprobe", "pdftoppm", "pdftotext", "pdfinfo", "yt-dlp",
         "youtube-dl", "convert", "magick", "gs", "sox", "identify"}
LLMCLI = {"claude", "codex", "gemini", "llm", "ollama", "aider"}
PKG = {"pip", "pip3", "apt", "apt-get", "dpkg", "yum", "dnf", "brew"}
PROC = {"ps", "pgrep", "pkill", "top", "htop", "systemctl", "journalctl", "kill",
        "lsof", "ss", "netstat", "free", "df", "uptime", "who", "id", "which"}

PRIORITY = ["llm-cli", "deps", "tests", "media", "wait-loop", "net", "inline-code",
            "git", "proc-inspect", "search-read", "other"]
RANK = {c: i for i, c in enumerate(PRIORITY)}


def unwrap(cmd):
    for _ in range(3):
        m = WRAP.match(cmd)
        if not m:
            break
        cmd = m.group(2)
    return cmd


def tokens(seg):
    """Грубая токенизация: кавычки склеиваются в один токен."""
    return re.findall(r"'[^']*'|\"[^\"]*\"|\S+", seg)


def head_of(toks):
    """Возвращает (голова, остаток) по правилу шага 3."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if ASSIGN.match(t) or t in SHELL_KW:
            i += 1
            continue
        base = os.path.basename(t.strip("'\"").split("=")[0])
        if base in WRAPPERS:
            i += 1
            # съедаем числовой/флаговый аргумент обёртки
            while i < len(toks) and re.match(r"^(-\S+|\d+(\.\d+)?[smhd]?)$", toks[i]):
                i += 1
            continue
        if base in ENVMGR:
            i += 1
            while i < len(toks) and ENVMGR_FLAG.match(toks[i]):
                # 'run' и флаги съедаем; у --with/-C есть значение
                if toks[i] in ("--with", "--with-requirements", "-C", "--directory",
                               "--python", "-p", "--project"):
                    i += 2
                else:
                    i += 1
            continue
        return base, toks[i + 1:]
    return "", []


def seg_class(seg):
    toks = tokens(seg)
    head, rest = head_of(toks)
    if not head:
        return None
    args = " ".join(rest)
    low = head.lower()

    if low.startswith("python") or low in ("python3", "py"):
        if re.search(r"(^|\s)-m\s+pytest\b", args):
            return "tests"
        if re.search(r"(^|\s)-m\s+(unittest|nose2)\b", args):
            return "tests"
        if re.search(r"(^|\s)-m\s+(pip|uv)\b", args) and "install" in args:
            return "deps"
        return "inline-code"
    if low in ("pytest", "py.test"):
        return "tests"
    if low in ("jest", "vitest", "mocha"):
        return "tests"
    if low == "node" or low == "deno" or low == "bun":
        return "inline-code"
    if low == "npm" or low == "yarn" or low == "pnpm":
        if re.match(r"^\s*(install|ci|i)\b", args):
            return "deps"
        if re.match(r"^\s*(test|run test)\b", args):
            return "tests"
        return "other"
    if low in PKG and "install" in args:
        return "deps"
    if low in LLMCLI:
        return "llm-cli"
    if low in MEDIA:
        return "media"
    if low == "sleep":
        return "wait-loop"
    if low == "git":
        sub = args.split()[0] if args.split() else ""
        return "net" if sub in ("clone", "fetch", "push", "pull", "ls-remote") else "git"
    if low in NETCMD:
        return "net"
    if low in SEARCH:
        return "search-read"
    if low in PROC:
        return "proc-inspect"
    if low in ("sqlite3", "psql", "mysql", "redis-cli"):
        return "inline-code"
    return "other"


def classify(cmd):
    body = unwrap(cmd)
    best = None
    for seg in SPLIT.split(body):
        if not seg.strip():
            continue
        c = seg_class(seg)
        if c and (best is None or RANK[c] < RANK[best]):
            best = c
    # ожидание в цикле: seq+pgrep без sleep-сегмента всё равно ожидание
    if best in (None, "proc-inspect", "search-read", "other"):
        low = re.sub(r"\s+", " ", body.lower())
        if "pgrep" in low and "seq " in low:
            best = "wait-loop"
    return best or "other"


def main():
    c = sqlite3.connect(DBF)
    try:
        c.execute("alter table calls add column cls2 text")
    except sqlite3.OperationalError:
        pass
    upd = []
    for tid, name, cmd in c.execute("select tool_id, tool_name, cmd from calls"):
        if name in ("Bash", "bash", "run_terminal_command"):
            upd.append((classify(cmd) if cmd else "other", tid))
        else:
            upd.append(("nonbash:" + name, tid))
    c.executemany("update calls set cls2=? where tool_id=?", upd)
    c.execute("create index if not exists i5 on calls(cls2)")
    c.commit()
    print("classified v2:", len(upd))


if __name__ == "__main__":
    main()
