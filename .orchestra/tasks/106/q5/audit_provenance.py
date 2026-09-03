import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
RESULTS = ROOT / "results"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, text=True, capture_output=True, check=True
    ).stdout.strip()


def main() -> None:
    lock = json.loads((RESULTS / "preregistration-lock.json").read_text())
    source_commit = lock["source_commit"]
    lock_path = "docs/tasks/106/q5/results/preregistration-lock.json"
    lock_commit = git("log", "-1", "--format=%H", "--", lock_path)
    source_time = git("show", "-s", "--format=%cI", source_commit)
    lock_commit_time = git("show", "-s", "--format=%cI", lock_commit)
    pilot = [
        json.loads(line)
        for line in (RESULTS / "pilot.jsonl").read_text().splitlines()
        if line.strip()
    ]
    first_pilot_start = min(item["started_at"] for item in pilot)
    source_hash_matches = {}
    for name, expected in lock["source_sha256"].items():
        relative = f"docs/tasks/106/q5/{name}"
        content = subprocess.run(
            ["git", "show", f"{source_commit}:{relative}"],
            cwd=REPO,
            capture_output=True,
            check=True,
        ).stdout
        source_hash_matches[name] = hashlib.sha256(content).hexdigest() == expected
    prior = []
    for path in (ROOT.parent / "fixtures.json", ROOT.parent / "q4" / "fixtures.json"):
        prior.extend(json.loads(path.read_text()))
    new = json.loads((ROOT / "fixtures.json").read_text())
    old_ids = {item["id"] for item in prior}
    new_ids = {item["id"] for item in new}
    old_transcripts = {
        hashlib.sha256(item["transcript"].encode()).hexdigest() for item in prior
    }
    new_transcripts = {
        hashlib.sha256(item["transcript"].encode()).hexdigest() for item in new
    }
    ordering = {
        "source_commit_before_lock_commit": datetime.fromisoformat(source_time)
        < datetime.fromisoformat(lock_commit_time),
        "lock_record_before_first_pilot_start": datetime.fromisoformat(
            lock["locked_at"]
        )
        < datetime.fromisoformat(first_pilot_start),
        "lock_commit_before_first_pilot_start": datetime.fromisoformat(
            lock_commit_time
        )
        < datetime.fromisoformat(first_pilot_start),
    }
    result = {
        "source_commit": source_commit,
        "source_commit_time": source_time,
        "lock_commit": lock_commit,
        "lock_commit_time": lock_commit_time,
        "lock_recorded_at": lock["locked_at"],
        "first_pilot_start": first_pilot_start,
        "ordering": ordering,
        "source_hash_matches": source_hash_matches,
        "all_source_hashes_match": all(source_hash_matches.values()),
        "corpus_exact_overlap": {
            "prior_fixture_count": len(prior),
            "new_fixture_count": len(new),
            "id_overlap": sorted(old_ids & new_ids),
            "byte_exact_transcript_hash_overlap": sorted(
                old_transcripts & new_transcripts
            ),
        },
        "scope_limit": "Exact ID/transcript non-overlap does not prove semantic independence or that fixture content did not influence candidate design.",
    }
    assert all(ordering.values())
    assert result["all_source_hashes_match"]
    assert not result["corpus_exact_overlap"]["id_overlap"]
    assert not result["corpus_exact_overlap"]["byte_exact_transcript_hash_overlap"]
    output = RESULTS / "provenance-audit.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(output), "ok": True}))


if __name__ == "__main__":
    main()
