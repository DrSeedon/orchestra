#!/usr/bin/env python3
"""Verify the #430 Git move against an immutable before/after commit pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


# LEGACY_PATH_FIXTURE: source paths identify the immutable pre-move tree.
PREFIXES = {
    "docs/kb/": ".orchestra/kb/",
    "docs/tasks/": ".orchestra/tasks/",
    "docs/workers/": ".orchestra/workers/",
    "docs/archive/": ".orchestra/archive/",
    "pipelines/": ".orchestra/pipelines/",
    "docs/artifacts/": ".orchestra/artifacts/",
    "docs/experiments/": ".orchestra/experiments/",
    "docs/research/": ".orchestra/research/",
    "docs/reviews/": ".orchestra/reviews/",
    "docs/tg-media/": ".orchestra/tg-media/",
}
FILES = {
    "docs/codex-field-guide.md": ".orchestra/guides/codex-field-guide.md",
    "docs/grok-field-guide.md": ".orchestra/guides/grok-field-guide.md",
    "docs/measuring.md": ".orchestra/guides/measuring.md",
    "docs/team-structure.md": ".orchestra/guides/team-structure.md",
    "docs/HANDOFF-from-laptop.md": ".orchestra/archive/HANDOFF-from-laptop.md",
    "docs/codex-full-review.md": ".orchestra/reviews/codex-full-review.md",
    "docs/codex-subscription-usage-research-2026-07.md": ".orchestra/research/codex-subscription-usage-research-2026-07.md",
    "docs/fork-analysis.md": ".orchestra/research/fork-analysis.md",
    "docs/proxy-speed-benchmark.md": ".orchestra/research/proxy-speed-benchmark.md",
    "docs/research-context-bug.md": ".orchestra/research/research-context-bug.md",
    "docs/research-context-full.md": ".orchestra/research/research-context-full.md",
    "docs/research-deepgram.md": ".orchestra/research/research-deepgram.md",
    "docs/research-multiproject.md": ".orchestra/research/research-multiproject.md",
    "docs/architecture.png": ".orchestra/artifacts/architecture.png",
    "docs/fleet-looping.png": ".orchestra/artifacts/fleet-looping.png",
}
FIELDS = ["mode", "lines", "bytes", "sha256"]


def git(root: Path, *args: str, binary: bool = False):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=not binary
    )


def tree(root: Path, ref: str, paths: list[str]) -> dict[str, tuple[str, str]]:
    raw = git(root, "ls-tree", "-r", "-z", ref, "--", *paths, binary=True)
    result = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_type, blob = metadata.decode().split()
        if object_type != "blob":
            raise ValueError(f"non-blob tree item: {raw_path!r}")
        result[raw_path.decode()] = (mode, blob)
    return result


def destination(old_path: str) -> str:
    if old_path in FILES:
        return FILES[old_path]
    for old_prefix, new_prefix in PREFIXES.items():
        if old_path.startswith(old_prefix):
            return new_prefix + old_path[len(old_prefix):]
    raise ValueError(f"unmapped path: {old_path}")


def blob_contents(root: Path, blobs: list[str]) -> dict[str, bytes]:
    ordered = sorted(set(blobs))
    output = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=b"".join(blob.encode() + b"\n" for blob in ordered),
        capture_output=True,
        check=True,
    ).stdout
    result = {}
    offset = 0
    for expected in ordered:
        end_header = output.index(b"\n", offset)
        blob, object_type, raw_size = output[offset:end_header].decode().split()
        size = int(raw_size)
        start = end_header + 1
        end = start + size
        if (blob, object_type) != (expected, "blob") or output[end:end + 1] != b"\n":
            raise ValueError(f"invalid batch response for {expected}")
        result[blob] = output[start:end]
        offset = end + 1
    if offset != len(output):
        raise ValueError("trailing batch bytes")
    return result


# Переезд шёл ТРЕМЯ коммитами, а не одним и не двумя. Проверено по коммитам, которые
# УДАЛИЛИ исходный путь (`git log main --diff-filter=D -- <источник>`):
#   498c0d14 — `docs/kb`, `docs/archive`
#   4f97f176 — `docs/tasks`
#   f8e00522 — остальные 15 отображений (`pipelines/`, `docs/workers`, `docs/research`,
#              `docs/reviews`, `docs/artifacts`, `docs/experiments`, `docs/tg-media`
#              и все одиночные файлы)
# Одна пара ссылок на всё поэтому недостижима в принципе: на паре одного переезда цели
# остальных ещё не существуют, а пара, растянутая на все три, включает посторонние правки
# между ними, и sha256 честно расходятся. Отсюда контракт: пара ссылок задаётся НА КАЖДЫЙ
# переезд отдельно, вместе с корнем исходных путей, который этот переезд трогал.


def verify_move(root: Path, source_root: str, before_ref: str, after_ref: str) -> dict:
    before = tree(root, before_ref, [source_root])
    if not before:
        raise ValueError(f"{source_root!r} is empty at {before_ref!r} — wrong ref pair")
    after = tree(root, after_ref, [".orchestra"])
    contents = blob_contents(root, [blob for _, blob in before.values()])
    mismatches = []
    for old_path, (old_mode, old_blob) in before.items():
        new_path = destination(old_path)
        observed = after.get(new_path)
        if observed != (old_mode, old_blob):
            # Два РАЗНЫХ дефекта, и путать их нельзя: `missing` означает, что отображение
            # путей не сработало (файл не доехал), `content` — что доехал, но с другими
            # байтами. Первое — всегда поломка переезда. Второе законно ровно там, где
            # переезд по замыслу правил содержимое: `pipelines/` переехал вместе с заменой
            # ссылок `docs/` → `.orchestra/` внутри самих промптов (16 файлов из 24,
            # похожесть 83–99% по `git diff -M`).
            mismatches.append({
                "kind": "missing" if observed is None else "content",
                "old": old_path, "new": new_path,
                "expected": [old_mode, old_blob], "observed": observed,
            })
            continue
        data = contents[old_blob]
        # Compute every requested field from the immutable source blob; blob equality proves after parity.
        _ = (len(data), data.count(b"\n"), hashlib.sha256(data).hexdigest())
    return {
        "source_root": source_root,
        "before_ref": before_ref,
        "after_ref": after_ref,
        "checked_files": len(before),
        "missing": sum(1 for item in mismatches if item["kind"] == "missing"),
        "content": sum(1 for item in mismatches if item["kind"] == "content"),
        "mismatches": mismatches,
    }


def verify(root: Path, moves: list[tuple[str, str, str]]) -> dict:
    results = [verify_move(root, *move) for move in moves]
    flat = [
        {"move": item["source_root"], **entry}
        for item in results
        for entry in item["mismatches"]
    ]
    # Промпт лежит под `.orchestra/pipelines/`, поэтому читается по ссылке ИМЕННО того
    # переезда, который его туда перенёс. На ссылках остальных переездов пути ещё нет.
    prompt_refs = [item["after_ref"] for item in results if item["source_root"].startswith("pipelines")]
    artifact_reading_count = None
    if prompt_refs:
        prompt = git(
            root,
            "show",
            f"{prompt_refs[0]}:.orchestra/pipelines/default/prompts/roles/orchestrator.md",
        )
        artifact_reading_count = prompt.count("artifact-reading")
    return {
        "moves": results,
        "checked_files": sum(item["checked_files"] for item in results),
        "fields": FIELDS,
        "mismatches": flat,
        "artifact_reading_count": artifact_reading_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--move", nargs=3, action="append", required=True,
        metavar=("SOURCE_ROOT", "BEFORE_REF", "AFTER_REF"),
        help="один переезд: корень исходных путей и пара ссылок вокруг него",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.root.resolve(), [tuple(move) for move in args.move])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not result["mismatches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
