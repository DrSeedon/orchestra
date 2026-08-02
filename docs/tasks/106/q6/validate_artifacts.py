import argparse
import hashlib
import json
from pathlib import Path

from candidates import PRIMARY_VARIANTS
from run_evaluation import result_succeeded


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
HOLDOUT_FIXTURES = 21
REPETITIONS = 3


def load(path: Path):
    return json.loads(path.read_text())


def latest(path: Path) -> dict[str, dict]:
    rows = {}
    for line in path.read_text().splitlines():
        if line.strip():
            item = json.loads(line)
            rows[item["job_id"]] = item
    return rows


def assert_hashes(manifest: dict) -> None:
    lock = load(RESULTS / "preregistration-lock.json")
    assert manifest["source_sha256"] == lock["source_sha256"]
    for name, expected in manifest["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name


def validate_mode(mode: str) -> None:
    mapping = load(RESULTS / f"{mode}-blinding-map.json")
    rows = latest(RESULTS / f"{mode}.jsonl")
    manifest = load(RESULTS / f"{mode}-manifest.json")
    assert set(rows) == set(mapping), f"{mode}: result/map ID mismatch"
    assert manifest["expected_jobs"] == len(mapping)
    assert manifest["observed_jobs"] == len(mapping)
    assert_hashes(manifest)
    for job_id, item in rows.items():
        assert result_succeeded(mode, item), f"{mode}: incomplete {job_id}"
        if mode in {"pilot", "primary"}:
            assert isinstance(item["files_before"], dict)
            assert isinstance(item["files_after"], dict)
        elif mode == "presave":
            assert len(item["passes"]) == 2
            for row in item["passes"]:
                assert isinstance(row["files_before"], dict)
                assert isinstance(row["files_after"], dict)
        else:
            assert len(item["generations"]) == 3
            for row in item["generations"]:
                assert isinstance(row["files_before"], dict)
                assert isinstance(row["files_after"], dict)


def validate_primary_scores() -> None:
    mapping = load(RESULTS / "primary-blinding-map.json")
    scores = load(RESULTS / "primary-scores.json")
    ids = [row["job_id"] for row in scores]
    assert len(ids) == len(set(ids)) == len(mapping)
    assert set(ids) == set(mapping)
    counts = {variant: 0 for variant in PRIMARY_VARIANTS}
    for row in scores:
        assert row["generation_ok"]
        assert row["score"]["recent_total"] == 3
        counts[row["variant"]] += 1
    assert set(counts.values()) == {HOLDOUT_FIXTURES * REPETITIONS}, counts


def validate_judge(name: str) -> None:
    primary = load(RESULTS / "primary-blinding-map.json")
    mapping = load(RESULTS / f"judge-{name}-blinding-map.json")
    batches = latest(RESULTS / f"judge-{name}.jsonl")
    manifest = load(RESULTS / f"judge-{name}-manifest.json")
    assert_hashes(manifest)
    assert len(mapping) == len(primary) == HOLDOUT_FIXTURES * REPETITIONS * 2
    assert (
        len(batches)
        == manifest["observed_jobs"]
        == manifest["expected_jobs"]
        == HOLDOUT_FIXTURES
    )
    assert {item["primary_job_id"] for item in mapping.values()} == set(primary)
    seen = []
    for batch in batches.values():
        assert batch["result"]["ok"]
        ids = [item["candidate_id"] for item in batch["result"]["judgment"]["candidates"]]
        assert len(ids) == len(set(ids)) == REPETITIONS * 2
        seen.extend(ids)
    assert set(seen) == set(mapping)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["pilot", "generations", "judges", "all"]
    )
    args = parser.parse_args()
    if args.stage in {"pilot", "all"}:
        validate_mode("pilot")
    if args.stage in {"generations", "all"}:
        for mode in ("primary", "presave", "recompact"):
            validate_mode(mode)
        validate_primary_scores()
    if args.stage in {"judges", "all"}:
        for name in ("claude", "codex"):
            validate_judge(name)
    print(json.dumps({"stage": args.stage, "ok": True}))


if __name__ == "__main__":
    main()
