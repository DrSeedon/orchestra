"""Залить извлечённые факты из docs/tasks/kb-extract/part-*.json в canonical knowledge.

Каждый факт становится самостоятельной записью: формулировка, причина, дата и ссылка
на evidence-запись исходного MD. После заливки ответ на вопрос приходит из базы, а не
из файла — ради этого всё и делалось.

Идемпотентен: stable_id факта выводится из (source_file, source_lines, statement),
повторный прогон не плодит дубли. Запуск без --apply только считает.
"""
import argparse
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # скрипт запускают из любого каталога
SRC = ROOT / "docs/tasks/kb-extract"
PROJECT = "orchestra"
NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def load_facts() -> list[dict]:
    facts = []
    for path in sorted(SRC.glob("part-*.json")):
        facts.extend(json.loads(path.read_text(encoding="utf-8")))
    return facts


def evidence_index() -> dict[str, str]:
    """source_path → evidence uri, по записям canonical нашего проекта."""
    root = Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
    ) / "orchestra/knowledge-v1/canonical/evidence" / PROJECT
    index: dict[str, str] = {}
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        source = record.get("source_path")
        uri = record.get("uri")
        if source and uri and source not in index:
            index[source] = uri
    return index


def fact_payload(fact: dict, evidence_uri: str) -> dict:
    """Собрать запрос promote под схему app/ia/knowledge.py.

    Поля фиксированы валидатором (_FACT_FIELDS / _REQUEST_FIELDS) — лишнее или
    недостающее даёт "promotion request has an invalid shape". Наши reason/kind/
    цитата не входят в схему факта и уезжают в metadata.
    """
    key = f"{fact.get('source_file')}::{fact.get('source_lines')}::{fact.get('statement')}"
    stable_id = str(uuid.uuid5(NS, key))
    topic = fact.get("topic") or "general"
    observed = fact.get("decided_at") or "2026-08-26"
    return {
        "event_id": str(uuid.uuid5(NS, "event::" + key)),
        "idempotency_key": stable_id,
        "topic": topic,
        "new_topic": {"topic": topic, "summary": topic},
        "fact": {
            "stable_id": stable_id,
            "fact_key": stable_id,
            "claim": fact["statement"],
            "status": fact.get("status") or "current",
            "confidence": "high",
            "valid_from": f"{observed}T00:00:00+00:00",
            "valid_to": None,
            "observed_at": f"{observed}T00:00:00+00:00",
            "refresh_after": None,
            "supersedes": [],
            "disputed_by": [],
            "metadata": {
                "reason": fact.get("reason"),
                "kind": fact.get("kind") or "fact",
                "quote": fact.get("evidence"),
                "source_file": fact.get("source_file"),
                "source_lines": fact.get("source_lines"),
            },
            "provenance": [{
                "evidence_uri": evidence_uri,
                "source_lines": fact.get("source_lines"),
            }],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="реально писать в canonical")
    parser.add_argument("--limit", type=int, default=0, help="залить только первые N")
    args = parser.parse_args()

    facts = load_facts()
    index = evidence_index()
    missing = Counter()
    ready: list[dict] = []

    for fact in facts:
        source = fact.get("source_file")
        uri = index.get(source)
        if not uri:
            missing[source] += 1
            continue
        ready.append(fact_payload(fact, uri))

    print(f"фактов всего:       {len(facts)}")
    print(f"с доказательством:  {len(ready)}")
    print(f"без доказательства: {sum(missing.values())}")
    for source, count in missing.most_common():
        print(f"  нет evidence для {source}: {count}")

    if not args.apply:
        print("\nсухой прогон. для записи добавь --apply")
        return 0

    from app.ia import runtime

    active = runtime.active_runtime()
    written = failed = 0
    batch = ready[: args.limit] if args.limit else ready
    for payload in batch:
        try:
            active.knowledge_service.promote(payload)
            written += 1
        except Exception as error:  # запись факта не должна ронять весь прогон
            failed += 1
            if failed <= 5:
                print(f"  ОШИБКА: {type(error).__name__}: {error}", file=sys.stderr)
    print(f"\nзаписано: {written}, ошибок: {failed}")
    return 1 if failed and not written else 0


if __name__ == "__main__":
    raise SystemExit(main())
