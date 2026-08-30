#!/usr/bin/env python3
"""T3: LLM link suggestions stay proposals; only approved one-hop links enter canonical KB."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import difflib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from app.pipeline import build_system_prompt  # noqa: E402


LINK_ANCHORS = (
    "LLM не записывает предложенную связь в `docs/kb/` как истину",
    "`candidate-link` остаётся в `docs/tasks/` до явного апрува",
    "Canonical `связи:` требует ссылку на approved ticket/plan anchor",
    "Retrieval раскрывает не больше одного перехода",
    "`depends_on|explains|contradicts|supersedes|evidence_for|related`",
)


def topic(fact: str, source: str = "docs/tasks/417/plan.md") -> str:
    return (
        "# memory-links\n\n## Установлено\n\n"
        f"{fact}\n\n## Отвергнуто\n\n- (пусто)\n\n"
        "## Пробелы\n\n- (пусто)\n\n## Источники\n\n"
        f"- {source} — acceptance fixture.\n"
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
    missing = [anchor for anchor in LINK_ANCHORS if anchor not in prompt]
    assert not missing, f"T3 link proposal/approval protocol is not delivered: {missing}"

    validator = ROOT / "scripts/check_kb_contract.py"
    assert validator.is_file(), "T3 requires the T2 Markdown validator"

    base = (
        "- `fact:prompt-delivery-owner` — Memory rules reach agents through the shared prompt module · "
        "искать: `memory-search.md`, `build_system_prompt`, «доставка памяти» · "
        "evidence: `app/pipeline.py:568` · 2026-08-30, #417"
    )
    approval_id = "kb-link-prompt-delivery-owner-depends-on-prompt-delivery"
    mismatched_id = "kb-link-other-fact-related-prompt-delivery"
    linked = (
        base
        + " · связи: `depends_on` → [prompt delivery](prompt-delivery.md)"
        + f" · approved: `docs/tasks/417/plan.md#{approval_id}`"
    )
    invalid = {
        "candidate-canonical": base + " · candidate-link: [x](prompt-delivery.md)",
        "unknown-relation": base + " · связи: `causes_magic` → [x](prompt-delivery.md)"
        + f" · approved: `docs/tasks/417/plan.md#{approval_id}`",
        "missing-target": base + " · связи: `related` → [x](absent-topic.md)"
        + f" · approved: `docs/tasks/417/plan.md#{approval_id}`",
        "missing-approval": base + " · связи: `related` → [x](prompt-delivery.md)",
        "wrong-approval": base + " · связи: `depends_on` → [x](prompt-delivery.md)"
        + " · approved: `docs/tasks/417/plan.md#missing-approval-id`",
        "mismatched-approval-tuple": base
        + " · связи: `depends_on` → [x](prompt-delivery.md)"
        + f" · approved: `docs/tasks/417/plan.md#{mismatched_id}`",
        "traversal-target": base + " · связи: `related` → [x](../foreign.md)"
        + f" · approved: `docs/tasks/417/plan.md#{approval_id}`",
    }

    with tempfile.TemporaryDirectory(prefix="kb-links-") as tmp:
        repo_root = Path(tmp)
        kb_root = repo_root / "docs/kb"
        kb_root.mkdir(parents=True)
        plan = repo_root / "docs/tasks/417/plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            "# approved links\n\n"
            f'<a id="{approval_id}"></a> source `fact:prompt-delivery-owner`; '
            "relation `depends_on`; target `docs/kb/prompt-delivery.md`.\n"
            f'<a id="{mismatched_id}"></a> source `fact:other-fact`; '
            "relation `related`; target `docs/kb/prompt-delivery.md`.\n",
            encoding="utf-8",
        )
        (kb_root / "prompt-delivery.md").write_text(topic(base), encoding="utf-8")
        good = kb_root / "good.md"
        good_text = topic(linked)
        good.write_text(good_text, encoding="utf-8")
        diff_file = repo_root / "links.patch"
        diff_file.write_text(patch("", good_text, good.name), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode == 0, (
            "T3 approved one-hop link was rejected:\n" + result.stdout + result.stderr
        )

        for name, fact in invalid.items():
            bad = kb_root / f"{name}.md"
            bad_text = topic(fact)
            bad.write_text(bad_text, encoding="utf-8")
            diff_file.write_text(patch("", bad_text, bad.name), encoding="utf-8")
            result = run_validator(kb_root, diff_file)
            assert result.returncode != 0, f"T3 invalid link fixture {name} was accepted"
            assert (result.stdout + result.stderr).strip(), (
                f"T3 invalid link fixture {name} failed without an actionable reason"
            )

        self_link = kb_root / "self-link.md"
        self_fact = (
            base
            + " · связи: `related` → [self](self-link.md)"
            + f" · approved: `docs/tasks/417/plan.md#{approval_id}`"
        )
        self_text = topic(self_fact)
        self_link.write_text(self_text, encoding="utf-8")
        diff_file.write_text(patch("", self_text, self_link.name), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode != 0, "T3 validator accepted a self-link"

        outside = repo_root / "foreign.md"
        outside.write_text(topic(base), encoding="utf-8")
        absolute_fact = (
            base
            + f" · связи: `related` → [foreign]({outside.resolve()})"
            + f" · approved: `docs/tasks/417/plan.md#{approval_id}`"
        )
        absolute_file = kb_root / "absolute-target.md"
        absolute_text = topic(absolute_fact)
        absolute_file.write_text(absolute_text, encoding="utf-8")
        diff_file.write_text(patch("", absolute_text, absolute_file.name), encoding="utf-8")
        result = run_validator(kb_root, diff_file)
        assert result.returncode != 0, "T3 validator accepted an absolute external target"

    print("T3 PASS: only approved, typed, existing-target one-hop links enter canonical KB")


if __name__ == "__main__":
    main()
