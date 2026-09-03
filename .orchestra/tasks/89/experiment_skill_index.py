"""Measure whether fresh Sol sessions progressively load a generated skill index.

This is a research harness, not production code. It intentionally records only tool
commands and final text; skill file contents may contain private project data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.pipeline import build_system_prompt, get_role
from app.runtime_registry import BackendBuildContext, build_backend


SEEDON_WORKTREE = Path(
    "/mnt/data/Projects/Python/orchestra/worktrees/"
    "mnt-data-projects-python-seedon/sales"
)

CASES = {
    "bobik": {
        "expected": ["bobik-generate"],
        "prompt": (
            "Нужно подготовить нового Бобика для карточки HR на сайте Сидона. "
            "Сейчас дай только безопасный план действий, ничего не генерируй и не меняй."
        ),
    },
    "direct_banner": {
        "expected": ["direct-banner"],
        "prompt": (
            "Нужно собрать баннер для Яндекс.Директа из уже готового Бобика в трёх "
            "форматах. Сейчас дай только план сборки, ничего не создавай и не меняй."
        ),
    },
    "html_report": {
        "expected": ["html-artifacts"],
        "prompt": (
            "Нужно оформить сравнение PostgreSQL и SQLite как интерактивный отчёт, "
            "который будут перечитывать. Сейчас дай только план артефакта, файлы не меняй."
        ),
    },
    "control_python": {
        "expected": [],
        "prompt": "Объясни в трёх предложениях разницу между list и tuple в Python.",
    },
    "control_git": {
        "expected": [],
        "prompt": "Назови одну безопасную команду Git, которая показывает текущую ветку.",
    },
    "control_runtime_read": {
        "expected": [],
        "prompt": (
            f"Прочитай `{ROOT / 'app/runtime_registry.py'}` и кратко объясни, "
            "что делает `_opencode_factory`. Ничего не меняй."
        ),
    },
    "control_test_read": {
        "expected": [],
        "prompt": (
            f"Прочитай `{ROOT / 'tests/test_backend_codex.py'}` и кратко объясни, "
            "что проверяет первый тест. Ничего не меняй."
        ),
    },
}


@dataclass
class Trial:
    case: str
    run: int
    expected: list[str]
    read_skills: list[str]
    hit: bool
    extra_reads: list[str]
    tool_commands: list[str]
    subagent_events: int
    final_text: str
    turn: dict


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.DOTALL)
    if not match:
        raise ValueError(f"missing YAML frontmatter: {path}")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise ValueError(f"invalid YAML frontmatter: {path}")
    return metadata


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def size_measurements() -> dict:
    from app.prompting import build_codex_skills_index

    role = get_role("default", "worker")
    assert role is not None
    pipeline_paths = [
        ROOT / "pipelines/default/prompts/skills/html-artifacts.md",
        ROOT / "pipelines/default/prompts/skills/codex-debate.md",
    ]
    pipeline_skills = {
        str(_frontmatter(path).get("name") or path.stem): path
        for path in pipeline_paths
    }
    pipeline_index = build_codex_skills_index(
        "default",
        role.skills,
        str(ROOT),
    )

    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", ".claude/skills/*/SKILL.md"],
        cwd=SEEDON_WORKTREE,
        check=True,
        capture_output=True,
    ).stdout.decode().split("\0")
    seedon_skills = dict(pipeline_skills)
    duplicate_collisions = []
    for relative in tracked:
        path = SEEDON_WORKTREE / relative
        if not relative or not path.is_file():
            continue
        clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=SEEDON_WORKTREE,
        ).returncode == 0
        if not clean:
            continue
        name = str(_frontmatter(path).get("name") or path.parent.name)
        if name in seedon_skills:
            winner = seedon_skills[name]
            duplicate_collisions.append({
                "name": name,
                "winner": {"path": str(winner), "sha256": _sha256(winner)},
                "shadowed": {"path": str(path), "sha256": _sha256(path)},
            })
        seedon_skills.setdefault(name, path)
    seedon_index = build_codex_skills_index(
        "default",
        role.skills,
        str(SEEDON_WORKTREE),
    )

    inline_blocks = [
        f"### Skill: {path.stem}\n\n{path.read_text(encoding='utf-8').strip()}"
        for path in pipeline_paths
    ]
    inline = (
        "\n\n## Skills (loaded — invoke as workflows when the trigger matches)\n\n"
        + "\n\n---\n\n".join(inline_blocks)
    )

    def measured(text: str) -> dict:
        return {
            "chars": len(text),
            "utf8_bytes": len(text.encode("utf-8")),
        }

    return {
        "current_inline": measured(inline),
        "pipeline_only_index": {
            **measured(pipeline_index),
            "sources": [
                {"path": str(path), "sha256": _sha256(path)}
                for path in pipeline_skills.values()
            ],
        },
        "seedon_index": {
            **measured(seedon_index),
            "duplicate_collisions": duplicate_collisions,
            "sources": [
                {"path": str(path), "sha256": _sha256(path)}
                for path in seedon_skills.values()
            ],
        },
    }


def _indexed_skill_paths(index: str) -> dict[str, Path]:
    result = {}
    for line in index.splitlines():
        match = re.match(r"^- `([^`]+)` — .* — `([^`]+)`$", line)
        if match:
            result[match.group(1)] = Path(match.group(2))
    return result


def _read_skills_from_commands(
    indexed_skills: dict[str, Path],
    tool_commands: list[str],
) -> list[str]:
    read_skills = []
    for name, path in indexed_skills.items():
        candidates = [str(path)]
        try:
            candidates.append(str(path.relative_to(SEEDON_WORKTREE)))
        except ValueError:
            pass
        if any(
            candidate in command
            for command in tool_commands
            for candidate in candidates
        ):
            read_skills.append(name)
    return sorted(read_skills)


def _summary(trials: list[dict]) -> dict:
    positive = [trial for trial in trials if trial["expected"]]
    controls = [trial for trial in trials if not trial["expected"]]
    return {
        "positive_hits": sum(trial["hit"] for trial in positive),
        "positive_attempts": len(positive),
        "control_false_reads": sum(bool(trial["read_skills"]) for trial in controls),
        "control_attempts": len(controls),
        "extra_read_attempts": sum(bool(trial["extra_reads"]) for trial in trials),
        "total_attempts": len(trials),
    }


def reclassify(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    indexed_skills = {
        name: Path(skill_path)
        for name, skill_path in payload["assembled_index_skills"].items()
    }
    for trial in payload["trials"]:
        read_skills = _read_skills_from_commands(
            indexed_skills,
            trial["tool_commands"],
        )
        expected = set(trial["expected"])
        trial["read_skills"] = read_skills
        trial["hit"] = expected.issubset(read_skills)
        trial["extra_reads"] = sorted(set(read_skills) - expected)
    payload["summary"] = _summary(payload["trials"])
    payload["reclassified_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["classification_note"] = (
        "Raw Bash commands were reclassified after the original detector missed "
        "cwd-relative project skill paths. No model trial was rerun."
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload["summary"], ensure_ascii=False))


async def run_trial(
    case_name: str,
    run: int,
    indexed_skills: dict[str, Path],
) -> Trial:
    case = CASES[case_name]
    context = BackendBuildContext(
        model="gpt-5.6-sol",
        provider="openai",
        cwd=str(SEEDON_WORKTREE),
        system_prompt=build_system_prompt("default", "worker"),
        resume_session_id=None,
        mcp_servers={},
        is_orchestrator=False,
        scope="/mnt/data/Projects/Python/seedon",
        pipeline="default",
        role="worker",
        profile="",
        effort="high",
        context_limit=258_400,
    )
    backend = build_backend("codex", context)
    tool_commands: list[str] = []
    subagent_events = 0
    final_parts: list[str] = []
    turn: dict = {}
    try:
        await backend.send(case["prompt"])
        async for event in backend.events():
            if event.type == "tool_use" and event.content.startswith("Bash: "):
                tool_commands.append(event.content)
            elif event.type.startswith("subagent_"):
                subagent_events += 1
            elif event.type == "text":
                final_parts.append(event.content)
            elif event.type == "turn_end":
                turn = {
                    key: event.metadata.get(key)
                    for key in (
                        "ok",
                        "stop_reason",
                        "input_tokens",
                        "output_tokens",
                        "cost_usd",
                    )
                }
    finally:
        await backend.disconnect()

    read_skills = _read_skills_from_commands(indexed_skills, tool_commands)
    expected = list(case["expected"])
    return Trial(
        case=case_name,
        run=run,
        expected=expected,
        read_skills=read_skills,
        hit=set(expected).issubset(read_skills),
        extra_reads=sorted(set(read_skills) - set(expected)),
        tool_commands=tool_commands,
        subagent_events=subagent_events,
        final_text="\n".join(final_parts),
        turn=turn,
    )


async def main(output: Path, repeats: int, control_repeats: int) -> None:
    from app.prompting import build_codex_skills_index

    role = get_role("default", "worker")
    assert role is not None
    index = build_codex_skills_index(
        "default",
        role.skills,
        str(SEEDON_WORKTREE),
    )
    indexed_skills = _indexed_skill_paths(index)

    jobs = []
    for case_name, case in CASES.items():
        count = control_repeats if not case["expected"] else repeats
        jobs.extend((case_name, run) for run in range(1, count + 1))
    random.Random(89).shuffle(jobs)

    semaphore = asyncio.Semaphore(3)

    async def limited(case_name: str, run: int) -> Trial:
        async with semaphore:
            return await run_trial(case_name, run, indexed_skills)

    trials = await asyncio.gather(*(limited(case_name, run) for case_name, run in jobs))
    serialized_trials = [asdict(trial) for trial in trials]
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "runtime_mode": "worker (is_orchestrator=False)",
        "assembled_runtime": "app.runtime_registry.build_backend(codex)",
        "assembled_index": index,
        "assembled_index_chars": len(index),
        "assembled_index_utf8_bytes": len(index.encode("utf-8")),
        "assembled_index_skills": {
            name: str(path) for name, path in indexed_skills.items()
        },
        "cases": CASES,
        "size_measurements": size_measurements(),
        "metrics_defined_before_run": {
            "positive_hit": (
                "every expected absolute or cwd-relative skill path appeared in a "
                "Bash tool command"
            ),
            "control_false_read": (
                "any indexed absolute or cwd-relative skill path appeared in a "
                "control Bash command"
            ),
            "extra_read": "a skill other than the expected skill was read",
        },
        "summary": _summary(serialized_trials),
        "trials": serialized_trials,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/tasks/89/experiment-assembled-system.json"),
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--control-repeats", type=int, default=3)
    parser.add_argument(
        "--reclassify",
        type=Path,
        help="Reclassify an existing result from its recorded raw Bash commands.",
    )
    args = parser.parse_args()
    if args.reclassify:
        reclassify(args.reclassify)
    else:
        asyncio.run(main(args.output, args.repeats, args.control_repeats))
