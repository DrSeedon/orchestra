import json
import subprocess
import sys


def test_migration_keeps_derived_model_and_unknown_outcome_distinct(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "artifacts": [
            {
                "path": ".orchestra/tasks/436/old-review.md",
                "sha256": "0" * 64,
                "size_bytes": 11,
                "model": "gpt-5.6-sol",
                "model_source": "inferred_historical_default",
                "outcome": "unknown",
                "outcome_source": "unknown",
            },
        ],
    }) + "\n")
    db_path = tmp_path / "migration.db"
    script = "scripts/migrate_review_receipts.py"
    result = subprocess.run(
        [sys.executable, script, "--dry-run", "--manifest", str(manifest),
         "--db", str(db_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "T4 migration dry-run must exist and classify the frozen manifest"
    )
    payload = json.loads(result.stdout)
    assert payload["artifacts"][0]["model_source"] == "derived"
    assert payload["artifacts"][0]["outcome"] == "unknown"
    assert payload["artifacts"][0]["outcome_source"] == "unknown"
