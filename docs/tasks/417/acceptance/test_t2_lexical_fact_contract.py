#!/usr/bin/env python3
"""T2: changed KB facts are atomic, evidence-backed, and searchable with literal rg terms."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import difflib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.pipeline import build_system_prompt  # noqa: E402


WRITE_ANCHORS = (
    "Каждый новый или изменённый факт — одна самодостаточная строка без местоименных ссылок",
    "`искать:` содержит 1–6 буквальных якорей будущего вопроса",
    "Сохраняй точные symbol, path, command и прежнее имя",
    "Добавь русскую или английскую формулировку, которой пользователь реально задаст вопрос",
    "Legacy-факты не переписываются пачкой; контракт применяется только к новым и изменённым строкам",
)


def topic(body: str) -> str:
    return (
        "# memory-test\n\n"
        "## Установлено\n\n"
        f"{body}\n\n"
        "## Отвергнуто\n\n- (пусто)\n\n"
        "## Пробелы\n\n- (пусто)\n\n"
        "## Источники\n\n- docs/tasks/417/plan.md — acceptance fixture.\n"
    )


def patch(old: str, new: str, relative: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )


def run_validator(root: Path, diff_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_kb_contract.py"),
            "--root",
            str(root),
            "--diff",
            str(diff_file),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    prompt = build_system_prompt("default", "full-cycle")
    missing = [anchor for anchor in WRITE_ANCHORS if anchor not in prompt]
    assert not missing, f"T2 full-cycle prompt lacks lexical fact contract: {missing}"

    validator = ROOT / "scripts/check_kb_contract.py"
    assert validator.is_file(), (
        "T2 repository-local Markdown validator is missing; agents would have to write ad-hoc Python"
    )
    assert "@mcp.tool" not in validator.read_text(encoding="utf-8"), (
        "T2 validator was exposed as an MCP retrieval tool instead of a deterministic merge check"
    )

    valid = (
        "- `fact:search-memory-disabled-fallback` — `search_memory` при `RAG_ENABLED=false` "
        "возвращает отказ и направляет агента в literal `rg` · искать: `search_memory`, "
        "`RAG_ENABLED=false`, «семантический поиск выключен», `rg` · "
        "evidence: `app/mcp_stdio.py:3020-3034` · 2026-08-30, #417"
    )
    invalid = {
        "missing-search": (
            "- `fact:no-search` — Факт имеет источник, но не содержит будущих поисковых слов · "
            "evidence: `x.py:1` · 2026-08-30, #417"
        ),
        "missing-evidence": (
            "- `fact:no-evidence` — `search_memory` использует `rg` · "
            "искать: `search_memory`, `rg` · 2026-08-30, #417"
        ),
        "duplicate-key": valid + "\n" + valid,
        "bad-key-shape": valid.replace(
            "fact:search-memory-disabled-fallback", "fact:Bad_Key"
        ),
        "zero-anchors": valid.replace(
            "искать: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg`",
            "искать:",
        ),
        "seven-anchors": valid.replace(
            "искать: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg`",
            "искать: `one`, `two`, `three`, `four`, `five`, `six`, `seven`",
        ),
        "multiline-fact": valid.replace(" · искать:", " ·\n  искать:"),
    }

    legacy = (
        "- Старый legacy факт без machine-полей остаётся grandfathered · "
        "evidence: `legacy.py:1` · 2026-08-01, #1"
    )

    with tempfile.TemporaryDirectory(prefix="kb-contract-") as tmp:
        repo_root = Path(tmp)
        kb_root = repo_root / "docs/kb"
        kb_root.mkdir(parents=True)
        good = kb_root / "good.md"
        good_text = topic(valid)
        good.write_text(good_text, encoding="utf-8")
        diff_file = repo_root / "good.patch"
        diff_file.write_text(patch("", good_text, "good.md"), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode == 0, (
            "T2 valid lexical fact was rejected:\n" + result.stdout + result.stderr
        )

        for name, line in invalid.items():
            bad = kb_root / f"{name}.md"
            bad_text = topic(line)
            bad.write_text(bad_text, encoding="utf-8")
            diff_file.write_text(patch("", bad_text, bad.name), encoding="utf-8")
            result = run_validator(kb_root, diff_file)
            assert result.returncode != 0, f"T2 invalid fixture {name} was accepted"
            assert (result.stdout + result.stderr).strip(), (
                f"T2 invalid fixture {name} failed without an actionable reason"
            )

        mixed = kb_root / "mixed.md"
        old_text = topic(legacy)
        good_mixed = topic(legacy + "\n" + valid)
        mixed.write_text(good_mixed, encoding="utf-8")
        diff_file.write_text(patch(old_text, good_mixed, mixed.name), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode == 0, (
            "T2 rejected unchanged legacy while validating a valid added fact:\n"
            + result.stdout
            + result.stderr
        )

        bad_mixed = topic(legacy + "\n" + invalid["missing-search"])
        mixed.write_text(bad_mixed, encoding="utf-8")
        diff_file.write_text(patch(old_text, bad_mixed, mixed.name), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode != 0, (
            "T2 grandfathering swallowed an invalid newly added fact in a legacy topic"
        )

        wrong_section = topic("- (пусто)").replace(
            "## Пробелы\n\n- (пусто)",
            "## Пробелы\n\n" + valid,
        )
        wrong = kb_root / "wrong-section.md"
        wrong.write_text(wrong_section, encoding="utf-8")
        diff_file.write_text(patch("", wrong_section, wrong.name), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode != 0, (
            "T2 accepted a structured fact outside Установлено/Отвергнуто"
        )

        outside = repo_root / "outside.md"
        outside.write_text(topic(valid), encoding="utf-8")
        for escaped in ("../outside.md", str(outside.resolve())):
            diff_file.write_text(patch("", outside.read_text(), escaped), encoding="utf-8")
            result = run_validator(kb_root, diff_file)
            assert result.returncode != 0, (
                f"T2 validator accepted changed path outside project-local KB: {escaped}"
            )

    print("T2 PASS: changed facts require stable key, literal search anchors, and evidence")


if __name__ == "__main__":
    main()
