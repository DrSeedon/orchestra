"""Доля англоязычных слов в русскоязычном диалоге агента — замер для #176.

Код, инлайн-код в backticks, пути и URL вырезаются: без этого метрика меряет
идентификаторы, а не язык (первый прогон дал обратную картину, см. research.md).

Запуск: python3 lang_stats.py /tmp/orch176.db
"""
import re
import sqlite3
import statistics
import sys

SEEDON_ORCH = "09b75a6c-c93f-45ea-b2f4-6728851a1bbd"


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"[/\w.-]*/[\w./-]+", " ", text)
    return re.sub(r"https?://\S+", " ", text)


def report(label: str, contents: list[str]) -> None:
    if not contents:
        print(f"{label:34s} НЕТ ДАННЫХ")
        return
    en = ru = 0
    for raw in contents:
        clean = strip_code(raw)
        en += len(re.findall(r"\b[A-Za-z]{3,}\b", clean))
        ru += len(re.findall(r"\b[А-Яа-яЁё]{3,}\b", clean))
    lengths = [len(c) for c in contents]
    share = en / (en + ru) * 100 if en + ru else 0.0
    print(
        f"{label:34s} n={len(contents):4d} avg={statistics.mean(lengths):6.0f} "
        f"med={statistics.median(lengths):5.0f} EN={en:5d} RU={ru:6d} EN_share={share:5.1f}%"
    )


def main(db_path: str) -> None:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    def texts(where: str) -> list[str]:
        sql = (
            "SELECT l.content FROM logs l JOIN sessions s ON s.id=l.session_id "
            "WHERE l.type='text' AND " + where
        )
        return [row[0] for row in db.execute(sql)]

    # Главный замер: один агент, один юзер, один проект — до и после смены рантайма.
    print("-- seedon-orchestrator: эпоха Claude против эпохи Sol --")
    report(
        "Claude 03-07.08",
        texts(f"s.id='{SEEDON_ORCH}' AND l.ts>='2026-08-03' AND l.ts<'2026-08-08'"),
    )
    report(
        "Sol 08-10.08",
        texts(f"s.id='{SEEDON_ORCH}' AND l.ts>='2026-08-08' AND l.ts<'2026-08-11'"),
    )

    print("-- воркеры --")
    report("Sol: groom", texts("s.name LIKE '%groom%'"))
    report(
        "Sol: прочие 09-10.08",
        texts(
            "s.model='gpt-5.6-sol' AND s.name NOT LIKE '%groom%' "
            "AND l.ts>='2026-08-09' AND l.ts<'2026-08-11'"
        ),
    )
    report(
        "Opus: seedon 04-06.08",
        texts(
            "s.model LIKE 'claude-opus%' AND s.is_orchestrator=0 "
            "AND s.scope='/home/kesha/projects/seedon'"
        ),
    )
    report(
        "Opus: orchestra до 09.08",
        texts(
            "s.model LIKE 'claude-opus%' AND s.is_orchestrator=0 "
            "AND s.scope='/home/kesha/orchestra' AND l.ts<'2026-08-09'"
        ),
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/orch176.db")
