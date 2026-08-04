"""#52 — собрать блок CHANGELOG из отчётов задач. Воркеры CHANGELOG больше не правят.

Почему так: правка общего файла в параллельных ветках даёт N−1 конфликт на N веток
(замер в docs/tasks/52/research.md), а отдельный шаг «не забудь дописать changelog»
не выполнялся вовсе — 0 записей на 8 смерженных задач при 97 написанных отчётах.
Поэтому источник — `docs/tasks/<id>/report.md`, который пишется всегда и проверяется
при приёмке; единственное требование к воркеру — первая строка отчёта читается как
строка changelog.

Скрипт ТОЛЬКО ДОПИСЫВАЕТ новый блок сверху. Он не переписывает ни одной существующей
строки: ниже границы лежит история, которую вели руками, и переписывать её ради
единообразия — худший размен.

    uv run python scripts/build-changelog.py                  # сухой прогон
    uv run python scripts/build-changelog.py --write --version v2.36.0
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
TASKS = ROOT / "docs" / "tasks"
BOUNDARY = "<!-- ниже — велось вручную до 04.08.2026 -->"
# Не только цифры: каталоги задач бывают вида `98-grok-runtime-audit`, и узкий шаблон
# молча не матчил всю строку-метку — отсечка выглядела проставленной, а не работала.
DONE_MARK = re.compile(r"<!-- tasks: ([^>]*?) -->")
TITLE = re.compile(r"^#\s+(?:Task\s+)?#(\d+)\s*[—\-:]\s*(.+?)\s*$")


def already_released() -> set[str]:
    """Задачи, уже попавшие в собранные блоки. Метка машиночитаемая намеренно."""
    if not CHANGELOG.exists():
        return set()
    done: set[str] = set()
    for line in CHANGELOG.read_text().splitlines():
        found = DONE_MARK.search(line)
        if found:
            done.update(part.strip() for part in found.group(1).split(",") if part.strip())
    return done


def report_entries() -> list[dict]:
    """Первая строка каждого отчёта + дата последнего коммита этого отчёта."""
    entries = []
    for report in sorted(TASKS.glob("*/report.md")):
        first = report.read_text().splitlines()[0].strip() if report.read_text() else ""
        matched = TITLE.match(first)
        if not matched:
            entries.append({"id": report.parent.name, "text": "", "raw": first,
                            "date": "", "skipped": "заголовок не читается как запись"})
            continue
        when = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(report.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.strip()
        text = matched.group(2)
        for prefix in ("отчёт: ", "отчёт — ", "отчет: "):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
        entries.append({"id": matched.group(1), "text": text, "raw": first,
                        "date": when or "—", "skipped": ""})
    return entries


def next_version() -> str:
    """Следующий патч от верхней версии в файле — номер назначается ПРИ СБОРКЕ."""
    for line in CHANGELOG.read_text().splitlines():
        found = re.match(r"^##\s+v(\d+)\.(\d+)\.(\d+)", line)
        if found:
            major, minor, patch = (int(g) for g in found.groups())
            return f"v{major}.{minor}.{patch + 1}"
    return "v0.1.0"


def build_block(version: str, entries: list[dict]) -> str:
    ids = ", ".join(e["id"] for e in entries)
    lines = [
        f"## {version} — {date.today().isoformat()} — задачи {ids}",
        "",
        f"<!-- tasks: {ids} -->",
        "",
    ]
    for entry in sorted(entries, key=lambda e: int(e["id"])):
        lines.append(f"- **#{entry['id']}** ({entry['date']}) — {entry['text']}")
        lines.append(f"  - подробности: `docs/tasks/{entry['id']}/report.md`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="применить, иначе сухой прогон")
    parser.add_argument("--version", default="", help="номер версии, иначе следующий патч")
    parser.add_argument("--seed", action="store_true",
                        help="разовая отсечка: пометить всё существующее как историю")
    args = parser.parse_args()

    done = already_released()
    entries = report_entries()
    if args.seed:
        # Разовая операция при переходе на сборку: всё, что уже описано в ручной части,
        # помечается как история. Иначе первый же прогон продублировал бы 63 задачи,
        # которые в файле давно есть, — это хуже, чем отсутствие записей.
        ids = ", ".join(e["id"] for e in entries)
        text = CHANGELOG.read_text()
        head, sep, rest = text.partition("\n## ")
        seed_block = (
            f"\n{BOUNDARY}\n"
            f"<!-- tasks: {ids} -->\n"
            f"\n> Всё, что ниже, писали руками до перехода на сборку из отчётов (#52).\n"
            f"> Новые записи добавляет `scripts/build-changelog.py` — ВЫШЕ этой границы.\n"
        )
        if args.write:
            CHANGELOG.write_text(f"{head}{seed_block}{sep}{rest}")
            print(f"Отсечка проставлена: {len(entries)} задач помечены как история.")
        else:
            print(f"Сухой прогон отсечки: {len(entries)} задач будут помечены как история.")
            print(seed_block)
        return 0
    fresh = [e for e in entries if e["id"] not in done and not e["skipped"]]
    unreadable = [e for e in entries if e["skipped"] and e["id"] not in done]

    if unreadable:
        print(f"Пропущено (заголовок не читается как строка changelog): {len(unreadable)}")
        for entry in unreadable[:10]:
            print(f"  #{entry['id']}: {entry['raw'][:70]}")
    if not fresh:
        print("Новых задач для changelog нет.")
        return 0

    block = build_block(args.version or next_version(), fresh)
    print(f"\nБудет добавлено записей: {len(fresh)}\n")
    print(block)
    if not args.write:
        print("Сухой прогон. Чтобы применить — повторить с --write.")
        return 0

    text = CHANGELOG.read_text()
    if BOUNDARY not in text:
        # Граница ставится один раз: всё, что ниже, писали руками до перехода на сборку.
        head, sep, rest = text.partition("\n## ")
        text = f"{head}\n{BOUNDARY}\n{sep}{rest}" if sep else f"{text}\n{BOUNDARY}\n"
    head, sep, rest = text.partition(BOUNDARY)
    CHANGELOG.write_text(f"{head}{block}\n{sep}{rest}")
    print(f"Записано в {CHANGELOG.relative_to(ROOT)}")
    return 0


sys.exit(main())
