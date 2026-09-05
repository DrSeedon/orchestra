"""Классификатор v3 — сегментация с учётом кавычек.

Дефект v2, который здесь исправлен: разделители `|` и `;` искались во всей строке,
включая содержимое кавычек. `rg -n 'F1|Codex|systemd' docs/...` резался на сегменты,
сегмент `Codex` получал голову `codex` и вызов уходил в класс llm-cli;
`rg -n "render|convert"` тем же путём уходил в media (raw/17-v2-validation-samples.txt).

ПРАВИЛО ОТНЕСЕНИЯ v3 (дословно, для перепроверки):

  Шаг 1. Разворачиваем обёртку `/bin/bash -lc '...'` (до 3 уровней), снимая внешние кавычки.
  Шаг 2. Идём по строке слева направо, отслеживая состояние кавычек (' и ") и экранирование.
         Режем на СЕГМЕНТЫ по `;` `&&` `||` `|` и переводу строки ТОЛЬКО вне кавычек.
  Шаг 3. У сегмента ищем ГОЛОВУ — первое слово, не являющееся присваиванием (`VAR=...`),
         ключевым словом оболочки, обёрткой запуска (`timeout N`, `nice -n N`, `env`,
         `sudo`, `xargs`, `stdbuf`, `nohup`) или менеджером окружения (`uv`, `poetry`,
         `npx`, ... вместе с их флагами). От головы берём базовое имя файла.
  Шаг 4. Голова + аргументы -> класс сегмента (таблица в seg_class).
         Дополнительно: если в сегменте ВНЕ КАВЫЧЕК встречается `-m pytest`, сегмент
         считается tests независимо от головы — это ловит запуск через переменную
         (`$PY -m pytest`), где голова не резолвится.
  Шаг 5. Класс вызова = сегментный класс с наивысшим приоритетом (PRIORITY сверху вниз).
"""
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DBF = os.path.join(HERE, "..", "raw", "calls.sqlite")

WRAP = re.compile(r"^\s*(?:/bin/)?(?:ba)?sh\s+-[lic]*c\s+(['\"])(.*)\1\s*$", re.S)
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_KW = {"do", "then", "else", "elif", "fi", "done", "if", "for", "while", "set",
            "cd", "exec", "time", "{", "}", "(", ")", "!", "eval", "local", "export",
            "source", ".", "[", "[["}
WRAPPERS = {"timeout", "nice", "env", "sudo", "xargs", "command", "stdbuf", "nohup",
            "ionice", "unbuffer", "script"}
ENVMGR = {"uv", "uvx", "poetry", "npx", "pdm", "hatch", "pipenv", "conda"}
ENVMGR_VALUED = {"--with", "--with-requirements", "-C", "--directory", "--python",
                 "-p", "--project", "--index", "--extra"}

SEARCH = {"rg", "grep", "egrep", "fgrep", "ag", "ack", "cat", "head", "tail", "less",
          "find", "ls", "wc", "sed", "awk", "jq", "nl", "sort", "uniq", "cut", "tr",
          "column", "diff", "stat", "du", "tree", "file", "strings", "xxd", "od",
          "basename", "dirname", "realpath", "readlink", "cmp", "md5sum", "sha256sum"}
NETCMD = {"curl", "wget", "ssh", "scp", "rsync", "nc", "ncat", "telnet", "dig",
          "host", "nslookup", "ping", "sftp", "http", "httpie"}
MEDIA = {"ffmpeg", "ffprobe", "pdftoppm", "pdftotext", "pdfinfo", "yt-dlp",
         "youtube-dl", "convert", "magick", "gs", "sox", "identify", "qpdf"}
LLMCLI = {"claude", "codex", "gemini", "llm", "ollama", "aider"}
PKG = {"pip", "pip3", "apt", "apt-get", "dpkg", "yum", "dnf", "brew"}
PROC = {"ps", "pgrep", "pkill", "top", "htop", "systemctl", "journalctl", "kill",
        "lsof", "ss", "netstat", "free", "df", "uptime", "who", "id", "which",
        "systemd-run", "loginctl", "nproc", "uname"}

PRIORITY = ["llm-cli", "deps", "tests", "media", "wait-loop", "net", "inline-code",
            "git", "proc-inspect", "search-read", "other"]
RANK = {c: i for i, c in enumerate(PRIORITY)}
DASH_M_PYTEST = re.compile(r"(?:^|\s)-m\s+pytest(?:\s|$)")


def unwrap(cmd):
    for _ in range(3):
        m = WRAP.match(cmd)
        if not m:
            break
        cmd = m.group(2)
    return cmd


def split_segments(s):
    """Режет по ; && || | и \\n ТОЛЬКО вне кавычек. Возвращает список сегментов."""
    out, buf, q, i, n = [], [], None, 0, len(s)
    while i < n:
        ch = s[i]
        if q:
            buf.append(ch)
            if ch == "\\" and q == '"' and i + 1 < n:
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == q:
                q = None
            i += 1
            continue
        if ch in "'\"":
            q = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(s[i + 1])
            i += 2
            continue
        if s.startswith("&&", i) or s.startswith("||", i):
            out.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in ";|\n&":
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [x for x in out if x.strip()]


def tokens(seg):
    return re.findall(r"'[^']*'|\"(?:\\.|[^\"])*\"|\S+", seg)


