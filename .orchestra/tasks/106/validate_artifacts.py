import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VARIANT_TOKENS = (
    "ORCHESTRA_CURRENT",
    "KESHA_FULL",
    "KESHA_HANDOFF_ONLY",
    "CONCISE",
    "orchestra_current",
    "kesha_full",
    "kesha_handoff_only",
    "concise",
)


def load_json(path: Path):
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def successful_primary(row: dict) -> bool:
    return bool(row.get("result", {}).get("ok"))


def validate() -> dict:
    fixtures = load_json(ROOT / "fixtures.json")
    split_counts = {
        split: sum(fixture["split"] == split for fixture in fixtures)
        for split in ("dev", "holdout")
    }
    assert split_counts == {"dev": 6, "holdout": 7}, split_counts
    assert all(
        "FAKE" in secret
        for fixture in fixtures
        for secret in fixture.get("fake_secrets", [])
    )

    primary = load_jsonl(RESULTS / "primary.jsonl")
    assert len(primary) == 122
    assert sum(successful_primary(row) for row in primary[:117]) == 112
    assert sum(not successful_primary(row) for row in primary[:117]) == 5
    assert all(successful_primary(row) for row in primary[117:])
    latest = {row["job_id"]: row for row in primary}
    assert len(latest) == 117
    assert all(successful_primary(row) for row in latest.values())
    assert all(
        isinstance(row.get("files_before"), dict)
        and isinstance(row.get("files_after"), dict)
        for row in primary
    )
    scores = load_json(RESULTS / "primary-scores.json")
    score_ids = [row["job_id"] for row in scores]
    assert len(score_ids) == len(set(score_ids)) == 117
    assert set(score_ids) == set(latest)

    judge_summary = {}
    for judge in ("claude", "codex"):
        rows = load_jsonl(RESULTS / f"judge-{judge}.jsonl")
        manifest = load_json(RESULTS / f"judge-{judge}-manifest.json")
        mapping = load_json(RESULTS / f"judge-{judge}-blinding-map.json")
        assert manifest["expected_jobs"] == manifest["observed_jobs"] == 13
        assert manifest["failures_this_invocation"] == 0
        assert len(rows) == 13
        assert len(mapping) == 117
        ratings = sum(len(row["result"]["judgment"]["candidates"]) for row in rows)
        assert ratings == 117
        rendered = (RESULTS / f"judge-{judge}.jsonl").read_text()
        assert not any(token in rendered for token in VARIANT_TOKENS)
        judge_summary[judge] = {"batches": len(rows), "ratings": ratings}

    analysis = load_json(RESULTS / "analysis.json")
    assert analysis["method"]["primary_generations"] == 117
    assert analysis["method"]["holdout_generations"] == 63
    assert analysis["presave"]["matched_first_pass_handoff"]["kesha_full"][
        "exact_hits"
    ] == 36
    return {
        "fixtures": split_counts,
        "primary": {
            "raw_records": len(primary),
            "initial_successes": 112,
            "initial_failures": 5,
            "latest_successful_jobs": len(latest),
            "unique_matching_score_jobs": len(score_ids),
            "raw_records_with_file_ledgers": len(primary),
        },
        "judges": judge_summary,
        "status": "ok",
    }


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
