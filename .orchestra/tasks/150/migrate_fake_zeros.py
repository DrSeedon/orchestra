#!/usr/bin/env python3
"""#150, одноразовая миграция: заменить ПОДДЕЛЬНЫЕ нули квоты на NULL.

Лежит в `docs/tasks/150/`, а не в `scripts/`, намеренно: повторный запуск не должен
выглядеть штатной операцией. Дефект уже починен в `app/routes/system.py` — новые строки
пишут NULL сами, и эта миграция нужна ровно один раз, для истории до фикса.

Признак подделки ровно один и доказан независимым полем ТОЙ ЖЕ строки:
`provider_usage.anthropic.status == "unavailable"` — сборщик сам записал, что источник
спросили и он не ответил. Никаких «похоже на»: эвристика «пустой resets_at при нулевом
pct» проверена на живых данных и отвергнута — она помечает подделкой 161 честную строку,
где провайдер ответил про только что сброшенное окно (`docs/tasks/150/report.md`).

Строки старой схемы (`provider_usage = '{}'`, июль) НЕ трогаются: доказательства нет,
а «не знаю», записанное как NULL, — та же ложь, только в другую сторону.

    python docs/tasks/150/migrate_fake_zeros.py --db /home/kesha/orchestra/data/orchestra.db
    python docs/tasks/150/migrate_fake_zeros.py --db ... --apply
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

UNTOUCHED = ("id", "ts", "five_hour_resets_at", "seven_day_resets_at",
             "total_cost_usd", "active_agents", "provider_usage")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Те же прагмы, что у приложения (`app/db.py:_conn`): WAL и ожидание блокировки,
    # чтобы наш UPDATE и пятиминутный INSERT сборщика не сбивали друг друга.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def fake_zero_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT id, provider_usage FROM usage_snapshots "
        "WHERE five_hour_pct = 0 AND seven_day_pct = 0"
    ).fetchall()
    ids = []
    for row in rows:
        anthropic = json.loads(row["provider_usage"] or "{}").get("anthropic") or {}
        if anthropic.get("status") == "unavailable":
            ids.append(row["id"])
    return ids


def census(conn: sqlite3.Connection) -> dict:
    """Срез, который обязан совпасть до и после всюду, кроме двух ожидаемых чисел."""
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    legit_zeros = 0
    for row in conn.execute(
        "SELECT five_hour_pct, provider_usage FROM usage_snapshots WHERE five_hour_pct = 0"
    ):
        anthropic = json.loads(row["provider_usage"] or "{}").get("anthropic") or {}
        if anthropic.get("windows"):
            legit_zeros += 1

    digest = hashlib.sha256()
    cols = ", ".join(UNTOUCHED)
    for row in conn.execute(f"SELECT {cols} FROM usage_snapshots ORDER BY id"):
        digest.update(repr(tuple(row)).encode("utf-8"))

    return {
        "всего снимков": one("SELECT COUNT(*) FROM usage_snapshots"),
        "оба pct = 0": one("SELECT COUNT(*) FROM usage_snapshots "
                           "WHERE five_hour_pct = 0 AND seven_day_pct = 0"),
        "подделок по признаку": len(fake_zero_ids(conn)),
        "оба pct NULL": one("SELECT COUNT(*) FROM usage_snapshots "
                            "WHERE five_hour_pct IS NULL AND seven_day_pct IS NULL"),
        "старая схема, оба нуля": one("SELECT COUNT(*) FROM usage_snapshots "
                                      "WHERE five_hour_pct = 0 AND seven_day_pct = 0 "
                                      "AND provider_usage = '{}'"),
        "законные нули (провайдер ответил)": legit_zeros,
        "sha256 нетронутых колонок": digest.hexdigest()[:16],
    }


def show(title: str, data: dict) -> None:
    print(f"\n{title}")
    for key, value in data.items():
        print(f"  {key:36} {value}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="путь к живой orchestra.db")
    ap.add_argument("--apply", action="store_true", help="без него — только показать")
    args = ap.parse_args()

    conn = connect(args.db)
    before = census(conn)
    show("ДО:", before)
    ids = fake_zero_ids(conn)
    if not ids:
        print("\nПодделок не найдено — миграция уже применена или признак не сработал.")
        return 0
    if not args.apply:
        print(f"\nDry run. Под правку попадают {len(ids)} строк, id {ids[0]}..{ids[-1]}."
              f"\nПовтори с --apply.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(f"/tmp/orchestra-before-150-{stamp}.db")
    # Онлайн-бэкап API, а не `cp`: при WAL копия файла .db без -wal теряет свежие коммиты.
    with sqlite3.connect(backup) as dst:
        conn.backup(dst)
    print(f"\nКопия до правки: {backup} ({backup.stat().st_size} байт)")

    placeholders = ",".join("?" * len(ids))
    with conn:  # одна транзакция
        cur = conn.execute(
            f"UPDATE usage_snapshots SET five_hour_pct = NULL, seven_day_pct = NULL "
            f"WHERE id IN ({placeholders})", ids)
        changed = cur.rowcount
    print(f"Обновлено строк: {changed}")

    after = census(conn)
    show("ПОСЛЕ:", after)

    ok = (
        changed == len(ids)
        and after["всего снимков"] == before["всего снимков"]
        and after["подделок по признаку"] == 0
        and after["оба pct = 0"] == before["оба pct = 0"] - len(ids)
        and after["старая схема, оба нуля"] == before["старая схема, оба нуля"]
        and after["законные нули (провайдер ответил)"] == before["законные нули (провайдер ответил)"]
        and after["sha256 нетронутых колонок"] == before["sha256 нетронутых колонок"]
    )
    print("\nСверка:", "OK" if ok else "РАСХОЖДЕНИЕ — откатывай из копии выше")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
