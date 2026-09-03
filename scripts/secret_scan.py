#!/usr/bin/env python3
"""Гейт на попадание секрета в git — единственный владелец списка ФОРМ (#453).

Список форм в проекте до этого жил только прозой (`CLAUDE.md`, `.orchestra/kb/repo-ops.md`)
и в замороженных однократных скриптах задач (`.orchestra/tasks/*/verify.py`). Прозу
исполнить нельзя, замороженные артефакты никто не зовёт — поэтому владелец заводится здесь,
а хуки остаются тонкими шимами без собственных шаблонов.

Правило отделения ЗНАЧЕНИЯ от УПОМИНАНИЯ — по НАГРУЗКЕ, а не по префиксу: совпадением
считается точная длина и алфавит формата провайдера. `CLAUDE.md` пишет `y0_`, `AIza`,
`gh[pousr]_` без нагрузки; регулярка в чужом скрипте пишет `y0_[A-Za-z0-9_-]+` — после
префикса стоит `[`, которого в алфавите нагрузки нет. Слой заглушек (`example`, `test`, …)
применяется ТОЛЬКО к двум правилам без собственного формата — `bearer` и телу PEM. К форматам
с провайдерским префиксом он не применяется намеренно: `ghp_<36 base62, содержащих "test">` —
валидный токен, и глушить его словом внутри нагрузки нельзя (найдено ревью Luna, #453).

Отбор по ПУТИ (пропускать `tests/`, `.orchestra/tasks/`) сознательно НЕ применяется:
единственная реальная утечка проекта, `docs/tasks/sol-efficiency/calls_strict.tsv`
(12.08.2026, два боевых OAuth-токена в публичном origin), лежала ровно в каталоге задач —
путевой аллоулист пропустил бы её.
"""

import argparse
import re
import subprocess
import sys

_ZERO = "0" * 40
_GITLINK = "160000"

# Разделители внутри нагрузки: настоящий пробельный символ ИЛИ его JSON-экранирование.
# Ключ Google service-account живёт в JSON именно так: `-----BEGIN PRIVATE KEY-----\nMIIE…`,
# где `\n` — два символа, и правило на настоящий перевод строки его не видит (ревью Luna).
_SEP = re.compile(r"\s|\\[nrt]")

# Одно правило = формат одного провайдера ЦЕЛИКОМ; `mentions` = применять ли слой заглушек.
# Границы (?<!…)/(?!…) делают длину точной: значение на символ длиннее — уже не ключ.
RULES: tuple[tuple[str, re.Pattern[str], int, bool], ...] = tuple(
    (name, re.compile(pattern), group, mentions)
    for name, pattern, group, mentions in (
        ("yandex-oauth", r"(?<![A-Za-z0-9_-])y0_[A-Za-z0-9_-]{40,}", 0, False),
        ("openrouter", r"(?<![A-Za-z0-9-])sk-or-v1-([0-9a-f]{64})(?![0-9a-f])", 1, False),
        ("anthropic", r"(?<![A-Za-z0-9-])sk-ant-(?:api|oat)[0-9]{2}-([A-Za-z0-9_-]{80,})", 1, False),
        ("google-oauth", r"(?<![A-Za-z0-9_-])ya29\.([A-Za-z0-9_-]{50,})", 1, False),
        ("github", r"(?<![A-Za-z0-9_])gh[pousr]_([A-Za-z0-9]{36})(?![A-Za-z0-9])", 1, False),
        ("github-pat", r"(?<![A-Za-z0-9_])github_pat_([A-Za-z0-9_]{70,})", 1, False),
        ("google-api-key", r"(?<![A-Za-z0-9_-])AIza([0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])", 1, False),
        ("bearer", r"(?i:bearer)\s+([A-Za-z0-9._~+/=-]{25,})", 1, True),
        # Заголовок PEM без тела — упоминание: так он и написан в `tests/test_secret_mask.py`
        # и в `app/runtime_history.py`. Значение обязано нести тело base64.
        (
            "pem-private-key",
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----((?:[A-Za-z0-9+/=]|\\[nrt]|\s){40,})",
            1,
            True,
        ),
    )
)

# Слово-заглушка внутри нагрузки означает, что значение написано рукой как пример.
_PLACEHOLDERS = (
    "example", "placeholder", "your", "fake", "dummy", "redacted",
    "secret", "sample", "changeme", "notreal", "test", "xxxx",
)


def _is_mention(core: str) -> bool:
    """Нагрузка написана как пример, а не выдана провайдером."""
    low = core.lower()
    if any(word in low for word in _PLACEHOLDERS):
        return True
    # `AAAA…`, `xxxx…`, `0000…`: у выданного ключа алфавит богаче.
    return len(set(core)) < 8


