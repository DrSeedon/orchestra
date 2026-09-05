#!/usr/bin/env python3
"""Classify legacy Orchestra paths and verify pinned historical evidence bindings."""

# LEGACY_PATH_FIXTURE: literals below are rejection targets, never runtime fallbacks.

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


FIELDS = ("stable_id", "git_commit", "source_path", "git_blob", "source_sha256")
DOC_LITERALS = ("docs/kb", "docs/tasks", "docs/workers", "docs/archive")
PIPELINE_LITERAL = "pipelines/"
NEGATIVE_MARKER = "LEGACY_PATH_FIXTURE"
HISTORICAL_MARKER = "LEGACY_PATH_HISTORY"
HISTORICAL_FILES = {"CHANGELOG.md"}
HISTORICAL_PREFIXES = ("deploy/",)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def tracked_files(root: Path) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)


def exact_occurrences(text: str) -> int:
    total = sum(text.count(literal) for literal in DOC_LITERALS)
    start = 0
    while True:
        offset = text.find(PIPELINE_LITERAL, start)
        if offset < 0:
            break
        if text[max(0, offset - len(".orchestra/")):offset] != ".orchestra/":
            total += 1
        start = offset + len(PIPELINE_LITERAL)
    return total


def _path_constants(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_constants(node.left)
        right = _path_constants(node.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Call) and node.args:
        return [
            str(argument.value)
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        ]
    return []


def split_python_occurrences(relative: str, text: str) -> int:
    if not relative.endswith(".py"):
        return 0
    try:
        tree = ast.parse(text, relative)
    except SyntaxError:
        return 0
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        values = _path_constants(node)
        if not values:
            continue
        joined = "/".join(value.strip("/") for value in values if value)
        source = ast.get_source_segment(text, node) or ""
        for literal in (*DOC_LITERALS, PIPELINE_LITERAL):
            normalized = literal.rstrip("/")
            if normalized in joined and literal not in source:
                if normalized == "pipelines" and ".orchestra/pipelines" in joined:
                    continue
                found.add((int(getattr(node, "lineno", 0)), literal))
    return len(found)


def occurrence_class(relative: str, text: str) -> str:
    if relative.startswith(".orchestra/pipelines/"):
        return "deferred"
    if relative.startswith(".orchestra/"):
        return "historical"
    if relative in HISTORICAL_FILES or relative.startswith(HISTORICAL_PREFIXES):
        return "historical"
    # Прозаическое упоминание СТАРОГО пути в описании прошлого (заголовок тикета, разбор утечки)
    # историей и остаётся: переписать его — соврать про то, что тогда произошло.
    if HISTORICAL_MARKER in text:
        return "historical"
    if relative.startswith("tests/") or NEGATIVE_MARKER in text:
        return "negative"
    return "live"


def classify_old_paths(root: Path) -> dict[str, object]:
    counts = {"live": 0, "historical": 0, "negative": 0, "deferred": 0}
    live_files: list[str] = []
    for relative in tracked_files(root):
        path = root / relative
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if b"\0" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        occurrences = exact_occurrences(text) + split_python_occurrences(relative, text)
        if not occurrences:
            continue
        category = occurrence_class(relative, text)
        counts[category] += occurrences
        if category == "live":
            live_files.append(relative)
    return {
        "live_old_path_occurrences": counts["live"],
        "historical_old_path_occurrences": counts["historical"],
        "negative_guard_occurrences": counts["negative"],
        "deferred_prompt_occurrences": counts["deferred"],
        "unclassified_old_path_occurrences": counts["live"],
        "live_old_path_files": sorted(set(live_files))[:50],
    }


def _records(root: Path) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for record_path in sorted((root / ".orchestra/kb/records").rglob("*.json")):
        value = json.loads(record_path.read_text(encoding="utf-8"))
        if not set(FIELDS) <= set(value):
            continue
        record = {field: str(value[field]) for field in FIELDS}
        stable_id = record["stable_id"]
        if stable_id in records:
            raise ValueError(f"duplicate historical stable_id: {stable_id}")
        records[stable_id] = record
    return records


# Отображение переезда #430: упразднённый корень → корень назначения. Историческая
# запись ЗАКОННО хранит старый путь — она описывает состояние на момент съёмки; предмет
# проверки не «путь новый», а «старый путь всё ещё РАЗРЕШАЕТСЯ» после переезда.
MOVE_MAP = {
    "docs/kb/": ".orchestra/kb/",
    "docs/tasks/": ".orchestra/tasks/",
    "docs/workers/": ".orchestra/workers/",
    "docs/archive/": ".orchestra/archive/",
    "docs/artifacts/": ".orchestra/artifacts/",
    "docs/experiments/": ".orchestra/experiments/",
    "docs/research/": ".orchestra/research/",
    "docs/reviews/": ".orchestra/reviews/",
    "docs/tg-media/": ".orchestra/tg-media/",
    "pipelines/": ".orchestra/pipelines/",
}


def _move_commit(root: Path, destination_root: str) -> str:
    """Коммит переезда корня — тот, что ВПЕРВЫЕ создал корень назначения.

    Якорь выводится из истории `main`, а не читается из квитанции: записанный SHA — это
    коммит ветки воркера, а мержи у нас squash, поэтому таких объектов в репозитории не
    существует (`source_commit` замороженного файла — ровно этот случай, `ABSENT`).
    """
    out = subprocess.check_output(
        ["git", "log", "main", "--diff-filter=A", "--format=%H", "--", destination_root],
        cwd=root, text=True,
    ).split()
    if not out:
        raise ValueError(f"в истории main нет коммита, создавшего {destination_root}")
    return out[-1]


def _paths_after_move(root: Path) -> set[str]:
    """Все пути под `.orchestra/`, существовавшие СРАЗУ ПОСЛЕ каждого переезда.

    Проверять разрешимость по СЕГОДНЯШНЕМУ дереву нельзя: файл мог быть законно удалён
    позже, и тогда исправный переезд выглядел бы как потерянная привязка.
    """
    seen: set[str] = set()
    for destination_root in sorted(set(MOVE_MAP.values())):
        commit = _move_commit(root, destination_root.rstrip("/"))
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "--name-only", commit, "--", destination_root.rstrip("/")],
            cwd=root,
        )
        seen.update(item.decode() for item in raw.split(b"\0") if item)
    return seen


