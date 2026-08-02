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


def test_confirmatory_split_has_no_exact_q4_overlap() -> None:
    fixtures = run_evaluation.load_fixtures()
    assert sum(item["split"] == "dev" for item in fixtures) == 2
    holdout = [item for item in fixtures if item["split"] == "holdout"]
    assert len(holdout) == 21
    prior = []
    for path in (ROOT.parent / "fixtures.json", ROOT.parent / "q4" / "fixtures.json"):
        prior.extend(json.loads(path.read_text()))
    assert {item["id"] for item in fixtures}.isdisjoint(item["id"] for item in prior)
    assert {item["transcript"] for item in fixtures}.isdisjoint(
        item["transcript"] for item in prior
    )
    for fixture in fixtures:
        assert candidates.recent_user_messages(
            run_evaluation.expand_transcript(fixture), fixture
        ) == [candidates.redact(item, fixture) for item in fixture["recent_messages"]]
        if fixture["split"] == "holdout":
            assert sum(len(items) for items in fixture["exact_anchors"].values()) == 8
            assert len(fixture["pending_actions"]) == 1
        for secret in fixture["fake_secrets"]:
            assert secret.startswith(("sk-FAKE-", "AKIA_FAKE_", "ghp_FAKE_"))


def test_only_locked_current_and_hot_variants_exist() -> None:
    assert tuple(candidates.PRIMARY_VARIANTS) == (
        "orchestra_current",
        "hot_state_ledger",
    )
    assert candidates.PRIMARY_VARIANTS["orchestra_current"] == candidates.ORCHESTRA_CURRENT
    assert candidates.CANDIDATE_VARIANTS == ("hot_state_ledger",)
    assert "existing canonical Markdown path" in candidates.HOT_LEDGER_PROMPT
    assert "Never create CLAUDE.md, TODO.md, BUGS.md" in candidates.HOT_LEDGER_PROMPT


def test_structural_composer_redacts_tail_and_marks_tool_gap() -> None:
    secret = fixture_map()["q6-confirm-secret-token-tail"]
    output = candidates.compose_handoff(
        "hot_state_ledger",
        "TASK STATE\ncredential failure",
        run_evaluation.expand_transcript(secret),
        secret,
        {},
        {},
    )
    assert "sk-FAKE-Q6-H13-884" not in output
    assert "[REDACTED SECRET: token]" in output
    assert output.count("PROTECTED RECENT USER MESSAGES") == 1

    gap = fixture_map()["q6-confirm-tool-gap-archive"]
    output = candidates.compose_handoff(
        "hot_state_ledger",
        "TASK STATE\narchive incomplete",
        run_evaluation.expand_transcript(gap),
        gap,
        {},
        {},
    )
    assert "[GAP unmatched tool event id=q6h02-b: result absent]" in output
    assert "[TOOL_RESULT id=q6h02-a]" in output


def test_composer_does_not_read_answer_keys() -> None:
    fixture = fixture_map()["q6-confirm-reversal-canary"]
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
    fixture = fixture_map()["q6-confirm-secret-ghp-file"]
    before = {"docs/a.md": "old"}
    after = {"docs/a.md": "ghp_FAKE_Q6_H15_771\nnew"}
    rows = candidates._file_ledger(before, after, fixture)
    assert len(rows) == 1
    assert "docs/a.md | modified" in rows[0]
    assert "ghp_FAKE_Q6_H15_771" not in rows[0]
    assert "[REDACTED SECRET: token]" in rows[0]


def test_score_checks_targeted_write_and_unrelated_changes() -> None:
    fixture = fixture_map()["q6-confirm-targeted-promotion"]
    before = fixture["seeded_files"]
    after = {
        **before,
        "docs/continuity-state.md": before["docs/continuity-state.md"]
        + "- Billing export owner: Aurora; status: waiting.\n",
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
        "pilot": 2,
        "primary": 126,
        "presave": 6,
        "recompact": 4,
    }
    for mode, expected in expectations.items():
        jobs, mapping = run_evaluation.build_jobs(mode, fixtures, 3, 700 + len(mode))
        assert len(jobs) == len(mapping) == expected
        assert len({item["job_id"] for item in jobs}) == expected
    job = run_evaluation.build_jobs("presave", fixtures, 3, 99)[0][0]
    failed = run_evaluation.runner_failure("presave", job, "model", RuntimeError("x"))
    assert failed["passes"][0]["files_before"] == {}
    assert failed["passes"][0]["files_after"] == {}


def test_judge_prompt_is_blinded_and_carries_diff_for_every_candidate() -> None:
    fixture = fixture_map()["q6-confirm-file-mixed-status"]
    payload = [
        {"candidate_id": f"opaque-{index}", "summary": "summary", "workspace_diff": {}}
        for index in range(6)
    ]
    prompt = run_judges.build_prompt(fixture, payload)
    schema = run_judges.output_schema(
        fixture, [item["candidate_id"] for item in payload]
    )
    assert prompt.count("<measured_workspace_diff>") == 6
    assert prompt.count("{}") >= 6
    assert "false_unchanged_file_action_claims" in prompt
    assert "false_unchanged_file_action_claims" in schema["properties"][
        "candidates"
    ]["items"]["required"]
    for forbidden in candidates.PRIMARY_VARIANTS:
        assert forbidden not in prompt