def scan_text(text: str, origin: str) -> list[str]:
    """Список находок вида `<файл>:<строка>: <правило> (N символов)`. Значение НЕ печатаем."""
    findings = []
    for name, pattern, group, mentions in RULES:
        for m in pattern.finditer(text):
            core = _SEP.sub("", m.group(group))
            if len(core) < 20:
                continue
            if mentions and _is_mention(core):
                continue
            line = text.count("\n", 0, m.start()) + 1
            findings.append(f"{origin}:{line}: {name} ({len(core)} символов)")
    return findings


def _git(*args: str) -> str:
    return _git_bytes(*args).decode("utf-8", "replace")


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(("git", *args), check=True, capture_output=True).stdout


def _scan_blob(sha: str, origin: str) -> list[str]:
    """Читаем блоб по SHA, а не по пути: путь бывает не-UTF8, а SHA всегда однозначен."""
    return scan_text(_git_bytes("cat-file", "blob", sha).decode("utf-8", "replace"), origin)


def _raw_entries(*diff_args: str) -> list[tuple[str, str]]:
    """`(blob_sha, путь)` из `--raw`: только добавленное/изменённое, без gitlink'ов.

    `--diff-filter=d` (строчная = «всё, кроме удалённого») вместо перечисления `ACM`:
    смена типа файла (`T`, симлинк с токеном в цели) и переименование в перечень не входили.
    `--no-renames` разворачивает `R` в пару D+A, поэтому новый путь сканируется как добавленный.
    """
    fields = _git_bytes(
        "diff", *diff_args, "--raw", "-z", "--no-renames", "--diff-filter=d"
    ).split(b"\0")
    entries = []
    for i in range(0, len(fields) - 1, 2):
        meta = fields[i].decode("utf-8", "replace").split()
        if len(meta) < 5:
            continue
        dst_mode, dst_sha = meta[1], meta[3]
        # gitlink: блоба не существует, `cat-file` упал бы и заблокировал честный коммит.
        if dst_mode == _GITLINK or set(dst_sha) == {"0"}:
            continue
        entries.append((dst_sha, fields[i + 1].decode("utf-8", "replace")))
    return entries


def _staged() -> list[str]:
    return [f for sha, path in _raw_entries("--cached") for f in _scan_blob(sha, path)]


def _pre_push() -> list[str]:
    """stdin: `<local ref> <local sha> <remote ref> <remote sha>` — контракт git.

    Идём по КАЖДОМУ публикуемому коммиту, а не по итоговому диффу диапазона: суммарный дифф
    не содержит файла, добавленного одним коммитом и удалённого следующим, и не содержит
    сообщений коммитов — а они публикуются наравне с содержимым (ревью Luna, #453).
    """
    findings = []
    for raw in sys.stdin.read().splitlines():
        parts = raw.split()
        if len(parts) != 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if local_sha == _ZERO:
            continue  # удаление ветки — содержимого не публикует
        if remote_sha != _ZERO:
            rev_args = (f"{remote_sha}..{local_sha}",)
        else:
            rev_args = (local_sha, "--not", "--remotes")  # новая ветка: что ещё не опубликовано
        for commit in _git("rev-list", "--reverse", *rev_args).split():
            short = commit[:8]
            findings += scan_text(
                _git("log", "-1", "--format=%B", commit), f"commit {short} message"
            )
            parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:]
            base = parents[0] if parents else _git("hash-object", "-t", "tree", "/dev/null").strip()
            for sha, path in _raw_entries(base, commit):
                findings += _scan_blob(sha, f"{path} @{short}")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--staged", action="store_true", help="проиндексированные файлы (pre-commit)")
    ap.add_argument("--pre-push", action="store_true", help="публикуемые коммиты (pre-push)")
    ap.add_argument("--commit-msg", help="файл с сообщением коммита (commit-msg)")
    ap.add_argument("paths", nargs="*", help="файлы на диске")
    args = ap.parse_args()

    findings: list[str] = []
    if args.staged:
        findings += _staged()
    if args.pre_push:
        findings += _pre_push()
    if args.commit_msg:
        with open(args.commit_msg, "rb") as fh:
            findings += scan_text(fh.read().decode("utf-8", "replace"), "commit message")
    for path in args.paths:
        with open(path, "rb") as fh:
            findings += scan_text(fh.read().decode("utf-8", "replace"), path)

    if not findings:
        return 0
    print("СЕКРЕТ В ГИТ НЕ ПОПАДЁТ. Найдено:", file=sys.stderr)
    for item in findings:
        print(f"  {item}", file=sys.stderr)
    print(
        "\nУбери значение из файла. Репозиторий публичный, история необратима.\n"
        "Ложное срабатывание чинится ФОРМАТОМ в scripts/secret_scan.py, а не обходом гейта.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        # Fail-closed: не смогли прочитать — не пропускаем.
        print(f"secret_scan: git упал: {exc.stderr.decode('utf-8', 'replace')}", file=sys.stderr)
        sys.exit(2)
