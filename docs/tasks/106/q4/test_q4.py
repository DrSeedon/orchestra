import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import candidates
import run_evaluation
import run_judges
import score_results


def fixture_map() -> dict[str, dict]:
    return {item["id"]: item for item in run_evaluation.load_fixtures()}


def test_fresh_split_and_recent_ledgers_match_transcripts() -> None:
    fixtures = run_evaluation.load_fixtures()
    assert sum(item["split"] == "dev" for item in fixtures) == 5
    assert sum(item["split"] == "holdout" for item in fixtures) == 8
    old_ids = {
        item["id"]
        for item in json.loads((ROOT.parent / "fixtures.json").read_text())
    }
    assert old_ids.isdisjoint(item["id"] for item in fixtures)
    for fixture in fixtures:
        assert candidates.recent_user_messages(
            run_evaluation.expand_transcript(fixture), fixture
        ) == [candidates.redact(item, fixture) for item in fixture["recent_messages"]]


def test_candidates_are_incremental_and_original_is_unchanged() -> None:
    current = candidates.ORCHESTRA_CURRENT
    assert candidates.PRIMARY_VARIANTS["orchestra_current"] == current
    assert "RECENT: Last 5-10 exchanges" not in candidates.EXACT3_PROMPT
    assert "RECENT USER MESSAGES: Copy the last 3" in candidates.EXACT3_PROMPT
    assert candidates.EXACT3_PROMPT.count("RECENT USER MESSAGES") == 1
    assert "protected, redacted raw tail" in candidates.RAW_TAIL_PROMPT
    assert "existing canonical Markdown path" in candidates.HOT_LEDGER_PROMPT
    assert "Never create CLAUDE.md, TODO.md, BUGS.md" in candidates.HOT_LEDGER_PROMPT


def test_structural_composer_redacts_tail_and_marks_tool_gap() -> None:
    fixture = fixture_map()["holdout-recent-secret"]
    output = candidates.compose_handoff(
        "raw_tail",
        "MODEL STATE",
        run_evaluation.expand_transcript(fixture),
        fixture,
        {},
        {},
    )
    assert "sk-FAKE-Q4-HOLD-773" not in output
    assert "[REDACTED SECRET: token]" in output
    assert output.count("PROTECTED RECENT USER MESSAGES") == 1

    gap = fixture_map()["holdout-tool-gap"]
    output = candidates.compose_handoff(
        "hot_state_ledger",
        "TASK STATE\nunknown",
        run_evaluation.expand_transcript(gap),
        gap,
        {},
        {},
    )
    assert "[GAP unmatched tool event id=h5-t2: result absent]" in output
    assert "[TOOL_RESULT id=h5-t1]" in output


def test_composer_does_not_read_answer_keys() -> None:
    fixture = fixture_map()["holdout-tool-gap"]
    mutated = copy.deepcopy(fixture)
    mutated["exact_anchors"] = {"invented": ["MUST NEVER APPEAR"]}
    mutated["semantic_anchors"] = [{"id": "x", "claim": "MUST NEVER APPEAR"}]
    mutated["forbidden_claims"] = ["MUST NEVER APPEAR"]
    mutated["pending_actions"] = ["MUST NEVER APPEAR"]
    original = candidates.compose_handoff(
        "hot_state_ledger", "STATE", fixture["transcript"], fixture, {}, {}
    )
    changed = candidates.compose_handoff(
        "hot_state_ledger", "STATE", fixture["transcript"], mutated, {}, {}
    )
    assert original == changed
    assert "MUST NEVER APPEAR" not in original


def test_file_ledger_uses_measured_state_and_redacts() -> None:
    fixture = fixture_map()["holdout-recent-secret"]
    before = {"docs/a.md": "old"}
    after = {"docs/a.md": "sk-FAKE-Q4-HOLD-773\nnew"}
    rows = candidates._file_ledger(before, after, fixture)
    assert len(rows) == 1
    assert "docs/a.md | modified" in rows[0]
    assert "sk-FAKE-Q4-HOLD-773" not in rows[0]
    assert "[REDACTED SECRET: token]" in rows[0]


def test_score_checks_ledger_files_and_unrelated_writes() -> None:
    fixture = fixture_map()["holdout-targeted-promotion"]
    before = fixture["seeded_files"]
    after = {
        **before,
        "docs/ops-state.md": before["docs/ops-state.md"]
        + "- Vendor schema owner: Northwind; status: pending.\n",
        "TODO.md": "invented\n",
    }
    summary = candidates.compose_handoff(
        "hot_state_ledger", "STATE", fixture["transcript"], fixture, before, after
    )
    score = score_results.score_output(
        fixture, "hot_state_ledger", summary, before, after
    )
    assert score["ledger_pass"]
    assert score["file_state"]["passed"]
    assert score["unrelated_changes"] == ["TODO.md"]


def test_job_counts_and_failure_ledgers() -> None:
    fixtures = run_evaluation.load_fixtures()
    expectations = {
        "pilot": (3, 3),
        "primary": (96, 96),
        "presave": (12, 12),
        "recompact": (8, 8),
    }
    for mode, expected in expectations.items():
        jobs, mapping = run_evaluation.build_jobs(mode, fixtures, 3, 700 + len(mode))
        assert (len(jobs), len(mapping)) == expected
        assert len({item["job_id"] for item in jobs}) == len(jobs)
    job = run_evaluation.build_jobs("presave", fixtures, 3, 99)[0][0]
    failed = run_evaluation.runner_failure("presave", job, "model", RuntimeError("x"))
    assert failed["passes"][0]["files_before"] == {}
    assert failed["passes"][0]["files_after"] == {}


def test_judge_prompt_is_blinded_and_carries_diff_for_every_candidate() -> None:
    fixture = fixture_map()["holdout-file-decoys"]
    candidates_payload = [
        {"candidate_id": f"opaque-{index}", "summary": "summary", "workspace_diff": {}}
        for index in range(3)
    ]
    prompt = run_judges.build_prompt(fixture, candidates_payload)
    assert prompt.count("<measured_workspace_diff>") == 3
    assert prompt.count("{}") >= 3
    for forbidden in candidates.PRIMARY_VARIANTS:
        assert forbidden not in prompt

