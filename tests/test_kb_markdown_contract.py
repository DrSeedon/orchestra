from __future__ import annotations

import difflib
import os
import subprocess
from pathlib import Path

import pytest

from scripts.check_kb_contract import validate


ROOT = Path(__file__).resolve().parents[1]


VALID_FACT = (
    "- `fact:search-memory-disabled-fallback` — `search_memory` при `RAG_ENABLED=false` "
    "направляет агента в literal `rg` · search: `search_memory`, `RAG_ENABLED=false`, "
    "«семантический поиск выключен», `rg` · evidence: `app/mcp_stdio.py:3020-3034` · "
    "2026-08-30, #417"
)
LEGACY_FACT = (
    "- Старый legacy факт без machine-полей остаётся grandfathered · "
    "evidence: `legacy.py:1` · 2026-08-01, #1"
)


def _topic(body: str, *, section: str = "Established") -> str:
    established = body if section == "Established" else "- (пусто)"
    gaps = body if section == "Gaps" else "- (пусто)"
    return (
        "# memory-test\n\n"
        f"## Established\n\n{established}\n\n"
        "## Rejected\n\n- (пусто)\n\n"
        f"## Gaps\n\n{gaps}\n\n"
        "## Источники\n\n- .orchestra/tasks/417/plan.md — fixture.\n"
    )


def _patch(old: str, new: str, relative: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )


def _validate_fixture(
    tmp_path: Path,
    current: str,
    *,
    old: str = "",
    relative: str = "topic.md",
) -> list[str]:
    root = tmp_path / ".orchestra/kb"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "topic.md"
    target.write_text(current, encoding="utf-8")
    patch_file = tmp_path / "change.patch"
    patch_file.write_text(_patch(old, current, relative), encoding="utf-8")
    return validate(root, patch_file)


def test_forward_only_contract_accepts_valid_addition_beside_legacy(tmp_path):
    old = _topic(LEGACY_FACT)
    current = _topic(LEGACY_FACT + "\n" + VALID_FACT)

    assert _validate_fixture(tmp_path, current, old=old) == []


def test_historical_observation_retains_fact_contract(tmp_path):
    historical = _topic(VALID_FACT).replace("## Established", "## Historical observations")
    assert _validate_fixture(tmp_path, historical) == []
    invalid = historical.replace(" · evidence:", " · absent-evidence:")
    assert any("missing inline evidence" in error for error in _validate_fixture(tmp_path, invalid))


@pytest.mark.parametrize(
    "invalid",
    [
        VALID_FACT.replace(" · search:", " · no-search:"),
        VALID_FACT.replace(" · evidence:", " · no-evidence:"),
        VALID_FACT.replace(
            "evidence: `app/mcp_stdio.py:3020-3034`",
            "evidence:",
        ),
        VALID_FACT + "\n" + VALID_FACT,
        VALID_FACT.replace("fact:search-memory-disabled-fallback", "fact:Bad_Key"),
        VALID_FACT.replace(
            "search: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg`",
            "search:",
        ),
        VALID_FACT.replace(
            "search: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg`",
            "search: `one`, `two`, `three`, `four`, `five`, `six`, `seven`",
        ),
        VALID_FACT.replace(" · search:", " ·\n  search:"),
    ],
    ids=[
        "missing-search",
        "missing-evidence",
        "empty-evidence",
        "duplicate-key",
        "bad-key-shape",
        "zero-anchors",
        "seven-anchors",
        "multiline-fact",
    ],
)
def test_forward_only_contract_rejects_malformed_added_fact(tmp_path, invalid):
    assert _validate_fixture(tmp_path, _topic(invalid))


def test_forward_only_contract_rejects_fact_in_wrong_section(tmp_path):
    assert _validate_fixture(tmp_path, _topic(VALID_FACT, section="Gaps"))


@pytest.mark.parametrize("relative", ["../outside.md", "/outside.md"])
def test_forward_only_contract_rejects_changed_path_outside_root(tmp_path, relative):
    assert _validate_fixture(tmp_path, _topic(VALID_FACT), relative=relative)


def test_forward_only_contract_accepts_repo_relative_docs_kb_path(tmp_path):
    assert _validate_fixture(
        tmp_path,
        _topic(VALID_FACT),
        relative=".orchestra/kb/topic.md",
    ) == []