def strip_quotes_outside(seg):
    """Возвращает сегмент, из которого вырезано содержимое кавычек."""
    out, q, i, n = [], None, 0, len(seg)
    while i < n:
        ch = seg[i]
        if q:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == q:
                q = None
            i += 1
            continue
        if ch in "'\"":
            q = ch
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def head_of(toks):
    i = 0
    while i < len(toks):
        t = toks[i]
        if ASSIGN.match(t) or t in SHELL_KW:
            i += 1
            continue
        base = os.path.basename(t.strip("'\"")).lower()
        if base in WRAPPERS:
            i += 1
            while i < len(toks) and re.match(r"^(-\S+|\d+(\.\d+)?[smhd]?)$", toks[i]):
                i += 1
            continue
        if base in ENVMGR:
            i += 1
            while i < len(toks):
                t2 = toks[i]
                if t2 in ENVMGR_VALUED:
                    i += 2
                elif t2 == "run" or t2.startswith("-"):
                    i += 1
                else:
                    break
            continue
        return base, toks[i + 1:]
    return "", []


def seg_class(seg):
    bare = strip_quotes_outside(seg)
    toks = tokens(seg)
    head, rest = head_of(toks)
    args = " ".join(rest)

    # запуск через переменную: $PY -m pytest
    if DASH_M_PYTEST.search(bare):
        return "tests"
    if re.search(r"(?:^|\s)playwright\s+install(?:\s|$)", bare):
        return "deps"
    if not head:
        return None
    low = head

    if low.startswith("python") or low == "py":
        if re.search(r"(^|\s)-m\s+(unittest|nose2)\b", args):
            return "tests"
        if re.search(r"(^|\s)-m\s+(pip|venv)\b", args) and (
            "install" in args or "-m venv" in args
        ):
            return "deps"
        return "inline-code"
    if low in ("pytest", "py.test", "jest", "vitest", "mocha", "tox"):
        return "tests"
    if low in ("node", "deno", "bun", "ts-node"):
        return "inline-code"
    if low in ("npm", "yarn", "pnpm"):
        if re.match(r"^\s*(install|ci|i)\b", args):
            return "deps"
        if re.match(r"^\s*(test|run\s+test)\b", args):
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
    for seg in split_segments(body):
        c = seg_class(seg)
        if c and (best is None or RANK[c] < RANK[best]):
            best = c
    if best in (None, "proc-inspect", "search-read", "other"):
        low = re.sub(r"\s+", " ", strip_quotes_outside(body).lower())
        if "pgrep" in low and "seq " in low:
            best = "wait-loop"
    return best or "other"


def main():
    c = sqlite3.connect(DBF)
    try:
        c.execute("alter table calls add column cls3 text")
    except sqlite3.OperationalError:
        pass
    upd = []
    for tid, name, cmd in c.execute("select tool_id, tool_name, cmd from calls"):
        if name in ("Bash", "bash", "run_terminal_command"):
            upd.append((classify(cmd) if cmd else "other", tid))
        else:
            upd.append(("nonbash:" + name, tid))
    c.executemany("update calls set cls3=? where tool_id=?", upd)
    c.execute("create index if not exists i6 on calls(cls3)")
    c.commit()
    print("classified v3:", len(upd))


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# v4: спасательное правило для вложенных кавычек.
#
# Дефект v3: при `/bin/bash -lc "... '"'...'"' ..."` (экранирование кавычек через
# склейку) отслеживание кавычек рассинхронизируется, сегменты склеиваются, и
# запуск pytest внутри такой команды теряется. Замер: 649 вызовов на 2.23 ч из
# 5.35 ч класса other содержат слово pytest (raw/21-other-pytest-leak.txt).
#
# ПРАВИЛО v4 (дословно): если v3 отнёс вызов к other/search-read/proc-inspect/git,
# но хотя бы одна ФИЗИЧЕСКАЯ СТРОКА команды удовлетворяет INVOKE_RE — то есть
# начинается (после присваиваний, timeout/nice/env/sudo и uv|poetry|npx run-флагов)
# с pytest или с `python[3] -m pytest` — вызов переносится в tests.
# Строки, начинающиеся с поисковой команды (rg/grep/ps/...), правилом не ловятся.
# ---------------------------------------------------------------------------

LEAD = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+|timeout\s+\d+\S*\s+|nice\s+-n\s+\d+\s+|" \
       r"env\s+|sudo\s+|set\s+[+-]\w+\s+|uv\s+run\s+(?:--\S+\s+|\S+\.txt\s+)*|" \
       r"poetry\s+run\s+|npx\s+)*"
INVOKE_RE = re.compile(
    r"^\s*" + LEAD + r"(?:[\w./-]*python[\d.]*\s+-m\s+pytest|[\w./-]*pytest)\b",
    re.M,
)
RESCUE_FROM = {"other", "search-read", "proc-inspect", "git", "net", "inline-code"}


def classify_v4(cmd):
    base = classify(cmd)
    if base in RESCUE_FROM and INVOKE_RE.search(unwrap(cmd)):
        return "tests"
    return base


def main_v4():
    c = sqlite3.connect(DBF)
    try:
        c.execute("alter table calls add column cls4 text")
    except sqlite3.OperationalError:
        pass
    upd = []
    for tid, name, cmd in c.execute("select tool_id, tool_name, cmd from calls"):
        if name in ("Bash", "bash", "run_terminal_command"):
            upd.append((classify_v4(cmd) if cmd else "other", tid))
        else:
            upd.append(("nonbash:" + name, tid))
    c.executemany("update calls set cls4=? where tool_id=?", upd)
    c.execute("create index if not exists i7 on calls(cls4)")
    c.commit()
    print("classified v4:", len(upd))