def _mapped(source_path: str) -> str | None:
    for old_prefix, new_prefix in MOVE_MAP.items():
        if source_path.startswith(old_prefix):
            return new_prefix + source_path[len(old_prefix):]
    return None


def verify_historical_bindings(root: Path) -> dict[str, object]:
    """Привязки исторических свидетельств пережили переезд #430.

    ПРЕДМЕТ ПРОВЕРКИ — ровно два утверждения:
      1. каждая замороженная запись СУЩЕСТВУЕТ (исчезновение — поломка);
      2. каждая разрешается в ТОТ ЖЕ путь после отображения переезда: старый путь,
         пропущенный через `MOVE_MAP`, обязан найтись в дереве коммита переезда
         (перепривязка или потеря — поломка).

    СОДЕРЖИМОЕ записи не проверяется вовсе, и вот почему. Прежняя версия сверяла sha256
    каждой записи с замороженным и краснела на 3174 записях из 12 759 (24.9%). Это не
    находка: `canonical` — живое изменяемое хранилище, записи там правятся законно и
    будут правиться дальше, поэтому «содержимое не менялось» ложно ПО ПОСТРОЕНИЮ, и
    завтра красных будет больше просто оттого, что идёт время. Такой тест не оракул ни в
    одну сторону — он не может ни подтвердить, ни опровергнуть то, ради чего заведён.
    Неизменность содержимого — свойство хранилища, а не переезда, и предметом #430 она
    не была никогда.
    """
    frozen = json.loads(
        (root / ".orchestra/tasks/430/evidence-bindings-frozen.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {str(key): str(value) for key, value in frozen["bindings"].items()}
    records = _records(root)

    missing = sorted(stable_id for stable_id in expected if stable_id not in records)
    after_move = _paths_after_move(root)
    unresolved = []
    resolved = 0
    for stable_id in sorted(expected):
        record = records.get(stable_id)
        if record is None:
            continue
        mapped = _mapped(record["source_path"])
        if mapped is None:
            continue
        resolved += 1
        if mapped not in after_move:
            unresolved.append(stable_id)
    return {
        "historical_bindings_checked": len(expected),
        "historical_binding_missing": len(missing),
        "historical_binding_missing_ids": missing[:20],
        "historical_binding_resolved": resolved,
        "historical_binding_unresolved": len(unresolved),
        "historical_binding_unresolved_ids": unresolved[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    summary = {
        "schema_version": 1,
        **classify_old_paths(root),
        **verify_historical_bindings(root),
    }
    print(
        json.dumps(summary, ensure_ascii=False, sort_keys=True)
        if args.json
        else "\n".join(f"{key}={value}" for key, value in sorted(summary.items()))
    )
    clean = (
        summary["live_old_path_occurrences"] == 0
        and summary["unclassified_old_path_occurrences"] == 0
        and summary["historical_binding_missing"] == 0
        and summary["historical_binding_unresolved"] == 0
        and summary["negative_guard_occurrences"] > 0
    )
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
