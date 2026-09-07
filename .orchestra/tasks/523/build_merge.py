#!/usr/bin/env python3
"""#523 — mechanical step of the KB rewrite: 40 topics → 16, records moved byte-for-byte.

This script does the part that must NOT be done by hand: it carries every bullet from the
old topic files into the new ones without retyping a single character. Rewording happens
afterwards, as ordinary edits on the merged files, so that
``.orchestra/tasks/523/check_no_fact_lost.py`` can tell a *move* (verbatim) from a
*rewrite* (anchors) and fail on a *loss*.

Run from the repo root:

    python3 .orchestra/tasks/523/build_merge.py

It reads ``.orchestra/kb/*.md`` at ``BASE_REF`` via ``git show`` — never the working tree —
so re-running it after the rewrite would regenerate the merged-but-not-yet-rewritten state.
That is why it is a one-shot recorded here as evidence, not a build step: it is the proof
that the merge itself moved text rather than paraphrasing it.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

BASE_REF = "979c46315049f7fb59200cbed4d04992962e4c09"
REPO = pathlib.Path(__file__).resolve().parents[3]
KB = REPO / ".orchestra" / "kb"

PREAMBLE = "\0preamble"
CANON = ["Established", "Historical observations", "Rejected", "Gaps", "Источники"]

# Headings that open a sub-topic inside one file: every canonical section after them
# belongs to that sub-topic, not to the file at large.
SUBTOPIC_OPENERS = {
    "SKILL.state (Google, arXiv 2608.26263), оценка 01.09.2026 — заявка «98%» синтетическая, реальный выигрыш 23–60% плюс точность":
        "SKILL.state (Google, arXiv 2608.26263), оценка 01.09.2026 — заявка «98%» синтетическая, реальный выигрыш 23–60% плюс точность",
}

# Section headings that are not part of the four-section schema. Each names the canonical
# section its content belongs to; the heading itself survives, demoted one level.
IRREGULAR = {
    "Sources": "Источники",
    "Toast 1 (Mixedbread), оценка 01.09.2026 — сам сервис нам не подходит, открытый harness может пригодиться": "Historical observations",
    "Обновления починки (22.08, #367, фаза 3)": "Historical observations",
    "Числа": "Historical observations",
    "Что модель делала хорошо": "Historical observations",
    "Где ломалась": "Historical observations",
    "Где ломался харнес (наш код, не модель)": "Historical observations",
    "Чего у харнеса нет по сравнению с Claude/Codex": "Historical observations",
    "Вердикт": "Historical observations",
    "Обновление 23.08.2026 — #236": "Historical observations",
    "Gaps (обновление #236)": "Gaps",
    "Источники (обновление #236)": "Источники",
    "Обновление #283 (23.08.2026)": "Historical observations",
    "Gaps (обновление #283)": "Gaps",
    "Источники (обновление #283)": "Источники",
    "Обновление #283 — Contabo continuation (23.08.2026)": "Historical observations",
    "Gaps (обновление #283 Contabo)": "Gaps",
    "Источники (обновление #283 Contabo)": "Источники",
    "SKILL.state (Google, arXiv 2608.26263), оценка 01.09.2026 — заявка «98%» синтетическая, реальный выигрыш 23–60% плюс точность": "Established",
}

# target file → (title, intro, [(source topic, label under which its records are grouped)])
TARGETS: list[tuple[str, str, str, list[tuple[str, str]]]] = [
    ("founder-intent.md", "Владелец: замысел продукта и дословные решения",
     "Зачем Orchestra вообще написана, что владелец решил сам и какими словами. "
     "Здесь его требования, а не наши выводы о них.",
     [("founder-intent", "")]),
    ("current-operations.md", "Что действует сейчас и у кого спрашивать",
     "Точка входа: кто владеет каким состоянием и где смотреть текущее значение. "
     "Выводы и доказательства — в темах ниже по списку.",
     [("current-operations", "")]),
    ("evidence-methods.md", "Замеры: как доказать число и не поймать шум",
     "Метод доказательства: как проверять предпосылку до работы, чем мерить, где шум "
     "выдаёт себя за эффект и какое доказательство не считается.",
     [("evidence-methods", "")]),
    ("code-and-tests.md", "Код и тесты: что доказано, что мертво, что лишнее",
     "Один вопрос на четыре стороны: доказывает ли зелёный прогон хоть что-то, какой тест "
     "можно выкинуть, какой код действительно недостижим и какое упрощение окупается.",
     [("test-oracles", "Оракулы тестов: почему зелёный прогон ничего не доказывает"),
      ("test-suite-pruning", "Чистка тестового сьюта"),
      ("dead-code-audit", "Мёртвый код и достижимость"),
      ("code-simplification", "Упрощение кода без потери смысла"),
      ("feature-usage-audit", "Аудит использования функций")]),
    ("review.md", "Ревью: дефекты схемы проверки и калибровка от проекта",
     "Почему ревью пропускает дефекты, сколько раундов имеет смысл и откуда рецензент "
     "берёт знание о проекте.",
     [("review-design-defects", "Дефекты дизайна ревью"),
      ("review-context", "Калибровка ревью от проекта")]),
    ("models-and-quotas.md", "Выбор модели, цена и квоты",
     "Какую модель брать под задачу, что она стоит, сколько осталось в пуле и почему "
     "дашборд показывает не то.",
     [("model-routing-selection", "Выбор модели и рецензента"),
      ("openrouter-quotas", "OpenRouter: бесплатные полосы и лимиты"),
      ("dashboard-quota-map", "Квоты в дашборде: сбои отображения"),
      ("ox-alpha-harness-verdict", "Ox Alpha на своём харнесе — историческая оценка")]),
    ("runtimes.md", "Рантаймы CLI: Codex/Sol, Antigravity, Muse Spark",
     "Поведение внешних CLI-рантаймов, которыми мы запускаем агентов: контекст, "
     "инструменты, изоляция, отказы.",
     [("codex-runtime", "Codex / Sol"),
      ("antigravity-runtime", "Antigravity"),
      ("muse-spark-runtime", "Muse Spark")]),
    ("agent-tools.md", "Инструменты агента: что врут, сколько ждут, где жрут память",
     "Встроенные тула́ рантайма и вспомогательные утилиты: где инструмент возвращает "
     "неправду, сколько времени уходит на вызов и какие вызовы убивают процесс.",
     [("harness-tools", "Встроенные тула́ рантайма"),
      ("tool-latency", "Время вызовов инструментов"),
      ("grep-memory-blowup", "grep/ugrep: взрыв памяти на шаблоне контекста"),
      ("agent-code-intelligence", "Навигация по коду: Serena/LSP против grep")]),
    ("knowledge-base.md", "База знаний и память агентов: устройство, источники, локальность",
     "Как знание попадает в базу, чем её хранение отличается от памяти агента и почему "
     "данные проекта живут в самом проекте.",
     [("knowledge-base-architecture", "Устройство базы знаний"),
      ("knowledge-pipeline", "Конвейер «сырьё → знание»"),
      ("agent-memory-architecture", "Память агентов: поиск, связи, версии"),
      ("data-locality", "Локальность данных проекта"),
      ("information-architecture-synthesis", "Общая архитектура данных")]),
    ("agent-control.md", "Промпты, правила и предохранители: как текст становится действием",
     "Путь правила до агента и обратно: чем собирается промпт, где текст модели начинает "
     "управлять системой и какие предохранители стоят на этом пути.",
     [("prompt-delivery", "Сборка и доставка промпта"),
      ("model-text-control-flow", "Текст модели как управляющий сигнал"),
      ("agent-guardrails", "Предохранители агента")]),
    ("tasks-and-projects.md", "Задачи, проекты, портфолио: хранение и жизненный цикл",
     "Где живёт задача, чем Git отличается от SQLite в этом хранении и как задачи "
     "собираются в проекты и портфолио.",
     [("task-storage-architecture", "Хранение задач: Git и SQLite"),
      ("project-portfolio", "Проекты, портфолио, roadmap")]),
    ("token-efficiency.md", "Токены: цена, экономия и отозванные обещания",
     "На что уходит контекст, какая экономия подтверждена замером и какие громкие "
     "проценты из чужих статей у нас не воспроизвелись.",
     [("token-efficiency", "")]),
    ("repo-ops.md", "Git, worktree, деплой, секреты в артефактах",
     "Операции над репозиторием и контуром: история main при живых воркерах, секреты в "
     "артефактах, копии одной мысли в двух файлах, ноутбук владельца как рабочая машина.",
     [("repo-ops", "")]),
    ("auto-work.md", "Авторабота и самоулучшение: когда система действует сама",
     "Что система запускает без человека, по какому триггеру и где проходит граница; "
     "и как из своих же ошибок получается правило.",
     [("auto-work", "Автоматическая работа и бесплатная полоса"),
      ("self-improvement-loop", "Событийный контур самоулучшения")]),
    ("external-harnesses.md", "Чужие харнесы и агенты: что у них есть и что мы взяли",
     "Разборы чужих продуктов: заявки лендинга против их же кода, механизмы, которые "
     "стоит перенять, и оси, по которым нас сравнивают.",
     [("prime-agent", "Prime Agent и Hermes"),
      ("competitive-landscape", "Сравнение с чужими ADE и субагентами")]),
    ("chat-and-telegram.md", "Чат, Telegram и происхождение сообщений",
     "Интерфейсы, через которые владелец видит работу: свежесть чата в дашборде, "
     "доставка медиа в Telegram и то, откуда пришло каждое сообщение.",
     [("chat-freshness", "Свежесть чата в дашборде"),
      ("tg-media-delivery", "Telegram: доставка медиа"),
      ("message-provenance", "Происхождение сообщений")]),
]


def read_base(name: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "show", f"{BASE_REF}:.orchestra/kb/{name}.md"],
        check=True, capture_output=True, text=True,
    ).stdout


def split_sections(text: str) -> list[tuple[str, str | None, list[str]]]:
    """[(canonical section, sub-topic label, body lines)] — nothing outside a `##` is dropped."""
    out: list[tuple[str, str | None, list[str]]] = []
    current: str | None = PREAMBLE
    sublabel: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("# ") and current is PREAMBLE and not body:
            continue  # the file's own H1 — replaced by the merged topic title
        if line.startswith("## "):
            heading = line[3:].strip()
            if current is not None:
                out.append((current, sublabel, body))
            body = []
            if heading in SUBTOPIC_OPENERS:
                sublabel = SUBTOPIC_OPENERS[heading]
                current = "Established"
            elif heading in CANON:
                current = heading
            elif heading in IRREGULAR:
                current = IRREGULAR[heading]
                body = [f"### {heading}", ""]
            else:
                raise SystemExit(f"unmapped section heading: {heading!r}")
            continue
        body.append(line)
    if current is not None:
        out.append((current, sublabel, body))
    return out


def demote(lines: list[str], levels: int) -> list[str]:
    return [("#" * levels + line) if line.startswith("###") else line for line in lines]


def trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def build(target: str, title: str, intro: str, sources: list[tuple[str, str]]) -> str:
    buckets: dict[str, list[str]] = {name: [] for name in [PREAMBLE] + CANON}
    open_heading: dict[str, str] = {}
    for topic, label in sources:
        for section, sublabel, body in split_sections(read_base(topic)):
            body = trim(list(body))
            if not body:
                continue
            heading = sublabel or label
            if heading:
                body = demote(body, 1)
                if open_heading.get(section) != heading:
                    body = [f"### {heading}", ""] + body
                    open_heading[section] = heading
            buckets[section].extend(body + [""])
    parts = [f"# {title}", "", intro, ""]
    preamble = trim(buckets[PREAMBLE])
    if preamble:
        parts.extend(preamble + [""])
    for section in CANON:
        lines = trim(buckets[section])
        if not lines:
            continue
        parts.extend([f"## {section}", ""] + lines + [""])
    return "\n".join(parts).rstrip("\n") + "\n"


def main() -> int:
    produced = set()
    for target, title, intro, sources in TARGETS:
        (KB / target).write_text(build(target, title, intro, sources), encoding="utf-8")
        produced.add(target)
        print(f"{target:26} ← {', '.join(t for t, _ in sources)}")
    for topic, _ in ((s, l) for _, _, _, ss in TARGETS for s, l in ss):
        old = KB / f"{topic}.md"
        if old.name not in produced and old.exists():
            old.unlink()
            print(f"removed {old.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
