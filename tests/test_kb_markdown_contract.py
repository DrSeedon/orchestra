from __future__ import annotations

import difflib
import os
import subprocess
from pathlib import Path

import pytest

from scripts.check_kb_contract import validate


ROOT = Path(__file__).resolve().parents[1]


VALID_FACT = (
    "- **`search_memory` при `RAG_ENABLED=false` направляет агента в literal `rg`.** "
    "· ищи: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg` "
    "· evidence: `app/mcp_stdio.py:3020-3034` · 2026-08-30, #417 "
    "· ключ `fact:search-memory-disabled-fallback`"
)
RETIRED_HEAD_FORM = (
    "- `fact:search-memory-disabled-fallback` — `search_memory` при `RAG_ENABLED=false` "
    "направляет агента в literal `rg` · search: `search_memory` · "
    "evidence: `app/mcp_stdio.py:3020-3034` · 2026-08-30, #417"
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
    # The topic fixture points at a task artifact, and #523 gates unopenable pointers, so the
    # artifact has to exist in the fixture tree exactly as it would in the repository.
    fixture_artifact = tmp_path / ".orchestra/tasks/417/plan.md"
    fixture_artifact.parent.mkdir(parents=True, exist_ok=True)
    fixture_artifact.write_text("fixture artifact\n", encoding="utf-8")
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
    invalid = historical.replace("evidence: `app/mcp_stdio.py:3020-3034`", "по ощущениям")
    assert any("missing inline evidence" in error for error in _validate_fixture(tmp_path, invalid))


@pytest.mark.parametrize(
    "invalid",
    [
        VALID_FACT.replace(" · ищи:", " · no-anchors:"),
        VALID_FACT.replace("evidence: `app/mcp_stdio.py:3020-3034`", "по ощущениям"),
        VALID_FACT.replace(
            "evidence: `app/mcp_stdio.py:3020-3034`",
            "evidence:",
        ),
        VALID_FACT + "\n" + VALID_FACT,
        VALID_FACT.replace("fact:search-memory-disabled-fallback", "fact:Bad_Key"),
        VALID_FACT.replace(
            "ищи: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg`",
            "ищи:",
        ),
        VALID_FACT.replace(
            "ищи: `search_memory`, `RAG_ENABLED=false`, «семантический поиск выключен», `rg`",
            "ищи: `one`, `two`, `three`, `four`, `five`, `six`, `seven`",
        ),
        VALID_FACT.replace(" · ищи:", " ·\n  ищи:"),
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
    invalid = VALID_FACT.replace(" · ищи:", " · no-anchors:")
    errors = _validate_fixture(tmp_path, _topic("++ /dev/null\n" + invalid))

    assert any("missing 'ищи:'" in error for error in errors)


def test_retired_head_key_form_is_no_longer_a_structured_fact(tmp_path):
    """#523 moved the stable key to the tail; a head-form line is plain grandfathered prose."""
    assert _validate_fixture(tmp_path, _topic(RETIRED_HEAD_FORM)) == []


# ── the record must actually claim something ────────────────────────────────────────────────

EMPTY_CLAIM_FACT = (
    "-  · ищи: `search_memory`, `RAG_ENABLED=false` "
    "· evidence: `app/mcp_stdio.py:3020-3034` · 2026-09-06, #523 "
    "· ключ `fact:search-memory-disabled-fallback`"
)


def test_fact_without_a_claim_is_rejected(tmp_path):
    """`.*?` used to accept an empty head, so a bullet of pure machine fields passed the gate."""
    errors = _validate_fixture(tmp_path, _topic(EMPTY_CLAIM_FACT))

    assert any("fact has no claim" in error for error in errors), errors
    assert any("topic.md:5" in error for error in errors), errors


@pytest.mark.parametrize(
    "head",
    ["- **   ** ", "- .:; ", "- ** — ** "],
    ids=["blank-bold", "punctuation-only", "dash-only"],
)
def test_claim_made_of_marks_and_spaces_is_still_no_claim(tmp_path, head):
    invalid = EMPTY_CLAIM_FACT.replace("- ", head, 1)

    assert any(
        "fact has no claim" in error for error in _validate_fixture(tmp_path, _topic(invalid))
    )


def test_ordinary_fact_still_passes_the_claim_check(tmp_path):
    assert _validate_fixture(tmp_path, _topic(VALID_FACT)) == []


def test_deleted_topic_file_is_allowed_when_its_key_survives_elsewhere(tmp_path):
    """Merging two topics deletes a file; its lines must not fail on "file does not exist"."""
    root = tmp_path / ".orchestra/kb"
    root.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / ".orchestra/tasks/417/plan.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("fixture artifact\n", encoding="utf-8")
    (root / "merged.md").write_text(_topic(VALID_FACT), encoding="utf-8")
    patch = _patch(_topic(VALID_FACT), "", "gone.md") + _patch("", _topic(VALID_FACT), "merged.md")
    patch_file = tmp_path / "merge.patch"
    patch_file.write_text(patch, encoding="utf-8")

    assert validate(root, patch_file) == []


LINK_BASE = (
    "- **Memory rules reach agents through the shared prompt module.** "
    "· ищи: `memory-search.md`, `build_system_prompt`, «доставка памяти» "
    "· evidence: `app/pipeline.py:568` · 2026-08-30, #417"
)
LINK_KEY = " · ключ `fact:prompt-delivery-owner`"
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
    (root / "prompt-delivery.md").write_text(_topic(LINK_BASE + LINK_KEY), encoding="utf-8")
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
        + LINK_KEY
    )

    assert _validate_link_fixture(tmp_path, linked) == []


@pytest.mark.parametrize(
    "invalid",
    [
        LINK_BASE + " · candidate-link: [x](prompt-delivery.md)" + LINK_KEY,
        LINK_BASE
        + " · links: `causes_magic` → [x](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`" + LINK_KEY,
        LINK_BASE
        + " · links: `related` → [x](absent-topic.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`" + LINK_KEY,
        LINK_BASE + " · links: `related` → [x](prompt-delivery.md)" + LINK_KEY,
        LINK_BASE
        + " · links: `depends_on` → [x](prompt-delivery.md)"
        + " · approved: `.orchestra/tasks/417/plan.md#missing-approval-id`" + LINK_KEY,
        LINK_BASE
        + " · links: `depends_on` → [x](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{WRONG_TUPLE_ID}`" + LINK_KEY,
        LINK_BASE
        + " · links: `related` → [x](../foreign.md)"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`" + LINK_KEY,
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
        + LINK_KEY
    )

    assert _validate_link_fixture(tmp_path, fact, source_name="self-link.md")


def test_absolute_link_target_is_rejected(tmp_path):
    outside = tmp_path / "foreign.md"
    outside.write_text(_topic(LINK_BASE), encoding="utf-8")
    fact = (
        LINK_BASE
        + f" · links: `related` → [foreign]({outside.resolve()})"
        + f" · approved: `.orchestra/tasks/417/plan.md#{APPROVAL_ID}`"
        + LINK_KEY
    )

    assert _validate_link_fixture(tmp_path, fact)


def test_approval_receipt_from_research_artifact_is_rejected(tmp_path):
    linked = (
        LINK_BASE
        + " · links: `depends_on` → [prompt delivery](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/417/research.md#{APPROVAL_ID}`"
        + LINK_KEY
    )

    assert _validate_link_fixture(tmp_path, linked)


def test_approval_receipt_without_task_id_is_rejected(tmp_path):
    linked = (
        LINK_BASE
        + " · links: `depends_on` → [prompt delivery](prompt-delivery.md)"
        + f" · approved: `.orchestra/tasks/plan.md#{APPROVAL_ID}`"
        + LINK_KEY
    )

    assert _validate_link_fixture(tmp_path, linked)


# ── `· открыть:` — a pointer that outlives its file (#523) ──────────────────────────────────

def _pointer_repo(tmp_path: Path) -> tuple[Path, str]:
    """A real throwaway repository: one committed artifact, then removed. Returns the KB root
    and the sha at which the artifact still opens, so the snapshot form is tested for real."""
    root = tmp_path / ".orchestra/kb"
    root.mkdir(parents=True, exist_ok=True)
    gone = tmp_path / ".orchestra/tasks/900/research.md"
    gone.parent.mkdir(parents=True, exist_ok=True)
    gone.write_text("evidence\n", encoding="utf-8")
    alive = tmp_path / ".orchestra/archive/laptop-tasks/900/report.md"
    alive.parent.mkdir(parents=True, exist_ok=True)
    alive.write_text("moved evidence\n", encoding="utf-8")
    git = ["git", "-C", str(tmp_path)]
    if (tmp_path / ".git").is_dir():  # a second call on the same tmp_path reuses the commit
        sha = subprocess.run(
            git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        gone.unlink()
        return root, sha
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["config", "user.email", "t@t"], check=True)
    subprocess.run(git + ["config", "user.name", "t"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "artifact"], check=True)
    sha = subprocess.run(
        git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    gone.unlink()
    return root, sha


def _pointer_errors(tmp_path: Path, line: str) -> list[str]:
    root, sha = _pointer_repo(tmp_path)
    from scripts.check_kb_contract import validate_task_pointers

    return validate_task_pointers(root, Path("topic.md"), 7, line.replace("<SHA>", sha))


def test_snapshot_and_moved_entries_open_a_missing_pointer(tmp_path):
    snapshot = "- Ссылка `.orchestra/tasks/900/research.md` · открыть: `git show <SHA>:.orchestra/tasks/900/research.md`"
    moved = (
        "- Ссылка `.orchestra/tasks/900/report.md` · открыть: "
        ".orchestra/tasks/900/report.md → `.orchestra/archive/laptop-tasks/900/report.md`"
    )

    assert _pointer_errors(tmp_path, snapshot) == []
    assert _pointer_errors(tmp_path, moved) == []


def test_pointer_without_any_entry_is_refused(tmp_path):
    errors = _pointer_errors(tmp_path, "- Ссылка `.orchestra/tasks/900/research.md` без поля")

    assert any("topic.md:7" in error and "no '· открыть:' entry" in error for error in errors)


def test_snapshot_that_does_not_open_is_refused(tmp_path):
    dead = "0" * 40
    errors = _pointer_errors(
        tmp_path,
        f"- Ссылка `.orchestra/tasks/900/research.md` · открыть: `git show {dead}:.orchestra/tasks/900/research.md`",
    )

    assert any("snapshot anchor does not open" in error for error in errors)


def test_a_neighbouring_live_path_does_not_cover_a_missing_one(tmp_path):
    """Coverage is addressed: another existing path in the same record closes nothing."""
    errors = _pointer_errors(
        tmp_path,
        "- Две ссылки: `.orchestra/tasks/900/research.md` и `.orchestra/tasks/900/other.md` "
        "· открыть: `.orchestra/archive/laptop-tasks/900/report.md`",
    )

    assert any(".orchestra/tasks/900/research.md is not in the working tree" in e for e in errors)


def test_one_covered_pointer_does_not_cover_its_neighbour(tmp_path):
    errors = _pointer_errors(
        tmp_path,
        "- Две: `.orchestra/tasks/900/research.md`, `.orchestra/tasks/900/second.md` "
        "· открыть: `git show <SHA>:.orchestra/tasks/900/research.md`",
    )

    assert any(".orchestra/tasks/900/second.md is not in the working tree" in e for e in errors)
    assert not any("900/research.md is not in the working tree" in e for e in errors)


@pytest.mark.parametrize(
    "reason", ["", " ", " нет", " —"], ids=["empty", "space", "one-word", "dash"]
)
def test_absent_entry_needs_a_real_reason(tmp_path, reason):
    errors = _pointer_errors(
        tmp_path,
        "- Ссылка `.orchestra/tasks/900/research.md` · открыть: "
        f".orchestra/tasks/900/research.md — нет в репозитории:{reason}",
    )

    assert any("needs a reason" in error and "topic.md:7" in error for error in errors)


def test_absent_entry_with_a_reason_is_accepted(tmp_path):
    line = (
        "- Ссылка `.orchestra/tasks/900/research.md` · открыть: "
        ".orchestra/tasks/900/research.md — нет в репозитории: синтетическая фикстура скретча"
    )

    assert _pointer_errors(tmp_path, line) == []


def test_an_arrow_in_ordinary_prose_is_not_coverage(tmp_path):
    """`→` and `git show` appear all over the KB as prose; only the field grants coverage."""
    errors = _pointer_errors(
        tmp_path,
        "- Миграция `docs/` → `.orchestra/` тронула `.orchestra/tasks/900/research.md`",
    )

    assert any("no '· открыть:' entry" in error for error in errors)


def test_pointer_outside_a_bullet_is_checked_too(tmp_path):
    """A path added in a paragraph or a continuation line used to pass unchecked."""
    root, _ = _pointer_repo(tmp_path)
    paragraph = "Подробности лежат в .orchestra/tasks/900/research.md рядом с отчётом."
    current = (
        "# memory-test\n\n" + paragraph + "\n\n## Established\n\n- (пусто)\n\n"
        "## Rejected\n\n- (пусто)\n\n## Gaps\n\n- (пусто)\n"
    )
    (root / "topic.md").write_text(current, encoding="utf-8")
    patch_file = tmp_path / "para.patch"
    patch_file.write_text(_patch("", current, "topic.md"), encoding="utf-8")

    assert any("no '· открыть:' entry" in error for error in validate(root, patch_file))


@pytest.mark.parametrize(
    "target", ["/etc/hosts", "../../../etc/hosts"], ids=["absolute", "traversal"]
)
def test_moved_to_target_must_stay_inside_the_repository(tmp_path, target):
    """`repo / '/etc/hosts'` is `/etc/hosts`, so an outside file used to "cover" a dead link."""
    errors = _pointer_errors(
        tmp_path,
        "- Ссылка `.orchestra/tasks/900/research.md` · открыть: "
        f".orchestra/tasks/900/research.md → `{target}`",
    )

    assert any("must stay inside the repository" in e and "topic.md:7" in e for e in errors)
    assert any("no '· открыть:' entry" in e for e in errors)


MARKUP_ONLY_TAIL = (
    " · ищи: `x`, `y` · evidence: `app/db.py:1` · 2026-09-06, #523 "
    "· ключ `fact:search-memory-disabled-fallback`"
)


@pytest.mark.parametrize(
    "head",
    [
        "- `foo`",
        "- **[foo](bar)**",
        "- [текст](путь.md)",
        "- **`foo`** ",
        "- ``foo``",
        "- [a][b]",
        "- <http://x>",
        "- <b>",
        "- ![a](b)",
    ],
    ids=[
        "code-span",
        "bold-link",
        "plain-link",
        "bold-code-span",
        "double-backtick",
        "reference-link",
        "autolink",
        "html-tag",
        "image",
    ],
)
def test_a_head_made_only_of_markup_is_not_a_claim(tmp_path, head):
    """Letters inside a code span or a link body are markup, not a statement."""
    errors = _validate_fixture(tmp_path, _topic(head + MARKUP_ONLY_TAIL))

    assert any("fact has no claim" in error for error in errors), errors


def test_a_claim_around_code_spans_still_passes(tmp_path):
    """The stripping must not swallow a real claim that merely quotes symbols."""
    fact = (
        "- **`db.add_log` — НЕ единственный писатель `user_message`.**" + MARKUP_ONLY_TAIL
    )

    assert _validate_fixture(tmp_path, _topic(fact)) == []


def test_moved_to_target_may_not_escape_through_a_symlink(tmp_path):
    """`is_file()` follows links, so a committed link with an innocent name resolved outside."""
    root, _ = _pointer_repo(tmp_path)
    # `tmp_path` IS the repository, so the escape target has to live above it.
    outside = tmp_path.parent / "outside-the-repo.md"
    outside.write_text("not part of this repository", encoding="utf-8")
    (tmp_path / "inside.md").symlink_to(outside)
    from scripts.check_kb_contract import validate_task_pointers

    errors = validate_task_pointers(
        root,
        Path("topic.md"),
        7,
        "- Ссылка `.orchestra/tasks/900/research.md` · открыть: "
        ".orchestra/tasks/900/research.md → `inside.md`",
    )

    assert any("must stay inside the repository" in e and "topic.md:7" in e for e in errors)
    assert any("no '· открыть:' entry" in e for e in errors)


@pytest.mark.parametrize(
    "claim",
    [
        "**`db.add_log` — НЕ единственный писатель `user_message`.**",
        "**Порог `>40` строк и 5 > 3 значит норма.**",
        "**Смотри [гайд](g.md): порог не усиливать.**",
        "**613 живых строк доказывают путь.**",
    ],
    ids=["cyrillic-with-code", "angle-brackets", "link-plus-prose", "digits"],
)
def test_stripping_markup_must_not_swallow_a_real_claim(tmp_path, claim):
    """Over-stripping would refuse legitimate records — the costlier direction of this check."""
    assert _validate_fixture(tmp_path, _topic("- " + claim + MARKUP_ONLY_TAIL)) == []