def test_validator_is_directly_executable():
    validator = ROOT / "scripts/check_kb_contract.py"

    assert os.access(validator, os.X_OK)
    result = subprocess.run(
        [str(validator), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_structured_fact_update_keeps_same_stable_key(tmp_path):
    updated = VALID_FACT.replace("направляет агента", "по-прежнему направляет агента")

    assert _validate_fixture(
        tmp_path,
        _topic(updated),
        old=_topic(VALID_FACT),
    ) == []


@pytest.mark.parametrize("replacement", ["", LEGACY_FACT])
def test_structured_fact_cannot_be_deleted_or_replaced_by_legacy(tmp_path, replacement):
    assert _validate_fixture(
        tmp_path,
        _topic(replacement),
        old=_topic(VALID_FACT),
    )


def test_added_content_cannot_masquerade_as_unified_diff_header(tmp_path):
    invalid = VALID_FACT.replace(" · search:", " · no-search:")
    errors = _validate_fixture(tmp_path, _topic("++ /dev/null\n" + invalid))

    assert any("missing 'search:'" in error for error in errors)


LINK_BASE = (
    "- `fact:prompt-delivery-owner` — Memory rules reach agents through the shared prompt module · "
    "search: `memory-search.md`, `build_system_prompt`, «доставка памяти» · "
    "evidence: `app/pipeline.py:568` · 2026-08-30, #417"
)
APPROVAL_ID = "kb-link-prompt-delivery-owner-depends-on-prompt-delivery"
WRONG_TUPLE_ID = "kb-link-other-fact-related-prompt-delivery"


def _validate_link_fixture(
    tmp_path: Path,
    fact: str,
    *,
    source_name: str = "topic.md",
) -> list[str]:
    root = tmp_path / ".orchestra/kb"
    root.mkdir(parents=True, exist_ok=True)
    (root / "prompt-delivery.md").write_text(_topic(LINK_BASE), encoding="utf-8")
    plan = tmp_path / ".orchestra/tasks/417/plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    receipts = (
        "# approved links\n\n"
        f'<a id="{APPROVAL_ID}"></a> source `fact:prompt-delivery-owner`; '
        "relation `depends_on`; target `.orchestra/kb/prompt-delivery.md`.\n"
        f'<a id="{WRONG_TUPLE_ID}"></a> source `fact:other-fact`; '
        "relation `related`; target `.orchestra/kb/prompt-delivery.md`.\n"
    )
    plan.write_text(receipts, encoding="utf-8")
    (plan.parent / "research.md").write_text(receipts, encoding="utf-8")
    (plan.parent.parent / "plan.md").write_text(receipts, encoding="utf-8")
    current = _topic(fact)
    source = root / source_name
    source.write_text(current, encoding="utf-8")
    patch_file = tmp_path / "link.patch"
    patch_file.write_text(_patch("", current, source_name), encoding="utf-8")
    return validate(root, patch_file)


def test_approved_one_hop_link_matches_exact_receipt_tuple(tmp_path):
    linked = (
        LINK_BASE
        + " · links: `depends_on` → [prompt delivery](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`"
    )

    assert _validate_link_fixture(tmp_path, linked) == []


@pytest.mark.parametrize(
    "invalid",
    [
        LINK_BASE + " · candidate-link: [x](prompt-delivery.md)",
        LINK_BASE
        + " · links: `causes_magic` → [x](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`",
        LINK_BASE
        + " · links: `related` → [x](absent-topic.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`",
        LINK_BASE + " · links: `related` → [x](prompt-delivery.md)",
        LINK_BASE
        + " · links: `depends_on` → [x](prompt-delivery.md)"
        + " · approved: `.orchestra/tasks/417/plan.md#missing-approval-id`",
        LINK_BASE
        + " · links: `depends_on` → [x](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{WRONG_TUPLE_ID}`",
        LINK_BASE
        + " · links: `related` → [x](../foreign.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`",
    ],
    ids=[
        "candidate-canonical",
        "unknown-relation",
        "missing-target",
        "missing-approval",
        "missing-receipt-anchor",
        "existing-wrong-tuple",
        "traversal-target",
    ],
)
def test_unapproved_or_unsafe_one_hop_link_is_rejected(tmp_path, invalid):
    assert _validate_link_fixture(tmp_path, invalid)


def test_self_link_is_rejected(tmp_path):
    fact = (
        LINK_BASE
        + " · links: `related` → [self](self-link.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`"
    )

    assert _validate_link_fixture(tmp_path, fact, source_name="self-link.md")


def test_absolute_link_target_is_rejected(tmp_path):
    outside = tmp_path / "foreign.md"
    outside.write_text(_topic(LINK_BASE), encoding="utf-8")
    fact = (
        LINK_BASE
        + f" · links: `related` → [foreign]({outside.resolve()})"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`"
    )

    assert _validate_link_fixture(tmp_path, fact)


def test_approval_receipt_from_research_artifact_is_rejected(tmp_path):
    linked = (
        LINK_BASE
        + " · links: `depends_on` → [prompt delivery](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/research.md#{APPROVAL_ID}`"
    )

    assert _validate_link_fixture(tmp_path, linked)


def test_approval_receipt_without_task_id_is_rejected(tmp_path):
    linked = (
        LINK_BASE
        + " · links: `depends_on` → [prompt delivery](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/plan.md#{APPROVAL_ID}`"
    )

    assert _validate_link_fixture(tmp_path, linked)
