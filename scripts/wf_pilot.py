#!/usr/bin/env python3
"""Run the pre-promotion wf_run schema-compliance pilot on closed tickets."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wf_run import WorkflowEngine, validate_pilot_manifest


TICKETS = (
    ("480", "Отчёт fan содержит первое сообщение ребёнка вместо его DONE — тихая потеря результата"),
    ("474", "Гейт мержа: нет потолка на ОДИН тест, и квитанцию ревью обнуляет посторонний коммит в main"),
    ("473", "Владение воркеров переживает переезд раскладки: миграция чинит owned_dirs"),
    ("448", "Девять тестов читают docs/tasks/ по живому пути и красные после переезда"),
    ("442", "Красный test_quota_admission_e2e блокирует все мержи"),
    ("434", "Fable 5.1: сколько она ест пула и покрывает ли подписка"),
    ("430", "Переезд docs/ в .orchestra/"),
    ("348", "Совместить новый send_file MCP с дорестартным HTTP 200 и не терять event_id"),
    ("342", "Evidence resolver, fact event log и typed promotion"),
    ("341", "Git-canonical TaskStore и production shadow wiring"),
    ("339", "Frozen task-store parity oracle"),
    ("337", "Durable receipt-backed TG file outbox"),
    ("335", "Typed namespace, record schema и private projection boundary"),
    ("331", "Починить три блокера полного pytest: process_guard pidfd и merge fake"),
    ("327", "Убрать import-time падение restart_guard без os.pidfd_open"),
    ("319", "Перенести дельту на актуальный main без старой истории"),
    ("309", "Аудит неиспользуемых функций Orchestra и кандидатов на удаление"),
    ("307", "Codex oversized JSONL: восстановить connect/resume/compact после записи >16 MiB"),
    ("306", "Остановить цикл Codex >16 MiB и автоматически переходить на fresh thread"),
    ("284", "Починить Codex JSONL >16MB и ложный running"),
)


SCHEMA = {
    "type": "object",
    "properties": {
        "ticket_id": {"type": "string"},
        "summary": {"type": "string", "minLength": 1},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["ticket_id", "summary", "risk"],
    "additionalProperties": False,
}


async def run_pilot(run_id: str, budget_usd: float) -> dict:
    run_dir = ROOT / "data" / "workflow-runs" / run_id
    resume_command = (
        f"{sys.executable} {Path(__file__).resolve()} --resume {run_id} "
        f"--budget-usd {budget_usd:g}"
    )
    engine = WorkflowEngine(
        run_id,
        run_dir,
        budget_usd=budget_usd,
        workflow_path=Path(__file__).resolve(),
        resume_command_override=resume_command,
        max_calls=60,
        max_concurrency=2,
        task_id="487",
    )

    async def ticket(ticket_id: str, title: str):
        schema = json.loads(json.dumps(SCHEMA))
        schema["properties"]["ticket_id"]["const"] = ticket_id
        return await engine.agent(
            (
                f"Closed Orchestra ticket #{ticket_id}: {title}\n"
                "Return only a compact JSON classification. Summarize the title; "
                "choose low, medium, or high risk."
            ),
            model="luna",
            schema=schema,
            label=f"closed-ticket-{ticket_id}",
        )

    values = await engine.parallel(
        [lambda item=item: ticket(*item) for item in TICKETS]
    )
    tickets = []
    for (ticket_id, _title), value in zip(TICKETS, values, strict=True):
        tickets.append({
            "ticket_id": ticket_id,
            "status": "completed" if value is not None else "failed",
            "schema_valid": value is not None,
            "result_path": value.result_path if value is not None else None,
        })
    report = {
        "run_id": run_id,
        "tickets": tickets,
        "spent_usd": engine.budget.spent_usd,
        "manifest_path": str(run_dir / "manifest.json"),
        "resume_command": resume_command,
    }
    engine.result = report
    engine.write_manifest()
    WorkflowEngine._atomic_json(run_dir / "pilot.json", report)
    validate_pilot_manifest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run-id", default="")
    group.add_argument("--resume", default="")
    parser.add_argument("--budget-usd", type=float, default=1.0)
    args = parser.parse_args()
    report = asyncio.run(run_pilot(args.resume or args.run_id or "pilot-487", args.budget_usd))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
